# 需求说明 Requirements: 发布申请提交性能优化（第一阶段）

## 阅读摘要
- 本文档说明：降低首钢门户知识库“发布文件”申请提交接口的同步耗时，同时保持权限、安全和审批事实语义不变。
- 当前状态：`implemented`
- 需要重点确认：新增独立通知 outbox 表及 Celery Beat 补偿任务；通知采用 at-least-once 交付语义。
- 本次只实现已确认的第一阶段，不包含 OpenFGA 审批人解析优化。

## 元信息 Metadata
- Feature ID: `054-file-publish-submit-performance`
- Status: `implemented`
- Mode: `bug-fix`
- Created: `2026-07-14`
- Updated: `2026-07-14`
- Source request: `创建发布申请接口响应约 14 秒；实现第一阶段性能优化`

## 需求入口摘要 Intake Summary
- 问题 Problem: `POST /api/v1/approval/shougang/file-publish/submit` 在返回前同步执行全量目标文档扫描、逐文件权限校验、逐审批人事务写入和站内信写入，观察耗时约 14 秒。
- 当前状态 Current state: 选择目标文档或文件时，提交接口使用空关键词重新拉取全部候选；提交复验仍逐候选执行 `view_file`；审批任务逐条提交；发布申请站内信同步发送。
- 目标结果 Target outcome: 提交只校验选中目标，删除多余逐文件权限检查，批量创建审批任务，并把发布申请站内信可靠地移入 Celery；日志能量化各阶段耗时。
- 影响对象 Affected users/systems: 首钢门户发布文件用户、审批中心、知识版本管理、消息中心、Celery Worker/Beat、MySQL/DM8。
- 请求停止点 Requested stopping point: `verification`

## 范围 Scope

### 包含 Includes
- 发布提交阶段增加可检索的分段耗时日志。
- 根据 `target_document_id` 或 `target_file_id` 定向校验单个目标，不再全量搜索候选。
- 发布提交复验不再执行候选文件 `view_file`，保留登录、源空间 `publish_file`、目标空间 `view_space` 和可选目录 `view_folder`。
- 新增独立的发布申请通知 outbox，由 Celery 发送站内信，并由 Beat 补偿未完成事件。
- `ApprovalGate` 首节点审批任务使用一次批量事务写入。
- 保持现有提交 API 请求/响应结构和前端交互不变。

### 不包含 Excludes
- 不异步化登录、空间权限、业务领域匹配、目标有效性校验或审批路由匹配。
- 不异步化审批人解析，不新增 `initializing` 审批状态。
- 不合并或缓存 OpenFGA owner/manager 查询；该项属于第二阶段。
- 不修改普通版本管理搜索接口和发布文件搜索列表的 20 条懒加载交互。
- 不把审计日志迁移到 Celery。
- 不修改审批通过后的文件复制、向量复制和版本关联流程。
- 不修改首钢门户宿主项目或 Client 前端。

## 需求列表 Requirements

### REQ-001: 发布提交可观测性
作为运维和研发人员，我需要看到发布提交各关键阶段的耗时，以便从生产日志区分数据库、权限、审批和通知入队耗时。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 发布提交成功 THEN 系统 SHALL 输出一次结构化性能日志，至少包含基础校验、目标校验、审批创建、通知入队和总耗时，以及不含敏感信息的业务 ID。
- `AC-REQ-001-02`: WHEN 发布提交在任一阶段失败 THEN 系统 SHALL 输出总耗时、已完成阶段耗时和失败阶段，且不吞掉原异常。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated test | `test/approval/test_shougang_approval_service.py` 捕获成功日志字段 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | automated test | `test/approval/test_shougang_approval_service.py` 捕获失败日志并断言异常继续抛出 |

### REQ-002: 单目标定向校验
作为发布申请人，我需要提交接口只校验我选中的目标文档或文件，以便目标空间规模不再线性放大提交耗时。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN 请求包含合法 `target_document_id` THEN 系统 SHALL 只加载该文档、其唯一版本和主文件，并返回与原候选条目一致的标题信息。
- `AC-REQ-002-02`: WHEN 请求包含合法 `target_file_id` THEN 系统 SHALL 只加载该文件及其版本归属，并确认它是目标空间内解析成功、尚未加入版本链的普通文件。
- `AC-REQ-002-03`: IF 目标跨空间、已删除、解析未成功、为目录、属于多版本链、已加入版本链或与请求类型不符 THEN 系统 SHALL 保持现有 `400 目标文档不可用于发布` 行为且不创建审批申请。
- `AC-REQ-002-04`: WHEN 执行目标复验 THEN 系统 SHALL NOT 调用空关键词全量候选搜索。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated test | `test/knowledge/test_knowledge_version_service_similar_scan.py` 定向文档校验 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | automated test | 同文件定向校验场景 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | automated test | Knowledge Service + Shougang Approval Service 参数化非法场景 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | automated test | 断言 `search_shougang_publish_version_sources` 未被提交路径调用 |

### REQ-003: 发布提交权限边界对齐
作为已拥有源空间发布权限和目标空间查看权限的用户，我需要提交目标复验与发布搜索保持一致，不再被目标文件级 `view_file` 二次阻断。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 用户通过源空间 `publish_file`、目标空间 `view_space` 和可选目录 `view_folder` 校验 THEN 系统 SHALL 不构造、不调用候选文件 `view_file` 权限检查器。
- `AC-REQ-003-02`: IF 用户缺少上述任一仍保留的空间或目录权限 THEN 系统 SHALL 在创建审批实例前拒绝请求。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | automated test | `test/approval/test_shougang_approval_service.py` 断言权限检查器未调用 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | regression test | 既有发布权限拒绝测试保持通过 |

### REQ-004: 发布申请通知异步化
作为发布申请人和审批人，我需要审批申请先可靠落库并快速返回，站内信在后台发送且失败可补偿。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: WHEN 新建发布申请返回 `pending` 且存在首节点任务 THEN 系统 SHALL 创建唯一通知 outbox 并在站内信发送完成前返回原响应。
- `AC-REQ-004-02`: WHEN Celery 消费通知 outbox THEN 系统 SHALL 批量获得审批人、发送一条原格式审批站内信，并把 outbox 标记为成功。
- `AC-REQ-004-03`: IF 消息发送失败或首次 Celery 投递失败 THEN 系统 SHALL 保留失败/待处理记录，由周期任务在最大重试次数内再次投递，并记录错误摘要。
- `AC-REQ-004-04`: WHEN 同一发布申请重复提交或成功 outbox 被重复消费 THEN 系统 SHALL 不新增第二个 outbox，且成功记录直接跳过。
- `AC-REQ-004-05`: WHEN 审批路由为 `pass`、返回异常、返回重复实例或没有 `task_ids` THEN 系统 SHALL 不创建发布申请通知 outbox。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | automated test | 提交服务断言仅入队、不调用同步 `send_generic_approval` |
| AC-REQ-004-02 | V-AC-REQ-004-02 | automated test | Worker 测试断言消息参数与 outbox 成功状态 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | automated test | Worker 失败、Beat 补偿和最大重试测试 |
| AC-REQ-004-04 | V-AC-REQ-004-04 | repository/worker test | 唯一约束、幂等创建和成功跳过 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | service test | 非 pending/无任务分支不入队 |

### REQ-005: 审批任务批量持久化
作为审批系统，我需要首节点多个审批任务在一次事务中创建，以便审批人数量不再导致逐条提交往返。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: WHEN 首节点解析出多个审批人 THEN 系统 SHALL 使用一次 Repository 批量调用创建全部任务，并按审批人解析顺序返回全部 `task_ids`。
- `AC-REQ-005-02`: IF 批量写入失败 THEN 系统 SHALL 不返回部分成功的 `task_ids`，且原错误继续向上抛出。
- `AC-REQ-005-03`: WHEN 其他审批场景使用 `ApprovalGate` THEN 任务字段、节点模式、状态和 API 响应结构 SHALL 保持不变。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | automated test | `test/approval/test_approval_gate.py` + Repository SQLite 测试 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | automated test | 模拟批量 Repository 失败 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | regression test | 审批模块相关测试集 |

### REQ-006: 兼容性与安全不回退
作为现有调用方，我需要本次性能修复不改变发布申请 API 和审批事实语义。

#### 验收标准 Acceptance Criteria
- `AC-REQ-006-01`: WHEN 前端提交现有请求 THEN 系统 SHALL 保持 `decision/instance_id/task_ids/exception_type/created` 响应字段和成功提示逻辑不变。
- `AC-REQ-006-02`: WHEN 接口返回申请成功 THEN 对应审批实例和首节点任务 SHALL 已经持久化；只有通知允许延后。
- `AC-REQ-006-03`: WHEN 审批通过 THEN 文件复制、向量复制和版本关联 SHALL 继续由原业务执行 outbox 处理，不使用通知 outbox。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | regression test | Shougang submit service/API 既有测试 |
| AC-REQ-006-02 | V-AC-REQ-006-02 | integration test | Gate 创建实例/任务后返回测试 |
| AC-REQ-006-03 | V-AC-REQ-006-03 | regression test | `test_approval_worker_tasks.py` 原业务 outbox 测试 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 选择目标文档后的提交校验数据库查询数量必须与目标空间候选总数无关。
- `NFR-002`: 通知 outbox 和审批任务写入必须兼容 MySQL 与 DM8，不使用方言专属 JSON 或 upsert。
- `NFR-003`: 新增通知 outbox 必须携带 `tenant_id`；Beat 跨租户扫描必须显式 bypass，单条消费必须恢复目标租户上下文。
- `NFR-004`: 不新增第三方依赖；Celery 任务继续路由到现有 `workflow_celery`。
- `NFR-005`: 日志不得记录审批原因、JWT、用户敏感属性或完整请求体。

## 澄清记录 Clarifications

### Session 2026-07-14
- Q: 第一阶段包含哪些操作？ -> A: 分段耗时日志、定向目标校验、移除提交 `view_file`、通知 outbox + Celery、审批任务批量写入。
- Q: 是否允许新增 outbox 表、迁移和 Beat 补偿任务？ -> A: 用户回复“开始”，接受规划中明确列出的影响。

## 假设 Assumptions
- 当前发布申请通知只在 `decision=pending` 且有首节点 `task_ids` 时有业务意义，与现有同步代码一致。
- 消息中心仍是提醒渠道，审批事实继续以 `approval_instance/approval_task` 为准，符合 `INV-1`。
- 通知采用 at-least-once 语义；唯一 outbox 和成功状态能覆盖常规重复投递，但 Worker 在消息提交后、状态提交前崩溃仍可能产生重复提醒。

## 风险 Risks
- 新表要求部署时先执行 Alembic migration；代码先上线会导致通知 outbox 写入失败。
- Celery Worker/Beat 不可用时通知会延迟，但审批申请仍已成立。
- 批量任务写入影响所有 `ApprovalGate` 调用场景，必须运行完整审批回归测试。
- 第一阶段不优化必须同步的 OpenFGA 空间权限和审批人解析，无法在无生产埋点证据时承诺固定响应时间。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
