# 需求 Requirements：专家表岗位字段迁移补齐

## 阅读摘要

- 当前状态：`approved`，已于 2026-07-21 确认并完成实现。
- 本修复只补齐 `qa_expert` 表缺失的 `position`、`job_family`、`job_category` 三个字段。
- 不调整专家初始化脚本的现有业务逻辑，不回填历史数据，不直接操作部署环境数据库。

## 元信息 Metadata

- Feature ID: `065-qa-expert-schema-sync`
- Status: `approved`
- Mode: `bugfix`
- Created: `2026-07-21`
- Updated: `2026-07-21`
- Version: `v2.6.0`
- Source request: 修复运行 `shougang_execute_qa_expert.py` 时出现的 MySQL 1054 `Unknown column 'qa_expert.position'`。

## 问题描述 Problem

`Expert` ORM 模型已经声明 `position`、`job_family`、`job_category`，但提交这些字段的变更没有配套 Alembic 迁移。`ExpertRepository.get_by_user_id()` 使用 `select(Expert)`，SQLAlchemy 会选择模型全部字段，因此数据库在读取第一条专家记录前即因缺少 `position` 中断。

同一模型变更同时增加了三个岗位字段；只修复日志首先报告的 `position` 会使查询继续在后续缺失字段上失败，必须一次补齐三列。

## 当前行为 Current Behavior

- `qa_expert` 表缺少至少 `position` 字段。
- `select(Expert)` 生成包含三个岗位字段的查询。
- 专家初始化脚本在幂等查询阶段失败，本次执行没有进入持久化阶段。
- 现有 `f049_add_qa_expert_major` 迁移只增加 `major`。

## 期望行为 Expected Behavior

- 执行最新 Alembic 迁移后，`qa_expert` 表包含三个可空字符串字段。
- 已存在字段的环境可以安全、幂等地执行迁移。
- 空库或没有 `qa_expert` 表的环境不因迁移失败。
- 迁移不修改现有专家数据，也不改变脚本业务逻辑。

## 范围 Scope

### 包含 Includes

- 新增 Alembic 迁移并接到当前唯一迁移头。
- 为 MySQL 与 DM8 使用 SQLAlchemy 通用列类型和项目方言检查函数。
- 增加迁移单元测试和专家初始化脚本回归测试验证。
- 记录部署迁移和脚本重跑步骤。

### 不包含 Excludes

- 不在本次任务中执行生产或日志对应环境的数据库迁移。
- 不回填三个新字段的历史数据。
- 不调整 `Expert` 模型其他格式或重构 QA Repository。
- 不修改专家初始化脚本已经确认的硬编码数据和处理逻辑。

## 需求列表 Requirements

### REQ-001：数据库结构与 ORM 一致

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`：WHEN 迁移在包含 `qa_expert` 表且缺少岗位字段的数据库执行 THEN 系统 SHALL 增加 `position`、`job_family`、`job_category`。
- `AC-REQ-001-02`：WHEN 新字段创建 THEN 每个字段 SHALL 使用长度为 255 的可空字符串类型，且不设置默认值、不执行数据回填。
- `AC-REQ-001-03`：WHEN 迁移完成后执行 `select(Expert)` 或专家初始化脚本幂等查询 THEN 查询 SHALL 不再因三个岗位字段缺失而失败。

### REQ-002：迁移兼容性和幂等性

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`：WHEN `qa_expert` 表不存在 THEN upgrade 和 downgrade SHALL 安全返回。
- `AC-REQ-002-02`：WHEN 任一目标字段已经存在 THEN upgrade SHALL 跳过该字段并继续检查其他字段。
- `AC-REQ-002-03`：WHEN downgrade 执行 THEN 只删除当前存在的三个目标字段，并按 `job_category`、`job_family`、`position` 的逆序处理。
- `AC-REQ-002-04`：迁移 SHALL 使用 `table_exists`、`column_exists` 和 SQLAlchemy 通用类型，不使用 MySQL 专属 SQL，保持 MySQL 与 DM8 兼容。

### REQ-003：回归保护

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`：自动化测试 SHALL 验证迁移 revision、down revision、字段定义及正常 upgrade 行为。
- `AC-REQ-003-02`：自动化测试 SHALL 覆盖表不存在、部分字段已存在以及 downgrade 行为。
- `AC-REQ-003-03`：现有专家初始化脚本测试 SHALL 继续全部通过。
- `AC-REQ-003-04`：Alembic SHALL 保持唯一迁移头。

## 风险与回滚 Risks and Rollback

- 升级只增加可空字段，不覆盖现有数据。
- downgrade 会永久删除三个字段及其中数据；字段投入使用后，生产回滚应采用前向修复，不应直接 downgrade。
- macOS 本地环境不能进行真实 DM8 驱动验证；DM8 实库验证留给 Linux CI 或部署环境。
