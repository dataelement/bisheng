{{- define "bisheng-sandbox.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "bisheng-sandbox.fullname" -}}
{{- if .Values.fullnameOverride -}}{{ .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else -}}{{ printf "%s-%s-code-runner" (.Release.Name | trunc 30 | trimSuffix "-") (printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 8) }}{{- end -}}
{{- end -}}

{{- define "bisheng-sandbox.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/name: {{ include "bisheng-sandbox.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: code-runner
{{- end }}

{{- define "bisheng-sandbox.selectorLabels" -}}
app.kubernetes.io/name: {{ include "bisheng-sandbox.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: code-runner
{{- end }}

{{- define "bisheng-sandbox.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "bisheng-sandbox.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "bisheng-sandbox.image" -}}
{{- $repo := .Values.image.repository -}}
{{- $registry := get (default (dict) .Values.global) "imageRegistry" -}}
{{- if $registry -}}
{{- $parts := splitList "/" $repo -}}
{{- if and (gt (len $parts) 1) (or (contains "." (first $parts)) (contains ":" (first $parts)) (eq (first $parts) "localhost")) }}{{ $repo = join "/" (rest $parts) }}{{ end -}}
{{- $repo = printf "%s/%s" (trimSuffix "/" $registry) $repo -}}
{{- end -}}
{{- if .Values.image.digest }}{{ printf "%s@%s" $repo .Values.image.digest }}{{ else }}{{ printf "%s:%s" $repo .Values.image.tag }}{{ end -}}
{{- end -}}
