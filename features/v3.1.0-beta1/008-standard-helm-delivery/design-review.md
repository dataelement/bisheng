# F008 设计审查

日期：2026-11-10。方法：仓库 `sdd-review design` 的 24 项检查、Constitution Check、三路独立范围审查。依据为 [已确认 spec](./spec.md)、[design](./design.md)、版本契约和实际源码基线 `90fa8fb953`。

历史复评结论（已由下列最新决定覆盖）：**REVISE。** 用户要求复评后，以 `19ba119e48` 的设计和源码进行新的独立架构审查、初始化链路审查及 Runtime 合同审查，确认下文 §4 的 5 项缺口。此前的 LGTM 结论和 24 项核对作为上一轮记录保留，由本轮结论覆盖；本轮只更新评审报告，没有修订设计、实现业务代码、构建镜像或部署线上。

独立架构报告原文见 [architecture-critique.md](./architecture-critique.md)。评审是建议，不新增审批环节；用户随后已确认简化方案并授权实施，原评审快照保留追溯。

**用户后续讨论的优先决定**：R-02 的旧部署接入兼容移出本期；R-05 的沙箱启用后关闭联动延期，不作为阻塞。R-03 中旧部署前代映射部分随范围移出，保留标准 Chart 自身后续升级的运行保护要求。R-01/R-04 先重新判断新增标记/地址冻结的必要性，不能把补齐所提新机制直接当作必修业务 Bug。完整解释及流程图见 [复评澄清](./design-clarifications.md)。下文五项保留为原评审快照，不再表示五项均属当前必修。

## 最新闭环（2026-11-10）

用户授权按最新讨论继续源码实施，以下是当前口径；后面的表格是历史审查记录。

| 复评项 | 最新处理 |
| --- | --- |
| R-01 初始化标记 | 删除拟新增的总标记/claim；等待实际 Alembic、匹配模型/Catalog 和官方目录。不是新增请求放行记录。 |
| R-02 旧安装迁入 | 用户排除；仅全新标准安装与其后续正常升级。 |
| R-03 Pod 保护 | 原 Admission/UID/删除基线 437 通过，无原规则缺陷；新增策略/资源接线保留保护，按实际问题修正新的参数链路。 |
| R-04 额外地址冻结 | 删除拟新增状态；稳定 Service、Manager 启动解析，应用仍仅经代理。 |
| R-05 沙箱热关闭 | 用户明确延期，默认开启持续使用；不宣称解决。 |

实现现状见 design.md，源码测试和真实集群未验收边界见 verification.md。本轮未构建镜像、未部署。旧 D-04/D-05 的总标记/claim、D-11 前代映射等建议不进入本期实现。

## 1. 重要问题与修订闭环

| ID | 等级 | 问题 | 设计修订 |
| --- | --- | --- | --- |
| D-01 | high | 空公钥 CM 在升级时可能覆盖 Job 产出；keep 仅防卸载 | owned CM lookup/归属校验后原样保留；派生 Job 一致 no-op，外部 CM 不接管 |
| D-02 | high | 无条件初始化 DAG 会使 Vibe 关闭后仍依赖 Manager/公钥/目录 | 按 runtime/gateway/各内置依赖列条件表，关闭时不生成专属初始化或等待 |
| D-03 | medium | 子 Chart alias、replicaCount 与 values 传递不明确 | 固定 runtime/sandbox alias、保留真实字段名，父端点/子资源调用同一命名 helper |
| D-04 | medium | 普通 Job 模板不可变，旧成功记录不能证明新目标完成 | init target/PodSpec 摘要入 Job 名；按目标完成标记、有限失败/重试，保留前代记录 |
| D-05 | medium | 迁移互斥不能依赖会被 DDL 提交释放的行锁 | 固定物理 schema scope 的持久 CAS claim；running 未确认不抢占；技术表布局版本化且排除普通 Alembic 删除 |
| D-06 | medium | OpenFGA 预置匹配模型、部分中断、正常兼容升级状态不完整 | 补七态矩阵：新建/预置/no-op/新兼容目标/显式续办/拒绝外来或不匹配；模型变更仍明确迁移 |
| D-07 | medium | 保护摘要输入/编码未定义 | 固定 scope/protection 子集和 canonical JSON 编码，提供共同测试向量，不把普通资源调值当保护断档 |
| D-08 | medium | policy 未声明总预算，仍可能由心跳自报 | 增加 execution_budget，由 Backend 期望文件核对，并与配额/并发同源 |
| D-09 | medium | Helper requests 小于 limits 时按 requests 预约会低估承诺 | 首期执行域 Helper CPU/内存 requests=limits，按真正阶段有效需求预约；控制面不受此等值约束 |
| D-10 | medium | ready/serving 仅文字分离，可能重新一律拦入口 | 明确 admission status 与持久 serving 谓词和五种状态表，诊断不参与，实际授权不续活 |
| D-11 | medium | legacy 保护连续性缺可验证输入 | 部署期前代映射精确核对 Backend 旧记录后一次登记；旧 false/unknown 永不追认 |
| D-12 | medium | 若报告与 policy 同文件，写诊断会改变策略摘要 | 独立 diagnostic CM/文件，CAS 只写报告，普通启动可无该卷；policy 原字节及冻结快照不变 |

D-05、D-06 经平台二轮复核进一步补齐 claim 的物理作用域/生命周期及同安装新目标正常升级分支，之后平台复核 LGTM。修订均为技术合同收敛，没有修改已确认 AC。

## 2. 24 项核对

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 1 目标清晰 | PASS | §1 标准交付与诊断解耦 |
| 2 非目标 | PASS | 不发行镜像、不部署、不迁移122、不装驱动/格式化、不新增模板UI |
| 3 特有约束 | PASS | §2 配对版本、冻结与信任边界 |
| 4 Constitution Check | PASS | C1 无Backend编排凭据；C2 双DB；C3/F114租户；C4生产模型仅operational；C6密钥分离/不泄漏；C8权威内容外置，其他全局法则引用原文 |
| 5 关键决策 | PASS | §3 八项决策 |
| 6 备选与理由 | PASS | 每项列被否方案与已有源码约束 |
| 7 重新考虑条件 | PASS | §3 明确对应触发条件，不预先扩展新形态 |
| 8 证据依据 | PASS | §4.1 源码耦合点、已确认需求与已复核合同 |
| 9 数据流 | PASS | §4.3 策略→冻结→执行/准入，§4.5 初始化DAG |
| 10 数据结构 | PASS | policy/心跳/摘要、前代映射、claim/marker、values字段 |
| 11 模块职责 | PASS | §4.9 做什么/不做什么 |
| 12 与实际阶段一致 | PASS | 已核实基线与拟实施目标分开，未称已经实现 |
| 13 已知坑 | PASS | §5 九项 |
| 14 坑的后果 | PASS | 每项列入口、数据、配额、TLS等后果 |
| 15 处理位置 | PASS | 对应函数/模块或目标章节 |
| 16 输出合同 | PASS | §6 内部HTTP、Python入口、文件、DB和values |
| 17 输入依赖 | PASS | §6 CNI/CSI、镜像/catalog、原Vibe合同 |
| 18 风险点 | PASS | §5/§6 及兼容/发行边界 |
| 19 测试层次 | PASS | §7 跨层配对、模板矩阵、真实验收独立 |
| 20 可操作验证 | PASS | §7 未来安装/日志命令及明确未执行状态 |
| 21 后续边界 | PASS | §8 延后范围和支持条件 |
| 22 修订历史 | PASS | 已记设计初稿/触发原因，未伪称特性完成 |
| 23 与spec一致 | PASS | 已确认26条AC及§3.1后继合同覆盖，无强制环境验收任务、无24h门槛 |
| 24 任务偏差一致性 | N/A | tasks 尚未生成；按仓库流程设计确认后先生成QA用例，再拆任务 |

## 3. 实施阶段验证要求

文档的链接、代码 fence、表格列数、AC 编号和空白可在本阶段静态校验。Job 代次/密钥三方升级、CAS 互斥、中断续办、双数据库、冻结策略与保护历史、正常入口独立性等必须在代码阶段以有意义的配对测试证明，不能用本报告替代。

兼容镜像/catalog、DM8/Linux、真实 CNI/CSI 和独立新集群证据仍是后续相应发行/部署验收前提；遵守本轮只改代码与部署文件的边界。

## 4. 用户要求复评后的确认问题

日期：2026-11-10。审查对象：`19ba119e48` 中的 `design.md`，未修改。方法：一名未参与设计的架构审查者，以及两名分别追查初始化、Runtime 生产消费链路的审查者，均只读源码。以下为设计缺口，不是已经发生的线上故障，也不能仅因代码尚未实现而成立。

### R-01 / P1：完成标记没有绑定完整授权目标

- **设计锚点**：§4.5，L171–172、L186–188、L194–206；对应独立报告 B1。
- **触发与影响**：只变更 OpenFGA 服务/Store 绑定，或只更新授权模型代码，而平台数据库、Alembic heads、官方 Runtime catalog 和功能开关不变，设计列举的 `init_target_digest` 输入仍可相同。新 Job 即使校验 SQL CURRENT pin/模型失败，新 API/worker 也可能凭旧 succeeded 标记启动。
- **源码证据**：`src/backend/bisheng/core/openfga/manager.py:69–113` 独立计算预期模型 checksum，且允许发现前代模型后启动 API/worker，同时将权限运行时置为不可用；`src/backend/bisheng/permission/application/catalog_bootstrap.py:218–229` 将 SQL CURRENT 绑定到授权模型 release。原 lifespan 不代替新 bootstrap 完成条件。
- **最小修订方向**：将预期授权模型 checksum、权限初始化合同/初始 Catalog manifest checksum、OpenFGA 服务及 Store 归属纳入目标，完成标记记录经验证的实际 pin；bootstrap 与等待者使用相同目标算法。无需把用户可编辑的实际 CURRENT Catalog 内容冻结进 Helm。

### R-02 / P1：旧安装首次接入新初始化协议没有接受路径

- **设计锚点**：§4.5，L188–204；对应独立报告 S1。
- **触发与影响**：健康旧安装有用户、CURRENT 和匹配模型，但没有本设计新增的 `deployment_bootstrap_claim`、目标摘要及完成标记。现有矩阵要求已有目标匹配或前代 claim 已成功，旧安装均无法满足；不能将它简单视为全新空库或外来库。
- **源码证据**：`src/backend/entrypoint.sh:42–56` 只有 Alembic 后启动 API，不产生这些新协调记录。§4.4 的 Runtime 保护前代映射也没有建立数据库初始化归属。
- **最小修订方向**：声明支持的旧版本基线，并提供验证 schema、授权 pin、数据归属后建立首个 claim/标记的受控接纳分支；保留既有用户、默认项和业务授权。此分支不承担 122 多 release 整并或卷迁移。

### R-03 / P1：前代保护映射只在 Backend，Admission 没有对应消费规则

- **设计锚点**：§4.3–4.4，L130、L139–159；对应独立报告 S2。
- **触发与影响**：部署映射接受旧保护历史，但目标 revision 与旧 Pod/PVC 注解不同。Backend 保留 true，Admission 却可能拒绝 kubelet 的真实终态或 PVC binding，导致停止证明无法完成，旧写入者及资源预约持续保留。
- **源码证据**：`src/runtime-manager/runtime_manager/k8s_admission.py:87–88、378–380、535–536、590–600` 使用单一 `self.revision`；`src/backend/bisheng/app_runtime/domain/repositories/runtime_kubernetes_repository.py:354–360` 要求停止证据匹配资源原 revision。
- **最小修订方向**：若兼容升级只适配摘要/schema，明确要求 revision 和完整 writer 规则不变；若允许变化，则明确受信前代 guard 的生产、分发和 Admission 本地消费及精确作用域。不能改写旧 UID 注解、追认 false/unknown 或让 status 路径回调 Backend。

### R-04 / P2：动态 Egress 地址尚未落入操作冻结权威

- **设计锚点**：§4.3、§4.7，L105、L128、L226。
- **触发与影响**：首装 Service UID/自动 ClusterIP 在 Helm 渲染时不存在；设计只冻结静态 policy，却未定义动态观测的持久字段、首次冻结时机和 Backend 已登记身份的来源。若观测只存于心跳/内存，Manager 重启或 Service 重建后，同一操作不同阶段可能使用不同地址。
- **源码证据**：`src/runtime-manager/runtime_manager/executors/kubernetes.py:615–623、718–721、1282–1285` 的材料 identity、运行环境、image-check 分别读取进程 egress 配置。
- **最小修订方向**：复用 Backend 保留的 operation payload，在首次资源 intention 前 CAS 冻结 namespace/name/UID/IP/port，并绑定 operation/policy digest；所有消费者统一读取。新操作可观测新 Service，旧操作保留原地址和期限，无需新建 Service 注册中心。

### R-05 / P2：关闭内置沙箱后，DB/Redis 旧端点仍可覆盖回来

- **设计锚点**：§4.2、§4.5–4.6，L76、L184、L216；规格 AC-12。
- **触发与影响**：页面曾保存本 release 的 ordinal Code Runner 地址，随后 `sandbox.enabled=false` 删除 Runner。仅清空部署默认端点仍会被 DB/Redis 保存的地址覆盖，代码执行继续引用已不存在的服务。
- **源码证据**：`src/backend/bisheng/common/services/config_service.py:55–67、584–627` 将页面配置覆盖部署配置；`src/backend/bisheng_langchain/gpts/tools/code_interpreter/factory.py:35–50` 将合并配置交给执行器。
- **最小修订方向**：明确关闭开关在有效配置解析/执行选择中的消费规则，抑制已关闭内置池的端点，保存值可保留供重新开启；使用外部池时应有明确外部绑定。不能静默切到 local，也不能无条件覆盖用户设置。

### 已排除的疑点与保持项

- 默认租户/角色/普通配置仍在原 lifespan，并不因此构成初始化循环：F001 Alembic 已 seed 默认租户；profile/Catalog 种子不依赖普通默认数据；`merge_old_config` 只遍历其默认配置键，额外完成标记不会混入 `initdb_config`。
- 未发现设计重新引入强制环境验收或 24 小时门槛；实际 UID 保护、权限、单写、阶段网络限制继续保留。
- Helper requests/limits 等值、init 有效 requests 与重叠预约已有明确约定；密钥派生的最小权限和升级保留公钥 CM 已覆盖。
- 本轮确认的问题均可在现有边界内补齐，不需要恢复环境预检、另建定期巡检或再建一套 Runtime 生命周期。
