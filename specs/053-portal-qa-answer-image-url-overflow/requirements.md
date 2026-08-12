# 需求说明 Requirements: 门户专家回答图片地址溢出修复

## 阅读摘要
- 本文档说明：修复门户专家问答发布带图回答时因 `qa_answer.images_url` 长度不足导致的 HTTP 500。
- 当前状态：`confirmed`
- 需要重点确认：数据库迁移只随代码交付，不在本次开发环境中直接执行。

## 元信息 Metadata
- Feature ID: `053-portal-qa-answer-image-url-overflow`
- Status: `confirmed`
- Mode: `bug-fix`
- Created: `2026-08-11`
- Updated: `2026-08-11`
- Source request: `分析并修复门户网站专家问答发布回答时报错`

## 需求入口摘要 Intake Summary
- 问题 Problem: 图片上传返回的 MinIO 预签名 URL 约 331 字符，`qa_answer.images_url` 实际为 `VARCHAR(255)`，提交回答时 MySQL 抛出 `DataError(1406)`。
- 当前状态 Current state: 带一张图片的回答无法创建，事务回滚并返回 HTTP 500。
- 目标结果 Target outcome: `images_url` 能持久化单张及门户允许的三张图片 URL，既有回答数据保持不变。
- 影响对象 Affected users/systems: 门户专家问答详情页、`POST /api/v1/qa_experts/answers`、`qa_answer` 表。
- 请求停止点 Requested stopping point: `verification`

## 范围 Scope

### 包含 Includes
- 将 `Answer.images_url` 改为 MySQL `LONGTEXT`、达梦 `CLOB`、其他方言 `TEXT` 的跨方言大文本类型。
- 新增 Alembic schema migration，将既有 `qa_answer.images_url` 从 `VARCHAR(255)` 扩容且保留现有数据。
- 新增 revision ID 为 `f083_qa_answer_images_url_longtext` 的 Alembic migration，并直接衔接当前分支 head `f082_department_short_name`。
- 增加模型类型和迁移 upgrade/downgrade 防护的回归测试。

### 不包含 Excludes
- 不在本次开发任务中执行当前数据库的 `alembic upgrade`。
- 不改变门户请求体、分号分隔格式、图片数量限制或 API 响应结构。
- 本 spec 不处理临时桶与预签名 URL 的长期持久化设计；该范围后续由已确认的 spec 054 实现。
- 本 spec 不定义其他字段扩容；spec 054 实施时确认两个 `attachments` 多值字段存在同类长度风险，因此复用尚未部署的 `f083` 一次性扩容。

## 需求列表 Requirements

### REQ-001: 带图回答地址可持久化
作为门户认证专家，我需要发布包含图片的回答，以便回答不会因图片地址超过 255 字符而失败。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN `images_url` 长度超过 255 字符且符合现有请求契约 THEN `qa_answer.images_url` SHALL 使用不受 255 字符限制的大文本持久化类型。
- `AC-REQ-001-02`: WHEN 新建数据库表 THEN MySQL SHALL 生成 `LONGTEXT`，达梦 SHALL 生成 `CLOB`。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated test | `test/qa_expert/test_answer_images_url_migration.py` 模型类型断言 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | automated dialect compilation | MySQL/达梦 DDL 编译断言 |

### REQ-002: 既有数据库可安全迁移
作为部署运维人员，我需要可审计、可重复、可回退的 schema migration，以便升级不依赖手工 SQL 且不损坏既有回答。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN upgrade 运行于包含 `qa_answer.images_url` 的 MySQL 或达梦数据库 THEN migration SHALL 将字段扩容并保持 nullable 与既有数据。
- `AC-REQ-002-02`: WHEN upgrade 重复运行或字段已是目标大文本类型 THEN migration SHALL 不重复修改。
- `AC-REQ-002-03`: IF downgrade 前存在长度超过 255 的值 THEN migration SHALL 明确拒绝降级，避免静默截断；否则恢复为 `VARCHAR(255)`。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated migration test | upgrade 的 MySQL/达梦 `alter_column` 参数 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | automated migration test | 缺表、缺列、已迁移场景无操作 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | automated migration test | downgrade 长度保护与合法回退 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 不新增第三方依赖，遵循项目 MySQL/达梦双数据库约束。
- `NFR-002`: migration 不包含数据回填，不修改既有行内容。

## 澄清记录 Clarifications

### Session 2026-08-11
- Q: 是否执行修复？ -> A: 用户明确要求“修复一下”。
- Q: 是否直接迁移当前数据库？ -> A: 本次只交付 migration 文件并验证，不直接执行 DDL。
- Q: 新迁移应使用哪个 revision？ -> A: 用户确认 `f085_merge_points_dept_short_name` 属于尚未合并的其他分支，不需要占位；当前分支从 `f082_department_short_name` 新增 `f083_qa_answer_images_url_longtext`。
- Q: 如何处理本机已被其他分支标记为 `f085` 的数据库？ -> A: 用户计划在代码外手动恢复到 `f082`；本任务不执行数据库 `downgrade` 或 `stamp`，恢复前需确保其他分支 DDL 已正确回滚或该数据库可重建。

## 假设 Assumptions
- 当前 API 继续以字符串形式保存用分号连接的图片 URL；本修复保持兼容。
- `qa_answer` 当前数据量很小，但 migration 仍按生产 schema 变更记录锁风险和回退条件。

## 风险 Risks
- MySQL/达梦执行字段类型变更时会持有表级元数据锁；应在低峰期部署并监控锁等待。
- 应用写入超长值后，直接 downgrade 到 `VARCHAR(255)` 不再安全，因此 downgrade 必须先检查最大长度并拒绝破坏性回退。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] Acceptance criteria sharing one behavior reuse an evidence target instead of duplicating commands.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
