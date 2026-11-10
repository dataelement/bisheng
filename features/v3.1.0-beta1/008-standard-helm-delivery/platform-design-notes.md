# 标准 Helm：平台与依赖设计草案

状态：技术设计输入，待合入正式 design.md 并 review；下述新增合同尚未实现。核对基线为 `feat/3.1.0-beta1@99f81004f`，日期 2026-11-06。

本草案按用户已确认的简化方向编写：只修改源码、部署文件及说明；取消强制集群环境验收及 24 小时报告门槛，保留手动诊断和每次应用发布的构建、镜像、启动与健康检查；默认开启 Vibe 与代码沙箱。取消环境报告门槛不扩大 Backend 的编排权限，也不解除运行中的准入、网络、身份与数据保护。

## 1. 单一安装入口与模板归属

继续以 `docker/helm/bisheng` 为公开 umbrella Chart，平台 API、Frontend、Worker、Linsight、Beat 仍由该 Chart 管理。复用并改进已有 `docker/helm/bisheng-sandbox`；公开新增 runtime 子 Chart 及必要的基础组件子 Chart。`Chart.yaml` 用本地依赖及 condition 逐项开关，发布包包含依赖归档及锁文件，用户不必从私有仓库下载模板。

建议结构：

```text
docker/helm/
  bisheng/                   # 唯一用户安装入口；平台模板、values/schema、README、examples
  bisheng-sandbox/           # 已有代码沙箱，继续作为唯一模板源
  bisheng-runtime/           # Manager、app/egress proxy、admission、执行空间策略
  components/
    mysql/ redis/ minio/ elasticsearch/ milvus/ openfga/ gateway/
```

`bisheng/charts/*.tgz` 仅为依赖打包产物，不维护第二套可编辑模板；不能从 `k8s-product` 连同环境配置直接复制整个目录。该私有仓库以后只保存环境 values、镜像锁及验收记录。

默认控制面与平台、沙箱使用 Helm release namespace。应用执行空间默认由 release 名推导为 `<release>-runtime-apps`，保持独立 namespace、restricted 标签、配额、RBAC 与网络隔离。基础组件默认同 release namespace；支持显式独立 infra namespace，但不接管其他 release 或既有 namespace 的标签。子 Chart 中的 namespace 必须通过统一 helper 显式选择，不能假定父 Chart 的一个值会改变 `.Release.Namespace`。

所有名称、selector、Webhook 名和 ClusterRole 名都包含安装标识；NetworkPolicy 只选择本安装相应组件 Pod。共享 namespace 下禁止对所有 Pod 下发控制面的默认拒绝策略。运行时安装标识从 release/namespace 派生并在升级时保持稳定，不含 IP 或节点名。

## 2. 依赖选择及最小 values 合同

基础组件默认随 Chart 提供单实例；生产 HA 由各组件资源/副本配置或外部服务承担，不将单实例安装说明成高可用。平台必需的每一种服务都必须恰好有一个来源：Chart 内置实例，或明确配置的外部地址。`enabled: false` 表示不部署该依赖，并不表示业务可以没有它。

建议统一字段形状，以下 MySQL 示例仅表达合同，不是已存在的 values：

```yaml
global:
  clusterDomain: cluster.local
  imageRegistry: ""
  imagePullSecrets: []

mysql:
  enabled: true
  external:
    enabled: false
    host: ""
    port: 3306
    tls:
      enabled: false
      existingSecret: ""
  auth:
    database: bisheng
    username: bisheng
    # 演示默认值，首次安装前可修改；不得使用生产环境真实密码作为默认值。
    password: "Bisheng-Demo-ChangeMe!"
    existingSecret: ""
    secretKeys:
      password: password
  resources: {}
  persistence:
    storageClass: null       # 省略 storageClassName，使用集群默认供应器
    size: 20Gi
    existingClaim: ""
  nodeSelector: {}
  affinity: {}
  tolerations: []

gateway:
  enabled: false
  database:
    name: bisheng_gateway
    username: bisheng_gateway
    existingSecret: ""
  license:
    existingSecret: ""
    key: license

runtime:
  enabled: true
  executionNamespace: ""    # 留空按 release 名推导
  profiles:
    source: builtin           # 或 deployment，使用下方只读配置清单
    existingConfigMap: ""
  diagnostics:
    mode: manual             # 不部署强制环境验收 Job/CronJob，不配置报告过期门槛

sandbox:
  enabled: true
  replicaCount: 2
  auth:
    existingSecret: ""       # 留空生成本安装持久化 token
    key: token

config:
  overrides: {}               # 非受管业务配置；不得覆盖同一份连接/开关的第二来源
```

对 Redis、MinIO、Elasticsearch、Milvus、OpenFGA 采用对应 `enabled`、`external`、`auth.existingSecret/secretKeys`、resources、persistence、placement 结构。各服务的地址、协议和认证类型按其真实客户端能力定义，不能强行共用一条万能 URL。无密码服务允许显式匿名配置；不能将缺失 Secret 当成匿名或空密码。

具体校验：

- 内置与 external 同时开启、必需组件两者均未开启、外部地址缺失、Secret key 为空：schema 或模板立即给出字段级错误。
- `existingSecret` 非空时只引用现有 Secret，不创建或更新同名 Secret；内联演示密码不再使用。key 名由 `secretKeys` 映射，Secret 不要求固定部署命名。引用所在 namespace 必须明确，跨 namespace 引用不假装由 Kubernetes 自动支持。
- 密码、URL 中的 `@:/%#`、IPv6、TLS CA、Redis ACL 用户等由配置装配器正确编码；不让用户自己预先进行两次 URL 编码。
- Redis 使用 `auth.username/password` 及平台、Celery、运行时各自的 DB 索引；不固定 DB7/8/10/11/12。DB 索引不是多租户安全边界，同共享实例使用时须由管理员分配。
- 外部 Milvus 不再部署其内置 etcd/对象存储。内置 Milvus 与平台对象存储使用不同 bucket/prefix，不隐式公用业务目录；其 etcd 和对象存储来源也必须显式关联，防止关闭一个子组件却遗留另一套依赖。
- 外部平台数据库只要求目标库范围的必要权限，不默认要求 root 或创建其他业务库。Gateway、OpenFGA 分别使用独立库和账号。客户外部数据库由运维预先提供；Chart 不默默执行 CREATE DATABASE/GRANT。
- 内置 MySQL 则由本 release 的显式初始化配置创建平台、OpenFGA 及已启用 Gateway 的独立库和库级账号，数据库账号不能共用平台账号。该管理权限只供内置库初始化使用，不下发给普通 Backend。后续升级才开启 Gateway 的情况也要有可重入补建机制，不能仅依赖新数据目录执行一次的 MySQL initdb.d。
- 平台的数据库合同仍保留外部 DM8 路径；MySQL 子 Chart 的开关不等于取消 C2。OpenFGA 的 datastore 依其官方支持配置，不能把平台 DM8 连接直接传给 OpenFGA。正式 design 需为此提供清晰的外部数据库示例。

Gateway 开关属于功能选择，与基础组件“内置或外部”的来源选择分开。后续若支持外部 Gateway，应增加显式 external 模式并验证许可/协议，不把一个任意 URL 当成兼容网关。

## 3. Backend 配置生成与凭据

当前 `ConfigService` 支持 YAML `!env`，但 MySQL/Redis URL 里的密码仍按现行 Fernet 合同解密。不能直接把普通 Secret 的明文密码拼进原 YAML URL，否则外部凭据可能无法加载。相关实现见 `common/services/config_service.py::load_settings_from_yaml` 和 `core/config/settings.py::decrypt_database_url/decrypt_redis_url`。

建议新增镜像内随发行版交付的通用配置装配入口：读取普通 ConfigMap 中的非秘密结构、投射 Secret 文件及固定清单，按现行 Settings 合同生成 Pod 私有 `emptyDir` 内的配置，然后启动原有进程。该入口只处理配置，不访问数据库或 Kubernetes API；不能以 ConfigMap 挂载 Python 代码替换镜像模块。此入口和代码一起测试、发版，不维护环境分叉。

装配器统一负责依赖地址推导、一次 URL 编码、必要的现有加密格式、运行时内部地址、沙箱 ordinal DNS、功能开关及 TLS 文件路径。全部进程角色使用相同装配规则。原始密码不进入普通 ConfigMap、日志、NOTES、渲染检查输出或证据文件。`helm template` 不需要读取线上 Secret；运行时缺失的引用在 Pod 启动时准确报 key/path 错误。

`config.overrides` 不允许覆写已由上述 values 管理的连接、沙箱 token/端点、运行时控制地址等字段，否则拒绝启动；这避免 values 显示开启功能而最终 YAML 反向关闭。高级完整配置入口若保留，应是单独互斥模式，并明确由用户承担同样的必需字段，不能悄悄叠加三套配置来源。

## 4. 默认功能与官方模板

`runtime.enabled: true` 同时控制运行组件、平台 `app_runtime.enabled` 与前端功能暴露；不能只有工作负载存在而产品入口仍关。关闭时去掉 Vibe 专属组件/路由与默认初始化，禁用新的托管应用入口，保留数据库及已有应用数据，不自动清理用户 PVC。

`sandbox.enabled: true` 关联沙箱 StatefulSet、同一 token、按副本数生成的 ordinal DNS 以及 API/Worker/Linsight 的访问配置。代码节点的 DB `workflow.code_node_enabled` 是另一层默认设置：首次创建或配置键缺失时种子默认开启；升级时不覆写管理员明确设置的 false。关闭沙箱要同时关闭新执行入口，不让代码节点继续显示可用却连向不存在的 runner；不清理历史数据或直接中断已有执行。

`open_platform.enabled` 与 `dsh.enabled` 为独立产品开关，不能与 Gateway 或 Vibe 简单绑定。当前 3.1 DSH 是原生身份/会话流程；关闭 Gateway 不应关闭 DSH 登录。DSH 的默认开关不因本需求擅自改变；开启时校验平台外部 URL 等它实际需要的字段。

官方 runtime profile/catalog 是 Python、Node、Static 对应的固定 digest 运行/准备镜像、平台架构、ABI 与工具链清单。它不是本地目录，也不是应用的 `bisheng-app.yaml`。应用可省略 `delivery.profile`，从语言默认记录解析；其启动 argv/端口仍由应用配置决定。

建议由镜像携带与发行版匹配、带内容校验的官方清单，系统初始化服务幂等补齐记录及缺失语言默认值；`runtime.profiles.source: deployment` 可读取运维提交的完整、经 schema 校验的自定义清单。不能使用未发布的假 digest 或把单架构镜像标成支持双架构的官方清单。

当前记录 `created_by` 必填且管理 API 要求真实超管。因此新增系统种子需要显式来源合同，例如新增 `origin=system|user`，允许 system 记录 `created_by=NULL`，普通 API 创建的 user 记录仍必须有真实 actor；后台种子入口不暴露为匿名 HTTP API，也不允许用户在普通导入请求里指定 system 来源。新增字段及回填必须遵守 C2。严禁创建假 user1 或让安装任务注册管理员。

同 code/revision 的相同内容重复执行为 no-op；不同内容报不可变冲突。升级可增加新 revision，不覆盖旧版本、已冻结 delivery 或用户选择的默认值。替换自定义镜像/仓库导致定义内容变化时要使用新 revision；不能静默重写原记录。高级手工导入/设默认仍保留真实超管 API 权限。

当前没有运行环境模板管理页面；系统设置里的资源档位不是镜像模板。本次只提供官方预置、values 清单入口与现有管理 API，不虚构已有 UI，也不顺带扩展前端管理产品。

管理员继续使用正常注册流程，第一个成功注册用户成为超管。配置模板不提供 `admin` 注册功能，初始化任务不创建平台用户或服务账号替代管理员。

## 5. 初始化职责与生产 OpenFGA

保留 Backend 现有 API entrypoint 的 Alembic 迁移及 lifespan 的默认业务数据初始化，不因采用 Helm 把它们统统拆成 Job。多 API 副本并行迁移仍需明确序列化/等待合同；不能仅假设单副本就永远安全，正式实现可使用受限数据库锁或单独迁移模式，并验证失败时不启动旧 schema 上的 API。

默认配置曾使用 `environment=dev`，此时 Backend 可自动 bootstrap 新 OpenFGA Store/model；生产模式只发现既有模型。标准生产交付不通过改成 dev 或 `force_write_model` 绕过 [C4](../../../docs/constitution.md#c4-permissions--verified-business-target--unified-action-runtime)。

显式生产初装采用独立 operational 初始化命令，可复用 Backend 镜像，并由按需一次 Job 调用。它与已取消的环境诊断 Job 是两类职责。命令只在目标 Store/model 为空且未发现既有权限发布/迁移数据时创建指定 Store 及当前模型；现有匹配模型 no-op；多个同名 Store、既有不匹配模型、旧权限数据或部分失败状态均明确失败，不自动覆盖/升级授权模型。复用权限模块的官方模型和校验，不在 Chart 里手写另一份模型 JSON。

普通 Backend runtime 始终只发现/验证生产模型；SQL 初始权限 Catalog 沿用已存在的幂等种子。外部 OpenFGA 可选择由同一 operational 命令初始化本安装独立 Store，或要求运维预先提供；无创建权限时给出清晰错误，不扩展运行期 SA/RBAC。

OpenFGA 自身的 datastore schema migrate 与毕昇授权 Store/model 初始化不同：前者由 OpenFGA 对应版本命令执行，后者由上述权限初始化入口执行。不能只建 MySQL 空库就认为两者已经完成。

初始化 Job 的依赖只包含服务已可访问、目标数据库与所需凭据；不等待 Backend readiness，避免 Backend 等初始化而 post-install hook 又等 Backend 的 `--wait` 死锁。可使用正常 Job 和进程就绪等待，不要求独立 installer namespace。Job 名/配置版本、超时、退避与保留诊断均参数化；既有模型冲突必须停止，不提交伪造成功结果。

Gateway 源码核对没有证明已有 Flyway/Liquibase 自动建表；选装时需要接入对应发行版提供的 schema 初始化机制。建议单独可重入初始化命令或 Job，只在 `gateway.enabled` 时生成，作用域限专用库；外部预建 schema 允许显式跳过。该路径不得复制本地旧 SQL 冒充任意 Gateway 镜像的最新初始化脚本。许可由用户 Secret 提供，不生成许可证；未提供时是否允许启动降级需在文档准确说明镜像既有行为。

## 6. 密钥、证书与数据存续

- 演示数据库/Redis 密码可以在 values 中给全新默认值并加修改注释，这是用户批准的部署示例；不得把示例密码写进业务代码或抄入现网凭据。
- 内部 HMAC、JWT/签名 seed、sandbox token、材料 CA 与服务器证书应每安装生成并保持，不能使用所有安装通用的演示密钥。优先允许 `existingSecret`；Chart 管理的 Secret 用稳定名称和明确归属，在升级/回滚复用，不因模板随机函数触发轮换。
- CA、签名根及数据恢复密钥必须在卸载时保留或由外部 Secret 持有；重新安装的恢复流程要能识别 retained Secret 归属。key/CA 轮换是显式操作，不与普通资源参数修改混在一起。
- Webhook caBundle、运行时信任根、平台/Manager 的材料服务证书必须来自同一安装的有效信任链。证书 SAN 从 Service DNS 与可配置 clusterDomain 推导；不含 122 IP。设置过期提示与显式轮换说明。
- 新 release 无权修改其他 release 的 Secret、PVC 或 namespace。关闭可选组件、失败回退和卸载不自动 DROP DATABASE、删除业务 PVC 或执行广域 Secret 清理。
- kubelet imagePullSecrets 只负责拉镜像；运行时访问 OCI 元数据及源码镜像发布所需凭据分别声明。可写仓库不是 bundle/image 模式的前置条件，不能阻塞默认普通应用交付。

## 7. NGINX 与可选 Gateway 路由

公开 Chart 当前只有 SPAs、通用 API 和对象存储代理，需要补齐 `/apps/` 与内部运行时材料路径。路由选择由 helper 推导，不能在 Gateway 关闭后残留指向不存在 Service 的 upstream。

| 路径/用途 | Gateway 关闭 | Gateway 开启 |
| --- | --- | --- |
| `/`、`/workspace/` | Frontend 两套 SPA | 相同 |
| 普通 `/api/` 与 `/workspace/api/` | Backend | 根据商业 Gateway 契约经 Gateway 到 Backend |
| `/apps/`、预览及其 WebSocket | app-proxy | app-proxy，沿用平台身份与入口鉴权 |
| 平台/Manager 内部材料与控制协议 | 内部 HTTPS 直达 Backend | 内部 HTTPS 直达 Backend，不误套浏览器 Gateway 逻辑 |
| 对象存储下载 | 按配置协议代理或使用外部直链 | 相同 |

内部材料协议已有 `/api/v1/internal/app-runtime/v2/...` 路由，流式上传下载需要显式超时、body-size 与 buffer 配置，并保持请求签名、原始 Host/协议含义。内部路径使用内部专用 Service/监听或明确访问限制，不因添加公网 location 暴露整个 internal API。具体白名单由实际 Manager 调用链和请求认证测试确定，不用宽泛前缀绕过权限。

应用 `/apps/` 匹配优先于 SPA fallback，保留 app-proxy 自身的入口授权、平台不可用页和预览授权，不能直接代理任意应用 Pod 绕过它。WebSocket/SSE 的 Upgrade、Connection、缓存和 read timeout 参数化；对象存储代理保留 SigV4 所需 Host，支持 HTTPS 和用户 CA。

所有外部地址通过 `publicUrl`/Ingress/Service 配置，NodePort 作为可选暴露模式，不固定 30080。内部 URL 由名称/namespace/clusterDomain 生成；不把浏览器访问地址硬用作 Pod 内材料流量地址。

## 8. 存储与发布检查

平台 API/Worker/Linsight 的本地目录默认每 Pod 独立、可限额的缓存 `emptyDir`；可选组件独立 RWO 或 existingClaim，RWX 仅作为有实际共享用途的可选模式，不是标准 Helm 安装前提。权威文件按 C8 存入 MinIO/数据库/Redis。现有 Linsight 缺 PVC 和单个 RWO 被跨节点多副本共用的问题必须修复/校验，不能用 RWX 强制要求掩盖。

托管应用的数据卷独立于上述平台缓存。保留当前 SQLite/文件锁/容量边界的真实支持合同，资源值、存储 class、容量、访问模式、执行节点与临时存储均参数化；`storageClass: null` 表示省略字段，`""` 表示显式无 class 的静态模式，不混为“集群默认”。不自动格式化宿主盘或以任意 hostPath 替代容量受控卷。

不再把集群环境实测报告的存在或年龄作为发布/入口放行条件；也不生成一份“全部通过”的假报告。保留发布时真实的镜像可用性、拉取认证、依赖安装/构建、应用启动与健康，以及运行中的 Pod 身份、准入和数据保护。手动诊断结果只用于排障，清晰报告限制，不改写业务成功状态。更完整的运行时 readiness 改造由 runtime 设计定义。

## 9. 最小验证矩阵

| 场景 | 必须验证的结果 |
| --- | --- |
| 默认值与 lint/template/schema | 内置基础组件、Vibe、沙箱存在；Gateway 缺席；无 122 IP/节点/目录，无 Python 启动补丁 |
| 每个依赖改 external | 对应内置 Workload/PVC/凭据不再创建，地址与现有 Secret 引用正确，无多余 etcd/MinIO |
| 两套 release | names、selectors、Webhook、namespace、Secret、网络策略隔离，不能修改另一 release |
| 关闭 Vibe、沙箱、Gateway | 组件与入口一致；正常平台/DSH 按各自开关工作；数据/PVC 保留 |
| 特殊字符、Redis ACL、IPv6/TLS | 配置可加载且编码一次；缺 Secret/key/CA 报准确错误；日志不含凭据 |
| 多副本、迁移失败 | 迁移不会竞争破坏 schema；失败拒绝启动，Worker 不运行在未迁移结构上 |
| prod 空 OpenFGA 初始化 | operational init 后正常启动；runtime 本身不写模型；重复执行 no-op；旧数据/模型冲突 fail closed |
| profile 系统种子 | 无平台用户也能预置，正常首次注册为超管；不可变冲突报错；升级保留用户默认和冻结 delivery |
| 升级/回滚/卸载重装 | 内部 token/签名根/CA 保持，数据不丢；外部 Secret 不改写；显式轮换另行验证 |
| 平台缓存分节点 | API/Worker/Linsight 独立缓存覆盖上传、知识处理、工作流文件、Linsight 技能与产物；记录遗留本地路径缺陷 |
| 真实应用发布 | Python/Node 各装一个基础镜像未带依赖，Static 启动；镜像认证失败、构建超时、PVC/健康失败可诊断 |
| 无环境报告及长时间运行 | 不因缺报告或经过 24h 阻断发布、入口；实际镜像/构建/健康失败仍拒绝 |

本轮不能用 lint/template 成功宣称安装验收完成：真实 fresh-install/升级及 Gateway schema/许可集成需要与源码匹配的正式镜像和独立测试集群。不得覆盖既有 v3.0.0 digest，也不得把 122 热补丁复制为正式交付。

## 10. 代码锚点与待正式 review 的事项

- 平台 Chart：`docker/helm/bisheng/{Chart.yaml,values.yaml,templates}`；沙箱：`docker/helm/bisheng-sandbox`。
- 默认功能与配置加载：`src/backend/bisheng/core/config/app_runtime.py`、`core/config/settings.py`、`common/services/config_service.py`、`bisheng/initdb_config.yaml`。
- profile：`app_runtime/domain/{schemas,models}/runtime_delivery.py`、`domain/services/runtime_profile_service.py`、`api/endpoints/runtime_management.py`。
- 初始化：`src/backend/entrypoint.sh`、`bisheng/main.py::lifespan`、`core/openfga/{manager,discovery}.py`、`permission/application/{process_runtime,catalog_bootstrap}.py`。
- 路由：`app_runtime/api/endpoints/{runtime_delivery,internal_app_proxy}.py`；当前普通 NGINX 模板 `docker/helm/bisheng/templates/configmap-nginx.yaml`。
- Gateway 仅核验本地工作树 `f6160db4` 与缓存 main `62399806` 的配置/依赖及建表约定，不据此证明线上镜像内容；对应镜像的 schema 版本与分发权限仍需取得确证。

正式 design review 重点：依赖 field/name 统一、系统 profile 来源及 C2 迁移、生产 operational init 的新旧安装判定和失败恢复、Secret/CA 生命周期、NGINX 商业 Gateway 路由白名单、迁移序列化、匹配镜像发行清单。以上是需要实现和验证的技术边界，不额外要求用户批准常规可逆工作，也不重复询问已确认的简化方向。
