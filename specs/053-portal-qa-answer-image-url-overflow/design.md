# 设计说明 Design: 门户专家回答图片地址溢出修复

## 阅读摘要
- 本文档说明：通过模型类型对齐和 `f083` 字段迁移修复 `images_url` 的 schema contract。
- 设计重点：复用项目 `LargeText`，让 `f083` 衔接当前分支 head，支持 MySQL/达梦幂等升级，并在不安全 downgrade 时失败关闭。
- 不在本设计中处理：图片对象生命周期和 URL 访问方式；这些由后续 spec 054 负责。

## 元信息 Metadata
- Feature ID: `053-portal-qa-answer-image-url-overflow`
- Status: `confirmed`
- Related requirements: `specs/053-portal-qa-answer-image-url-overflow/requirements.md`
- Created: `2026-08-11`
- Updated: `2026-08-11`

## 上下文 Context
- 现有架构 Existing architecture: 门户提交 `images_url` 字符串，FastAPI service 原样构造 `Answer`，Repository 在独立异步 session 中提交。
- 已检查文件 Relevant files inspected: `database/models/qa_expert.py`、`qa_expert/domain/{schemas,services,repositories}.py`、`core/cache/utils.py`、`core/storage/minio/minio_storage.py`、现有 Alembic migrations 与 `test/qa_expert/`。
- 现有测试或验证命令 Existing tests or validation commands: `uv run pytest test/qa_expert/...`、`uv run ruff check`、`uv run alembic heads`。
- 项目约束 Constraints from project guidance: schema change 必须使用 Alembic；双数据库必须使用 `dialect_helpers.LargeText`；bug fix 必须有回归证据。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals
- 当前模型和既有数据库 schema 均支持超过 255 字符的 `images_url`。
- upgrade 幂等，不改写业务数据；downgrade 不允许截断超长值。
- `f083` 直接衔接当前分支已跟踪的 `f082_department_short_name`，不为其他未合并分支创建占位 revision。

### 非目标 Non-Goals
- 不重新设计图片上传和持久化协议；后续设计见 spec 054。
- 不修改门户前端或回答业务流程。

## 边界承诺 Boundary Commitments
| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| `Answer.images_url` | ORM 列类型改为 `LargeText` | 改字段名、nullability、请求格式 | API contract 或字段语义变化 |
| Alembic graph | 新增可回退 `f083`，衔接当前分支 `f082` head | 引入其他分支 revision、执行当前数据库 DDL、手工 stamp | migration head 或支持方言变化 |
| `test/qa_expert` | 新增模型与 migration 回归测试 | 新建通用测试框架 | 现有测试无法证明方言契约 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01, AC-REQ-001-02 | `Answer.images_url = Column(LargeText)` | 类型断言与方言 DDL 编译 |
| REQ-002 | AC-REQ-002-01..03 | `f083_qa_answer_images_url_longtext` migration | mock 方言迁移路径与降级保护 |

## 架构设计 Architecture
- Pattern: ORM schema contract + forward Alembic schema migration。
- Rationale: 问题根因是模型隐式映射和实际数据库同时为 `VARCHAR(255)`，两者必须同时修复。
- Preserved existing patterns: 复用 `LargeText` 和既有 `f026_chatmessage_files_longtext` 方言迁移模式。
- Architecture change justification, if any: 无架构变更；仅修正 ORM schema contract，并沿当前分支的 Alembic 单链新增迁移。

## 文件结构计划 File Structure Plan
| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/database/models/qa_expert.py` | modify | 新建表时生成跨方言大文本列 | REQ-001 |
| `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f083_qa_answer_images_url_longtext.py` | create | 既有表字段扩容与安全回退 | REQ-002 |
| `src/backend/test/qa_expert/test_answer_images_url_migration.py` | create | 回归模型和迁移 contract | REQ-001, REQ-002 |
| `specs/053-portal-qa-answer-image-url-overflow/verification.md` | create | 记录实际验证证据 | REQ-001, REQ-002 |

## 组件与接口 Components and Interfaces

### ORM Model
- Responsibility: 为 `images_url` 声明明确的大文本持久化类型。
- Inputs: 现有 `str | None`。
- Outputs: MySQL `LONGTEXT`、达梦 `CLOB`、SQLite/其他 `TEXT`。
- Dependencies: `bisheng.core.database.dialect_helpers.LargeText`。
- Error behavior: 请求及业务错误行为不变。
- Requirements: `REQ-001`

### Alembic Migration
- Responsibility: 将已存在的 `VARCHAR(255)` 原地扩容。
- Inputs: 当前表、列和方言元数据。
- Outputs: 目标大文本类型；不支持方言或已达目标状态时不产生破坏性操作。
- Dependencies: `table_exists`、`column_exists`、`get_column_type`。
- Error behavior: downgrade 检测到超长数据时抛出 `RuntimeError`。
- Requirements: `REQ-002`

## 数据 / 状态变化 Data / State Changes
- Entities: `qa_answer.images_url`。
- Persistence changes: `VARCHAR(255)` 扩容为 MySQL `LONGTEXT` / 达梦 `CLOB`。
- Migration or rollback: upgrade 原地扩容；downgrade 仅在 `MAX(CHAR_LENGTH(images_url)) <= 255` 时恢复 `VARCHAR(255)`。
- Compatibility: API 和已有短值完全兼容；新应用应在 migration 完成后启用写流量。

## 测试策略 Testing Strategy
| Acceptance IDs | Risk / Level | Distinct Outcomes | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-02 | medium/V2 | 模型不再生成 `VARCHAR(255)`；双方言 DDL 正确 | model contract | EG-001 | MySQL/达梦编译与类型断言通过 |
| AC-REQ-002-01..03 | high/V3 | upgrade、幂等跳过、安全 downgrade、拒绝破坏性 downgrade | migration unit/contract | EG-002 | 所有独立迁移结果通过 |

## 设计决策 Decisions
### Decision: 使用 `LargeText` 而不是扩大固定 VARCHAR
- Context: 门户当前允许三张约 331 字符的预签名 URL，拼接值约 995 字符，未来 URL 参数仍可能变化。
- Options considered: `VARCHAR(1024)`、恢复 `JsonType`、使用 `LargeText`。
- Decision: 使用 `LargeText`，保持当前字符串 contract。
- Rationale: 无脆弱固定上限，不改变 API 数据形态，并满足项目双数据库规则。
- Consequences: 字段不再适合普通 B-tree 索引；该字段当前没有索引或过滤需求。

### Decision: `f083` 直接衔接当前分支 `f082`
- Context: `f085_merge_points_dept_short_name` 属于尚未合并的其他分支，不是当前分支迁移历史的一部分。
- Options considered: 使用跨分支编号 `f086`、等待其他分支合并、让当前分支从 `f082` 新增下一顺序 revision `f083`。
- Decision: 使用 revision `f083_qa_answer_images_url_longtext`，`down_revision=f082_department_short_name`。
- Rationale: revision 编号不要求连续；迁移依赖必须反映当前分支真实图谱，不能用占位文件提前模拟其他分支。
- Consequences: 若后续合并含 `f085` 的分支，应由合并提交根据实际两个 head 新增 merge revision。

## 风险 / 取舍 Risks / Trade-Offs
| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| `ALTER COLUMN` 获取元数据锁 | 部署时短暂阻塞写入 | 低峰执行、先观察锁等待；当前表数据量很小 | deployment |
| downgrade 遇到超长新值 | 无法直接回滚 schema | migration 主动拒绝并提示先清理/转存数据 | rollback |
| 预签名 URL 最终过期 | 图片长期不可访问 | 明确排除并作为后续独立设计问题 | follow-up |
| 后续合并其他分支产生多个 Alembic head | 部署迁移图可能需要合并 | 合并发生后基于真实 head 新增 merge revision，不提前占位 | branch integration |

## 设计质量门 Design Quality Gate
- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Verification uses the lowest sufficient layer and avoids duplicate commands across acceptance criteria.
- [x] Test cases map to distinct outcomes/risks instead of tasks, branches, roles, or raw input count.
- [x] One primary test layer is selected per behavior unless a boundary has independent risk.
- [x] Boundary Commitments include allowed and disallowed changes.
- [x] Every changed file has one clear responsibility and linked requirement.
- [x] Existing architecture is preserved or changes are justified.
- [x] Runtime prerequisites, migrations, and risky operations are explicit.
- [x] No speculative abstractions are included.
