# APA — local Kubernetes dev environment (kind)
#
# Typical flow:
#   make up        # create cluster + install everything
#   make forward   # expose UIs on localhost
#   make down      # delete cluster
#
# Individual targets are also available for surgical operations.

CLUSTER_NAME  := apa
NAMESPACE     := apa
CHART_PATH    := k8s/charts/apa
INFRA_DIR     := k8s/infra
KIND_CONFIG   := k8s/kind-config.yaml
ENV_FILE      := .env
PID_DIR       := .run

# Pinned chart versions — bump intentionally.
KPS_VERSION    := 83.5.0
LOKI_VERSION   := 6.55.0
ALLOY_VERSION  := 1.7.0
ARGOCD_VERSION := 7.7.5
CNPG_VERSION   := 0.23.0

ARGOCD_NS     := argocd

.DEFAULT_GOAL := help

# ─── Help ────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo "APA — kind dev environment"
	@echo ""
	@echo "Combos:"
	@echo "  up                Full manual setup: cluster + infra + app"
	@echo "  argocd-up         GitOps setup: cluster + ArgoCD + let it sync everything"
	@echo "  down              Delete cluster (teardown)"
	@echo "  reset             down + up"
	@echo ""
	@echo "Cluster:"
	@echo "  cluster-up        Create kind cluster"
	@echo "  cluster-down      Delete kind cluster"
	@echo ""
	@echo "Infra:"
	@echo "  infra-install     Install CNPG + Prometheus stack + Loki + Alloy"
	@echo "  infra-uninstall   Remove infra charts"
	@echo "  cnpg              CNPG operator + apa-pg cluster CR"
	@echo "  kube-prometheus   Prometheus + Grafana + Alertmanager"
	@echo "  loki              Grafana Loki (SingleBinary mode)"
	@echo "  alloy             Grafana Alloy log collector (DaemonSet)"
	@echo ""
	@echo "App:"
	@echo "  secret            Create apa-secrets from $(ENV_FILE)"
	@echo "  app-install       helm install/upgrade apa chart"
	@echo "  app-uninstall     Uninstall apa chart"
	@echo ""
	@echo "ArgoCD:"
	@echo "  argocd-install    Install ArgoCD via helm in argocd namespace"
	@echo "  argocd-bootstrap  Apply root Application (triggers app-of-apps sync)"
	@echo "  argocd-password   Print initial admin password"
	@echo "  argocd-forward    Port-forward ArgoCD UI → localhost:8080"
	@echo ""
	@echo "Access:"
	@echo "  forward           Port-forward Grafana/Prom/AM/Listener (background)"
	@echo "  forward-stop      Kill all port-forwards"
	@echo ""
	@echo "Diagnostics:"
	@echo "  status            kubectl get pods -n $(NAMESPACE)"
	@echo "  logs SVC=<name>   Tail logs for a deployment"
	@echo "  psql              Open psql session on apa-pg-1"

# ─── Combos ──────────────────────────────────────────────────────────────
.PHONY: up
up: cluster-up infra-install app-install

.PHONY: down
down: cluster-down

.PHONY: reset
reset: down up

.PHONY: argocd-up
argocd-up: cluster-up secret argocd-install argocd-bootstrap

# ─── Cluster ─────────────────────────────────────────────────────────────
.PHONY: cluster-up
cluster-up:
	kind create cluster --name $(CLUSTER_NAME) --config $(KIND_CONFIG)

.PHONY: cluster-down
cluster-down:
	-kind delete cluster --name $(CLUSTER_NAME)
	-rm -rf $(PID_DIR)

.PHONY: namespace
namespace:
	@kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

# ─── Helm repos ──────────────────────────────────────────────────────────
.PHONY: repos
repos:
	@helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update >/dev/null
	@helm repo add grafana https://grafana.github.io/helm-charts --force-update >/dev/null
	@helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update >/dev/null
	@helm repo update >/dev/null

# ─── Infra ───────────────────────────────────────────────────────────────
.PHONY: cnpg
cnpg: namespace repos
	helm upgrade --install cnpg-operator cnpg/cloudnative-pg \
		--namespace cnpg-system --create-namespace \
		--version $(CNPG_VERSION)
	kubectl -n cnpg-system wait --for=condition=Available deployment/cnpg-operator-cloudnative-pg --timeout=120s
	kubectl apply -f $(INFRA_DIR)/cnpg/cluster.yaml
	kubectl -n $(NAMESPACE) wait --for=condition=Ready cluster/apa-pg --timeout=180s

.PHONY: kube-prometheus
kube-prometheus: namespace repos
	helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
		--namespace $(NAMESPACE) \
		--version $(KPS_VERSION) \
		-f $(INFRA_DIR)/kube-prometheus-values.yaml

.PHONY: loki
loki: namespace repos
	helm upgrade --install loki grafana/loki \
		--namespace $(NAMESPACE) \
		--version $(LOKI_VERSION) \
		-f $(INFRA_DIR)/loki-values.yaml

.PHONY: alloy
alloy: namespace repos
	helm upgrade --install alloy grafana/alloy \
		--namespace $(NAMESPACE) \
		--version $(ALLOY_VERSION) \
		-f $(INFRA_DIR)/alloy-values.yaml

.PHONY: infra-install
infra-install: cnpg kube-prometheus loki alloy

.PHONY: infra-uninstall
infra-uninstall:
	-helm uninstall alloy --namespace $(NAMESPACE)
	-helm uninstall loki --namespace $(NAMESPACE)
	-helm uninstall kube-prometheus --namespace $(NAMESPACE)
	-kubectl delete -f $(INFRA_DIR)/cnpg/cluster.yaml
	-helm uninstall cnpg-operator --namespace cnpg-system

# ─── App ─────────────────────────────────────────────────────────────────
.PHONY: secret
secret: namespace
	@test -f $(ENV_FILE) || { echo "ERROR: $(ENV_FILE) not found"; exit 1; }
	kubectl create secret generic apa-secrets \
		--namespace $(NAMESPACE) \
		--from-env-file=$(ENV_FILE) \
		--dry-run=client -o yaml | kubectl apply -f -

.PHONY: app-install
app-install: secret
	helm upgrade --install apa $(CHART_PATH) --namespace $(NAMESPACE)

.PHONY: app-uninstall
app-uninstall:
	-helm uninstall apa --namespace $(NAMESPACE)

# ─── ArgoCD ──────────────────────────────────────────────────────────────
.PHONY: argocd-repo
argocd-repo:
	@helm repo add argo https://argoproj.github.io/argo-helm --force-update >/dev/null
	@helm repo update argo >/dev/null

.PHONY: argocd-install
argocd-install: argocd-repo
	helm upgrade --install argocd argo/argo-cd \
		--namespace $(ARGOCD_NS) --create-namespace \
		--version $(ARGOCD_VERSION) \
		-f k8s/argocd/values.yaml
	kubectl -n $(ARGOCD_NS) wait --for=condition=Available deployment/argocd-server --timeout=180s

.PHONY: argocd-bootstrap
argocd-bootstrap:
	kubectl apply -f k8s/argocd/root.yaml

.PHONY: argocd-password
argocd-password:
	@kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret \
		-o jsonpath="{.data.password}" | base64 -d; echo

.PHONY: argocd-forward
argocd-forward:
	@mkdir -p $(PID_DIR)
	@kubectl -n $(ARGOCD_NS) port-forward svc/argocd-server 8080:80 >/dev/null 2>&1 & echo $$! > $(PID_DIR)/argocd.pid
	@sleep 1
	@echo "ArgoCD UI → http://localhost:8080 (admin / \`make argocd-password\`)"

# ─── Access ──────────────────────────────────────────────────────────────
.PHONY: forward
forward:
	@mkdir -p $(PID_DIR)
	@kubectl -n $(NAMESPACE) port-forward svc/kube-prometheus-grafana 3000:80 >/dev/null 2>&1 & echo $$! > $(PID_DIR)/grafana.pid
	@kubectl -n $(NAMESPACE) port-forward svc/prometheus-operated 9090:9090 >/dev/null 2>&1 & echo $$! > $(PID_DIR)/prometheus.pid
	@kubectl -n $(NAMESPACE) port-forward svc/alertmanager-operated 9093:9093 >/dev/null 2>&1 & echo $$! > $(PID_DIR)/alertmanager.pid
	@kubectl -n $(NAMESPACE) port-forward svc/listener 9000:9000 >/dev/null 2>&1 & echo $$! > $(PID_DIR)/listener.pid
	@sleep 1
	@echo "Grafana       → http://localhost:3000 (admin / admin)"
	@echo "Prometheus    → http://localhost:9090"
	@echo "Alertmanager  → http://localhost:9093"
	@echo "Listener API  → http://localhost:9000"

.PHONY: forward-stop
forward-stop:
	@if [ -d $(PID_DIR) ]; then \
		for f in $(PID_DIR)/*.pid; do \
			[ -f "$$f" ] && kill $$(cat $$f) 2>/dev/null; rm -f $$f; \
		done; \
	fi
	@echo "port-forwards stopped"

# ─── Diagnostics ─────────────────────────────────────────────────────────
.PHONY: status
status:
	@kubectl -n $(NAMESPACE) get pods

.PHONY: logs
logs:
	@test -n "$(SVC)" || { echo "Usage: make logs SVC=<name>"; exit 1; }
	kubectl -n $(NAMESPACE) logs -f deployment/$(SVC)

.PHONY: psql
psql:
	kubectl -n $(NAMESPACE) exec -it apa-pg-1 -- psql -U apa -d apa
