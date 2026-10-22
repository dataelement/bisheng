# Kubernetes 开源应用托管层

本 Chart 只安装 runtime-manager、app-proxy、egress-proxy 和独立 admission 进程。毕昇 backend、Celery、MySQL/DM8、Redis、MinIO、OpenFGA 继续按平台原有方式部署。所有模块开源，无商业额度或许可证执行点。

目标验收版本为 Kubernetes 1.28.15，支持 Linux amd64/arm64 独立执行域。Chart 渲染和单元测试不是集群实测；每个环境都必须执行下述真实探测及业务 E2E。单节点 local PV 不提供跨节点恢复或高可用承诺。

## 1. 身份、权限和网络

| 进程/身份 | 允许访问 | 不授予 |
| --- | --- | --- |
| 安装者（外部 kubeconfig） | 安装专用 namespace、PSA、网络、配额、准入证书、RBAC、PV；运行预检、更新描述文件与探测报告 | 不向任何业务 Pod 传递此身份；不由 manager 安装或扩大权限 |
| runtime-manager ServiceAccount | 仅 execution namespace：Pod/Service/PVC/Secret 的 get/list/watch/create/patch/delete；pods/log、events、endpoints、EndpointSlice 的 get/list/watch | nodes、PV、StorageClass、Namespace、RBAC、ConfigMap、Deployment、pods/status、exec、attach、portforward；不访问 control namespace 中的 Secret/工作负载 |
| app-proxy | backend 的授权及只读路由 API；执行 Pod 的 `http` 端口 | Kubernetes token、manager/control HMAC、数据库或 MinIO 账号 |
| egress-proxy | 独立 backend 策略身份；受控 DNS、平台及允许目标 | Kubernetes token、编排 API 权限 |
| admission | 只读 backend admission plan API；只读 canary plan/public settings；TLS 服务证书 | Kubernetes token、应用凭据、owner 私钥、数据库或 MinIO 账号 |
| 执行 Pod/helper | 其冻结模板与当前任务的最小材料/应用身份；业务流量只连接 egress ClusterIP | SA token、宿主敏感目录、跨应用卷、平台存储账号 |

manager 的 token 由显式 projected ServiceAccountToken 投射，3600 秒轮换，每次 API 请求重新读取；所有 Pod 禁用自动挂载。其权限仍是可创建工作负载的强权限，必须保留独立进程、namespace RBAC 和无 token 的 admission 服务。

执行 namespace 默认拒绝全部入站和出站。仅 app-proxy→`http`、manager→`http`/`data-control`；出站只到系统 namespace 的 egress-proxy:3128，不直接允许 DNS、backend、MinIO、集群 API 或其他应用。`services.egressClusterIP` 必须是已规划且空闲的 Service IP，应用无需 DNS 即可连接。域名解析、私网地址/重绑定和授权时效继续由代理检查。

系统 namespace 也默认拒绝，values 明确列出 API-server、DNS（包括实际 NodeLocal DNS 地址）、backend、入口和控制端点来源 CIDR/端口。backend CIDR 应按真实目的地址最小化，不能宽泛覆盖应用 Pod 网段。标准 NetworkPolicy 无法约束可信节点和 cluster-admin；存在不可信 hostNetwork 工作负载时须先配置等价 CNI 主机策略并验证，不能宣称默认策略已经覆盖。

集群启用审计时按 `system:serviceaccount:<control>:<account>` 查询 manager；未启用时验收记录注明“未启用”，本工具不生成伪造审计日志。

## 2. 安装前置和配置

先复制 `values.yaml` 到部署目录，配置实际地址和精确镜像引用。默认空镜像/CA/CIDR 会被 schema 拒绝；空探测报告永远不会让节点 ready。

- `platform.origin`：材料及内部控制 API 的 HTTPS origin，禁止内嵌账号、路径和查询参数。`platform.caConfigMap` 中的 `ca.crt` 为公开 CA 链。
- `platform.backendBase`：app-proxy 使用的平台内部地址。当前 app-proxy 未提供专用私有 CA 参数，使用受保护的内部 HTTP 或系统信任的 HTTPS；不要关闭 TLS 校验。
- `services`：独立系统 namespace、现存身份/seed/TLS Secret 名、控制及入口的共享暴露。外部平台访问不了 ClusterIP 时，使用两个受保护的共享 NodePort（默认不开启），由 nginx/backend 指向它们并验证真实源地址与 ACL。每应用不开放节点端口。
- `execution`：独立业务 namespace、逻辑 node_id、cluster_id、架构、预算、临时磁盘上限、公开 data key、冻结 CRI 检查 profile。`sandbox` 为 default/recommended/hardened；强档 RuntimeClass 映射由 `runtimeClasses` 指定。
- `images`：manager、entry、egress、admission、helper、assembler 的 `repo@sha256:…`。egress/admission 复用同版本 manager 镜像，覆盖进程命令。helper/assembler 独立镜像。控制进程需要拉取凭据时配置 `services.pullSecret`；执行 Pod 使用独立 namespace 的 `execution.pullSecret`。
- `storage`：经实际验证的 ext4/xfs 块文件系统；预置 PV 或指定 StorageClass，生产和 scratch 独立。默认 `sqliteCompatible: false`，核实存储前不能填 true。
- `offline`：离线默认开启；显式配置包源、镜像端点、可选 source-image 目标仓库及 registry Secret。无公共源兜底。节点 CRI 的镜像拉取由节点配置负责，不受 Pod 的 NetworkPolicy 约束。source-image 仓库/认证/CDN 出站按完整 origin 显式登记 `imageRegistryEndpoints`；私有仓库若用 5000/5443 等端口，`network.egressPorts` 也必须包含该端口。`insecureRegistry` 仅为指定目标 origin 启用 HTTP，不降低其他 base/认证端点的 TLS；跨仓库组装需为完整 OCI tar 预留临时磁盘配额。

### 必需的既有 Secret 与公钥

Secret 在 control namespace 中预先创建，私密值通过部署系统/安全文件供应；不要放进 values、Git、报告或命令行参数。

| Secret | 键 | 消费者 |
| --- | --- | --- |
| `services.credentialsSecret` | manager-key-id、manager-secret | manager→backend，仅 manager 角色 |
| 同上 | control-key-id、control-secret | backend→manager 的独立入站身份 |
| 同上 | entry-key-id、entry-secret、authz-secret | app-proxy 只读路由及既有授权协议 |
| 同上 | egress-key-id、egress-secret | egress→backend，仅 egress 角色 |
| 同上 | admission-key-id、admission-secret | admission→backend，仅只读 admission 角色 |
| `services.materialIssuerSecret` | seed：恰好 32 个原始字节 | manager 的独立持久 Ed25519 根种子，按授权 fsGroup 只读 0440 投射 |
| `services.admissionTlsSecret` | tls.crt、tls.key | admission HTTPS，SAN 包含 `runtime-admission.<control>.svc` |

backend 另行登记各角色、node_id、HMAC 与 controller 绑定。backend 的 owner 数据签名私钥仅保留在 backend；Chart 只接受 `execution.dataPublicKeys` 公钥字典，写入 execution 的指定 ConfigMap。公钥轮转须保留仍有效 key_id，并复核 helper 实际可见值；不能把 manager seed 或 owner 私钥作为公钥填入。

### 命名空间引导与安装

Helm release 存在独立 installer namespace，避免 manager 所在 namespace 拥有 Helm release Secret。control/execution namespace 被 Chart 标为 `keep`。若为预置 Secret 先创建这些 namespace，需要显式写入本 release 的 Helm ownership（先确认没有其他安装拥有它们）：

```sh
kubectl create namespace runtime-installer
kubectl create namespace bisheng-runtime-system
kubectl label namespace bisheng-runtime-system app.kubernetes.io/managed-by=Helm
kubectl annotate namespace bisheng-runtime-system meta.helm.sh/release-name=bisheng-runtime meta.helm.sh/release-namespace=runtime-installer
```

execution 如需预置 pull/registry Secret，也按同样方式创建并登记 ownership。然后由安全文件创建既有 Secret、公开 CA ConfigMap，配置持久证书；升级时不随机重生成 CA/种子。

```sh
helm lint deploy/kubernetes/app-runtime -f /secure/deploy/runtime-values.yaml
helm template bisheng-runtime deploy/kubernetes/app-runtime -n runtime-installer -f /secure/deploy/runtime-values.yaml > /secure/deploy/runtime-rendered.yaml
helm upgrade --install bisheng-runtime deploy/kubernetes/app-runtime -n runtime-installer -f /secure/deploy/runtime-values.yaml --wait --timeout 5m
```

不要用 `helm --wait` 成功代替运行域 ready；服务可启动但尚未通过探测时，backend 必须拒绝业务执行。manager 按只读描述读取数据，无 `kubectl`、Docker CLI 或 docker.sock 依赖。

## 3. 本地卷、SQLite 和容量

可用无 StorageClass 的预置 local PV。`storage.volumes` 分 production/scratch/preflight 池，设置真实容量、唯一目录、节点、Retain 和 nodeAffinity；生产与临时卷禁止共用路径。manager 只创建/消费授权 PVC，不创建宿主目录、格式化磁盘或修改 PV。

**目录存在不等于有界持久卷。** local PV 的 capacity 字段不会把普通目录限制为指定大小。建议节点管理员预置独立块设备/逻辑卷，或专用有界 loopback 文件系统；所有格式化操作须先证明是本次新建且专用的设备/文件，禁止把示例命令用于已有盘。设置 UID/GID 10001 可写、0700/适当目录权限；只为应用开放 business 子目录，备份和平台日志目录不可见。

节点管理员需维护持久 mount unit、实际文件系统 UUID/挂载点和容量标记，启动时确认挂载成功才允许该节点承载应用。loop 未挂载时底层空目录必须 fail closed，不能让初始化器把它当作新数据库。升级/reboot 验收必须模拟挂载失败并验证拒绝启动；单次预检不能替代此运行期保护。

真实 storage canary 在独立 preflight PVC 上测试：跨进程 flock、真实 SQLite 建表与 integrity_check、文件/目录 fsync、实际挂载文件系统及容量。工具只接受 ext4/xfs，容量约为该 PVC 申请大小（0.8–1.1 倍，容许文件系统开销），拒绝把 1Gi PVC 目录映射到整块数百 Gi 宿主盘。CSI 若以共享底层容量呈现，必须另有经验证的配额证据，不能跳过该检查。NFS/SMB 不作为 SQLite WAL 的替代。

local PV 节点失效时数据不能自动跟随新节点。Retain 的 scratch/preflight PV 在 PVC 释放后可能进入 Released；安装者仅在所有相关 Pod 同 UID 停止并清理确认后回收专用临时池，不能按名字清生产卷或无条件清 claimRef。卷池耗尽时准备失败；保留生产数据。

## 4. 离线物料分开核对

1. **镜像可用**：供应同版本 `dist/runtime-release.json`、单架构 `runtime-images-<arch>.json`、runtime-profiles、Chart、镜像 archive、licenses 和摘要。必须核对目标架构及每个 digest。`docker load` 成功不是 CRI 按该引用启动成功；使用实际目标 CRI 灌入并执行精确引用 canary。无法保留 digest 时供应可选内网只读分发端点。
2. **依赖可用**：预制 runtime/preparer 镜像、SDK wheel、完整且带 hash 的 wheelhouse/npm 包缓存、系统动态库、前端编译工具。首次发布或新增依赖前提前在匹配 OS/架构/ABI 的环境准备、校验并经 backend 上传。已有缓存不保证新增依赖可解析；离线模式不得向公网临时补包。
3. **运行期接口可用**：平台 HTTPS/CA/HMAC、材料下载上传、授权/路由/策略，以及应用需要的模型、检索、附件 API；应用运行不需要外网并不代表可离线调用外部模型。

当前默认 bundle 路径不构建新 OCI 镜像：backend 分发版本化源码/依赖，helper 在 Pod 的独立卷中物化；runtime 挂载只读代码/环境运行。完整 image 路径直接启动冻结镜像；兼容 source-image 路径额外需要可推送内网仓库和 assembler，缺少只阻断这一路径。发行清单中的 config image_id、单平台 manifest digest、multiarch index 和 tag 含义不同，不互相替代。

自定义 bundle 运行镜像必须实现对应的启动器合同：Python 包含冻结版本的解释器；Node 20 保留 `/usr/local/bin/docker-entrypoint.sh` 的标准参数处理；static 保留 `/opt/bisheng/entrypoint.sh`，按 `PORT` 在可写 `/tmp` 生成 nginx 配置。代码和依赖挂载只读、应用以 profile 冻结的非特权 UID/GID 运行。任意自定义镜像若不满足这些合同，应走完整 image 模式，由它自己的 ENTRYPOINT/CMD 决定启动方式。

## 5. 安装验证工具

使用同版本 Python 3.11+ runtime-manager 依赖、kubectl 和既有 installer kubeconfig。默认只读；启用 `--live` 才创建本次 `preflight-*` canary。工具不改变 kube-system、节点代理、Docker daemon 或现有业务应用；安装者需可 impersonate manager ServiceAccount，以真测 namespace RBAC，而非用管理员身份假装 manager。

```sh
python scripts/verify_k8s_runtime.py --context <context> --control-namespace bisheng-runtime-system --execution-namespace bisheng-runtime-apps --probe-plan /secure/deploy/runtime-probes.json
python scripts/verify_k8s_runtime.py --context <context> --control-namespace bisheng-runtime-system --execution-namespace bisheng-runtime-apps --probe-plan /secure/deploy/runtime-probes.json --live --write-report
```

probe plan 为安装者本地文件，不放任何 secret：

```json
{
  "installation_id": "bisheng-runtime",
  "webhook_name": "bisheng-runtime-runtime",
  "node_name": "dedicated-worker",
  "node_id": "bisheng-k8s-amd64",
  "platform_origin": "https://platform.internal",
  "platform_ca_file": "/secure/deploy/platform-ca.crt",
  "storage_size_mb": 1024,
  "verify_registry": false,
  "release_manifest": "/secure/deploy/runtime-release.json",
  "dependency_files": [{"path": "/secure/deploy/wheelhouse.tar", "sha256": "<64 lowercase hex>"}],
  "network_targets": {
    "network-direct-denied": [
      {"name": "backend", "host": "<backend IP>", "port": 7860, "expected": "denied"},
      {"name": "minio", "host": "<MinIO IP>", "port": 9000, "expected": "denied"},
      {"name": "kubernetes-api", "host": "<API IP>", "port": 6443, "expected": "denied"},
      {"name": "other-app", "host": "@preflight", "port": 8080, "expected": "denied"}
    ],
    "network-egress-allowed": [{"name": "egress", "host": "<egress ClusterIP>", "port": 3128, "expected": "allowed"}],
    "network-dns-denied": [{"name": "cluster-dns", "host": "<actual DNS IP>", "port": 53, "expected": "denied", "protocol": "udp-dns"}]
  }
}
```

`other-app` 可用 `@preflight` 指向工具自身已启动的独立 idle canary，避免首次安装还没有业务应用的循环前置；负例仍从另一个执行 Pod 发起并做监听正对照。工具运行位置须能连到计划中的正对照目标（通常是专用集群管理机/节点）。

HMAC 由安全环境变量 `RTM_VERIFY_PLATFORM_KEY_ID`、`RTM_VERIFY_PLATFORM_SECRET` 注入，限本安装 node_id 的 manager 角色。它验证控制侧 HTTPS、签名允许/未签名拒绝及节点范围；**不能代替后续应用 Pod/SDK/材料委托链路 E2E**。

`execution.canaryProfiles` 必须包含本执行域每个实际启用的 runtime/preparer 镜像的 digest 和固定版本命令，例如 Python `["python","--version"]`、Node `["node","--version"]`、static `["nginx","-v"]`。helper 也实际启动；观察原生 Node 架构、Pod spec 固定引用、CRI imageID。只是镜像清单或 Docker 本地缓存存在不会通过这项检查。

工具逐项执行 15 个必需检查：namespace 预算、restricted PSA、允许及拒绝准入、可信 status 来源、删除后原子 binding 拒绝、跨 namespace RBAC、exec 拒绝、入口白名单、直连拒绝、proxy 端口允许、UDP DNS 拒绝、SQLite 卷、实际 CRI、材料 TLS、平台签名 API。危险 PodSpec 负例使用 API-server `dryRun=All`；正例用真实 Pod。网络负例在实际拒绝前后分别验证目标确实监听，connection refused、无路由、未知结果不算隔离成功。入口正反使用系统 namespace 的无凭据 helper Pod，分别采用 entry/manager/untrusted 标签，从实际网络身份发起。

`verify_registry: true` 时，用同版本离线供应的 `crane` 在独立随机 preflight 子仓库做真实 copy/digest/delete，验证 source-image 推送条件；registry 凭据使用安装者已有 DOCKER_CONFIG，不复制给应用。强沙箱实际 canary 失败会记录 `sandbox-recommended` 或 `sandbox-hardened` 失败；只有全部默认必需基线成功才允许显式回退默认档。

canary 通过受保护的 ConfigMap 声明固定模板，plan 只有 1 小时以内寿命。无业务 Secret、源码或生产卷。installer 观察实际 UID 后更新授权，删除携带 UID/resourceVersion/宽限期；只有 fresh 同 UID 的终态或受保护的未调度删除证据才移除 finalizer。404、NodeLost、超时、同名替换一律保留，不能按名字强删。

清理失败会发布失败报告并返回非零。崩溃后可显式运行 `--cleanup-expired`，只处理当前安装已过期且 UID 已确认的 preflight 资源；不接管活跃探测，不操作业务应用。缺 UID、对象丢失或替换时停止，需管理员核对后处理。

### 报告刷新与结果边界

报告绑定 descriptor 摘要，只有真实执行 driver 的结果才能成功；每项包含观察时间、资源 UID 和安全原因。更改 helper、profile、namespace、预算、存储、策略或沙箱设置使旧报告失效。CM 整体 resourceVersion replace 防止覆盖并发配置；manager 只读消费，不能自行签发 ready。

有效期 24 小时，由**外部运维身份**每 6 小时重复真实验证并原子更新：

```sh
python scripts/verify_k8s_runtime.py --context <context> --control-namespace bisheng-runtime-system --execution-namespace bisheng-runtime-apps --probe-plan /secure/deploy/runtime-probes.json --live --write-report --repeat-seconds 21600
```

将该进程纳入客户现有运维监督，失败退出时告警并修复；不新增具有安装者权限的集群常驻 Pod。工具不会在用户机器擅自安装定时任务。报告失效/探测失败后必需基线 fail closed；不存在跳过隔离的开关。刷新只创建预检资源、更新报告，不重装 Chart或删除业务资源。

## 6. 升级、卸载与验收

升级先保存脱敏值、descriptor/profile/策略版本和证据，确认镜像/依赖/平台接口独立可用。保持 admission CA、material seed、owner 公钥和策略保护连续；不能卸掉 webhook 后领养旧 Pod。升级服务 Deployment 不创建应用 Deployment/Job ownerReference，不连带重建或删除独立应用 Pod/PVC。manager 采用 Recreate 避免旧新控制进程争用；多副本只允许后端租约保证单持有者，不以租约超时认定旧写入者已死。

代理升级会断开被终止进程的 TCP/WebSocket；按既有排空/重连协议验收，不承诺原连接永不重建。每次变更后重做真实探测，核对保持的同 UID 应用、SQLite 数据、附件和版本路由。

卸载前用平台停用入口并安全停止执行，确认所有 writer 的停止事实；保留源码、依赖、快照、附件和应用 PVC。`helm uninstall` 保留 Chart 的 namespace、公钥 ConfigMap和 local PV；没有 Helm ownerReference 的应用 Pod/PVC也不会随控制层删除。不能以卸载成功代替 writer 停止。只有 owner 显式删除应用的既有流程在停写确认和安全擦除成功后允许清理应用数据；Retain PV 后续由安装者按证据处理。

真实交付还必须补业务 E2E：发布审批/预览、Python/Node/static bundle与完整镜像/source-image、HTTP/WebSocket、应用身份/OBO/SDK、材料/附件、SQLite 数据权限、停用恢复；以及初始化失败、取消、重启、响应丢失、未知写入者、迁移失败、数据库快照恢复、升级和卸载保留。记录静态、模拟、真实执行、未验证和环境限制；189 单节点 amd64 不代表跨节点或 arm64 已通过。
