# F059 合入前 L2：runtime 核心范围只读审查

- 日期：2026-10-23。
- 审查源：`codex/059-k8s-runtime@cda8dccf26298af91a1df277dcd1a49787b6b444`。
- 合入目标：`feat/3.0.0-vibe@4aa9ce69b2830b81162fe631b9c801057c40ee8b`；本地 merge-base 等于目标，目标已在源历史内。
- 继承基线：F086 `5131b8119` / `755d4456e50c015a3fa88da0c0c35ab53bbd1650`；后者是源历史祖先。没有将 F086 原有实现误算为本轮新设计。
- 方法：使用仓库 `sdd-code-review` 七维框架，读取当前源码、相关 diff/历史、已存在测试与189证据记录。无远端操作、无仓库改动、未运行新全量或原生测试。

## 1. 结论

**产品代码范围：PASS，未发现新增 HIGH / MEDIUM 产品缺陷。**

**冻结 cda 文档同步：NEEDS_FIX，仅下述 D1。** 产品代码未因此需要增加实现；主 agent 更新设计现状并复核后，本报告的文档门可以关闭。本文是 runtime 分工审查，不是整个 Feature 的 L2、全 AC 验收或 T072 已完成证明。

### D1 — HIGH：设计现状段落和已知坑索引没有收拢到最新实现

位置：`features/v3.0.0/059-k8s-runtime-backend/design.md:120`、`§5`、`:843`。

1. §4.1 的“F059 实施进展”仍写 `265/269`、R29、T069 剩安全删除。任务/证据后续已经记录 R31 删除、M2 新恢复、R32 在途重启及 `267/271`；读现状段会得到过期的实现与部署快照。
2. T272/T273 的反直觉根因在修订历史完整记录，但 §5 已知坑表未登记：新 manager 在旧 holder 的租约尚有效时收到正常 `409/controller_lease_held`，若进入业务 `_failure`，可在稍后取得租约后清理仍运行的安装，错误地终结原 prepare。当前 `operations.execute` 已把 K8s `_controller()` 放在业务 claim/try 之前，避免该路径。

`sdd-code-review` 维度7明确要求当前 design 快照与代码一致、反直觉修复进入已知坑表。最小修正：刷新 §4.1 当前状态且保留历史记录；§5 新增该事实、“误终结在途安装”后果和 `operations.execute` 前置租约门处理位置。无需改 spec 或产品合同，无需重跑全量。

## 2. 七维结果

| 维度 | 结果 | 实际检查与依据 |
| --- | --- | --- |
| 1 边界条件 | PASS | 冻结 profile 对象与 manifest 字符串分层；optional lock 的 None/省略归一和非法类型拒绝；初始化阶段锚点、原 operation deadline、取消/UID/坏状态/非法报告时间均 fail closed。数据响应、材料票据、解包/条目等有既有边界；没有以新的 now 重新延长业务期限。 |
| 2 权限与认证 | PASS（本分工） | 控制 API 使用平台 HMAC/nonce；材料使用同 UID 的 Ed25519 委托，不给源码/安装脚本控制身份；数据 RPC 保留 owner 数据授权和动作/参数/实例票据；路由与访问授权分别查询 backend，不以 manager 存活或任意私网 IP 代替用户鉴权。已存在普通 owner/非 owner/跨租户真实拒绝记录。backend 全部业务权限实现另由后端分工审查。 |
| 3 并发安全 | PASS（本分工） | controller 锁、epoch/fact/资源 SQL 围栏；唯一 create intent→begin→receipt/fence；结果先持久化再清理；停止按同 UID 证据而不是租约/404；未知创建、未知 writer、未知响应均不变成停止。检查 SIGKILL 后租约交接、异步 PVC 删除、prepared_delivery/维护结果持久化、nonce 请求去重和 cancel 后新数据动作拒绝。 |
| 4 信息泄漏 | PASS（本分工） | 工作负载签名/材料票据不交给 app；可信 transfer 与无凭据 install 分开；业务仅挂本 app 数据子目录；admission 拒绝日志使用固定安全枚举；材料/数据网络异常不原样输出响应正文。HTTP/WS 统一剥离平台身份头和平台会话 cookie，再注入受控身份及 OBO。未读取实际配置、密钥或 token。 |
| 5 测试覆盖 | PASS（代码审查范围） | 已有真实 executor/operation、实际 backend schema/ASGI、材料向量与数据拒绝配对，避免仅宽松桩隐藏 wire 合同。已复用晚期红绿、189业务/迁移/删除/取消/在途重启证据；没有把本地 mock 或日志记录当成本轮新执行。T067/T070/T071 等未完成项仍独立保留。 |
| 6 代码风格 | PASS（本分工） | executor/材料/数据/准入模块职责明确；manager 不直接读平台 DB/MinIO；无为绕过失败新增泛化 fallback。晚期4行 controller 门、purge 等待只作用 K8s，Docker 保持既有路径。复用已有 Ruff/format/逐路径架构门记录，本轮未重新运行全仓门。 |
| 7 文档同步 | NEEDS_FIX（D1） | design 的决策、保护报告协议、材料/API、UID/创建围栏及恢复/销毁细化已有正文和修订；但现状与 §5 索引有上面的确定遗漏。其余未验能力如 NodeLost、跨节点、卸载、ARM、公开发行仍有边界记录，不应删掉。 |

## 3. 关键调用链核对

### 3.1 准备、取消和重启

`OperationExecutor.execute → controller 前置准入 → platform.claim → _prepared_delivery → KubernetesExecutor.prepare/_phase`。

- 已有 `prepare_progress`/`prepared_delivery` 通过事实持久化，不能在 latest-detail 投影里被后续事实覆盖；失去提交响应只接受 fresh 重读得到同一结果。
- 同操作重启复用确定 ref、记录的模板 deadline、已确认阶段结果及 scratch UID。未知 install 不盲目重跑。
- 每阶段进入、缓存返回、资源创建前、Running 轮询与结果提交前核取消/代次/归属/原截止。`PlatformError` 不被转换成成功；controller 初始拒绝不进入应用失败清理，真正业务异常仍进入原失败路径。
- 已有 operation terminal/pending 清理不覆盖初始 reason/stage/tail，不将旧失败复活为运行中。

### 3.2 停止、资源销毁和 SQLite 单写

`stop_instances → request_stop → fresh 同 UID / late node bind → classify_stop → backend stopped ACK → finalizer removal → fresh absence → cleanup fact`。

- `never_scheduled` 与可信 `kubelet_terminal` 是不同证据；NodeLost、Unknown、运行态、替换 UID、失信历史 flag、单纯 API404 继续 held。
- 控制租约过期不等于应用进程停止。controller 更新不修改 creator UID、历史停止/保护事实。
- 过期 stop 先记录 timeout/pending 保留 active fence，然后仅沿后端既有 terminal-own cleanup 权限收尾；空 stop 资源集不证明全 app writer 已停。
- K8s destroy 在 purge 前先持久化合法 `maintenance` 阶段；purge 结果 ACK 后才允许 PVC 清理。异步删除仅对精确 `purge_volume_cleanup_pending` 等待；原 deadline/取消/围栏持续检查，不重复执行已持久的 purge helper。
- 生产 PVC 不随普通准备、预览或停用清理。在线数据 helper 在同 Pod；离线会话先证明旧 writer 关闭，再使用固定位置和真实预占。

### 3.3 材料、数据和代理

- 材料任务/部署初始化身份区分；动作、工件、偏移、hash、大小、请求体、UID、票据窗口共同签名。HTTPS/CA 验证、禁环境代理与有界续期保持；app 无平台存储凭据。
- 数据票据绑定同 app/operation/ref/PodUID/action/参数摘要。helper 使用持久 started/result + flock；已开始结果未知不重放写。取消后的新签票和新 RPC 动作拒绝，不能把已开始动作当已回滚。
- HTTP/WS 共用 backend verdict 和身份头构造；路由 cache 与权限 cache 分开，v2 route 来自平台投影，manager 失联不直接中断已运行应用访问。WS 有期限、主动关闭与周期复核。
- egress 平台投影最大5秒；建立隧道后仍周期复核，过期/撤销关闭。DNS 检查后拨已验证地址，不将任意域名解析到内网作为授权。
- helper/assembler/运行包并不以 socket/任意 kubectl/宿主命令执行用户源码；受信 transfer 与无凭据脚本执行分开，模板严格校验额外字段和安全上下文。

## 4. 已读文件范围

以下为本 runtime 分工的实质阅读范围，不表示全仓每个变更行均独立审过。

- `src/runtime-manager/runtime_manager/`：`operations.py`、`executors/kubernetes.py`、`executors/protocol.py`、`k8s_lifecycle.py`、`k8s_admission.py`、`k8s_capabilities.py`、`k8s_templates.py`、`k8s_data_executor.py`、`k8s_data_helper.py`、`k8s_appdb.py`、`data_grant.py`、`k8s_helper.py`、`k8s_prepare.py`、`material_client.py`、`material_protocol.py`、`platform_client.py`、`platform_egress.py`、`egress_proxy.py`、`main.py`、`api/operations.py`、`api/platform_data.py`、`api/platform_observe.py`。
- `src/app-proxy/app_proxy/`：`clients.py`、`authz.py`、`headers.py`、`routing.py`、`proxy.py`、`websocket.py`；以及受其调用的 v2 平台协议和连接关闭职责。
- `src/app-runtime/common/prepare.py`、`src/runtime-manager/Dockerfile` 的可信工具/运行合同。
- backend 只为核调用合同读取：`runtime_kubernetes_service.py`、`runtime_kubernetes_repository.py`、`runtime_operation_service.py`、材料/数据 grant/session 服务及恢复提交/route 投影相关路径；不冒充对整个 backend 的重复 L2。
- 相关测试重点：`test_kubernetes_executor.py`、`test_operations_v2.py`、`test_k8s_admission.py`、`test_k8s_lifecycle.py`、`test_k8s_data_executor.py`、`test_k8s_data_helper.py`、`test_k8s_appdb.py`、`test_k8s_helper.py`、`test_k8s_prepare_cancellation.py`、`test_k8s_controller_restart.py`、`test_k8s_destroy_fact_contract.py`、`test_k8s_purge_cleanup.py`、`test_k8s_protection_report.py`、`test_k8s_protection_heartbeat.py`、`test_k8s_capabilities.py` 及代理路由/HTTP/WS/egress 原有配对。
- 文档：F059 `spec.md`、`design.md`、`tasks.md`、`task-reviews.md`、`validation.json`、`e2e-evidence/{installation,platform,fault-upgrade}.{json,md}` 的对应范围与最新命名快照。

## 5. 复用的测试及189证据（不是本轮重新执行）

| 证据 | 实际范围及限制 |
| --- | --- |
| T268/T269 runtime 完整回归记录 | `1787 passed / 13 skipped`，source `6c9694f0f`；并非最新0f2之后再次全量。首次测试夹具过短导致的失败保留，后来仅修夹具，不改产品期限。 |
| T270/T271 backend 回归 | `1174 passed / 19 skipped`，app_runtime 范围；不是全 backend/DM8 真机通过。 |
| T272/T273 精确配对 | 旧实现7例4红/3绿；主树首次直接邻接123绿/1旧断言失败，随后最窄13绿；没有倒填第一次全绿，也没有额外全量。 |
| 安装和控制 canary | `installation.json#registry_upstream_dedc_real_validation`：真实16项；同业务Service selector的5个canary连续观察未Ready/Serving，第6个不在该连续selector范围。TCP、外部crane和业务assembler证据分层。 |
| 五种交付模式、r11 | `platform.json` 各明确命名晚期记录：Python/Node/static、source-image、完整镜像；r11单v1审批预览、HTTP/WS、SDK/OBO、附件/拒绝配对、停用SQLite查改CSV和同v1恢复；不把历史running摘要当最终结论。 |
| manager停机 | `fault-upgrade.json#manager_outage_r11_r3`：15.931s、超缓存5轮、原WS/CONNECT及新连接/拒绝，恢复新PodUID；不证明任意长HTTP流或在途工作恢复。 |
| 迁移/恢复、销毁 | `fault-upgrade.json#actual_migration_restore_189_gen4`、`platform.json#r31_safe_delete`：新显式恢复和健康完整镜像唯一DELETE；旧failed恢复/删除保留，不重放unknown，不把空snapshot样本冒充非空删除。 |
| owner取消 | `fault-upgrade.json#actual_cancel_189_r31`：Node240钩子在54.85s真实同UID/CID取消，cancelled/cleanupcomplete、6资源自然缺席、容量释放，owner/非owner/foreign拒绝配对。 |
| 最新在途SIGKILL恢复 | `fault-upgrade.json#inflight_manager_sigkill_189_r32_lease_handoff`，source `0f2db1f9a29213ca94d4596e64b00ad8fcbac528`：同manager Pod重启、epoch30→31；同install UID/CID自然240.006s结束；原deadline `2026-10-23T07:22:07`/阶段结果不变；prepare8资源正常停止后缺席、预约释放，后续probe完成。不是整个T070、审批上线或probe物理缺席证明。 |

最新SIGKILL前的R31失败记录继续为 NOT_PASSED，修复后新attempt的R32成功不覆盖历史；旧r4未知创建及旧false保护资源仍held，不将其自动恢复为true或释放。

## 6. 两个旧私有分支的内容整合核对

### 6.1 `codex/f059-protection-runtime`

- 私有tip：`0338d2f65ff2b16af047648cbf2e90657bc9b8cb`。
- 集成对应：`2992a28a8`。
- 实测 `git diff --exit-code 0338d2f65 2992a28a8 --` 以下六路径：**无差异**：
  - `runtime_manager/k8s_capabilities.py`
  - `runtime_manager/executors/kubernetes.py`
  - `runtime_manager/operations.py`
  - `tests/test_k8s_protection_report.py`
  - `tests/test_k8s_protection_heartbeat.py`
  - `tests/test_k8s_capabilities.py`
- 私有tip对当前cda的这些文件只有 `operations.py` 后续 `+23/-1`，其余仍相同。变化为合法维护阶段、purge异步等待和controller前置，不是丢失保护修复。

### 6.2 `codex/f059-destroy-maintenance-phase`

- 私有tip：`dd549c009fbdd4cdac5d9d97ee7d2a9c67fa75f4`。
- 集成对应：`1532e115e`。
- 实测两个提交的 `runtime_manager/operations.py` **完全无差异**。
- 私有tip对当前cda只多出后续 `_wait_purge_cleanup` 和执行前controller门，`maintenance` ACK/fresh checkpoint原修复保留。

核对依据包括文件 diff 和主线 `git log -- .../operations.py`：`2992a28a8 → 1532e115e → 6c9694f0f → 0f2db1f9a`。**没有只凭 git cherry 判断，也没有发现需要把旧分支内容再次合回的产品差异。**

## 7. 不得由本报告关闭的门

- 本报告不重跑任何全量、新远端、ARM、Docker109、客户离线安装、正式CI/DockerHub/tag发行。
- 未完成的T067/T070/T071和全AC子句继续记录：例如独立卸载、完整故障矩阵、NodeLost/跨节点物理fencing及其他未取得真实证据的性能/权限/材料续期子句。单节点189不能证明跨节点恢复。
- DM8仍按用户已确认口径仅静态模型/约束核对。
- 主 agent 集成后的最终SHA、跨分工L2汇总、设计D1修正和必要合入验证仍归主流程；不在此勾选T072，也不声明整个Feature已交付通过。


## 8. D1 定向复审关闭（2026-10-23）

- 复审位置：`/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration` 当前工作副本，未提交设计文档；没有修改该仓库。
- 已读设计文件 SHA256：`9f41bbc3acc64525eb3aedf4c97f4f846a201b520cefd4278844f762b4638dce`。
- §4.1（当前第120–124行）已改为当前 R32 / Helm32，记录 source `0f2db1f9a29213ca94d4596e64b00ad8fcbac528`、原deadline/同安装UID-CID/240秒自然完成；明确原267/271及追加T274后的268/272，列出T067/T070/T071/T072仍为交付门。R31删除、R11数据、M2恢复已收拢，同时保留未验故障/卸载、ARM/新增109/发行、旧false/unknown围栏边界。过期R29/T069剩删除已不再充作当前快照。
- §5 已知坑（当前第421行）已加入“旧holder租约尚未到期的正常409不得进入业务失败”，准确记录误清理在途安装后果、`operations.py` 的claim/执行/业务失败处理前controller门，以及T272/T273/R32同UID-CID证据。
- **D1 两项均已修复，CLOSED。维度7本次定向复审 PASS。** 原报告中冻结cda的D1发现保留为历史；本节替代其未关闭结论。
- **最终 runtime 分工七维结论：PASS，无未关闭 HIGH / MEDIUM。** 本结论仅覆盖原报告范围及上述两项文档修正，不包含追加T274的独立代码审查，不代表整个feature、T072、未验AC或正式发行通过。
- 本次只读定向复审，未运行测试、未远端操作、未扩大产品审查范围。
