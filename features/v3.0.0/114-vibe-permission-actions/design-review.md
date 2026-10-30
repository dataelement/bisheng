# F114 统一 v2 设计复审记录

**日期**：2026-10-30。**结论**：LGTM；R1–R6 均 CLOSED。用户要求按建议修订后，同一独立 architecture-critic 复审结果为 PROCEED，七维均为绿色，无 blocker、should-fix 或 nit；主代理按 sdd-review 的 24 项检查复审通过。前稿 REVISE 与曾撤回的同代理 LGTM 原样保留为历史，不作为当前结论。本轮仅文档与源码静态核对，不是运行测试或部署验证；整份设计已于2026-10-30获用户单独确认，开始任务拆解与开发。

**依据**：修订 spec 共 71 条 AC、design、design 模板、release-contract、constitution、当前代码基线 `bb62790ad22a3204493e7dce5878e0a4f7109599` 与用户本轮决定。实际代码仍含 v1；本稿不宣称已删除旧实现。

## 1. 当前审查结果

LGTM

当前独立复审：[architecture-critique-r4-r6.md](./architecture-critique-r4-r6.md)，结论 PROCEED；修订前报告另存为 [历史评审](./architecture-critique.md)。以下三项原问题与其行号对应修订前设计，关闭依据见 §6。

**原审查问题（修订前）**：§4.5/§4.8 未为 observation → recover 创建的新 deploy 定义独立系统授权上下文；沿用户凭据检查会阻断自愈，按 deploy/auto_commit 放行又会与配置重建混淆，无法闭合 AC-60。 | SEVERITY: high | LOC: design.md:185–192、design.md:222

**原审查问题（修订前）**：§4.5 的阶段准入未明确先于 maintenance 投影和停止旧 writer；现有执行先阻断旧路由并停实例，再迁移/启动，晚到的授权拒绝已不能保持旧服务。 | SEVERITY: medium | LOC: design.md:189–192

**原审查问题（修订前）**：§4.7/§4.9 新增预览凭据，但未定义同一复用键的并发串行点及会话/凭据/operation 的提交、失败和未知结果回收顺序，查询索引不能保证幂等。 | SEVERITY: medium | LOC: design.md:211–218、design.md:235

**前轮 R3 收窄内容（保持）**：旧绑定导入、升级、rebind 一并退役；同版本环境变量生效复用 AC-26 和 config_restart，代码/镜像/运行环境变更复用 AC-35、AC-36 正常新版本发布；移除 runtime_upgrade 用途，不新增独立通用重建。R3 原始问题和源码证据见 §2.3。

- 用户原规格已确认；本轮明确共用接口原权限及唯一 v2 支持方向，已形成可审阅的收敛条款。修订设计仍须用户单独确认后才拆任务和编码。
- 资源仍归属服务账号配置的自然人，owner/tenant 与受保护 owner 不变；真实服务账号只用于该次授权、可撤销初始来源与操作者审计。
- 本轮仅文档；没有业务测试、浏览器视觉测试、镜像发行或 116/189 环境变更。

## 2. 问题历史与关闭状态

| 问题 | 原严重度 | 原因 | 本次收敛 | 状态 |
| --- | --- | --- | --- | --- |
| R1 共用接口 | high | 前缀通配强制管理头会波及助手/工作流等既有读取与调用 | D3/§4.4/§6.1 维持原最小权限和调用，不新增统一读门槛/路由拆分；具体管理范围和专用写保护分开 | CLOSED |
| R2 v1 阶段授权缺口 | high | 旧 manager 在 RPC 内启动/切路由，无法套用 v2 operation 阶段端口 | 用户明确只保留 v2；D9/§4.11 删除旧执行/回退/绑定导入入口，阶段授权只需一套；配置、代理、交付与测试同步，旧资产单独处置 | CLOSED |
| R3 通用重建的保留依据 | medium | 旧 rebind 仅接入 deploy；正常在线同版本直接返回原实例，不能证明通用 v2 重建已实现 | 用户采纳收窄建议：AC-57/M22 明确退役；D7/D9/§4.11/§6.1 指向现有配置确认重建与正常新版本发布，不新增通用重建 | CLOSED |
| R4 系统自愈授权来源（独立 B1） | high | recover 新建 deploy/auto_commit，设计却仅定义用户主体与凭据复核，未知来源拒绝 | 补独立系统意图生产、持久化与验证，绑定原可信 route/epoch/版本，不以通用标志豁免 | CLOSED |
| R5 首次副作用前的授权（独立 S1） | medium | maintenance 事实先阻断路由/出站策略并停旧实例，早于迁移/启动 | 明确首次准入先于维护投影及旧 writer 停止，说明进入维护后撤权的安全收尾 | CLOSED |
| R6 预览并发与凭据失败回收（独立 S2） | medium | 会话先查后建且单独提交；新凭据加入后的事务/补偿未定义 | 明确复用键串行点，会话/凭据/operation 的原子关系或可恢复状态及单凭据回收 | CLOSED |

### 2.1 本轮静态核对依据

- [Compose](../../../docker/docker-compose.yml) 默认 backend 为 2，manager/入口/出口配置为 2；[K8s Chart](../../../deploy/kubernetes/app-runtime/templates/workloads.yaml) 同样为 2。源码 config 仍存在默认 1，故列为明确清理项，而非声称只改开关即可完成。
- [DockerExecutor](../../../src/runtime-manager/runtime_manager/executors/docker.py) 已有 bundle/image/source-image；[RuntimeDeliveryCoordinator](../../../src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py) 将缺少 delivery 的已有源码包转为 source-image；K8s 使用其现有执行后端，未新增编排体系。
- [legacy_prepare](../../../src/runtime-manager/runtime_manager/legacy_prepare.py) 及 [OCI assembler](../../../src/runtime-manager/runtime_manager/oci_assembler.py) 仍引用 builder 模板；v2 预览/data_worker/K8s helper 使用 appdb。设计明确提取共用能力后再删除旧 RPC 壳，防止删旧代码时破坏现行功能。
- [manager main](../../../src/runtime-manager/runtime_manager/main.py) 仍按协议启动不同对账循环并注册旧 routers；[旧 inventory](../../../src/runtime-manager/runtime_manager/api/upgrade.py) 虽以 /v2 命名仍读取旧 desired-state。清理按调用用途而非数字或文件名。
- [RuntimeUpgradeService](../../../src/backend/bisheng/app_runtime/domain/services/runtime_upgrade_service.py) 的 import_binding 是旧执行体/存储导入；rebind 虽调用 v2 coordinator，但正常在线同版本会命中既有实例返回分支。上一轮以“调用 v2 coordinator”推断“现有通用 v2 受控重建”的结论不充分，详见 R3。
- 唯一阶段授权端口位于现有 `/api/v1/internal/app-runtime/v2/operations/{operation_id}/authorize-step`，复用 RuntimeRoute、manager 服务角色及 v2 签名/nonce，不另建旧签名通道。

### 2.2 实施前保留事项

此处为既有安全前置，不是未关闭的设计问题：真实环境协议、镜像、Engine 标签、legacy_exec_ref/导入记录、附件端点与卷必须盘点。配置值为 2 不保证没有旧导入执行体；source-image 或 manifest_version:1 也不能作为旧运行协议的判据。仅原生 v2 绑定可沿“不主动重建”规则，旧资产按授权先保留数据再重建，不提供长期双协议。

### 2.3 R3：原问题、证据与本轮修订

**原问题定位**：修订前 design D7（第 75 行）、§4.11 清理矩阵（第 259 行）、§6.1 退役入口（第 317 行），关联 spec AC-57 和 M22。上述行号是上一稿历史定位，现行锚点为 D7/D9/§4.11/§6.1。原稿将“现有 v2 受控实例重建”作为保留项，却未给出与旧 rebind 的执行边界；先前评审把接入 v2 coordinator 当作能力已存在的依据。

**静态证据**：

1. [runtime_management.py](../../../src/backend/bisheng/app_runtime/api/endpoints/runtime_management.py) 第 112–125 行将 `/runtime/upgrade` 接至 import_binding，将 `/runtime/upgrade/rebind` 接至 rebind。
2. [runtime_upgrade_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_upgrade_service.py) 第 131–159 行将旧导入 route 写为 `maintenance` 并返回 `requires_rebind`；第 161–166 行的 rebind 只加载 current_version 后调用 `coordinator.deploy(..., preserve_pending=True)`。
3. [runtime_delivery_coordinator.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py) 第 356–358 行：route 为 `serving`、version 等于 current version 且 app 为 `online` 时，直接返回既有 exec_ref/operation_id。该分支没有创建重建操作、增加 generation 或启动新实例。旧导入 route 的 maintenance 状态不会命中它，但这不构成原生 v2 通用重建能力。
4. 已有配置确认重建是另一条真实链路：[secret_rebuild_service.py](../../../src/backend/bisheng/app_runtime/domain/services/secret_rebuild_service.py) 第 117–154 行验证 delivery/确认快照，写入 `purpose=config_restart`，直接 submit 新 deploy operation。它对应 AC-26，不能作为存在独立 runtime_upgrade 能力的证明。源码扫描也未发现业务代码写入 `purpose=runtime_upgrade`。

**影响**：接手实现者可能保留一个点击后仍返回原实例的“重建”入口，或在权限映射任务中临时增加通用重建行为；AC-57 的交付边界、旧入口删除和验证对象因此不清楚。这是现状依据和执行契约深度问题，未发现因此直接突破权限边界，严重度为 medium。

**本轮已采纳的修订**：用户明确“按照建议修改”，采用更小范围。旧 `/runtime/upgrade/rebind` 与绑定导入一并退役；同版本环境变量生效保留 AC-26 配置确认重建，代码/镜像/profile/运行环境变更保留 AC-35、AC-36 正常新版本发布。M22 不再分配可授权执行动作，D7 不登记 runtime_upgrade；§4.11/§6.1 明确现有入口、确认快照/幂等和阶段授权。普通 deploy 的同版本幂等返回保持，不增 force 或独立通用重建 API。

**定向验证计划**：检查旧 inventory/upgrade/rebind 均不注册且无运行/存储副作用；配置确认重建仍创建新 operation，保存不重启、取消确认不创建、重复确认幂等，固定版本/delivery 和 writer 围栏保持；代码/镜像/profile 变更仍经新版本发布和审批。此处为后续实现验证计划，本轮未运行测试。

**本轮文档差异**：仅修改 AC-57 正文，其余 70 条 AC 与上一收敛稿一致；discovery、spec、design、release-contract、两份评审及三份离线 HTML 同步。设计仍待单独确认，尚未创建 tasks、修改业务代码、提交、推送或部署。

### 2.4 修订前独立评审：R4、R5、R6（历史）

独立代理 `/root/f114_convergence_design_critic` 使用全新上下文，只读取 spec、design 和源码，未收到设计讨论过程，也未读取既有评审报告。其原文完整保存在 [architecture-critique.md](./architecture-critique.md)，不改写独立结论；原文的 B1/S1/S2 分别对应本表 R4/R5/R6。7 维评审中“数据与状态建模”为红，“失败与规模现实性”为黄，结论 REVISE。该架构结论是建议；SDD 设计本身也尚未获用户单独确认。

#### R4：给系统自愈一个可验证的授权来源（high）

- **当前源头**：[RuntimeOperationService.observation](../../../src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py) 第 701–723 行验证观测与 route 围栏后调用 recover；[RuntimeDeliveryCoordinator.recover](../../../src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py) 第 481–542 行新建 deploy，写 auto_commit，重新注入环境；fact 第 571–574 行还会自动提交新路由。
- **设计缺口**：D6/§4.5/§4.8 只说明用户主体、凭据与 F048 当前资格，缺来源或未知用途拒绝；但 AC-60 要求自愈不依赖历史操作者。配置确认重建也使用 deploy/auto_commit，不能靠这两个通用字段辨认系统资格。
- **建议**：沿现有 authorization_context 区分用户意图与 backend 生成的系统自愈意图，说明 observation/recover 如何绑定原 operation、route/epoch、tenant、批准版本及当前有效运行意图，authorize-step 和 route commit 如何验证；用户不可自证系统来源。明确系统自愈取消与应用下线的既有动作边界。不新增授权引擎或恢复框架。
- **仅需的定向验证**：历史发布人撤权后，原批准版本仍能受控自愈；伪造系统来源、版本/route 变化被拒绝；用户配置重建仍须 edit AND publish，不能借 auto_commit 豁免。

#### R5：检查需要早于旧服务被影响（medium）

- **当前首个效果**：[OperationExecutor._deploy](../../../src/runtime-manager/runtime_manager/operations.py) 第 304–318 行先 report maintenance、stop_instances，之后才备份和迁移；backend fact 第 491–497 行在 maintenance 即调用投影阻断；[RuntimeProjectionService.block](../../../src/backend/bisheng/app_runtime/domain/services/runtime_projection_service.py) 第 20–28 行修改 route 并撤销出站策略。
- **设计缺口**：仅列“迁移/正式启动/新路由”之前检查，不足以保证 AC-40 的旧服务保护；实现者若在迁移前才检查，已撤权请求可能先停掉旧服务。
- **建议**：给出最小阶段顺序表，首次准入必须在 maintenance 投影与停止旧 writer 之前；分别说明迁移、启动、路由提交的检查和已进入维护后的必要收尾。保留既有围栏和清理，不要求跨进程全局事务。
- **仅需的定向验证**：准备完成、维护开始前撤权，旧 route、出站策略和 writer 不变；进入维护后拒绝新效果时能够按原意图安全收尾，不重新发布未授权内容。

#### R6：预览会话、凭据和操作需要共同收敛（medium）

- **当前提交顺序**：[PreviewInstanceService.start](../../../src/backend/bisheng/app_publish/domain/services/preview_instance_service.py) 第 165–181 行先查后建，会话在 _insert_session 第 429–444 行独立提交 running，之后才提交运行操作；启动异常只关闭会话。既有查询索引不保证活跃会话唯一。
- **设计缺口**：§4.7/§4.9 新增 per-preview credential 和用途复用键，但没有声明并发启动的串行点、凭据签发的事务参与关系、崩溃与未知结果后的幂等回收。认证拒绝未绑定凭据只能限制访问，不能自动消除重复会话或遗留凭据。
- **建议**：明确同一 version/viewer/purpose/task 的串行点，复用可参与事务的凭据签发方式；定义会话/credential/operation 一起提交或可续办的最小状态，失败只回收本会话 credential，重复处理保持幂等，不影响生产凭据。
- **仅需的定向验证**：同键并发启动只获得一个有效预览；签发失败、签发后崩溃、operation 提交未知结果、启动失败及重复回收不会留下可用孤立凭据，也不撤销生产凭据。

**排除的疑点**：不把“自愈启动读取当前保存的环境变量”追加为新问题。F055 spec AC-70、AC-73 已允许正式启动/恢复按本次受理选定配置取值；本轮需补的是系统授权来源，不是另加旧环境值冻结规则。预览附件使用不同凭据也不单独作为缺陷，因为设计已要求会话/用途/operation 绑定，尚未证明另有独立问题。

以上为修订前设计缺口和后续定向验证建议，原评审未运行测试或修改设计。用户随后要求修订，现已补齐并按 §6 复审关闭；不重新打开 R1/R2/R3，不改变已确认产品口径。

## 3. 24 项设计检查

| # | 检查项 | 结果 | 设计证据 |
| --- | --- | --- | --- |
| 1 | 目标简明 | PASS | §1：统一 Vibe 六动作、具体租户及唯一运行协议 |
| 2 | 非目标 | PASS | §1/§8：不迁归属、不重写编排、不改助手共享权限、不全量回归 |
| 3 | 特有约束 | PASS | §2：原归属、可信主体、组合动作和单协议 |
| 4 | 宪法引用及门禁 | PASS | 只引用全局规则；C1–C8 核对见 §4，无已发现冲突 |
| 5 | 关键决策 | PASS | D1–D9 覆盖所有主要边界 |
| 6 | 备选/选定/原因 | PASS | 每项含被否方案；D9 明确不维护双协议的依据 |
| 7 | 重审条件 | PASS | 每个决策明确何时重审，不允许实现中恢复回退 |
| 8 | 原因证据 | PASS | CURRENT/CREATOR_GRANT、真实 actor、现有配置/执行器/共用函数有代码依据 |
| 9 | 数据流闭合 | PASS | §4.5 明确 observation/recover 生产与阶段/路由消费；§4.7 明确预览原子登记、ready 激活及失败回收 |
| 10 | 数据结构与格式 | PASS | §4.5/§4.9/§6.2 明确 origin_kind、source、maintenance_transition 与预览 operation_id/status；用户与系统结构互斥 |
| 11 | 模块边界 | PASS | §4.1/§4.11 列移除与保留，公开 application 端口不泄露 ORM |
| 12 | 现状/目标一致 | PASS | §4.1/§4.11 和坑 15 记录旧 rebind 的同版本返回；不再把它写成现有通用重建 |
| 13 | 反直觉事实 | PASS | §5 共 18 项；新增 recover 与配置重建同 kind、maintenance 首效果及预览独立提交的现状与处理 |
| 14 | 坑的后果 | PASS | 权限泄露、生产凭据中断、错租户、误删公共能力均说明 |
| 15 | 处理位置 | PASS | 各坑定位到决策/函数/§4.11 清单 |
| 16 | Outgoing | PASS | §4.5/§6.1/§6.2 明确维护前准入、fact 投影再验、有效确认后停 writer，以及预览生命周期事务端口 |
| 17 | Incoming | PASS | §6.4 权限、身份、审批、运行、存储/代理与 UI，无新增基础设施 |
| 18 | 风险 | PASS | §4.5/§4.7 覆盖维护前后撤权、回复未知、Version 串行/锁序、提交前后失败与单凭据回收；原协议清理风险保留 |
| 19 | 测试分层 | PASS | §7：动作配对、v2 默认/旧入口拒绝/能力保留、专用 E2E，不运行 v1 成功链或全量 |
| 20 | 人工验证 | PASS | §7.3 页面、临时主体、计划命令明确；计划用例未冒充存在/通过 |
| 21 | 后续边界 | PASS | §8 不保留旧长期兼容、不做自动迁移/新增运行体系 |
| 22 | 修订历史 | PASS | 原初版、R1 收窄、D9/v2 收敛分别留痕，未伪造用户确认 |
| 23 | spec 一致 | PASS | §4.5 补齐 AC-60 系统恢复与 AC-40 旧服务保护；§4.7 补齐预览执行设计；71 条 AC 原文未改，六动作和归属不变 |
| 24 | tasks 偏差 | PASS/N/A | 未有 tasks、未编码，未记录不存在的实施偏差 |

## 4. Constitution Check

| 规则 | 核对结果 |
| --- | --- |
| C1 | 业务通过 application 端口，数据库在所属 repository；backend 不增加 Docker/K8s 权限 |
| C2 | JsonType 在 Python 解析、nullable 增列/索引；无数据库专用语法或业务数据迁移写入 Alembic |
| C3 | 具体管理范围与真实身份分开；ContextVar 自动过滤，内部任务携可信 tenant，共用业务权限不变 |
| C4 | 六动作、真实主体及唯一 v2 保持；系统恢复只消费可信原运行意图，用户效果在维护前及后续阶段复核，不能以 deploy/auto_commit 泛化豁免 |
| C5 | 错误来源和 19704/19705 设计预留不变，编码前再检查冲突并三语生成 |
| C6 | 不存 JWT/key 原文；预览凭据与会话/operation 原子绑定、ready 后激活、仅单凭据回收；提交未知先查询，生产凭据不受影响 |
| C7 | 请求包装层与 hook，store 不调用 HTTP |
| C8 | 平台 DB/Redis/对象存储为真相；本地缓存保留，旧本地控制真相退役；能力端口在 API/worker 注册 |

## 5. 变更与阶段记录

原规格 70 条已获确认；用户随后明确唯一 v2 方向，新增 AC-71。前一轮实质复审发现 R3 后整体结论为 NEEDS_FIX；用户随后采纳更小范围建议，本轮进一步收窄 AC-57/M22，原 R1/R2 仍关闭。R3 经前一轮同代理静态复审关闭，当时整体结论恢复为 LGTM；原始源码证据由 §2.3 保留。用户随后选择继续评审，独立 architecture-critic 发现 B1/S1/S2，主代理核对后记为 R4/R5/R6，当时整体结论改为 NEEDS_FIX；本次按用户要求补齐 R4/R5/R6 后，同一独立代理复审 PROCEED，24 项设计检查恢复 LGTM。未把设计或架构意见当作已实现事实。

依据 AGENTS.md §6、SDD-Guide §3、sdd-review，修订设计仍需用户单独确认后才能拆任务和编码。用户此次明确采纳收窄建议是修改授权，不替代对整份设计的单独确认。本轮没有业务测试、浏览器视觉测试、代码、提交、推送、镜像发行或 116/189 环境变更。

**文档核查范围**：核对修订差异、71 条 AC 追溯、36 项盘点编号、24 项设计检查、真实端口/类名/确认参数及退役边界；Markdown/HTML 同步、目录锚点、本地文件链接、离线资源与宽窄屏/打印样式作静态检查。未执行浏览器视觉验证、业务测试、旧入口删除、容器重建或部署，后续只做本功能定向验证。

**修订前独立评审锚点（历史 SHA-256）**：

- spec.md：`f40eda6ede3a6179b192af74d908fe09b33fc7331a508c4f656173fd5fb24b6b`
- design.md：`01406fbb63ec295d91f360aa97cb3c4f06e851eac9d9ff31a049fb6474b487ab`

**修订前独立复审记录（历史）**：代理 `/root/f114_convergence_design_critic`；完整原文 [architecture-critique.md](./architecture-critique.md)。当轮只更新评审、阶段索引及 HTML，spec/design 当时与上列历史锚点一致；本次用户要求的设计修订及新锚点见 §6。

## 6. R4/R5/R6 本轮修订与复审关闭

- R4：D6、§4.5、§4.8、§6.2 明确 user_request/system_recovery 互斥来源、observation/recover 生产及逐阶段/auto_commit 消费；系统只恢复原可信运行意图，不以历史用户或通用字段授权。系统恢复无用户通用取消，现有 unpublish 终止运行意图与恢复。
- R5：§4.5 补首个副作用顺序，准入早于维护投影和停旧 writer；维护事实、精确 route 转换与 sequence 同事务；回复未知只确认同次事实，进入维护后撤权只安全收尾，后续新效果仍拒绝。
- R6：D5、§4.7、§4.9、§6.1 补 Version 串行点、同一 repo/UoW、starting/operation_id、事务签发绑定与审计、ready 激活、提交后 wakeup、未知结果及幂等单凭据回收；预览 fact/reclaim 统一锁顺序，不新增表/框架。

71 条规格原文不变，以上均是现有 AC 的执行设计补齐，当前尚未实现。原独立报告 architecture-critique.md 原样保留为上一稿快照，其设计行号对应旧 design SHA-256 `01406fbb63ec295d91f360aa97cb3c4f06e851eac9d9ff31a049fb6474b487ab`，现行章节锚点不变。复审通过不替代用户对整份设计的单独确认。


**当前复审结论**：LGTM。主代理重新按 24 项设计检查及 Constitution Check 核对，未发现未关闭的设计问题。同一独立代理全文读取当前 spec/design 并核实相关事务、凭据签发和执行顺序源码，结论 PROCEED，七维均为绿色；原 B1/S1/S2 对应 R4/R5/R6，全部闭合。独立意见为设计建议，不代表代码实现或运行验收通过。

**当前审阅锚点（SHA-256）**：

- spec.md：`f40eda6ede3a6179b192af74d908fe09b33fc7331a508c4f656173fd5fb24b6b`（原文未变）
- design.md：`67af078df54babc7d40a13ecdd0d9720063b86502cb0e24e2ca0b8d8774b9f6b`

独立复审原文：[architecture-critique-r4-r6.md](./architecture-critique-r4-r6.md)，逐字保存；原报告另存未覆盖。Markdown/HTML 章节、71 条 AC 与 36 项盘点追溯、目录/本地链接、离线及响应/打印 CSS 仅做静态检查；没有视觉验收、业务测试、代码修改、提交、推送或部署。依 AGENTS.md §6、SDD-Guide §3 和 sdd-review，下一步仍是用户单独确认整份修订设计，然后才拆任务与编码。

## 7. 用户确认与实施阶段

2026-10-30用户选择“确认设计，进入任务拆解和开发”。该确认发生在上列完整复审后；历史评审及SHA仍指当时快照。现行design增加实施状态、spec只更新阶段元数据，71条AC正文不变。tasks按21项清单LGTM，当前16/66任务完成，78项定向检查通过；这不是整项代码审查或真实部署验收。
