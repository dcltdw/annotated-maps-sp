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

{{/*
Django SECRET_KEY. Symmetric to databaseUrl above: fail fast rather than ship an
empty SECRET_KEY, so a prod/demo install that forgets to supply one is rejected
at render time instead of silently starting with no key (#102). The dev
values.yaml carries an insecure default, so the in-cluster dev path renders.
*/}}
{{- define "annotated-maps.djangoSecretKey" -}}
{{- if .Values.secrets.djangoSecretKey -}}
{{- .Values.secrets.djangoSecretKey -}}
{{- else -}}
{{- fail "secrets.djangoSecretKey is required (set it via --set secrets.djangoSecretKey=... or a values file)" -}}
{{- end -}}
{{- end }}
