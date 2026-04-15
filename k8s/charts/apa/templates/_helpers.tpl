{{/*
Shared labels applied to every resource.
*/}}
{{- define "apa.labels" -}}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: agentic-apa
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
