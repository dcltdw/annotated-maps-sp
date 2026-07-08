{{/* deploy/helm/annotated-maps/templates/_helpers.tpl */}}
{{- define "annotated-maps.name" -}}
{{- .Chart.Name -}}
{{- end }}

{{- define "annotated-maps.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{- define "annotated-maps.labels" -}}
app.kubernetes.io/name: {{ include "annotated-maps.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{- define "annotated-maps.selectorLabels" -}}
app.kubernetes.io/name: {{ include "annotated-maps.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* DATABASE_URL: explicit value wins; else derived from the in-cluster postgres;
     else the chart refuses to render — a prod install without a DB URL is a mistake. */}}
{{- define "annotated-maps.databaseUrl" -}}
{{- if .Values.secrets.databaseUrl -}}
{{- .Values.secrets.databaseUrl -}}
{{- else if .Values.postgres.enabled -}}
{{- printf "postgis://%s:%s@%s-postgres:5432/%s" .Values.postgres.user .Values.postgres.password (include "annotated-maps.fullname" .) .Values.postgres.database -}}
{{- else -}}
{{- fail "secrets.databaseUrl is required when postgres.enabled=false" -}}
{{- end -}}
{{- end }}
