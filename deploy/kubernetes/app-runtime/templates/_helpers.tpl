{{- define "runtime.base" -}}
{{- printf "%s-%s" (.Release.Name | trunc 30 | trimSuffix "-") (printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 8) -}}
{{- end -}}
{{- define "runtime.name" -}}
{{- printf "%s-%s" (include "runtime.base" (index . 0)) (index . 1) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- define "runtime.defaults" -}}
{{- $credentials := get (default (dict) .Values.global) "credentials" | default (dict) -}}
{{- range $key, $source := dict "credentialsSecret" "existingRuntimeSecret" "materialIssuerSecret" "existingIssuerSecret" "admissionTlsSecret" "existingAdmissionTlsSecret" -}}
{{- if get $credentials $source }}{{ $_ := set $.Values.services $key (get $credentials $source) }}{{ end -}}
{{- end -}}
{{- if get $credentials "existingCaConfigMap" }}{{ $_ := set .Values.platform "caConfigMap" (get $credentials "existingCaConfigMap") }}{{ end -}}

{{- if not .Values.platform.caConfigMap }}{{ $_ := set .Values.platform "caConfigMap" (include "runtime.name" (list . "platform-ca")) }}{{ end -}}
{{- if not .Values.platform.origin }}{{ $_ := set .Values.platform "origin" (printf "https://%s-%s-internal:443" (.Release.Name | trunc 32 | trimSuffix "-") (printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 8)) }}{{ end -}}
{{- if not .Values.platform.backendBase }}{{ $_ := set .Values.platform "backendBase" .Values.platform.origin }}{{ end -}}
{{- if not .Values.services.namespace }}{{ $_ := set .Values.services "namespace" .Release.Namespace }}{{ end -}}
{{- if not .Values.execution.namespace }}{{ $_ := set .Values.execution "namespace" (include "runtime.name" (list . "apps")) }}{{ end -}}
{{- if not .Values.execution.installationId }}{{ $_ := set .Values.execution "installationId" (include "runtime.base" .) }}{{ end -}}
{{- if not .Values.execution.nodeId }}{{ $_ := set .Values.execution "nodeId" (include "runtime.name" (list . "node")) }}{{ end -}}
{{- range $key, $suffix := dict "credentialsSecret" "identities" "materialIssuerSecret" "issuer" "admissionTlsSecret" "admission-tls" "managerAccount" "manager" -}}
{{- if not (get $.Values.services $key) }}{{ $_ := set $.Values.services $key (include "runtime.name" (list $ $suffix)) }}{{ end -}}
{{- end -}}
{{- if not .Values.execution.dataKeyConfigMap }}{{ $_ := set .Values.execution "dataKeyConfigMap" (include "runtime.name" (list . "data-public-keys")) }}{{ end -}}
{{- end -}}
{{- define "runtime.policy" -}}
{{- include "runtime.defaults" . -}}
{{- $storage := dict "class" .Values.storage.className "size_mb" .Values.storage.sizeMi "scratch_size_mb" .Values.storage.scratchSizeMi "filesystem" .Values.storage.filesystem "sqlite_compatible" .Values.storage.sqliteCompatible "node_local" .Values.storage.nodeLocal "static_pool" (not (empty .Values.storage.volumes)) -}}
{{- $d := dict "schema_version" 2 "configuration_source" "operator-configured" "cluster_id" .Values.execution.clusterId "node_id" .Values.execution.nodeId "installation_id" .Values.execution.installationId "namespace" .Values.execution.namespace "platform" (printf "linux/%s" .Values.execution.architecture) "memory_budget_mb" .Values.execution.memoryBudgetMi "cpu_budget_millicores" .Values.execution.cpuBudgetMillicores "temporary_storage_mb" .Values.execution.temporaryStorageMi "status_policy_revision" .Values.execution.statusPolicyRevision "manager_username" (printf "system:serviceaccount:%s:%s" .Values.services.namespace .Values.services.managerAccount) "cni_username" .Values.execution.cniUsername "storage_controller_usernames" .Values.execution.storageControllerUsernames "helper_image" .Values.images.helper "assembler_image" .Values.images.assembler "storage" $storage "capabilities" (dict "pod_cidrs" .Values.network.podCidrs "service_cidrs" .Values.network.serviceCidrs) "pod_cidrs" .Values.network.podCidrs "service_cidrs" .Values.network.serviceCidrs "runtime_class" .Values.execution.runtimeClass "control_pull_secret" .Values.services.pullSecret "pull_secret" .Values.execution.pullSecret "data_public_keys_configmap" .Values.execution.dataKeyConfigMap "package_endpoints" .Values.offline.packageEndpoints "image_repository" .Values.offline.imageRepository "image_registry_endpoints" .Values.offline.imageRegistryEndpoints "registry_secret" .Values.offline.registrySecret "insecure_registry" .Values.offline.insecureRegistry "offline" .Values.offline.enabled "sandbox" (dict "requested" .Values.execution.sandbox "runtime_classes" .Values.execution.runtimeClasses) "operation_timeout_seconds" .Values.execution.operationTimeoutSeconds "helper_resources" .Values.execution.helperResources "timeouts" .Values.execution.timeouts "placement" .Values.execution.placement -}}
{{- $d | toJson -}}
{{- end -}}

{{- define "runtime.admission" -}}
{{- $context := index . 0 -}}
{{- $caBundle := index . 1 -}}
{{- with $context -}}
{{- include "runtime.defaults" . -}}
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: {{ printf "%s-runtime" .Values.execution.installationId }}
  annotations: {helm.sh/resource-policy: keep}
webhooks:
{{- range $name := list "resources" "status" }}
  - name: {{ printf "%s.%s.runtime.bisheng.io" $name $context.Values.execution.installationId }}
    admissionReviewVersions: [v1]
    sideEffects: None
    failurePolicy: Fail
    matchPolicy: Equivalent
    timeoutSeconds: {{ $context.Values.admission.timeoutSeconds }}
    namespaceSelector:
      matchLabels: {runtime.bisheng.io/installation: {{ $context.Values.execution.installationId }}}
    clientConfig:
      caBundle: {{ $caBundle | quote }}
      service:
        namespace: {{ $context.Values.services.namespace }}
        name: {{ include "runtime.name" (list $context "runtime-admission") }}
        path: /validate
        port: 443
    rules:
      - apiGroups: [""]
        apiVersions: [v1]
        scope: Namespaced
{{- if eq $name "status" }}
        operations: [UPDATE]
        resources: [pods/status]
{{- else }}
        operations: [CREATE, UPDATE, DELETE]
        resources: [pods, services, secrets, persistentvolumeclaims]
{{- end }}
{{- end }}

{{- end -}}
{{- end -}}
