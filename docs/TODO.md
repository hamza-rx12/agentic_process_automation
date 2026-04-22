# Deferred work

Things discussed in earlier sessions that we chose to come back to later.
Roughly ordered by value / effort ratio.

## 1. ArgoCD auto-sync on new image builds

**What:** CI writes the new image SHA into `k8s/charts/apa/values.yaml`
and commits, so ArgoCD picks up image bumps without manual rollouts.

**Why deferred:** Finished the log-formatting refactor first; image tag
churn didn't need to land in the same push.

**Next step:** Extend `.github/workflows/build-push.yml` with a `yq`
step that updates each service's image tag after push and commits back
on `master`. Add `paths-ignore: ['k8s/**']` to the workflow trigger so
the bump commit doesn't re-fire it.

**Alternative:** ArgoCD Image Updater controller. More infra, same
end result. Prefer the CI approach unless multi-cluster comes up.

---

## 2. Monitor-agent re-scope

**What:** Current monitor-agent has two tools — `grafana_query` (read)
and `grafana_artifact` (write dashboards/alert rules). The write tool
is questionable: an LLM inventing PromQL thresholds is a footgun, and
the `created_by: monitor-agent` loop-guard is a tell.

**Paths considered:**
- **A. Alert triage agent** — drop `grafana_artifact`, focus on
  turning a firing alert into a human-readable root-cause summary
  (Slack / GitHub comment).
- **B. Runbook executor** — read a `runbooks/` directory, execute the
  matching runbook step-by-step.
- **C. Remove it** — pick a different use case that better exercises
  the pipeline.

**Next step:** Decide between A / B / C, then refactor
`services/monitor-agent/`.

---

## 3. Fix monitor-agent's LogQL prompt

**What:** The 400 Bad Request we saw
(`{level="critical"} | logfmt` on plaintext logs). Logs are JSON now,
so the prompt/tool description should suggest
`{service="..."} | json | level="ERROR"` patterns.

**Next step:** Update the monitor-agent system prompt and/or the
`grafana_query` tool description with concrete JSON-log examples.
Subsumed by #2 if we pick path A.

---

## 4. ServiceMonitors for app-level metrics

**What:** Expose `/metrics` endpoints in each service, add
`ServiceMonitor` CRs so Prometheus scrapes them. Then
`up{job="listener"}` etc. become meaningful, and we can build a real
"app health" dashboard.

**Why deferred:** No business metrics identified yet.

**Next step:** Decide what each service should export (messages
processed, task duration, turns per agent call, cost in USD), then
wire `prometheus_client` into each service and author a dashboard.

---

## 5. External Secrets Operator for prod

**What:** Replace the dev-only
`kubectl create secret --from-env-file=.env` flow with ESO pointing at
AWS Secrets Manager (or equivalent).

**Why deferred:** Still on kind. Not needed until EKS.

**Next step:** When moving to EKS — install ESO, create a
`ClusterSecretStore`, switch the Helm template to render an
`ExternalSecret` instead of relying on a manually-created Secret.

---

## 6. Kind port-mapping for ArgoCD required `make reset`

Already wired (`30080 → 8080`), but note: any future NodePort we add
requires cluster recreation. Consider switching to an ingress-based
approach (nginx-ingress is already mapped on 80/443) once service
count grows.
