# BiSheng Helm charts

Two independent charts. The platform never talks to the Kubernetes API; the
worker finds runners by DNS (`code-runner-{n}.code-runner…` from ordinal 0).

| Chart | What it installs |
|-------|------------------|
| `bisheng-sandbox` | StatefulSet + **headless** Service `code-runner` |
| `bisheng` | frontend, backend API, Celery worker |

MySQL / Redis / MinIO / Elasticsearch / Milvus / OpenFGA are **not** in these
charts. Point `bisheng` values (and `files/config.yaml` hosts) at Services that
already exist.

## Install

```bash
# 1. Sandbox — keep the Service name code-runner (default fullnameOverride)
helm upgrade --install sandbox docker/helm/bisheng-sandbox \
  --namespace bisheng-sandbox --create-namespace \
  --set token.value="$SANDBOX_TOKEN"

# 2. Platform
helm upgrade --install bisheng docker/helm/bisheng \
  --namespace bisheng --create-namespace \
  --set sandbox.token="$SANDBOX_TOKEN" \
  --set sandbox.discoverHostPattern='code-runner-{n}.code-runner.bisheng-sandbox.svc.cluster.local'
```

`SANDBOX_TOKEN` must be the same on both releases.

NetworkPolicy on the sandbox chart only allows TCP/8080 from pods labeled
`app.kubernetes.io/component=worker` in namespace `bisheng` (automatic
`kubernetes.io/metadata.name` label). Change `networkPolicy.allowFrom` if you
use other names.

## Why not one ClusterIP for runners

`keep_session` sticks to a **hostname** (`http://code-runner-0.code-runner…`).
A ClusterIP / kube-proxy VIP would send the next `exec` to another Pod and
lose the working directory.

## Scale runners

```bash
helm upgrade sandbox docker/helm/bisheng-sandbox --reuse-values --set replicaCount=4
```

The worker refresh thread picks up new ordinals; no worker restart.

## Check

```bash
kubectl -n bisheng-sandbox get sts,svc,po
kubectl -n bisheng exec deploy/bisheng-worker -- \
  getent hosts code-runner-0.code-runner.bisheng-sandbox.svc.cluster.local
```

配置项、工具类型切换、页面用法与排障见
[沙箱配置与使用说明](../../features/v3.0.0-beta1/068-code-execution-sandbox/沙箱配置与使用说明.md)。
