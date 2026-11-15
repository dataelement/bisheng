{{- define "bisheng.name" -}}{{ default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- define "bisheng.fullname" -}}
{{- if .Values.fullnameOverride -}}{{ .Values.fullnameOverride | trunc 40 | trimSuffix "-" }}
{{- else -}}{{ printf "%s-%s" (.Release.Name | trunc 32 | trimSuffix "-") (printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 8) }}{{- end -}}
{{- end -}}
{{- define "bisheng.component" -}}{{ printf "%s-%s" (include "bisheng.fullname" (index . 0)) (index . 1) | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- define "bisheng.labels" -}}
app.kubernetes.io/name: {{ include "bisheng.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
{{- define "bisheng.selectorLabels" -}}
app.kubernetes.io/name: {{ include "bisheng.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "bisheng.backendService" -}}{{ include "bisheng.component" (list . "backend") }}{{- end -}}
{{- define "bisheng.frontendService" -}}{{ include "bisheng.component" (list . "frontend") }}{{- end -}}
{{- define "bisheng.image" -}}
{{- $root := index . 0 -}}{{- $image := index . 1 -}}{{- $repo := $image.repository -}}
{{- if $root.Values.global.imageRegistry -}}
{{- $parts := splitList "/" $repo -}}
{{- if and (gt (len $parts) 1) (or (contains "." (first $parts)) (contains ":" (first $parts)) (eq (first $parts) "localhost")) -}}{{- $repo = join "/" (rest $parts) -}}{{- end -}}
{{- $repo = printf "%s/%s" (trimSuffix "/" $root.Values.global.imageRegistry) $repo -}}
{{- end -}}
{{- if $image.digest -}}{{ printf "%s@%s" $repo $image.digest }}{{- else -}}{{ printf "%s:%s" $repo (required "image.tag or image.digest is required" $image.tag) }}{{- end -}}
{{- end -}}
{{- define "bisheng.host" -}}
{{- $root := index . 0 -}}{{- $name := index . 1 -}}{{- $value := index $root.Values $name -}}
{{- if $value.enabled -}}{{ include "bisheng.component" (list $root $name) }}
{{- else -}}{{ required (printf "%s.external.host is required when its built-in instance is disabled" $name) $value.external.host }}{{- end -}}
{{- end -}}
{{- define "bisheng.databaseHost" -}}
{{- if .Values.database.host -}}{{ .Values.database.host }}{{- else -}}{{ include "bisheng.host" (list . "mysql") }}{{- end -}}
{{- end -}}
{{- define "bisheng.authSecret" -}}
{{- $root := index . 0 -}}{{- $name := index . 1 -}}{{- $auth := index . 2 -}}
{{- if $auth.existingSecret -}}{{ $auth.existingSecret }}{{- else -}}{{ include "bisheng.component" (list $root $name) }}{{- end -}}
{{- end -}}
{{- define "bisheng.sandboxName" -}}
{{- include "bisheng-sandbox.fullname" (dict "Release" .Release "Values" .Values.sandbox "Chart" .Chart) -}}
{{- end -}}
{{- define "bisheng.sandboxSecret" -}}
{{- if .Values.sandbox.token.existingSecret -}}{{ .Values.sandbox.token.existingSecret }}{{- else -}}{{ include "bisheng.sandboxName" . }}{{- end -}}
{{- end -}}
{{- define "bisheng.sandboxEndpoints" -}}
{{- $values := list -}}{{- $root := . -}}
{{- range $index := until (int .Values.sandbox.replicaCount) -}}
{{- $name := include "bisheng.sandboxName" $root -}}
{{- $values = append $values (printf "http://%s-%d.%s.%s.svc.%s:%d" $name $index $name $root.Release.Namespace $root.Values.global.clusterDomain (int $root.Values.sandbox.service.port)) -}}
{{- end -}}{{ $values | toJson }}
{{- end -}}
{{- define "bisheng.secretVolumes" -}}
- name: settings-secrets
  projected:
    defaultMode: 0400
    sources:
      - secret:
          name: {{ include "bisheng.authSecret" (list . "db-platform" .Values.database.auth) }}
          items: [{key: {{ .Values.database.auth.passwordKey }}, path: database/password}]
      - secret:
          name: {{ include "bisheng.authSecret" (list . "redis-auth" .Values.redis.auth) }}
          items: [{key: {{ .Values.redis.auth.passwordKey }}, path: redis/password}]
      - secret:
          name: {{ include "bisheng.authSecret" (list . "minio-auth" .Values.minio.auth) }}
          items:
            - {key: {{ .Values.minio.auth.accessKeyKey }}, path: minio/access-key}
            - {key: {{ .Values.minio.auth.secretKeyKey }}, path: minio/secret-key}
      - secret:
          name: {{ default (include "bisheng.component" (list . "platform-keys")) .Values.global.credentials.existingPlatformSecret }}
{{- if .Values.elasticsearch.auth.enabled }}
      - secret:
          name: {{ required "elasticsearch.auth.existingSecret is required with basic-auth JSON key" .Values.elasticsearch.auth.existingSecret }}
          items: [{key: basic-auth, path: elasticsearch/basic-auth}]
{{- end }}
{{- if .Values.milvus.auth.enabled }}
      - secret:
          name: {{ required "milvus.auth.existingSecret is required with authentication enabled" .Values.milvus.auth.existingSecret }}
          items: [{key: {{ .Values.milvus.auth.passwordKey }}, path: milvus/password}]
{{- end }}
{{- if .Values.sandbox.enabled }}
      - secret:
          name: {{ include "bisheng.sandboxSecret" . }}
          items: [{key: {{ if .Values.sandbox.token.existingSecret }}{{ .Values.sandbox.token.existingSecretKey }}{{ else }}token{{ end }}, path: sandbox/token}]
{{- end }}
{{- if .Values.runtime.enabled }}
      - secret:
          name: {{ .Values.runtime.services.credentialsSecret }}
      - secret:
          name: {{ default (include "runtime.name" (list . "data-signing")) .Values.global.credentials.existingDataSecret }}
          items: [{key: seed, path: data/seed}]
{{- end }}
{{- end -}}
{{- define "bisheng.backendVolumes" -}}
- name: generated
  emptyDir: {medium: Memory, sizeLimit: 16Mi}
- name: deployment
  configMap:
    name: {{ default (include "bisheng.component" (list . "config")) .Values.config.existingConfigMap }}
{{ include "bisheng.secretVolumes" . }}
{{- if .Values.runtime.enabled }}
- name: official-catalog
  configMap:
    name: {{ include "bisheng.component" (list . "official-catalog") }}
- name: runtime-policy
  configMap:
    name: {{ include "runtime.name" (list . "runtime-deployment-descriptor") }}
{{- end }}
{{- end -}}
{{- define "bisheng.backendMounts" -}}
- {name: generated, mountPath: /run/generated}
- {name: deployment, mountPath: /run/deployment, readOnly: true}
- {name: settings-secrets, mountPath: /run/settings-secrets, readOnly: true}
{{- if .Values.runtime.enabled }}
- {name: runtime-policy, mountPath: /run/runtime-policy, readOnly: true}
- {name: official-catalog, mountPath: /run/official-runtime-catalog, readOnly: true}
{{- end }}
{{- end -}}
{{- define "bisheng.renderInit" -}}
- name: render-settings
  image: {{ include "bisheng.image" (list . .Values.backend.image) | quote }}
  command: [python, -m, bisheng.core.config.deployment_renderer]
  args:
{{- if .Values.config.existingConfigMap }}
    - --existing
    - /run/deployment/config.yaml
{{- else }}
    - --spec
    - /run/deployment/deployment.json
{{- end }}
    - --output
    - /run/generated/config.yaml
{{- if .Values.runtime.enabled }}
    - --data-seed
    - /run/settings-secrets/data/seed
{{- end }}
  resources: {{ toYaml .Values.bootstrap.resources | nindent 4 }}
  volumeMounts: {{ include "bisheng.backendMounts" . | nindent 4 }}
{{- end -}}
{{- define "bisheng.backendEnv" -}}
- {name: config, value: /run/generated/config.yaml}
- {name: TZ, value: {{ .Values.timezone | quote }}}
{{- with .Values.config.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- if .Values.runtime.enabled }}
- {name: BISHENG_RUNTIME_DATA_SIGNING_KEY_FILE, value: /run/generated/data-keys.json}
{{- end }}
{{- end -}}
{{- define "bisheng.runtimeDefaults" -}}
{{- if .Values.runtime.enabled -}}
{{- if not .Values.runtime.platform.origin }}{{ $_ := set .Values.runtime.platform "origin" (printf "https://%s:443" (include "bisheng.component" (list . "internal"))) }}{{ end -}}
{{- if .Values.global.credentials.existingRuntimeSecret }}{{ $_ := set .Values.runtime.services "credentialsSecret" .Values.global.credentials.existingRuntimeSecret }}{{ end -}}
{{- if .Values.global.credentials.existingIssuerSecret }}{{ $_ := set .Values.runtime.services "materialIssuerSecret" .Values.global.credentials.existingIssuerSecret }}{{ end -}}
{{- if .Values.global.credentials.existingAdmissionTlsSecret }}{{ $_ := set .Values.runtime.services "admissionTlsSecret" .Values.global.credentials.existingAdmissionTlsSecret }}{{ end -}}
{{- if .Values.global.credentials.existingCaConfigMap }}{{ $_ := set .Values.runtime.platform "caConfigMap" .Values.global.credentials.existingCaConfigMap }}{{ end -}}
{{- include "runtime.defaults" (dict "Release" .Release "Values" .Values.runtime "Chart" .Chart) -}}
{{- end -}}
{{- end -}}
{{- define "bisheng.ownedSecret" -}}
{{- $root := index . 0 -}}{{- $name := index . 1 -}}{{- $data := index . 2 -}}
{{- $old := lookup "v1" "Secret" $root.Release.Namespace $name -}}
{{- if and $root.Release.IsUpgrade (not $old) -}}
{{- $runtimeWasInstalled := false -}}
{{- if $root.Values.runtime.enabled }}{{ $runtimeWasInstalled = not (empty (lookup "v1" "ConfigMap" $root.Values.runtime.execution.namespace $root.Values.runtime.execution.dataKeyConfigMap)) }}{{ end -}}
{{- if or (hasSuffix "-platform-keys" $name) (and $runtimeWasInstalled (or (hasSuffix "-identities" $name) (hasSuffix "-issuer" $name) (hasSuffix "-data-signing" $name) (hasSuffix "-internal-tls" $name) (hasSuffix "-admission-tls" $name))) }}{{ fail "owned cryptographic Secret is missing on upgrade; restore the original instead of rotating silently" }}{{ end -}}
{{- end -}}

{{- if $old -}}
{{- if or (ne (get (default (dict) $old.metadata.annotations) "meta.helm.sh/release-name") $root.Release.Name) (ne (get (default (dict) $old.metadata.annotations) "meta.helm.sh/release-namespace") $root.Release.Namespace) -}}{{ fail "Secret is not owned by this release; reference an existingSecret instead" }}{{- end -}}
{{- range $key, $_ := $data -}}{{- if not (hasKey $old.data $key) -}}{{ fail (printf "owned Secret %s is missing expected key %s; refusing silent rotation" $name $key) }}{{- end -}}{{- end -}}
{{- $data = $old.data -}}
{{- end }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ $name }}
  annotations: {helm.sh/resource-policy: keep}
  labels: {{ include "bisheng.labels" $root | nindent 4 }}
type: Opaque
data: {{ toYaml $data | nindent 2 }}
{{- end -}}

{{- define "bisheng.bootstrapPlacement" -}}
{{- with .Values.bootstrap.nodeSelector }}
nodeSelector: {{ toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.bootstrap.affinity }}
affinity: {{ toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.bootstrap.tolerations }}
tolerations: {{ toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
