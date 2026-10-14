{{- define "bisheng-sandbox.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "bisheng-sandbox.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

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
