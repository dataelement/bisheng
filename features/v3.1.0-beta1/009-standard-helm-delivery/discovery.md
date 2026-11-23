# 标准 Helm 交付：需求核对与待确认边界

状态：Discovery 已确认。用户于 2026-11-06 明确要求继续简化：取消强制环境预检和 24 小时限制，保留手动诊断及应用发布检查。正式规格见 [spec.md](./spec.md)，规格已于 2026-11-10 确认，进入设计，设计门确认后实施。

核对日期：2026-11-06。源码基线：`feat/3.1.0-beta1@99f81004fd2d2d754290aba223eac3fa7a099b56`。
工作分支：`codex/3.1.0-beta1/standard-helm-delivery`。

## 已确认范围

- 标准 Chart 源码放在公开 `dataelement/bisheng` 仓库，建议沿用 `docker/helm/bisheng` 作为唯一安装入口。
- 资源、超时、节点调度、网络和存储通过 values 配置，并提供 schema 校验。
- 删除 122 IP、主机名、节点名、目录等环境绑定，以及注入 Python 代码的 ConfigMap 启动补丁；正常配置 ConfigMap 保留。
- 基础组件逐项可选，支持外部 MySQL、Redis、对象存储、Elasticsearch、Milvus、OpenFGA 等；不得接管客户既有 release。
- Gateway 可选；Vibe 和代码沙箱默认开启，文档给出关闭方式。
- 可提供带修改提醒的全新示例数据库密码，并支持 existingSecret；真实 122 凭据、许可证及私钥不得进入公开仓库。
- 管理员沿用首次注册成为超管的正常流程，不预建管理员或伪造用户身份。
- 本轮只修改代码、部署文件和说明，不构建/更新镜像，不部署线上。
- 取消强制环境诊断及其报告对运行准入、恢复和入口路由的门槛，不默认创建环境验收 Job/CronJob；取消 24 小时自动失效。
- 保留真实手动诊断及每个应用的镜像、构建、启动和健康检查；实际权限/隔离、资源、UID 停止证明、单写和未知状态数据保护继续生效。

## 1. 安装初始化与预检的用途

这里有两个不同职责：

1. 安装初始化：生成并保留本安装的内部密钥和证书、解析实际 Service 地址、执行所需的受控初始化。
2. 环境安装验收：在运行控制面、Namespace、RBAC、网络策略等已经安装后，验证其隔离和运行能力确实生效，而不只是 Kubernetes API 接受了 YAML。这不是在运行时部署前执行，也不是每个应用的发布预检。

应用发布检查是另一套流程：每次提交后检查镜像、安装/构建依赖、启动该应用并验证健康。它消费执行域 ready 状态，不会每次重跑上述集群能力诊断。
依据：`app_publish/domain/services/publish_pipeline_service.py`、`runtime_manager/operations.py`。

改造前的源码基线强制核对 15 项能力：配额、PSA、准入、状态来源、绑定/删除保护、RBAC、禁止 exec、入站隔离、禁止直连、代理出站、禁止直连 DNS、SQLite 存储、实际 CRI 镜像执行、材料 TLS、平台鉴权。
依据：`src/runtime-manager/runtime_manager/k8s_capabilities.py` 的 `REQUIRED_CHECKS`、`assess_capabilities`。

改造前报告有效期固定为 24 小时；脚本 periodic 模式要求每 6 小时刷新。
依据：同文件 `report_validity`；`scripts/verify_k8s_runtime.py` 的 repeat-seconds 校验。
报告过期会阻止新执行；不会仅因到期主动重启已有应用 Pod。Backend 对报告过期与真实保护失效有单独处理，见 `runtime_operation_service.py`。

影响范围补充：同文件 `route` 在 Kubernetes node.status 非 ready 时返回 unhealthy，故报告过期还可能阻断正常运行应用的新入口访问；不是只影响新发布。
入口地址另由 Service 与 EndpointSlice 的当前 Pod UID/IP 跟踪（`executors/kubernetes.py` 的 `_observed`），24 小时 TTL 不承担 Pod 地址更新或入口保活职责。
所查引入提交、规格和设计只给出固定 86400 秒，没有“必须 24 小时”的业务推导；其用途是避免长期沿用旧环境验证结果的保守新鲜度策略。

独立 installer namespace 的环境验收 Job/CronJob 曾作为候选提出，现已按用户要求排除。手动诊断仍可使用外部运维身份，不向常驻 Manager 增加安装权限。

**初始化现状更正：默认配置下 Backend 确实支持初始化全新 OpenFGA Store/model。**
Settings 和公开 Helm 配置的 environment 均默认 dev；非生产模式在首次获取 OpenFGA 实例时，缺少 Store/model 会在 Redis 锁下 bootstrap。
只有显式 prod/production/production-* 配置才禁止业务进程创建模型，仅发现既有 Store/model。
SQL 的初始权限 Catalog 已有幂等 seed，但依赖上述 Store/model 可用。
依据：`core/openfga/manager.py` 的 `_async_initialize` 与 `permission/application/process_runtime.py` 的 `initialize`。
显式生产模式下，安装流程需要受控初始化全新 Store/model，或验证用户提供的外部已初始化服务；升级不得无条件覆盖既有授权模型，也不通过切换 dev 绕过生产约束。

现有 Backend Alembic 迁移仍在 API entrypoint，默认业务数据仍在 lifespan 初始化。目前没有把 Backend、OpenFGA、Gateway 的全部初始化拆进 Job；Helm 改造本身也不要求如此拆分。
OpenFGA 数据库表结构迁移（服务自身 migrate 命令）与毕昇 Store/授权模型是两类工作，不能混称为模型初始化。

Gateway 本地源码/缓存 main 未发现 Flyway/Liquibase 或建表初始化器；部署配置要求预建库表并提供 `docker/db/init.sql`。选装 Gateway 的标准安装需要接入对应版本的建表机制；关闭时不执行。现有 ApplicationRunner 装载规则不等于创建表。
本地核对范围：`bisheng-gateway` 工作树 `f6160db4`、缓存 `origin/main@62399806`；尚未核验任何线上镜像内部实现。

用户已确认的新合同：运维负责提供合格 CNI/CSI、权限与网络。真实环境诊断保留为可选工具，其结果与业务运行准入解耦；没有诊断报告、诊断失败或超过 24 小时不单独阻断业务。未实测必须显示未检测，不能伪造 cluster-probe 通过证据。

取消的是诊断门槛，运行前的合法配置与实际 API 检查、应用发布检查、Pod UID 证明、单写和业务鉴权继续保留。跨进程的部署保护策略合同需在设计中明确，由 Backend 与 Manager 一致验证，不直接把当前所有 ready/保护位写成 true。

## 2. StorageClass、访问模式与文件系统分别说明

StorageClass 是用户集群已有的存储供应配置；Chart 不要求固定名称或特定厂商。
访问模式属于 PVC 的挂载能力，与文件系统类型是两件事：

| 配置 | 含义 | 本次交付口径 |
| --- | --- | --- |
| RWO | 单节点可读写，同节点可以有多个 Pod | 托管应用数据卷的当前合理默认 |
| RWX | 多节点可同时读写 | 仅在组件确需跨节点共享文件时采用 |
| ext4/xfs | 挂载后呈现的文件系统 | 当前 Vibe 存储校验的产品支持白名单 |

Kubernetes 依据：[PV access modes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes)。

**纠正前置条件：平台统一要求 RWX 不成立。**
122 共享 `/app/data` 是既有部署选择；当前公开 Chart 给 Backend、Worker 分别提供 RWO/emptyDir，架构 C8 要求跨进程权威数据放在 MinIO、数据库或 Redis。
仍须核对遗留本地文件路径，不能凭现有模板推导所有路径已经满足 C8；也不能把 122 共享卷选择变成标准安装必须提供两类 StorageClass。
标准配置应按组件提供 class、size、accessModes、existingClaim 和拓扑限制；是否需要 RWX 由实际共享用途决定。
用户已确认采用本节的简化方向。

**Vibe 数据卷确实存在当前产品限制。**
应用使用持久化 SQLite；应用和 data-helper 在同一 Pod 挂载同一应用 PVC，不要求多节点同时写该卷。准备阶段依次使用 scratch PVC。
依据：`k8s_templates.py` 的生产 Pod/data-helper 模板与 `pvc_template`。

SQLite WAL 对共享内存和文件锁有要求，不支持网络文件系统；RWX/RWO 标签本身无法证明 SQLite 兼容。
依据：[SQLite WAL](https://www.sqlite.org/wal.html)。

`k8s_helper.verify_volume` 和 `k8s_capabilities.storage_checks` 当前只接受 ext4/xfs，并检查真实容量约为申请值的 0.8–1.1 倍。
这是毕昇的保守支持边界，不是 Kubernetes 要求，也不代表 SQLite 只支持这两种文件系统。
容量检查用于拒绝把申请 1Gi 的普通目录暴露成整块宿主盘，防止失去容量边界。
现有预检验证同 Pod 跨进程 flock、SQLite 建表/integrity_check、文件/目录 fsync；不构成跨节点锁或断电耐久性保证。
其他文件系统或共享容量 CSI 如需支持，应增加可验证的锁、持久化和配额合同，不直接删除检查。

新增已确认缺陷：`pvc_template` 和验证工具把空 class 写成 `storageClassName: ""`，实际关闭动态供应，无法按“留空使用集群默认 StorageClass”的预期工作。动态默认与显式静态无 class 模式必须区分，纳入本次修复。

平台 Chart 还有一处已确认缺陷：Linsight 启用持久化时引用 `*-linsight-data`，但 `templates/pvc.yaml` 只生成 Backend/Worker 两个 PVC。需补齐并验证；单角色多个副本跨节点共用 RWO 的组合也须校验，不以 RWO 默认值宣称自动支持横向扩容。

## 3. 官方运行环境模板与应用配置

前次提问中的“运行目录”用词不准确，应称为“运行环境模板清单（runtime profile/catalog）”，不是文件系统目录。

| 对象 | 作用 |
| --- | --- |
| 应用 `bisheng-app.yaml` | 声明 runtime、端口、资源档位及可选 delivery.profile 等应用要求 |
| 平台 runtime profile/catalog | 将语言/版本和架构映射到固定 digest 的运行镜像、准备镜像、ABI、工具链和默认版本 |

应用选择 `python3.11` 后，平台仍需从清单解析可信镜像。用户未指定 profile 时，当前 `RuntimeProfileService.resolve` 查数据库的默认记录；缺失时返回 `profile_unavailable`。

当前 `import_revision`、`set_default` 是超管管理接口，导入记录要求真实 `created_by`，尚无受控系统种子入口。
该权限限制针对平台级模板管理，不意味着部署应用的用户都需要超管。
依据：`runtime_profile_service.py`、`runtime_delivery.py` schema、`app_manifest.py`。

已确认的简化方向：正式发行的默认模板由受控、幂等的系统初始化预置；保留手工导入/修改接口的超管要求。应用继续使用 `bisheng-app.yaml`，管理员无需额外导入官方模板。
前次提出的“首个超管首次登录后导入”只是候选实现，不应作为标准 Helm 的必需用户操作。
系统种子身份、模板来源校验、升级时保留用户默认值仍需设计并确认，不能用伪造 user1 或绕过现有接口的临时 SQL 实现。

**当前没有运行环境模板管理页面。** 两个前端未发现上述 profile API 的页面或调用；系统设置中的资源档位页面修改 CPU/内存，不是运行镜像模板。
当前入口为 `GET/POST /api/v1/runtime/profiles`、`GET /api/v1/runtime/profiles/defaults`、`PUT /api/v1/runtime/profiles/default` 等管理 API。
本次标准交付提供官方默认清单和部署级 values 覆盖，高级定制保留 API；不将尚未存在的前端页面描述成已有能力。新增管理页面属于额外产品范围。

## 后续交付检查

- Chart 与兼容镜像版本需要对应；旧 v3.0.0 digest 不含已合并修复，不能宣称去掉补丁后旧镜像即可完整工作。
- 在线依赖下载、企业镜像源、离线模式分开配置。可写 OCI 仓库只影响 source-image 等相应能力，不应阻塞普通 bundle/image 模式。
- Gateway 关闭时不绑定关闭当前 3.1 原生 DSH 登录；DSH 默认值和附加商业集成分别说明。
- 初装、升级、保留密钥/数据、外部依赖、两个 release 隔离、关闭 Vibe/沙箱、缺失存储/权限、真实预检回收均需覆盖验证。
- 真实集群安装验收需等待兼容镜像和独立测试环境；本轮不将模板检查等同于已完成安装验收。

按 `docs/SDD-Guide.md` §2–3，Discovery 已确认；正式规格已于 2026-11-10 确认；设计门禁和后续实现按仓库流程推进。
