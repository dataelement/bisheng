# F086 + F059 后端合入 L2 独立审查

- 审查日期：2026-10-23。
- 审查对象：`codex/059-k8s-runtime@cda8dccf26298af91a1df277dcd1a49787b6b444`。
- 合入目标：`feat/3.0.0-vibe@4aa9ce69b2830b81162fe631b9c801057c40ee8b`；该目标为审查对象的共同祖先。
- 兼容基线：F086 `5131b81194a5fa390593e58d822bcbde52b6ca64`；F059 接续基线 `755d4456e50c015a3fa88da0c0c35ab53bbd1650`。
- 范围：backend 的应用发布/运行入口、权限和 tenant、持久状态与幂等、HMAC/材料/附件、SQLite 数据 API、模型注册及 Alembic。manager/Chart/镜像实现由其他审查线负责。
- 方法：按 `sdd-code-review` 七维及 backend AGENTS，逐调用链静态审查与既有实际证据交叉。未执行测试、SSH、API、集群或数据库操作；未改仓库。未把继承的 F048、ASR、Linsight 等非 Vibe 改动纳入本报告的代码结论。

## 结论

**代码范围：未发现 HIGH/MEDIUM 阻断；开发合入可行。整体：NEEDS_FIX，仅 D1 文档现状同步，修正后可定向复审关闭。**

本结论针对用户要求的“先合开发”，不是全部 AC、完整故障矩阵、离线交付或正式发行通过。不得据此把未完成 T070/T067/T071 等交付项改成通过。

| 维度 | HIGH | MEDIUM | 结论 |
|---|---:|---:|---|
| 边界条件 | 0 | 0 | PASS |
| 权限与认证 | 0 | 0 | PASS |
| 并发安全 | 0 | 0 | PASS |
| 信息泄漏 | 0 | 0 | PASS |
| 测试覆盖 | 0 | 0 | 已核既有定向/实际证据；完整交付边界另列 |
| 代码风格/分层 | 0 | 0 | PASS，未重跑静态工具 |
| design 现状同步 | 1 | 0 | D1：刷新当前描述后复审 |

## D1 — HIGH：design 当前快照落后于已记录的实现与实证

`features/v3.0.0/059-k8s-runtime-backend/design.md` 以下是当前状态描述，而非修订历史：

- 第 120 行仍写 L1 265/269、R29/f886/epoch24、T069 剩安全删除、T070 迁移待验；当前任务及实际证据已含 R31 安全删除、M2 显式恢复 gen4、R32 租约交接定向通过。
- 第 262 行 §4.7 标题仍写“正式初始化待验收”，但五种模式发布与 r11 初始化已有实际证据；完整续期矩阵仍未证明，应保留该边界。
- 第 304、306、308 行仍称 K8s 数据业务/owner 完整数据行程未验；r11 在线与停用数据 API、编辑后恢复已实测。
- 第 447 行仍称真实 owner 数据行程待验收。

按技能“design 与代码现状偏离视为 HIGH”需合入前刷新。建议只更新上述现状段，引用 `e2e-evidence/platform.json`、`fault-upgrade.json` 的相应实际子合同；历史失败、旧快照、旧 false/unknown writer 和剩余矩阵均保留。不要泛化为全部 feature/AC 完成交付。

相关证据文件中也有按历史快照追加的旧状态，顶层当前指针应清晰标明；本报告不要求删除历史。

## 1. 边界条件与真实入口

1. 发布 pipeline 在 `publish_pipeline_service.py:531` 按 runtime protocol v2 冻结 delivery/准备，`:573` 按 `resolved_delivery` 进入 v2 probe；online/preview、stop/destroy 也有实际选择分发。不是只有类定义没有注册。
2. `api/router.py:25,135` 注册 app-runtime；`main.py:250` 注册独立材料入口；`app_runtime/api/router.py` 接入 management、storage、Kube、delivery、应用与代理内部接口。
3. `app_data_service.py:65-176` 在原 owner 和参数验证之后分发 K8s `RuntimeDataSessionService`，Docker 保留原 RPC。表/列标识、排序、页码、行键和值均有界校验，不把任意 SQL 暴露给 manager。
4. 材料接口、产物上传、附件流均设上限。材料 8MiB 分片、offset/size/hash 和平台枚举校验；最终总大小和完整 SHA 校验后才 confirmed/verified。数据导出用受限文件流与摘要校验，不把 CSV 塞入持久 journal。
5. 查询/等待有原操作 deadline；数据库事务不包住跨进程网络等待。未知结果持久保留，不自动换请求重做写动作。

## 2. 权限、tenant 与认证

- 人工接口：`runtime_management_service.py:35` 及 `app_data_service.py:188-213` 检查 tenant/自然 owner。自然 owner 是额外的业务约束，未以 RBAC 菜单或自写 FGA tuple 放行。App 生命周期仍走 permission/application 适配及投影。
- 用户访问：entry 判定经权限平台，路由读取不是最终用户授权。HTTP/WS 所需身份和 OBO 仍由原代理路径处理；没有把 manager key 作为用户权限替代品。
- 内部 HMAC：`runtime_protocol.py:34-105` 绑定 method、目标路径/排序 query、body SHA、timestamp、nonce、key_id；恒定时间比较、60s 时间窗、Redis 单次 nonce、角色与 node 绑定。Kube 控制面还要求专用服务角色。
- 免 cookie 的路径：`utils/http_middleware.py:48-50,439` 仅为内部运行/材料/附件协议建立其自己的可信作用域；对应 endpoint 仍执行 HMAC、Ed25519 或 opaque storage credential，不是匿名资源入口。
- 新表：`ScopedRuntimeRecord.tenant_id` 为 `None` 等待 ContextVar 填充，数据库非空/索引不变；Kube resource/delegation 均继承该模型。没有用默认租户 0 覆盖显式租户。
- 模型发现：`app_runtime/domain/models/__init__.py` 同时注册 RUNTIME_TABLES/KUBERNETES_TABLES，且被 `core/database/tenant_filter.py:131` 的强制导入覆盖，避免 lazy import 漏 tenant 表。
- 服务端 infra catalog（node/profile）为有意全局配置；跨租户容量查询只聚合 node 内资源，不向普通业务调用返回其他租户明细。

## 3. 事务、并发、幂等与资源围栏

- `runtime_delivery_repository.py:53-97` 的 UOW/tenant scope 在嵌套调用共享 session；外层提交与异常回滚。save 同时验证目标和已有对象，不依赖自动 SELECT 过滤去保护 bulk UPDATE/DELETE。
- `create_operation():285` 用 scope+idempotency_key 唯一性及内容 digest；并发冲突经 savepoint 后读取已提交同项，不重新提交不同内容。
- `admit():320` 在同一 node 行锁下计算 held/active、心跳和预算；不同租户争用使用同锁。数据会话按 node→assignment 同序锁，原 app 互斥和 helper 并发上限都持久化。
- `app_state_service.py:648` 提交 ready 时同事务校验 operation、tenant、expected state/current/pending、批准版本与冻结 delivery，并完成 App CAS、实例、route 及权限投影。没有仅凭进程内状态就提前正式切路由。
- 材料和资源不能由 self-reported UID 建立授权。resource 意图、UID、generation/owner/controller、停止事实与 cleanup 独立保留。旧 false/unknown 不因新心跳恢复；无法证明停止时保留资源与容量，未看到后台强清绕过。
- T271 restore→serve 入口仅允许严格 `resume_after_restore is True`、同操作已持久恢复结果、合法启动阶段；仍复用原冻结模板/资源/租约/停止验证。没有放宽全部 restore 的 purpose 白名单。
- restore current-v1 的 route commit、清 pending 与材料复核有现成链路；M2 第二次正常新请求 gen4 的实际证据验证该完整链，不把旧失败 gen3 改为成功。

## 4. 材料/产物与存储安全

- `RuntimeMaterialService._authority/_current` 将 delegation→op→resource→tenant/app/node/generation/owner/current assignment 和冻结 delivery 复核。每次 request/transfer 以及长 I/O 中重新检查，不把 300s ticket 当独立长期授权。
- workload 签名绑定 raw path/query/body、key、Pod UID、时间和 nonce；backend 仅保存公钥与授权记录。manager root seed/private key 不入 SQL，普通 app 不获得 manager HMAC。
- frozen artifact 仅允许明确 kind、digest、platform、app/tenant；公共 offline 材料还要求同 profile id/digest。下载不接受任意 object key/URL；上传只允许该 purpose 派生的 kind。
- transfer 按 authorization kind/id/artifact/action 唯一；刷新 ticket 作废旧 hash。分片同 offset 内容才能幂等；完整上传仍校验 parts、size、SHA、当前授权后才 confirmed/verified。
- 附件已统一走 backend `app_storage`，app token 仅保存 hash，绑定 app/version/当前 serving 或 preview；对象 prefix 为 tenant/app 或该 preview session。键名拒绝 traversal/control/backslash；legacy prefix 只容许该 app 精确附件根。
- cleanup 先 revoke binding，再限定 prefix 删除；preview 不删除正式附件。purge 快照/临时 transfer chunks 与源码历史有区分。manager 不直接持有 MinIO 配置/密钥。
- 本次未发现新硬编码凭据、私钥落库、SQL/traceback 直接暴露路径。内部诊断是受限管理员协议，公开接口用固定业务错误；此结论是相关改动静态审查，不是全仓敏感数据扫描。

## 5. SQLite / 数据 API

- owner 数据 API、SDK 附件与应用自身访问是不同授权面。K8s data grant 由 backend 独立私钥签发，绑定 actor/action/parameter digest/operation/request/app/version/exec_ref/PodUID/generation，5s 接纳窗和原 60s 总期限；manager 不可签发 owner grant。
- 在线只用当前同 UID sidecar；离线使用保留稳定 PVC，在旧 writer 停止后建立受控 data Pod，不为读取创建第二生产 writer。维护互斥、会话完成清理与结果未知均在 backend 持久。
- Docker WAL 修复限定该 app 数据目录可写以允许 SQLite WAL/SHM，SQL read action 仍 `mode=ro`，未采用 immutable 丢弃 WAL 的方式；F059 分发未改变 Docker 原通路。
- 迁移/恢复保护快照须 verified/confirmed 关联再 DDL/替换。快照可 dedup，判断依据是同操作 fact+confirmed transfer 和 artifact，不要求快照计数增加。
- 原失败和未知动作不自动恢复。显式 restore 要自然 owner、数据丢失 ACK、fresh generation、同 app snapshot、当前版本冻结 delivery；不提供任意版本选择/隐式代码回滚。

## 6. F086 兼容性与迁移

### F086 保持与升级前提

- protocol v1 的历史发布/迁移路径仍保留；v2 bundle/source-image/image 能力仅在 protocol2 选择，不能把新包误送旧 manager。
- Docker 数据 RPC/预算保持；Kube 增加 sidecar/helper 预占及 namespace/profile/report 前置。新增配置不是无条件把现有 Docker node 解释为 Kube。
- app SDK 的相对附件/模型/OBO 接口保留，附件存储权威改在 backend；不要求 manager 新建 MinIO 实例/桶。
- 受控 helper 与材料接口是新后端/manager 的成套合同，不能只更新 manager 而让旧 backend 缺 API；Kube 还要求真实 RBAC/准入/网络/稳定卷能力报告，缺前置 fail closed。
- transfer authority 扩展的历史 nullable authorization_id 无迁移内数据回填；客户升级应按设计停止旧 transfer 并执行已声明的版本/数据前置，不把模型新 default 当旧历史行已回填。

### `667546bb7` 已继承，不是遗漏

- F059 继承提交：`ea3b1f6afb68da2b52ba4fd1fcf0bb5e060510ba`。
- 当前 `f086_runtime_byte_counters.py` 与 `667546bb77eeb366e66a13d544d122ef24811e35` **逐文件 diff 为零**。
- 当前 `RuntimeArtifact.size_bytes` / `RuntimeTransfer.offset` 均为 non-null/default0 的 `BigInteger`。
- `f059_merge_f086_heads` 显式汇合 F059 与 byte-counter 两父链。不能仅因该修复 SHA 不是 ancestor 就判断缺失。

### Alembic 静态图

本次用 AST 读取 115 个 revision：唯一 head `f059_resource_phases`；missing parent 为零。

链路包括 `f059_runtime_kubernetes` 与 `f086_runtime_byte_counters` → `f059_merge_f086_heads` → release-head merge → `f059_resource_phases`。保持原历史父链；清除旧 operation/kind/name 唯一索引允许顺序阶段保留独立不可变证据，降级要求先处理冲突，未直接删审计行。

此为静态模型/DDL 审查，未新执行 MySQL/DM8 升级。DM8 依用户确认仅静态核约束/SQL 类型，不宣称实测兼容。

## 7. 已有证据及明确边界

### 可以引用的既有证据

- `e2e-evidence/platform.json`：T069 五交付模式 v1/v2、审批/预览、HTTP/WS/SDK/OBO、数据、权限、停启与 scoped 删除业务闭环；文档明确不是所有 AC/故障/卸载/发行通过。
- `e2e-evidence/fault-upgrade.json`：保留各历史失败和精确子项。R11 真实离线数据/恢复；M2 真实迁移失败与 gen4 显式恢复；R32 在途准备租约交接。
- 独立证据报告 `/private/tmp/f059-m2-restore4-independent-evidence-review.md`（SHA `52e7750627fa602226800ec4b44968ed5416b0f61784dafb6d195ad2c35f3f1a`）：原失败 parent/gen3 不变，gen4 单次恢复、NULL+随机哨兵摘要、v1 route、pending 清除、同操作 confirmed upload / dedup artifact 和导出完整性一致；不输出数据/nonce。
- 独立证据报告 `/private/tmp/f059-prepare-sigkill-r4-independent-evidence.md`（SHA `a89f59ae73a2b54a91b550b3497bcf467c1d46609e2a65dec912571c304202a2`）：同原 prepare/deadline/install UID/CID，manager controller30→31，原240s hook自然完成，8准备资源正常清理/released。后续 probe 是 SQL completed/cleanupcomplete+正式版本，不据此声称 probe 物理清理或批准上线。
- 已有实际 Service/SQLite 配对、定向 L1 日志包括保护 sticky/false/metadata、restore→serve、幂等/租约/资源事实及自然 owner 拒绝。此次审查未重跑它们，也未用 mock 替代远端验证。

### 仍保留的交付边界

1. 完整离线客户安装、完整依赖/缓存组合、全部 fault/UID替换/未知 writer/响应丢失、独立安装域卸载保留等仍按各 AC 的现有未验标记，不能由局部通过替代。
2. 旧 r4 和历史 false/unknown held writer 继续保留围栏/资源/容量，不为合入强清。
3. ARM、追加109、跨节点/NodeLost、正式公共 CI/Docker Hub/tag 发行本轮暂停/未执行。189 单节点 amd64 不证明这些能力。
4. CLI 最新 wheel已定向本地源码匹配，不意味着客户发行已完成。静态迁移图不等于客户旧数据库真实升级。
5. 本报告仅后台审查线，不代替 runtime/安装/发行/前端或 root 的最终集成判断；不直接勾选全交付 T072。

## 合入建议

先由 root 修正 D1 的当前文档快照，保留历史和上述边界后做文档定向复审。后台代码无需因本报告新增实现或重跑全量；可以按用户授权将开发合入 `feat/3.0.0-vibe`，另保留未完成交付事项。


## D1 定向复审关闭（2026-10-23）

**复审结论：D1 CLOSED；后台开发合入 L2：PASS。** 本节取代前文因 D1 暂列 NEEDS_FIX 的结论；原发现及审查过程保留。

仅检查整合工作树 `/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration` 的本次 `design.md` 文档 diff，未做新的代码审计或测试，未操作远端。

- 第 120–124 行当前快照已更新为 R32、原 267/271 加 T274 后 268/272，并明确余项属于交付门，不等同四块未实现业务代码。
- 第 266 行将正式初始化与准备实证列为已验证，完整续期故障矩阵仍保留待验。
- 第 308、310、312、453 行已按 R11 owner 在线/停用编辑、CSV、恢复一致性及 M2 显式恢复更新，不再保留相反的当前状态描述。
- 第 421 行已知坑明确旧 holder 未到期的正常 409 不得进入业务失败清理，以及 T272/T273 的既有处理落点与 R32 实证。
- 文档保留历史、旧 false/unknown writer 围栏、ARM/追加109暂缓、DM8静态、完整离线/剩余故障/独立卸载/跨节点/公开发行未完成边界；没有把准备资源清理或 probe SQL终态扩大为物理清理/审批上线证明。
- 头部区分设计起点与实现基线、更新日期，并追加本轮修订历史。CI 锁条目为本次整合文档同步，不在本后端复审中新增 CI 实现审计结论。

复审文档 SHA256：`9f41bbc3acc64525eb3aedf4c97f4f846a201b520cefd4278844f762b4638dce`。

此 PASS 仅为当前后端开发合入范围；前述完整交付边界保持。无需因关闭 D1 补跑全量验证。
