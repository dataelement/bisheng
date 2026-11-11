{{- define "bisheng.backendDeployment" -}}
{{- $root := index . 0 -}}{{- $name := index . 1 -}}{{- $value := index $root.Values $name -}}
{{ include "bisheng.runtimeDefaults" $root }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "bisheng.component" (list $root $name) }}
  labels: {{ include "bisheng.labels" $root | nindent 4 }}
spec:
  replicas: {{ $value.replicaCount }}
  selector:
    matchLabels:
      {{- include "bisheng.selectorLabels" $root | nindent 6 }}
      app.kubernetes.io/component: {{ $name }}
  template:
    metadata:
      annotations:
        checksum/settings: {{ include (print $root.Template.BasePath "/configmap-config.yaml") $root | sha256sum }}
        deployment.bisheng.io/config-revision: {{ $root.Values.global.configRevision | quote }}
{{- if $root.Values.runtime.enabled }}
        checksum/runtime-policy: {{ include "runtime.policy" (dict "Release" $root.Release "Values" $root.Values.runtime "Chart" $root.Chart) | sha256sum }}
{{- end }}
      labels:
        {{- include "bisheng.selectorLabels" $root | nindent 8 }}
        app.kubernetes.io/component: {{ $name }}
    spec:
      automountServiceAccountToken: false
      {{- with (concat $root.Values.global.imagePullSecrets $root.Values.imagePullSecrets) }}
      imagePullSecrets: {{ toYaml . | nindent 8 }}
      {{- end }}
      initContainers:
        {{- include "bisheng.renderInit" $root | nindent 8 }}
        - name: wait-initialization
          image: {{ include "bisheng.image" (list $root $root.Values.backend.image) | quote }}
          command: [python, scripts/wait_schema.py]
          args: [--timeout, {{ $root.Values.bootstrap.timeoutSeconds | quote }}{{ if $root.Values.runtime.enabled }}, --runtime{{ end }}]
          env: {{ include "bisheng.backendEnv" $root | nindent 12 }}
          resources: {{ toYaml $root.Values.bootstrap.resources | nindent 12 }}
          volumeMounts: {{ include "bisheng.backendMounts" $root | nindent 12 }}
      containers:
        - name: {{ $name }}
          image: {{ include "bisheng.image" (list $root $value.image) | quote }}
          imagePullPolicy: {{ $value.image.pullPolicy }}
{{- if eq $name "backend" }}
          command: [sh, entrypoint.sh, api-managed]
          ports: [{name: http, containerPort: {{ $root.Values.backend.service.port }}}]
{{- else if eq $name "worker" }}
          command: [celery, -A, bisheng.worker.main, worker, -l, info, -P, threads, -c, {{ $value.concurrency | quote }}, -Q, "knowledge_celery,ocr_celery,workflow_celery,celery", -n, "worker@%h"]
{{- else if eq $name "linsight" }}
          command: [python, bisheng/linsight/worker.py, --worker_num, {{ $value.workerCount | quote }}, --max_concurrency, {{ $value.maxConcurrency | quote }}]
{{- else }}
          command: [celery, -A, bisheng.worker.main, beat, -l, info]
{{- end }}
          env:
            {{- include "bisheng.backendEnv" $root | nindent 12 }}
{{- if eq $name "backend" }}
            - {name: BISHENG_API_PORT, value: {{ $root.Values.backend.service.port | quote }}}
            - {name: BISHENG_API_WORKERS, value: {{ $root.Values.backend.workers | quote }}}
{{- end }}
            {{- with $value.extraEnv }}{{ toYaml . | nindent 12 }}{{ end }}
          volumeMounts:
            {{- include "bisheng.backendMounts" $root | nindent 12 }}
            - {name: data, mountPath: /app/data}
          resources: {{ toYaml $value.resources | nindent 12 }}
{{- with $value.startupProbe }}
          startupProbe: {{ toYaml . | nindent 12 }}
{{- end }}
{{- with $value.readinessProbe }}
          readinessProbe: {{ toYaml . | nindent 12 }}
{{- end }}
{{- with $value.livenessProbe }}
          livenessProbe: {{ toYaml . | nindent 12 }}
{{- end }}
      volumes:
        {{- include "bisheng.backendVolumes" $root | nindent 8 }}
        - name: data
{{- if or $value.cache.enabled $value.cache.existingClaim }}
          persistentVolumeClaim:
            claimName: {{ default (include "bisheng.component" (list $root (printf "%s-cache" $name))) $value.cache.existingClaim }}
{{- else }}
          emptyDir: {sizeLimit: {{ $value.cache.sizeLimit }}}
{{- end }}
{{- with $value.nodeSelector }}
      nodeSelector: {{ toYaml . | nindent 8 }}
{{- end }}
{{- with $value.affinity }}
      affinity: {{ toYaml . | nindent 8 }}
{{- end }}
{{- with $value.tolerations }}
      tolerations: {{ toYaml . | nindent 8 }}
{{- end }}
{{- end -}}
