# Design: 标准 Helm 交付与可选环境诊断

**状态**：`sdd-review design` 已审查通过，待用户确认；本文描述选定的实施方案，不表示代码已实现或集群已验收。
**版本**：v3.1.0-beta1 / F008。**更新**：2026-11-10。
**关联**：[已确认规格](./spec.md) · [规格确认记录](./spec-confirmation.md) · [Vibe 兼容审查](./vibe-compatibility-review.md) · [版本契约](../release-contract.md)。
**源码基线**：独立分支 `codex/3.1.0-beta1/standard-helm-delivery@90fa8fb953`，已合入发版线 `be67ce5b16`。从原核查基线 `99f81004` 到此发版线，Runtime、Backend app_runtime、平台配置、现有 Chart 与诊断脚本没有相关代码漂移。F007 已由项目同步功能占用，本特性顺延 F008，26 条 AC 正文不变。

## 1. 目标与非目标

将公开仓库的 Chart 整合为一次 Helm 安装入口，按参数部署平台、可选基础组件/Gateway、默认 Vibe/代码沙箱。将 Kubernetes 环境诊断变成显式运维工具，运行准入依据受信配置和实际运行状态，不依赖报告或 24 小时续期。

保持发布必审、冻结版本/资源、网络和权限隔离、精确 UID 停止证明及单写数据保护。F114 的六动作、具体租户、恢复 `edit`/涉及正式启动另需 `publish` 继续优先于早期 owner-only 条款。

本轮不构建/推送镜像、不部署线上、不合并旧 122 release、不迁移其业务数据，不安装 CSI/CNI 或格式化磁盘，不新增模板管理页面。必要密钥/数据库初始化与已取消的环境验收是两件事：不创建环境验收 Job/CronJob，不在启动时自动执行 15 项环境诊断。

## 2. 关键约束

遵循 [constitution](../../../docs/constitution.md) C1–C8，以及已确认 spec §3.1 的后继合同。Backend 不取得 Kubernetes/Docker 凭据；生产运行进程不写 OpenFGA 模型。新增数据库字段和初始化操作同时兼容 MySQL/DM8。

- 配置版本、运行控制协议版本和应用清单版本独立：新部署配置为 v2；运行控制仍为现有 v2；清单 v1 兼容不恢复已退役控制协议 v1。
- 应用主容器来自 ResourceTier/冻结版本。Helm 调整控制面、系统 Helper、执行域总配额及合法调度条件，不能为应用另建绕过档位的资源入口。
- 原操作绝对期限、冻结模板、UID/RV 和停止历史不能因参数调整或服务重启重置。
- 诊断缺失、失败、老化不改变业务资格；真实配置/API/材料/镜像/应用失败仍按其原链路处理。诊断不能伪造成功，也不取得业务停用权限。
- 平台跨进程权威内容在数据库/Redis/对象存储，本地文件仅缓存；应用 SQLite PVC 是独立持久化合同。
- 现有 v3.0.0 镜像不包含新合同。代码交付与正式镜像、发行目录、真实集群证据分别验收，不编造 digest 或复用 122 非官方目录充当官方发行。

## 3. 方案对比与选定

| 决策 | 选定方案及原因 | 被否方案 / 重新考虑条件 |
| --- | --- | --- |
| 诊断与准入 | 单一 `operator-configured` 来源：Backend 验证本节点部署配置，Manager 报告真实控制链路；诊断单独展示。符合用户确认，不给报告续期权 | 不采用默认 `ready=true`、假通过报告或默认 installer 巡检。若未来产品要求持续实测，再立新合同，不隐藏恢复旧门槛 |
| 策略一致性 | 同一策略文件给 Backend/Manager/Admission；Backend 为新操作冻结策略和摘要，后续按冻结快照执行 | 不让每层从当前 values 分别猜参数，不在对账时用新配置重画旧 Pod。跨版本 schema 必须走显式适配 |
| Chart 唯一源码 | 父 Chart 仍为 `docker/helm/bisheng`；复用两个现有本地子 Chart，基础组件使用父 Chart 条件模板 | 不复制私有 122 Chart 或维护第二份 Runtime 模板。若未来复用规模确需独立基础组件包，再提取版本化子 Chart |
| 初始化 | Helm 正常资源中的一次性密钥派生及 Backend operational 初始化，复用正式镜像和原迁移服务；业务进程等待初始化版本再启动 | 不用 ConfigMap Python 启动补丁，不让 Manager 自检、自改安全根，不把授权模型写入普通生产 lifespan |
| 密钥存续 | Helm 管理的随机 seed/HMAC/CA 首装生成、升级保留；外部 Secret 优先。公钥派生 Job 只有指定 CM 的 get/patch 权 | 不给 Job 宽泛 Secret create、Pod create 或 webhook 修改权；不让普通 Manager 写数据公钥。显式轮换单独操作 |
| 官方模板 | 受信发行目录的受控系统种子，仅补缺项；人工入口仍真实超管，历史不可变 | 不自动导入任意 values/用户上传的目录，不伪造 user1，不原地重写旧镜像仓库引用 |
| 网络地址 | 内部控制/材料用 Service DNS HTTPS；应用代理 IP 由 Manager 读取指定 Egress Service 并冻结 | 应用 Pod 仍禁 DNS/ServiceLinks，不能用 FQDN 简单替换代理 IP。无需 installer 发现 IP 或 Backend 集群权限 |
| 存储 | 各用途配置 StorageClass/PVC；平台独立缓存，应用有界文件系统 RWO；静态池显式选用 | 不统一强制 RWX，不将宿主普通目录当有界卷。扩展 CSI/文件系统须另有容量/锁/持久化验证 |

重新考虑的触发条件分别为：产品重新要求持续实测（诊断）、运行协议无法承载冻结策略（策略）、客户明确禁止初始化 Job（改由运维执行同一正式初始化命令）、显式密钥轮换或更换 PKI（密钥）、新增官方来源/模板管理产品（种子）、应用 DNS/Service 拓扑合同变化（网络）、取得更多 CSI 配额和 SQLite 兼容证据（存储）、稳定多消费者需要独立基础组件包（Chart）。触发前不预先引入这些额外部署形态。

## 4. 系统现状与目标实施合同

### 4.1 已核实的现状

- `k8s_capabilities.assess_capabilities` 由 15 项报告和 86400 秒年龄计算 ready；`operations.heartbeat`、Backend `_node_report/_protection_update` 消费它；Backend `route` 将非 ready 的 Kubernetes 节点视作 unhealthy。
- `RuntimeKubernetesRepository.bind_resource` 在首次 UID 绑定时固化保护历史；停止确认同时要求历史位和当前保护位。只删报告判断会破坏清理/恢复。
- Helper 资源、镜像检查和启动阶段时间、Linux/架构 selector 在多层固定校验；准备/数据/正式实例的预约也有固定开销。
- 公开平台 Chart 没有基础组件依赖，沙箱开关未实际安装 Code Runner；Linsight 引用的 PVC 没有生成；Runtime 的名称/控制 namespace 策略及 Egress IP 固定。
- 全局 profile 目前只有超管 API，无前端页面；`created_by` 必填。生产 OpenFGA 仅发现/验证现有模型；默认 dev 的自动创建不能作为生产安装办法。

以下各节是拟实施目标；不能据此宣称上述源码已改变。

### 4.2 Chart 源码、命名和 values

唯一入口 `docker/helm/bisheng/Chart.yaml` 增加固定版本依赖：

| 依赖 | 唯一源码 | 条件 |
| --- | --- | --- |
| `name: bisheng-app-runtime, alias: runtime` | `file://../../../deploy/kubernetes/app-runtime` | `runtime.enabled` |
| `name: bisheng-sandbox, alias: sandbox` | `file://../bisheng-sandbox` | `sandbox.enabled` |

`Chart.lock` 固定版本；打包脚本从源目录生成 `charts/*.tgz` 并校验内容一致。发行父包内置依赖，安装者不必在线拉 Chart；源码仓库不维护第二份可编辑模板。基础组件首版在父 Chart 内按条件生成单实例参考资源，不引入在线第三方 Chart 依赖，不宣称参考安装具有 HA。

values 主合同：

| 组 | 关键字段 / 默认语义 |
| --- | --- |
| `global` | `imageRegistry`、`imagePullSecrets`、`clusterDomain=cluster.local`、通用 placement；镜像引用由正式 image-set 锁定 |
| `service` / `ingress` | 默认 ClusterIP；NodePort/Ingress 显式开启，NodePort 不固定；`publicUrl` 供需要绝对地址的功能使用，DSH 启用时必须合法 |
| `backend/worker/linsight/beat/frontend` | 各自 `replicaCount`、resources、startup/readiness/liveness、nodeSelector/affinity/tolerations、缓存/PVC、额外非秘密配置 |
| `database` | 平台 `engine=mysql\|dm8`、连接绑定；DM8 为 external。平台数据库与是否创建 MySQL 实例分开 |
| `mysql/redis/minio/elasticsearch/milvus/openfga` | 各自 `enabled`、`external`、`auth.existingSecret`、`auth.secretKeys`、resources/placement/persistence；关闭内置必须提供合法外部绑定 |
| `gateway` | `enabled=false`；独立镜像、库/账号、配置及 license Secret；关闭不创建该组件/初始化/悬空路由 |
| `runtime` | 新装 enabled=true；control 默认 release namespace；execution namespace 默认 `<fullname>-runtime-apps`；策略、镜像、Helper、网络、存储及包源 |
| `sandbox` | 新装 `enabled=true, replicaCount=2`；逐 ordinal DNS；`token.existingSecret/existingSecretKey` 与子 Chart 同名；升级不覆盖 DB 或用户配置 |
| `dsh/openPlatform` | 独立开关，保留其既有默认与语义，不因 Gateway/Vibe 默认值顺带开启 |
| `bootstrap` | 有限等待/执行预算、日志保留、必要初始化开关；没有环境验收或定时刷新配置 |

所有普通工作负载单副本起步；Admission 默认 2，Code Runner 默认 2。基础组件资源的参考默认值及镜像组合随发行 image-set 提供；代码/模板 fixture 不构成性能承诺。系统 Helper 首轮默认 requests=limits：镜像检查 1 CPU/256Mi，下载/上传/数据维护 100m/128Mi，依赖安装/组装 1 CPU/1Gi，在线数据 sidecar 25m/128Mi；本期执行域 Helper 的 CPU/内存 requests 与 limits 必须按 quantity 解析后相等，只参数化其共同额度；不引入未计入承诺的 burst。控制面 Deployment 仍可分别配置。预约同步计算。默认 image-check 120 秒、单 init 90 秒、健康 90 秒、清理 900 秒；实际执行始终取原操作剩余期限，正常前提下 300 秒恢复承诺不因单项窗口相加而延长。

父子字段不再另造 `sandbox.replicas` 或平行配置树：父 `.Values.runtime` 完整传入 alias runtime，`.Values.sandbox` 完整传入 alias sandbox。Runtime 保留 `services.managerReplicas/entryReplicas/egressReplicas/admissionReplicas`；新增每用途配置使用 `execution.helperResources/timeouts/placement`，控制面使用 `services.resources/probes/placement`，StorageClass 使用 `storage.className` 三态。父端点生成与子 Chart 共同调用其导出的纯命名 helper，输入同一 `.Release.Name/.Release.Namespace`、明确覆盖名和 `global.clusterDomain`，不各自拼 DNS 或 Secret 名。使用数量/调度/端口的非默认值验证传递，禁止只验证条件开关。

资源名使用 release namespace/release/component 的稳定短 hash，长名保留 hash 和组件后缀。所有 selector 同时包含安装身份与组件。集群级 webhook 名包含 release namespace，支持不同 namespace 中同名 release。
控制 namespace 创建/PSA 标签管理默认关闭；执行域专用，保留 Restricted/配额/准入，可选择运维已创建的专用 namespace。共享 namespace 的控制面 NetworkPolicy 只选本 release 对应组件，不使用影响全 namespace 的空 selector。外部基础组件不被 adopt。

外部凭据 Secret 必须存在于消费者所在 namespace；连接外部 `infra` Service 不代表能跨 namespace 引用它的 Secret。文档说明复制最小应用凭据或在对应 namespace 提供已有 Secret，不让程序自动读取其他 release 的 root Secret。
Redis 的模式和索引单独校验：cluster 只能 DB0，不将 122 的 DB10/11/12 当通用默认；库号隔离也不替代 key 前缀/权限。MySQL 为平台/OpenFGA/Gateway 分别建库和库级账号；外部模式由运维预建且不给初始化程序外部 root。Milvus external 时不建其 etcd/对象存储；内置时显式配置它的依赖，并使用独立 bucket/范围账号。外部绑定要求按实际消费者计算：平台选 DM8、OpenFGA 选 external 且 Gateway 关闭时，未被消费的 MySQL 不要求填虚假外部配置。

### 4.3 受信策略与冻结

同一份 `runtime-policy.json` 作为只读配置分发给 Backend/Manager/Admission；不含 Secret 内容。配置 schema 版本为 2，控制协议仍为 v2。

```text
schema_version: 2
mode: operator-configured
scope: installation_id / node_id / cluster_id / control_namespace / execution_namespace / platform
execution_budget: memory_mb / cpu_millicores / max_pods / max_parallel_tasks / max_data_sessions
protection: status_policy_revision / guard_contract_version / status_writer_rules / binding_delete_rules / trusted_writers
images: manager/helper/assembler 引用及兼容版本
helper_resources: purpose -> requests/limits
timeouts: image_check/init_phase/health/request/cleanup
placement: nodeSelector/affinity/tolerations
sandbox: requested/runtime_classes
network: egress_service 身份/端口、允许CIDR、API/平台目标和包源
storage: class_mode/class_name/access_mode/sizes/filesystem/static_pool
delivery: enabled_modes/package_sources/registry_secret_refs
```

Chart 生成确定的 UTF-8 JSON 文件，摘要定义为 **SHA256(文件原始字节)**；换行也属于文件内容。Backend 保留并冻结这些原始字节，避免 Go/Python 二次序列化产生不同摘要。JSON 解析拒绝重复键、非有限数字、未知必需合同版本和非法作用域。`execution_budget` 与 Namespace 配额、并发配置同源，Backend 核对期望总预算，不接受 Manager 自报扩大；默认并发继承当前服务上限，不开放不受预算约束的任务并发。

Backend `AppRuntimeConf` 增加 `runtime_kubernetes_nodes[node_id]`，每项引用期望 policy 文件。Backend 根据已配置文件计算摘要，而不是接受 Manager 自报期望值。文件只能由部署配置提供，不开放给应用包/API 调用者修改。
Manager 心跳增加：

```text
capabilities.configuration:
  version: 2
  source: operator-configured
  policy_digest: <SHA256 of policy bytes>
  protection_baseline_digest: <canonical protection subset hash>
  state: configured | invalid
```

Backend 核对 Manager HMAC 角色、node_id、scope、策略摘要、预算及实际控制状态；不匹配明确拒绝新编排。`probe_report` 仅为独立诊断对象：无报告为 `state=not_run, observed_at=null, checks=[]`；失败显示真实失败；旧摘要显示针对旧配置，时间只用于展示。不能制造 cluster-probe 记录或将“运维已配置”显示为“实测通过”。

配置文件与诊断文件分离：owned policy CM 的 `runtime-policy.json` 不含 probe_report；可选独立 diagnostic CM 的 `report.json` 记录 `policy_digest`、时间和真实 checks。Manager 分别只读挂载；诊断卷可缺省，不阻塞普通启动。verifier 的 `--write-report` 仅 CAS 更新独立 CM，不能改变 policy 字节/摘要。原 schema1 报告可只读显示为旧配置诊断，不成为 v2 运行权威。

创建 operation 时由 Backend 写入保留字段 `payload.execution_policy_json`（原文件字节的 UTF-8 字符串）及 `execution_policy_digest`。拒绝调用方提交同名字段；Manager 解码校验并使用该快照。Backend 的 resource intention、Manager PodPlan 和 Admission CREATE/普通 UPDATE 校验均消费该操作的冻结配置；已保存 approved template 为资源对账的权威。

status/binding/delete 使用稳定保护基线和已有 UID/身份围栏，不在 Pod status 更新时调用 Backend，不用新 policy 重解释旧 Pod。新策略只用于新操作，修改 values 不自动重建应用、不修改审批/运行版本。

资源预约按真正同时存在的容器有效 requests 计算：普通容器合计与最大 init 需求取 max；本期执行域 requests=limits，故同时是承诺额度。相邻生命周期可能重叠的 Helper/旧实例分别占用，不能只增加 Pod CPU 而保留旧预约。应用主容器依旧取冻结 ResourceTier；档位部署初始值只补缺项，管理员修改后不覆盖。

镜像检查内部期限、Pod activeDeadlineSeconds、Backend/Admission 上限共同取冻结策略和原剩余 deadline。Pod 创建时间、前一 init finishedAt、阶段起点跨重启不重置。票据寿命、租约安全规则、UID 围栏不作为任意关闭的调参项。
调度将 Linux/架构必要条件与运维 selector/affinity/tolerations 取交集，不允许 `nodeName`、hostPath、提权或用户任意 PodSpec，不绕过 PV nodeAffinity。

### 4.4 保护历史、入口与迁移

`policy_digest` 覆盖完整新操作配置。保护摘要精确输入为 `{"schema_version":2,"scope":{installation_id,node_id,cluster_id,execution_namespace},"protection":{status_policy_revision,guard_contract_version,status_writer_rules,binding_delete_rules,trusted_writers}}`；这些键不得省略。保护规则字段来自版本化安全合同，不是可关闭的任意开关；控制账号的完整身份属于对应规则。无序身份集合去重排序后，以 `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True, allow_nan=False)` 的 UTF-8、无尾换行计算 SHA256，Backend/Manager 使用相同测试向量。普通资源、超时、镜像或调度偏好不在保护摘要中，不清除旧 UID 历史。

- 首次绑定新 UID 时，以 Backend 已认可的保护配置建立历史位。其来源标为 operator-configured，不声称刚做过实测。
- 旧 false/unknown 永不因模式升级、配置声明、心跳恢复或诊断成功补成 true；未知写入者仍阻止新写入、清卷和预约释放。
- 真实保护语义/身份变化或确认保护断档按原保守规则处理；暂时无法读取配置不授予当前停止权，也不能把恢复读取当作历史修复。
- `never_scheduled`、`kubelet_terminal` 仍要求精确 UID/RV/删除时间和当前/历史保护；404、替换 UID、NodeLost、Unknown 不等于停止。

将“可接受新编排”与“已确认 serving 路由”分开。`node.status` 继续表示编排准入状态，不直接作为路由总开关。`route_eligible` 使用已提交且未被替代的 serving 归属、当前应用/授权、保护基线未被明确判为失效、没有已确认停止/不健康事实；诊断不参与，普通心跳超时不改写已确认路由。不新增每次入口实时询问 Manager，保留短缓存/撤权上界。

| 情况 | 新编排 / 当前停止权 | 既有已确认 serving 路由 |
| --- | --- | --- |
| 诊断未测/失败/老化，配置与控制正常 | 按合法配置和真实状态正常判断 | 不受诊断影响 |
| Manager 短暂失联或其 Kubernetes API 不可达 | 暂停新编排；不能凭旧控制观测授予新的停止确认 | 持久目标及当前授权仍有效时继续，实际转发失败按原错误页处理 |
| 资源/超时等非保护参数非法，或期望配置暂不可读取 | 不接受新操作/不授予新的停止权；不追认旧历史 | 不仅因此撤销已确认且基线未被判坏的旧目标；保留权限和运行健康判定 |
| 保护 scope/revision 实际不一致、受信运维确认保护断档 | 拒绝相关执行与停止事实，按既有规则降低受影响历史 | 不再以旧保护承诺放行，保留诊断与修复入口 |
| 应用停用、被替代、权限失效、确认停止或不健康 | 按其原业务流程 | 拒绝/呈现对应状态，不因取消诊断时效续活授权 |

这里的保护失效指受信配置/运行事实或显式运维变更已确认的失效；不承诺自动发现管理员在 Chart 外的所有 CNI/CSI 改动。该信任边界正是用户确认的“由运维保障环境、诊断可选”。

配置 v2 与配对新镜像一起交付；不承诺旧 Manager 能读取新 schema，不用旧报告兼容放行新操作。旧运行控制协议 v1 继续退役。新标准 release 的升级保存冻结快照，旧操作用其快照/approved template 对账；缺失无法可靠重建的旧策略时阻止相应新变更并给出维护原因，不自动采用当前策略。
存量 legacy 配置转 v2 时，部署期 `runtime.upgrade.predecessorProtection[]` 明确给出 node_id、cluster_id、execution_namespace、旧 status_policy_revision、旧 protection_contract_version 和旧 baseline_digest，绑定本次目标保护摘要。该映射只来自部署配置，不能从心跳/API body 提交。Backend 在节点事务内与服务端旧 scope/revision/黏性版本/摘要精确核对，再登记一次性已采纳的前代→目标映射；原 true 仅在精确连续性成立时保留，false/unknown 永不补 true。缺映射或不匹配不授予旧资源新的停止权，不自动清卷；原记录和维护原因保留。全新 v2 安装不需要此前代配置。
旧 122 多 release 整并及 namespace/卷迁移仍不自动执行。升级说明提供配对版本/停接新任务/保留运行应用/核对在途操作与基线的步骤，混合版本不支持新编排时明确报告，不能将它当失败清数据的理由。

强化 RuntimeClass 沿用原合同：实际不可用时告警并记录实际档，回退满足基线的默认档。回退前必须证明失败候选未创建或已停止；未知写入者不能借回退出现第二实例。不新增全局 RuntimeClass 管理权限，不因没有诊断报告静默声称已加固。

### 4.5 必要初始化 DAG

这些是密钥和数据库初始化，不执行环境验收。使用正常 Job 资源，与依赖一起创建，不使用等待业务 ready 后才执行的 post-install hook。文档安装命令包含 `--wait --wait-for-jobs`，每个 Job 都有有限 activeDeadline/backoff、可查询日志和明确完成条件。[Helm lifecycle](https://helm.sh/docs/v3/topics/charts_hooks/)、[Job 等待参数](https://helm.sh/docs/v3/helm/helm_install/)。

1. **Helm 基础资源**：生成 Services、配置、必要 namespace、稳定随机 HMAC/seed 与 CA/证书、空且无授权的公钥 CM，以及 RBAC/Webhook。用户可用 existingSecret/既有公共 CA；不读取或接管外部 release 的密码。
2. **内部数据库供应**：内置 MySQL 的幂等建库/账号步骤只使用该实例初始化凭据；外部库不做 root 建库。OpenFGA 使用其精确镜像版本的 datastore migration 完成后启动 API。Milvus 等按各组件正常依赖启动，失败显示真实原因。
3. **Ed25519 公钥派生**：一次 key-init Job 复用正式 Manager 镜像中的独立命令，挂只读 issuer/data 私钥 seed，派生分别供 Backend/Helper 验证的公钥。Chart 预建目标 CM；SA 只可 get/patch 指定 CM，无 Secret API、Pod create、exec、SA/RBAC/webhook 权限。校验现有内容，一致则 no-op，不一致失败；不自动轮换，不等业务执行域 ready。成功后等待该公钥的 initContainer 才继续。
4. **Backend operational bootstrap**：复用 Backend 镜像及正式 Alembic/权限模块，串行执行 schema migration → 生产空 Store/model 初始化或匹配 no-op → 可信官方 profile/缺项默认 seed → 写入初始化版本完成标记。无 Kubernetes 身份。普通生产 runtime 仍只发现/校验模型，不使用 `force_write_model` 或 dev 绕过。
5. **业务服务启动**：Chart 的部署级 initContainer 执行正式 `wait-schema` 命令，只查询数据库 schema 和初始化完成标记，再启动不重复 Alembic 的 `api-managed` 或原 worker 入口。主进程保留原 lifespan；不新增 HTTP/WebSocket/Celery/Linsight 的全局请求闸门或数据库/model liveness 检查，不把一次性授权迁移程序嵌入运行时健康定义。服务不读 Job 状态、不持集群身份。Compose 原 `api` 入口保留原迁移行为，Helm 不让每个 API 副本再并行 Alembic。

初始化的条件如下；关闭功能不会保留对其镜像、公钥或标记的等待：

| 条件 | 生成/执行的初始化 |
| --- | --- |
| 平台启用 | 平台 schema 和需要的权限基础初始化；与 Vibe 是否开启独立 |
| 内置 MySQL | 仅本实例需要的库/账号；平台/OpenFGA/Gateway 各按消费者开启，不建无消费者的库 |
| 内置 OpenFGA | 该服务 datastore migration；外部服务不执行其 datastore 迁移 |
| `runtime.enabled=true` | issuer/data 公钥派生、运行时专属密钥与等待、官方 profile 缺项 seed |
| `runtime.enabled=false` | 不生成 key-init，不等待运行时公钥，不 seed profile，不依赖 Manager 镜像 |
| `gateway.enabled=true` | Gateway 独立数据库初始化；关闭时无该 Job/等待条件 |
| `sandbox.enabled=true` | 稳定 token 和逐副本端点；关闭时不引用 Code Runner |

初始化目标 `init_target_digest` 覆盖安装身份、目标数据库身份（不含密码）、schema heads、初始化合同版本、正式 catalog 摘要及已启用的初始化功能；密钥派生目标另绑定公开 key-set-id 和公钥格式版本。普通 Job 名包含其 Pod 模板的 `job_spec_digest` 短 hash（镜像/命令/调度/资源/Secret引用及目标摘要），升级生成新名字，不能 patch 旧 Job 的不可变模板。`wait-schema` 只接受自己镜像/配置预期的目标摘要，不能拿旧成功 Job 当新版本完成证明。

完成标记放在现有系统配置存储的安装/目标专属 key，字段固定为 `installation_id, schema_heads, catalog_digest, init_target_digest, run_token, status, completed_at`，不含凭据；status 必须为 succeeded 且目标与数据库实际 schema 精确匹配。旧目标成功记录作为审计和升级前代保留，新目标不能靠旧记录放行；这不构成自动数据库降级或未经验证的旧镜像回退授权。成功后其他副本仅等待/读取，资源参数变化不重新解释运行应用。Job 日志按配置保留，完成后可 TTL 回收；相同目标重建 Job 为验证后 no-op，失败无无限 backoff。

跨 Alembic 互斥使用持久 CAS claim，而不是假定事务行锁跨 DDL 不会释放。operational 层在迁移前建立独立技术协调表 `deployment_bootstrap_claim`（SQLAlchemy 可移植建表/检查，非业务授权对象）；仅并发创建同结构对象可接受，其他建表错误失败。主键为当前物理数据库/schema 内固定的 `scope_key=platform-schema`，不能用含 host/用户名的 DSN hash，避免连接别名绕过互斥。字段含 `layout_version=1`、安装身份、目标/前代摘要、随机 run_token、running/succeeded/unknown、已确认阶段摘要，既有布局必须严格核验。该技术表由 bootstrap 版本化管理，在 Alembic autogenerate 反射/比较中明确 exclude，普通 downgrade 不得删除或重建它。
提交 running 后才执行迁移；其他初始化器看到未完成 claim 不按 TTL 抢占、不并行 Alembic。成功仅当前 token 可 CAS 完成并发布标记。正常兼容升级仅可从同安装已 succeeded 且 schema/模型/前代目标被认可的 claim CAS 到新 run_token/目标，保留前代完成记录；不把它和未知中断抢占混同。
中断、丢失归属或部分 DDL 未知时不写成功；后续 Job 明确报告需要恢复。显式续办必须先确认旧初始化进程停止，核对数据库实际 heads 与已记录阶段，以原目标/token 受控接续或按原 Alembic 修复流程处理，不自动重跑未知 DDL。不同 release 指向已被另一安装认领的业务库直接拒绝，不能接管。该协调表仅用于部署初始化，API 不暴露其写入口，不授予应用/Manager 数据库权限。

OpenFGA 初始化状态矩阵：

| SQL/Store 状态 | operational 行为 |
| --- | --- |
| 全新 SQL，目标专用 Store 不存在 | 在持久 claim 下创建唯一目标 Store、记录身份，创建匹配模型，再初始化 SQL 权限控制状态 |
| 全新 SQL，唯一专用 Store 无模型且无业务 tuples | 创建当前匹配模型，记录阶段，继续 SQL 初始化 |
| 全新 SQL，运维已提供专用 Store/匹配模型且无业务 tuples | 校验来源/唯一性/模型 checksum，采用该 pin 完成 SQL 初始化，不重复发模型 |
| 完整既有 SQL CURRENT/模型/目标摘要匹配 | 验证后 no-op，不改业务授权 |
| 同安装前代 claim 已成功、CURRENT/模型匹配，新 catalog 或启用功能形成兼容新目标 | 核对安装归属、前代 schema/目标及兼容声明，CAS 新 claim；执行适用 schema 迁移和官方缺项种子，保留 CURRENT/用户默认/冻结版本，完成新目标；模型变更仍走明确升级工具 |
| 本次已记录的部分初始化，尚无最终标记 | 默认阻止重试；确认旧执行停止后按原 claim/阶段显式核对续办，不重新创建模型 |
| 同名多个 Store、外来 tuples/控制状态、不匹配模型或无法确认归属 | 失败，保留证据；转既有明确升级/修复工具，不覆盖 CURRENT Catalog |

外部 OpenFGA 默认使用运维已准备的专用 Store/模型，仅显式允许时才创建本安装的新 Store；不对外部服务执行 datastore 迁移。`openfga.enabled=false` 表示不用内置实例，不等于关闭 Backend 授权或回退 RBAC。不切 dev、不自动打开 force_write_model，不创建管理员。
Gateway 启用时，使用锁定版本的初始化 SQL/迁移入口处理其独立数据库；首次空库初始化与已存在且版本匹配 no-op 分开，非空未知 schema 不以 `CREATE IF NOT EXISTS` 冒充升级成功。初始化仅在 gateway.enabled 时产生；外部库权限不足明确失败，不要求提供外部 root。

### 4.6 Secret、配置装配与官方种子

Helm 用加密随机源生成每安装独立 HMAC、32 字节 issuer/data seed、sandbox token；例如 `randBytes 32` 的输出已经是 Base64，不再次编码成错误长度。内部 CA/leaf 在同一模板数据源生成并复用，证书 SAN 来自 Service DNS/clusterDomain。升级校验 owned Secret 并保留原内容，缺失/不匹配不静默重新生成。existingSecret 只引用，不尝试读取用户数据库密码来渲染模板；外部 TLS 需明确提供其公链 CA。[Helm 密钥函数](https://helm.sh/docs/v3/chart_template_guide/function_list/#randbytes)。
签名目的分离：JWT/OBO/控制/代理/egress/material issuer/data signing 不共用。数据私钥仅 Backend 和一次派生 Job 可见；常驻 Manager/Helper/应用不获得它。Manager 不拥有公钥 CM 写权。Secret/公钥 CM/数据卷使用保留策略；重装识别原安装身份，显式恢复/轮换，普通升级不换根。

公钥 CM 首装可为空，由 key-init 唯一填充；**升级必须 lookup 并校验同 release/namespace/安装身份的 owned CM，原样保留其数据**，不能只加 keep 后仍渲染空 data。Job 校验现有公钥与挂载 seed 一致后 no-op，不一致失败。外部 CM 仅引用不接管；缺失的预期 owned CM 不自动补新键。Secret 同样校验归属并保留数据，不因演示密码或新默认变化自动轮换。公钥就绪标记绑定 key-set-id；等待者只验相应公共内容/标记，不因未测环境报告等待。

Backend 镜像提供正式配置装配入口：读取非秘密部署配置和投射 Secret 文件，按现有 Fernet、SQLAlchemy URL/Redis 编码生成 Pod 私有 emptyDir 配置，再启动原服务；不在命令行或日志输出明文，不从 ConfigMap 执行 Python。`managed` 与 `existingConfigMap` 两种模式互斥，existing 模式说明必须自备新合同配置，不能半自动覆盖。

官方种子只读取与配对 Backend/运行镜像发行一致、带固定 digest/平台/ABI 的正式目录，校验清单摘要和发行元数据；不开放 `source: deployment` 自动导入任意 profile。自定义环境仍走真实超管 API。RuntimeProfile 增加 `origin=system|user`、可空 `created_by` 和发行来源/目录摘要；历史记录为 user，system 记录 created_by=NULL，不伪造用户0/1，写 API 不接受 origin/system 来源。迁移使用现有双数据库类型和幂等约束。
相同 code/revision 内容一致 no-op，不一致失败；默认映射只补缺项，已有默认、审批中/运行版本和仍被引用的旧 profile/材料保留。更换镜像仓库会改变 profile 内容摘要，须提供对应正式 catalog/new revision 或明确迁移，不能用 global.imageRegistry 原地重写历史环境。正式目录继续满足既有双架构发行合同，fixture/122 单架构非官方目录不冒充正式产物。

### 4.7 网络、入口和存储

公共 NGINX 的普通 API 按 Gateway 开关选择上游；`/apps/`、预览保持 app-proxy，关闭 Vibe 时保留 Backend 未启用引导。保留 WebSocket/流式、尾斜杠与用户授权语义。
同一 Frontend 提供独立内部 TLS listener/ClusterIP Service，明确允许 runtime v2 控制/材料路径，原样保留 URI/query/body/HMAC，关闭缓冲；公共 listener 不宽泛开放整个 internal 前缀。内部 origin 不依赖 publicUrl 或预选 Service IP。

Egress Service 默认由 Kubernetes 分配 ClusterIP。Manager 只新增对控制 namespace 中该指定 Service 的 get 权限，读其名称/namespace/UID/IP/port，校验配置的目标和 CIDR，提交冻结观测，Backend 按已登记 Service 身份/CIDR/端口核对，不持集群凭据。新操作重读，旧操作不热改冻结代理地址；Service 重建导致旧地址不可用时保留实际阶段错误与原期限，不猜地址或绕过代理。应用仍禁 DNS/ServiceLinks。Pod/Service/API CIDR 是运维输入，不能猜 122 网段或固定 RFC1918 范围。

PVC 统一三态：`storageClass:null` 省略字段使用默认；非空指定；`""` 显式无 class 静态匹配。Manager、Admission、手动诊断一致。平台缓存默认每 Pod 有界 emptyDir，可选按用途 PVC/existingClaim；不将单个 RWO 跨节点多副本误当合法布局，也不统一强制 RWX。[Kubernetes 访问模式](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes)。
应用卷默认动态 Filesystem/RWO，数据与 scratch 明确容量/回收。保留 ext4/xfs、实际容量约申请值 0.8–1.1 倍、flock/fsync/SQLite 与单写检查；这是当前产品支持范围，不宣称任何 CSI 都兼容。静态 local pool 由运维预置有界文件系统，Chart 仅声明节点/路径/容量，不格式化、不 SSH、不自动清未知卷。

### 4.8 手动诊断、发行和文档

保留 verifier 的真实 `--live`、CAS 报告更新、安全 UID 清理与脱敏结果。取消固定 21600 秒循环限制，标准教程以单次命令为主；周期调用由运维自选。报告写入不改 policy/ready/路由/旧保护历史。
诊断 canary/权限为显式工具所需，不是普通启动依赖；无账本时普通 Admission 仍运行，但不接受 canary 授权。有活动账本时升级保留原 UID/所有权/计划，不因关闭诊断清空或自动清卷；缺历史证据的资源按未知处理。

发行打包脚本接受真实 image-set 和正式 catalog，校验源码/合同版本、架构、digest 和全部工作负载/Job/Helper 镜像覆盖，再生成发布 values/锁定清单和带依赖的 tgz。缺兼容镜像或正式 catalog 必须拒绝正式打包；开发模板 CI 可使用明确 fixture，但不得将它发布或称为可安装发行。
本轮新增 workflow 只 lint/schema/template/源码定向测试与 package-check，不触发镜像 build/push、Chart 发布或生产 kubectl。教程放公开 Chart README 及 `docker/helm/README.md`，覆盖新装、外部/混合依赖、开关、企业镜像源/离线、Secret、手动诊断、升级/卸载保留数据和实际支持范围。

### 4.9 模块职责

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| 父/子 Chart 和打包脚本 | 命名/依赖/values/schema、配置与资源生成、镜像清单校验 | 122 操作、现场磁盘格式化、自动诊断放行、假镜像发行 |
| Backend app_runtime | 期望 policy、操作冻结、业务授权/状态、正式路由和保护历史 | Kubernetes SDK、节点文件/卷操作、伪造诊断 |
| Manager/Helper/Admission | 按冻结策略执行/校验，真实事实、UID 停止、受限材料处理 | 修改安全根、登记全局 profile、绕过数据维护权限 |
| 一次 key-init | 私钥 seed 派生公钥并校验持久输出 | 修改 Secret/RBAC/webhook、创建测试 Pod、环境验收 |
| Backend operational bootstrap | schema/全新授权/官方种子初始化与完成标记 | 常规运行写授权模型、迁移未知业务库、创建管理员 |
| 手动 verifier | 真实诊断和安全回收、报告 | 运行准入、静默停业务、维护长期安装者权限 |

实施入口固定为：Manager 镜像内 `runtime_manager.bootstrap_keys`；Backend 镜像内 `scripts/standard_helm_bootstrap.py`、`scripts/wait_schema.py`；纯配置装配器 `bisheng.core.config.deployment_renderer`。前两类 operational 脚本可访问各自需要的 SQL/权限模块，不进入普通业务路由；配置装配器不访问领域服务。Chart 位于 `templates/bootstrap-*.yaml`，只载入命令/配置，不从 ConfigMap 执行业务 Python。上述路径为拟新增文件，当前尚不存在。

## 5. 已知坑与反直觉事实

| 事实 | 忽略后果 | 处理位置 |
| --- | --- | --- |
| report ready 还参与路由和停止历史，不只是新发布 | 删 TTL 后仍堵入口，或补 true 导致错误清卷 | capabilities/heartbeat/route、RuntimeKubernetesRepository，§4.3–4.4 |
| 原 ResourceTier/Helper 预约与 Pod 实值可能不同 | Pod 调大 CPU 后再次出现准入/配额不一致 | operation create/capacity/PodPlan/Admission，§4.3 |
| `storageClassName:""` 不是默认 class | 新集群有默认 SC 仍 PVC Pending | PVC/诊断/准入三态，§4.7 |
| 公钥 CM 写权等于可替换验签根 | Manager 可伪造数据授权 | key-init 受限 SA，普通 Manager 无写权 |
| post-install --wait 在资源 ready 后才执行 | 必要初始化与 API ready 相互等待 | 普通初始化资源和有限 wait，§4.5 |
| registry 重写改变 immutable profile digest | 相同 revision 冲突或历史环境被改写 | 种子/发行目录/new revision，§4.6 |
| F114 已替代早期 owner-only | 恢复/材料/删除权限无声回退 | spec继承表、业务授权原入口 |
| 沙箱端点含会话绑定 | 普通 Service 负载均衡或换 token 导致会话丢失 | StatefulSet ordinal DNS、升级保留 |
| CA 多次随机生成可能不一致 | webhook/内部材料 TLS 无法连接 | 同一模板数据源、owned Secret 保留 |

## 6. 对外契约与依赖

| 类型 | 契约 | 消费者 / 风险 |
| --- | --- | --- |
| HTTP/内部消息 | 既有 runtime v2 路由；心跳增加 configuration，诊断独立；新 operation 冻结原始 policy JSON/摘要 | Backend/Manager/Admission 必须配对，新配置版本不与旧控制v1混淆 |
| Python/初始化 | 保留 RuntimeProfileService 的人工超管入口；新增受控官方种子与 operational bootstrap | 系统来源不能由 API body 冒充；普通生产 lifespan 不写模型 |
| 数据库 | profile 来源/可空创建者、现有配置存储中的安装完成标记 | MySQL/DM8 迁移与失败恢复需覆盖；不能篡改历史版本/用户默认 |
| 文件 | runtime-policy.json 原字节、公开 CA/公钥、Secret 文件、真实 image-set/catalog | 解析严格；秘密不进入 policy/报告/日志/Helm普通配置 |
| Helm values | §4.2 的分组与默认、每组件 external/existingSecret、storageClass三态 | 旧 values 需明确升级说明，不猜无效字段或自动接管外部资源 |
| 集群前提 | 运维保证 CNI执行NetworkPolicy、CSI满足声明存储能力、允许所需webhook/RBAC；提供网络CIDR | 配置声明不等于实测通过；真实运行失败正常报告 |
| 原 Vibe | spec §3.1、F114六动作、必审、组合冻结、恢复预算、RuntimeClass回退、材料身份 | 本功能仅替代明确登记部分，其他既有业务合同继续生效 |

## 7. 验证与可观测

代码阶段先做有效的跨层配对回归：无/失败/多日旧报告的 prepare/admit/route、真实坏配置/权限/API仍拒绝、旧 false 历史/Unknown writer、冻结策略跨重启/升级、Helper预约与Pod实值、F114恢复权限、必审与预览、RuntimeClass回退。保留相邻现有生命周期、数据和发布回归，不写只镜像实现的机械测试。

模板矩阵覆盖默认、逐项 external/混合、各功能关闭、existingSecret、双 release/共享 namespace、三态SC/已有PVC、初装/升级密钥稳定、无诊断资源、非默认资源/超时/节点、包源/离线、source-image只禁自身路径。静态渲染校验所有引用/selector/NS/镜像与公钥生成流程；正常 `helm template` 不访问集群，涉及已存在 Secret/账本的真实升级校验另列测试。

设计确认后按仓库 QA 八列表格生成 test-cases，再拆任务；实现时使用 e2e-test/sdd-code-review。真实部署/E2E、DM8/Linux、CSI/CNI与分架构发行证据在相应授权和镜像具备后执行，未执行标未验证。

未来手动验证入口（本轮不执行）：

```sh
helm upgrade --install demo ./bisheng-release.tgz -n demo --create-namespace -f values.yaml --wait --wait-for-jobs --timeout 20m
kubectl -n demo get pods,jobs
kubectl -n demo logs -l 'app.kubernetes.io/instance=demo,app.kubernetes.io/component=backend-bootstrap' --all-containers=true --tail=100
# 显式环境诊断仍使用同版本 verifier --live；不作为上述命令前置。
```

日志分别呈现 `configuration invalid`、真实控制连接失败、应用阶段失败、初始化失败及独立 `diagnostic not_run/failed`；禁止将配置声明显示为环境已实测。保留安全错误码/脱敏，不输出密码、私钥或材料票据。

## 8. 交付限制与后续

本轮交付代码、Chart、配置/打包/验证脚本和教程。正式可安装发行仍需包含新合同的 Backend/Manager/Helper/Admission 等镜像、真实官方目录、Gateway schema 对应证据及独立集群安装/升级验证；旧 v3.0.0 digest 不能替代。

不新增新的持续环境监控产品、不提供存储驱动或自动格式化、不合并 122 多 release、不做自动数据恢复或新的模板管理页面。更广的 CSI/文件系统、HA 和镜像仓库历史迁移须在实际测试支持范围内另行扩展。

## 修订历史

| 日期 | 改动 | 原因 |
| --- | --- | --- |
| 2026-11-10 | 规格确认后整合为正式设计草稿，编号顺延F008；配对策略/保护历史/初始化/密钥/Chart合同 | 用户确认修订规格，进入设计审查；未开始实现 |
