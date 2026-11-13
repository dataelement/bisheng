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
- name: BS_SECRET_KEYS_FILE
  value: /run/secrets/bisheng-fernet-keys.json
- name: BISHENG_GATEWAY_HMAC_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "bisheng.fullname" . }}
      key: gatewayHmacSecret
- name: BS_CREDENTIAL_REVISION
  value: {{ .Values.credentials.configRevision | quote }}
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
- name: BS_SANDBOX_CONF__ENDPOINTS
  value: {{ .Values.sandbox.endpoints | toJson | quote }}
{{- end }}
{{- end }}

{{- define "bisheng.credentialValidate" -}}
{{- if or (hasKey .Values "middleware") (hasKey .Values "config") -}}
{{- fail "migrate legacy middleware/config values to credentials.existingSecret; secret values are not rendered" -}}
{{- end -}}
{{- $_ := required "credentials.existingSecret is required" .Values.credentials.existingSecret -}}
{{- $_ := required "credentials.configRevision is required" .Values.credentials.configRevision -}}
{{- range $component := list "backend" "worker" "linsight" -}}
{{- range $env := (index $.Values $component).extraEnv -}}
{{- if or (hasPrefix "BS_MINIO_" $env.name) (hasPrefix "BS_MILVUS_" $env.name) (hasPrefix "BS_ELASTICSEARCH_" $env.name) (has $env.name (list "config" "BS_SECRET_KEYS_FILE" "bisheng_DATABASE_URL" "BS_DATABASE_URL" "BS_REDIS_URL" "BS_CELERY_REDIS_URL")) -}}
{{- fail "migrate credential environment overrides to external Secret config.yaml" -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "bisheng.credentialRevision" -}}
{{- include "bisheng.credentialValidate" . -}}
bisheng.io/credential-revision: {{ .Values.credentials.configRevision | quote }}
{{- end -}}

{{- define "bisheng.credentialMounts" -}}
- name: credentials
  mountPath: /app/bisheng/config.yaml
  subPath: config.yaml
  readOnly: true
- name: credentials
  mountPath: /run/secrets/bisheng-fernet-keys.json
  subPath: fernet-keys.json
  readOnly: true
{{- end -}}

{{- define "bisheng.credentialVolume" -}}
- name: credentials
  secret:
    secretName: {{ .Values.credentials.existingSecret | quote }}
    defaultMode: 0400
    items:
      - key: config.yaml
        path: config.yaml
      - key: fernet-keys.json
        path: fernet-keys.json
{{- end -}}
