# BiSheng Helm 安装与运维

## 交付状态和前提

这是 3.1.0-beta1 标准安装源码，包含正式初始化命令及运行协议变更。**本轮只完成代码与部署文件；配套镜像尚未构建，真实安装和双架构验收尚未执行。** 正式用户应使用包含 `files/image-set.json`、`files/runtime-catalog/catalog.json` 及锁文件的发行 Chart，不能将源码 Chart 配到旧版镜像。

运行前提：Kubernetes 1.28+、Helm 3.14+，Linux amd64 或 arm64 节点；支持实际执行 NetworkPolicy 的 CNI；API Server 能到达 Admission HTTPS Service。运维提供本集群 Pod/Service CIDR、DNS/API/内部平台访问范围，以及可用的持久存储。Chart 不安装存储驱动、不探测后宣称网络隔离成立、不修改节点 cgroup/磁盘。

平台和运行控制面部署在 `--namespace` 指定空间；独立托管应用空间默认从 release 名和命名空间摘要派生，可通过 `runtime.execution.namespace` 指定。控制空间可共享，Chart 不创建或修改其 PSA 标签；执行空间专用，保留 restricted、预算、最小 RBAC、Admission 和默认拒绝网络。

默认开启 Vibe 和两个代码沙箱，Gateway 默认关闭。MySQL、Redis、MinIO、Elasticsearch、Milvus、OpenFGA 默认各单实例，可分别改用外部组件。此默认规模用于初始安装，不能视为高可用承诺。模型服务、许可证及企业基础组件由运维提供。

## 1. 准备参数

先复制发行包的 values 到受控私有配置仓库，填写真实网络、存储和公开访问地址。例如：

```yaml
publicUrl: https://bisheng.example.com
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: bisheng.example.com
      paths: [{path: /, pathType: Prefix}]
  tls:
    - secretName: bisheng-public-tls
      hosts: [bisheng.example.com]
runtime:
  execution:
    architecture: amd64
    namespace: demo-runtime-apps
    clusterId: company-cluster
    # 应用额度还要包含每个任务的 Helper/init；4 核不是业务常量。
    memoryBudgetMi: 8192
    cpuBudgetMillicores: 4000
  network:
    # 以下仅为示例，必须替换为本集群范围；不要为方便填 0.0.0.0/0。
    podCidrs: [10.244.0.0/16]
    serviceCidrs: [10.96.0.0/12]
    kubernetesApiCidrs: [10.10.0.10/32]
    dnsCidrs: [10.96.0.10/32]
    backendCidrs: [10.96.0.0/12]
  storage:
    className: bounded-ext4
    sqliteCompatible: true
    filesystem: ext4
    sizeMi: 1024
    scratchSizeMi: 4096
  offline:
    enabled: false
    packageIndex: https://pypi.company.example/simple
    npmRegistry: https://npm.company.example
    # 供现有材料出口策略核对，URL 需包含端口且无 path。
    packageEndpoints: [https://pypi.company.example:443, https://npm.company.example:443]
```

`cniUsername` 与 `storageControllerUsernames` 是实际 CNI/调度/CSI 参与者身份，按集群真实实现配置。默认存储控制器列表适用于标准 kube-controller-manager/kube-scheduler；自定义 CSI、CNI 写入 Pod 状态/绑定时须补充其精确身份。它们影响状态来源保护，不是放宽任意调用者权限的开关。

平台缓存默认每个 Pod 独立、有限的 emptyDir，不统一要求 RWX。需要保存共享缓存时，配置各组件 `cache.enabled/size/storageClass/accessMode` 或 `cache.existingClaim`；跨节点多副本共享同一 Claim 要求 RWX。核心业务对象放数据库/对象存储。暂存文件与工具输出能否跨 Worker 节点共享取决于业务工具本身，部署前按所用工具选择共享卷。

应用数据/SQLite 使用有容量边界、满足锁与持久化要求的 RWO 块 CSI，文件系统 ext4/xfs；`sqliteCompatible: true` 是运维对已验证能力的声明，不是自动测试通过。未实测的 CSI 不得作为已支持驱动发布。应用 scratch 独立申请容量。Chart 不把 NFS 的目录大小当成容量隔离，也不格式化 hostPath。

所有 PVC 的 StorageClass 三态：`null` 省略字段、使用集群默认；`""` 显式无 class、用于预绑定静态卷；具体字符串选择已有类。已有 Claim 使用 `existingClaim`，不创建新 PVC。基础组件持久化默认开启；关闭仅适合可丢数据的测试。

## 2. 凭据

`database.auth.password`、`mysql.auth.rootPassword`、`redis.auth.password`、`minio.auth.secretKey` 等是**公开示例默认密码**，安装前修改，或优先引用 `existingSecret`。这些示例不是随机生成的。

平台 JWT、内部服务 HMAC、材料签名 seed、数据签名 seed 和内部 TLS 由 Helm 为该安装随机生成。升级通过有所有权检查的 `lookup` 沿用原值，不静默轮换；不要删除这些 Secret。材料签名与数据签名使用不同 seed。公钥初始化 Job 只能读取/补齐指定公钥 ConfigMap，不能访问 Secret API 或获得 Manager 的执行权限。证书包含内部 Service DNS；公开 Ingress TLS 由运维另行提供。

部署前创建的 Secret 必须位于对应使用者的命名空间。平台数据库 Secret 只需 `password`；Redis 默认 `password`，MinIO 默认 `access-key/secret-key`。可通过各 `*Key` 参数改键名。外部 Elasticsearch 认证需 `elasticsearch.auth.enabled: true` 和 `existingSecret`，键 `basic-auth` 内容是 JSON 数组 `["username","password"]`；外部 Milvus 认证配置 `milvus.auth.enabled/user/existingSecret/passwordKey`。额外 TLS 参数放在 `config.settings.vector_stores`，不会被默认端点覆盖。

`global.credentials.existingPlatformSecret/existingRuntimeSecret/existingIssuerSecret/existingDataSecret` 适合外部密钥管理，键结构参照 `templates/secret.yaml`。已有内部证书须同时提供 `existingTlsSecret`、`existingAdmissionTlsSecret`、`existingCaConfigMap` 及公开 `caBundle`，证书 DNS 与实际 Service 一致。frontend 只挂叶证书，不挂 CA 私钥。

控制面镜像拉取配置 `global.imagePullSecrets` 或 `runtime.services.pullSecret`；应用执行空间单独预置 Registry Secret 并设置 `runtime.execution.pullSecret`；材料组装使用 `runtime.offline.registrySecret`。Chart 不跨命名空间读取、复制私有凭据。

## 3. 安装和初始化

```bash
helm upgrade --install demo ./bisheng-0.2.0.tgz \
  --namespace demo --create-namespace -f company-values.yaml \
  --wait --wait-for-jobs --timeout 20m
kubectl -n demo get pods,jobs
```

源码维护者先执行 `helm dependency build docker/helm/bisheng --skip-refresh`；正式包已带固定本地依赖，用户安装不需要访问第三方 Chart 仓库。`helm template`/客户端 dry-run 不读取实时 Secret，随机值会变化；不要把它当作保留密钥的升级安装结果。真实升级由服务端 lookup 读取所属 release 的原 Secret。

初始化均为版本化镜像内命令，ConfigMap 仅存数据，无 Python/入口替换补丁：

1. 使用内置 MySQL 时，专属 Job 仅建立本安装配置的库、账号和库级授权；外部 MySQL 不传 root、不建库。内置 OpenFGA 先等待其专用库并执行官方 datastore migrate。
2. 平台初始化 Job 执行现有 Alembic、全新环境 OpenFGA/权限 Catalog 初始化，以及启用 Vibe 时的可信官方运行目录缺项初始化。遇到已有但不匹配的授权状态报错，不能覆盖未知业务库。不存在“整套版本初始化已完成”的新表或总标记。
3. API、Worker 等只读等待实际 schema/权限/catalog 状态，然后进入正常服务入口。Job 与应用可同时创建，通过有限等待处理启动先后。Gateway 开启时另行初始化固定版本专用 SQL，JVM 等待其就绪。
4. 打开网页登录并正常注册。**第一个注册用户成为超管**；没有预置 admin、密码或伪造账号。其他默认业务数据沿用服务正常启动逻辑。

初始化失败查看该 Job 日志并修复真实配置后重试；不要手工伪造完成标记。普通生产 API/Worker 不获得授权模型写权限。`bootstrap.timeoutSeconds/activeDeadlineSeconds` 决定有限等待，`helm --timeout` 应覆盖初始化和镜像拉取时间。

官方运行目录来自发行包内固定文件，系统来源没有用户身份，升级只补缺项、不覆盖用户语言默认选择，不改已经冻结的应用组合。人工导入/选择全局运行环境仍走既有超管 API/CLI；本次不新增模板管理页面。

## 4. 外部依赖与混合部署

```yaml
mysql: {enabled: false}
database:
  host: mysql.infra.svc.cluster.local
  port: 3306
  name: bisheng
  username: bisheng
  auth: {existingSecret: platform-db, passwordKey: password}
redis:
  enabled: false
  external: {host: redis.infra.svc.cluster.local, port: 6379}
  auth: {existingSecret: platform-redis, passwordKey: password}
  cacheDb: 10
  celeryDb: 11
  gatewayDb: 12
openfga:
  database:
    host: mysql.infra.svc.cluster.local
    name: bisheng_openfga
    username: bisheng_openfga
    auth: {existingSecret: openfga-db, passwordKey: password}
```

运维事先建立专用平台/OpenFGA 库及账号，utf8mb4/utf8mb4_general_ci，授予对应库初始化、迁移所需权限。OpenFGA 与 Gateway 各用独立库/账号；Chart 不接管 `infra` 或其他 release 的 MySQL/Redis。账号名、库名须满足模板限定，密码支持特殊字符，连接 URL 由镜像内配置装配器转义/加密。

各组件独立配置 `enabled: false` 和 `external.host/port/scheme`；MinIO 凭据/buckets、ES TLS、Milvus connection_args、OpenFGA `storeName` 须匹配企业服务。完全外部 OpenFGA 的 datastore 迁移由其服务运维负责，平台只初始化自己唯一 Store/匹配模型。外部 DM8 使用 `database.engine: dm8`、host/port/name(schema)及专用凭据，授权服务自己的 datastore 仍使用其支持的独立数据库。

Redis 默认支持独立 Redis 与 DB index 分离。不要据此假定 Sentinel/Redis Cluster 的 Celery broker 已支持；集群 Redis 仅 DB0 也不能用 index 隔离。需要其他已有 Settings 拓扑时使用完整自管配置并独立验收。

内置 Milvus 默认使用同一 MinIO 账户的独立 bucket；可用 `milvus.objectStorage.existingSecret/accessKeyKey/secretKeyKey/bucket` 配置运维预建的专用账户和 bucket。`milvus.etcd.externalEndpoint` 可替换内置 etcd。不声称默认账户已有 bucket 级授权隔离。

复杂企业配置可设置 `config.existingConfigMap`，其中 `config.yaml` 为完整 BiSheng Settings（可使用既有 !env）；通过 `config.extraEnv` 引用 Secret。该模式和 `config.settings` 互斥，由运维承担完整配置，不能期望自动再覆盖其中连接信息。

## 5. Gateway、Vibe、沙箱开关

```yaml
# 首次安装关闭选项
runtime: {enabled: false}
sandbox: {enabled: false}
# 原生 DSH 的基本登录独立于 Gateway 开关
# dsh: {enabled: true}
```

Vibe 关闭时无运行控制面、材料入口和目录初始化；新装关闭沙箱时沿用正常未启用流程。**本期不支持已开启沙箱、已保存端点/执行器/会话后的热关闭联动**；默认开启后持续使用，后续专门修复该业务缺陷。

Gateway 默认关闭，无许可证/数据库必需引用。开启配置 `gateway.enabled: true`、`gateway.license.existingSecret/key` 和独立 `gateway.database`；当前 SQL 合同固定为 1.8.0，发行镜像必须匹配。内置 MySQL 自动创建该专用库；外部 MySQL 先建库授权。未知非空 SQL 结构会拒绝初始化，不能当成通用迁移工具。Nginx 自动切换 API 上游，保留 WebSocket、流式响应和正常 DSH 入口。

## 6. 参数、网络与资源

| 用途 | 参数入口 |
| --- | --- |
| 平台副本/资源/探针/节点 | `backend/worker/linsight/beat/frontend.{replicaCount,resources,startupProbe,readinessProbe,livenessProbe,nodeSelector,affinity,tolerations}` |
| 基础组件 | 各组件 `resources`、探针、placement 与 `persistence`；内置单实例，Beat 固定 1 |
| 运行控制面 | `runtime.services.resources.{manager,entry,egress,admission}`、`placement`、`probes`、`apiTimeoutSeconds/dnsTimeoutSeconds` |
| 应用预算与系统 Helper | `runtime.execution.memoryBudgetMi/cpuBudgetMillicores/helperResources` |
| 应用调度与阶段期限 | `runtime.execution.placement/timeouts.{image_check,init_phase,health}`、`operationTimeoutSeconds` |
| OCI 组装仓库 | `runtime.offline.imageRepository/imageRegistryEndpoints/registrySecret/insecureRegistry` |

应用和 Helper 的 CPU/内存 requests 与 limits 一致，按有效 init 峰值和并发存活 Pod 合计预约，超预算拒绝创建。Helper 调整不能绕过应用档位/业务授权，运行中的规格和操作总 deadline 不因配置升级/重启重置。镜像检查期限与脚本、Pod、服务端验证配套，支持 1–1800 秒；HTTP 调用期限单独配置。

应用不能直接访问 DNS、平台数据库、集群 API 或其他应用；仅到 Egress Service 的代理端口。Manager 在启动时解析稳定 Service 地址，应用无须 DNS；不维护额外地址注册表。Egress 继续核对平台给出的任务目标、域名/IP 和材料身份，不是任意公网代理。替换 Egress Service 的 ClusterIP 需要停发任务、重启 Manager 并按实际失败恢复，普通 Pod 滚动不会改变 Service 地址。

在线安装仅在既有受控下载阶段允许配置的依赖源。编译/安装隔离阶段和应用运行阶段沿用既有权限；企业包源的转发、证书、认证由运维配置。不支持的依赖源/构建方式应失败并给出原因，不自动回退公网。离线模式 `runtime.offline.enabled: true`，还须按发行清单准备 runtime/preparer/helper/基础服务镜像及依赖材料；仅配置开关不等于材料已准备好。需要推送组装镜像的方式才要求可写 OCI 仓库。

## 7. 手动诊断与验收

默认**没有**环境验收 Job、定期 CronJob、24 小时准入有效期或自动“验收通过”记录。应用仍执行自身镜像、构建、启动和健康检查。`kubectl get pods` 绿色不等于完整业务成功。

需要主动诊断时设置 `runtime.diagnostics.enabled: true` 后正常升级。这只创建独立报告/测试计划 ConfigMap，不触发检查；下载对应 release 的脚本：

```bash
python scripts/verify_k8s_runtime.py --help
# 参数使用该 release 实际生成的名字；先执行只读 baseline。
python scripts/verify_k8s_runtime.py --context company \
  --control-namespace demo --execution-namespace demo-runtime-apps \
  --manager-account ACTUAL_MANAGER_SA --probe-plan ./diagnostic-plan.json
```

`diagnostic-plan` ConfigMap 的 `plan.json` 提供真实名称映射；运维补充 node_name、network_targets、可信 canary_profiles、CA 文件和本机身份凭据后再显式 `--live --write-report`。否定网络检查必须配置正对照，避免把目标宕机当隔离成功。诊断管理员需要受限 impersonate 与测试资源操作权限，不把这些权限授给 Manager。报告存独立 ConfigMap，带策略摘要和检测时间；历史/失败结果只显示，不回写配置、不授权运行。

`--cleanup-expired` 为显式恢复模式：只处理本安装测试资源，重新读取 UID、状态、删除围栏并保留未确认写入者；不能用 `kubectl delete --force` 代替安全回收。没有为失败诊断强行删除 PVC 或绕过 stop finalizer。

正式验收至少检查：首个用户注册/权限、按需 DSH/Gateway 许可证、代码沙箱执行及会话保持、Python/Node/Static 发布、预置镜像外依赖下载/完整构建、卷持久化、并发预算拒绝、退出后再部署与 UID 停止证明。当前源码检查不替代这些真实集群验收。

## 8. 升级、卸载与故障

标准 Chart 尚未对外发布，本期不提供既有 122/其他手工安装迁入路径。未来同一标准 release 升级使用原 `--namespace/release`、原 values 和原 Secret；保留用户 false、语言默认、已冻结组合和 PVC。先备份数据库/对象/卷及凭据，检查兼容 image-set/catalog 后执行普通 `helm upgrade --wait --wait-for-jobs`。不靠重装来升级授权模型，不自动改变原出网策略。

卸载或关闭 Vibe 前先经正常平台流程停止应用、确认数据写入者已停止并备份。应用 Pod/数据不是 Helm 管理的控制器，`helm uninstall` 不等于停止应用或数据回滚。执行 namespace、PVC/PV、签名根、公钥、执行空间拒绝网络和 Admission 配置保留；Admission 服务删除后其执行域变更按 failurePolicy Fail 拒绝。运维在确认没有活动/未知写入者后，才单独审查清理这些保留资源。不要移除隔离规则后遗留运行 Pod。

初始化/迁移失败应停止后续操作，记录失败 Job/Pod 与脱敏日志；回退 Chart 不会回退数据库。只清理本 release 的新增控制资源，数据和凭据保留。所有公共样例不含固定客户 IP、节点名或生产密码。

## 9. 维护者发行流程

`python scripts/package_helm.py --image-set release/image-set.json --catalog release/runtime-catalog --output dist/helm` 只打包 Chart，**不构建镜像、不访问集群**。清单 schema 1 需包含 release/source_revision、runtime_contract=2、gateway_sql_contract=1.8.0；images 必须覆盖平台、基础组件、Gateway、沙箱及全部 runtime/Helper，记录实际 digest、双架构和源码镜像相同 source_revision。catalog_images 必须完整覆盖官方目录的 runtime/preparer 材料。

目录锁文件记录 schema_version=1、release、catalog_sha256；profiles 遵守 RuntimeProfileDefinition，包含 Python3.11、Node20、Static 双架构及合法默认引用。包带完整 image-set/catalog/本地子 Chart 并生成 SHA256 文件。CI 只做源码矩阵检查，使用明确的虚构 fixture，不发布伪造正式包。真实镜像来源、原生架构运行、隔离与持久化证据仍由正式发行流水线另行验证。

发行脚本还要求 image-set 的 source_revision 等于当前 Git HEAD，且镜像/Chart 源码干净；目录按随包 RuntimeProfileDefinition JSON Schema 校验。打包工具依赖 PyYAML 和 jsonschema。测试内虚构清单只验证拒绝/归档路径，不能作为正式镜像证据。

如需 NodePort，设置 `frontend.service.type: NodePort`、`nodePort/clientNodePort`（0 表示自动分配），并把 publicUrl 改为实际外部入口。基础组件可配置 podSecurityContext；内置 Bitnami ES 默认 fsGroup=1001，关闭 mmap，避免要求 Chart 修改宿主 sysctl；需要 mmap 时由运维满足对应 ES 版本的节点要求，再覆盖 extraFlags。真实驱动挂载权限仍在独立集群验收。

私有执行镜像需要先在执行空间放 Registry Secret。若该空间由运维预建，设置 `runtime.namespaceManagement.createExecution: false`，明确并固定 `runtime.execution.installationId`，由运维给专用 Namespace 设置同值 `runtime.bisheng.io/installation` 以及 restricted PSA 标签；不要将共享业务空间作为执行空间。控制空间通过 Helm --namespace 选择。新空间由 Chart 创建时自动带这些标签。

受管配置/运行策略/Nginx/Gateway 配置通过 Pod template checksum 触发正常 Helm 滚动，无手工启动补丁。已有外部 ConfigMap/Secret 内容在 Chart 外变化时，更新 `global.configRevision` 为新的运维版本号后升级，以让进程重新装配配置/读取身份；不要用此参数自动轮换签名根。
