{{/*
Shared labels applied to every resource.
*/}}
{{- define "rpa.labels" -}}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: agentic-rpa
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
