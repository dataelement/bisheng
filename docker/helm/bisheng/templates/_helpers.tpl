{{- define "bisheng.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "bisheng.fullname" -}}
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

{{- define "bisheng.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/name: {{ include "bisheng.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "bisheng.selectorLabels" -}}
app.kubernetes.io/name: {{ include "bisheng.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "bisheng.backendService" -}}
{{- printf "%s-backend" (include "bisheng.fullname" .) }}
{{- end }}

{{- define "bisheng.frontendService" -}}
{{- printf "%s-frontend" (include "bisheng.fullname" .) }}
{{- end }}

{{- define "bisheng.commonEnv" -}}
- name: TZ
  value: {{ .Values.timezone | quote }}
- name: BS_SSO_SYNC__GATEWAY_HMAC_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "bisheng.fullname" . }}
      key: gatewayHmacSecret
- name: BS_MILVUS_CONNECTION_ARGS
  value: {{ .Values.middleware.milvus.connectionArgs | quote }}
- name: BS_MILVUS_IS_PARTITION
  value: {{ .Values.middleware.milvus.isPartition | quote }}
- name: BS_MILVUS_PARTITION_SUFFIX
  value: {{ .Values.middleware.milvus.partitionSuffix | quote }}
- name: BS_ELASTICSEARCH_URL
  value: {{ .Values.middleware.elasticsearch.url | quote }}
- name: BS_ELASTICSEARCH_SSL_VERIFY
  value: {{ .Values.middleware.elasticsearch.sslVerify | quote }}
- name: BS_MINIO_SCHEMA
  value: {{ .Values.middleware.minio.schema | quote }}
- name: BS_MINIO_CERT_CHECK
  value: {{ .Values.middleware.minio.certCheck | quote }}
- name: BS_MINIO_ENDPOINT
  value: {{ .Values.middleware.minio.endpoint | quote }}
- name: BS_MINIO_SHAREPOINT
  value: {{ .Values.middleware.minio.sharepoint | quote }}
- name: BS_MINIO_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "bisheng.fullname" . }}
      key: minioAccessKey
- name: BS_MINIO_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "bisheng.fullname" . }}
      key: minioSecretKey
{{- end }}

{{- define "bisheng.sandboxEnv" -}}
{{- if .Values.sandbox.enabled }}
- name: BS_SANDBOX_CONF__TOKEN
  valueFrom:
    secretKeyRef:
      {{- if .Values.sandbox.existingSecret }}
      name: {{ .Values.sandbox.existingSecret }}
      key: {{ .Values.sandbox.existingSecretKey }}
      {{- else }}
      name: {{ include "bisheng.fullname" . }}
      key: sandboxToken
      {{- end }}
- name: BS_SANDBOX_CONF__DISCOVER_HOST_PATTERN
  value: {{ .Values.sandbox.discoverHostPattern | quote }}
- name: BS_SANDBOX_CONF__DISCOVER_INDEX_START
  value: {{ .Values.sandbox.discoverIndexStart | quote }}
- name: BS_SANDBOX_CONF__DISCOVER_TTL_S
  value: {{ .Values.sandbox.discoverTtlS | quote }}
- name: BS_SANDBOX_CONF__CODE_NODE_ENABLED
  value: {{ .Values.sandbox.codeNodeEnabled | quote }}
{{- end }}
{{- end }}
