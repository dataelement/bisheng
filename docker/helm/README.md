# BiSheng Helm charts

Two independent charts. The platform never talks to the Kubernetes API; the
worker calls the replica URLs in `sandbox.endpoints`.

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
  --set sandbox.endpoints='{http://code-runner-0.code-runner.bisheng-sandbox.svc.cluster.local:8080,http://code-runner-1.code-runner.bisheng-sandbox.svc.cluster.local:8080}'
```

`SANDBOX_TOKEN` must be the same on both releases.

NetworkPolicy on the sandbox chart only allows TCP/8080 from pods in namespace
`bisheng` labeled `app.kubernetes.io/component=worker`, `backend` or `linsight`
(automatic `kubernetes.io/metadata.name` label). Change `networkPolicy.allowFrom`
if you use other names. Egress is allowed by default
(`networkPolicy.denyEgress: false`). Set it to `true` to block all outbound
traffic from the runner pods.

## Why not one ClusterIP for runners

`keep_session` sticks to a **hostname** (`http://code-runner-0.code-runner…`).
A ClusterIP / kube-proxy VIP would send the next `exec` to another Pod and
lose the working directory.

## Scale runners

```bash
helm upgrade sandbox docker/helm/bisheng-sandbox --reuse-values --set replicaCount=4
```

Then add each new Pod URL to the platform chart `sandbox.endpoints` and upgrade that release. Nothing scans DNS for new ordinals.

## Check

```bash
kubectl -n bisheng-sandbox get sts,svc,po
kubectl -n bisheng exec deploy/bisheng-worker -- \
  getent hosts code-runner-0.code-runner.bisheng-sandbox.svc.cluster.local
```

配置项与排障见
[沙箱部署说明](../../features/v3.0.0-beta1/068-code-execution-sandbox/沙箱部署说明.md)，
页面用法见
[沙箱使用说明](../../features/v3.0.0-beta1/068-code-execution-sandbox/沙箱使用说明.md)。


## 外部凭据 Secret（v3.1.0-beta2）

应用 Chart 不部署或改密外部中间件。先使用同版本工具在安全目录生成 config.yaml（本次密码均为密文）及外部 keyring 文件；本次真实密码不得放进普通 values/ConfigMap。示例仅包含文件路径：

```bash
kubectl -n bisheng create secret generic bisheng-credentials-a --from-file=config.yaml=/secure/bisheng/revisions/revision-a/config.yaml --from-file=fernet-keys.json=/secure/bisheng/keys/keys.json
helm upgrade --install bisheng docker/helm/bisheng -n bisheng --set credentials.existingSecret=bisheng-credentials-a --set credentials.configRevision=<非秘密版本> -f /secure/bisheng/nonsecret-values.yaml
kubectl -n bisheng rollout status deployment/bisheng-backend
kubectl -n bisheng rollout status deployment/bisheng-worker
kubectl -n bisheng rollout status deployment/bisheng-linsight
```

三个 Python Deployment 只读挂载同一 Secret 的 config.yaml 与 fernet-keys.json，BS_SECRET_KEYS_FILE 指向后者。Secret 更新不会自动触发 Helm rollout；每次切换更新 configRevision，等待全部副本替换后逐进程验证。Secret 的集群静态加密/RBAC 由客户 Kubernetes 管理策略负责，Base64 不等于加密。

旧 middleware/config values 会明确报 migrate 错误；把主机、TLS、账号和密文放进外部 Secret 的 config.yaml。Nginx 非秘密对象存储地址移到 frontend.objectStorageEndpoint / objectStorageSharepoint，须与业务配置一致。禁止通过 extraEnv 重新引入本次旧密码覆盖。独立 Gateway HMAC 与 sandbox Secret 契约保留。

先在中间件管理流程执行真实改密，配套准备配置并执行全部消费者新连接与业务验收；恢复也需同步真实服务端密码和客户端 Secret。使用已包含本次工具/验证器的镜像，values 中目标标签不代表镜像已经发布。完整迁移/恢复见 [运维手册](../../docs/中间件凭据运维手册.html)。
