# 需求说明 Requirements: F071 看板个人知识库统计

## 阅读摘要

- 本文档说明：知识空间内容统计纳入门户个人知识库，并排除固定“我的收藏”知识库。
- 当前状态：`approved`
- 用户已确认：所有指标纳入个人库，现有显示名称“个人库”保持不变。

## 元信息 Metadata

- Feature ID: `071-dashboard-personal-library-stats`
- Status: `approved`
- Mode: `bug-fix`
- Created: `2026-08-06`
- Updated: `2026-08-06`
- Source request: `统计门户个人知识库；排除我的收藏；所有指标纳入；沿用个人库名称`

## 范围 Scope

### 包含 Includes

- 文件总数、新增文件数、贡献人数、预览次数纳入 `space_level=personal`。
- 全量与增量投影排除 `Knowledge.is_favorite=True`。
- 收藏库预览不写入统计；清理收藏空间既有文件和预览记录。
- 知识库大类枚举显示“个人库”。

### 不包含 Excludes

- 不修改个人知识库业务权限、名称或创建流程。
- 不新增数据库或 Elasticsearch 字段。
- 不恢复服务端隐式数据范围过滤。

## 需求列表 Requirements

### REQ-001: 统计门户个人知识库

作为看板用户，我需要知识空间内容指标包含正常个人知识库，以便看到门户个人内容的真实规模和使用情况。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 个人知识库包含有效主版本文件 THEN 文件总数、新增文件数和贡献人数 SHALL 纳入这些文件。
- `AC-REQ-001-02`: WHEN 正常个人知识库文件被成功预览 THEN 预览次数 SHALL 纳入该事件。
- `AC-REQ-001-03`: WHEN 选择知识库大类 THEN `personal` SHALL 显示为“个人库”。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated test | 数据集种子和投影可见性测试 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | automated test | 个人库预览写入测试 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | automated test | 大类枚举标签测试 |

### REQ-002: 排除“我的收藏”

作为看板用户，我需要固定收藏库不进入知识空间内容统计，以免引用内容重复计数。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN 空间 `is_favorite=True` THEN 全量和增量文件投影 SHALL 不保留该空间记录。
- `AC-REQ-002-02`: WHEN 收藏库文件被预览 THEN 系统 SHALL 不新增或累计预览统计。
- `AC-REQ-002-03`: WHEN 清理收藏空间 THEN 系统 SHALL 同时删除文件快照和历史预览记录。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated test | 投影可见性与查询条件测试 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | automated test | 收藏库预览短路测试 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | automated test | 空间记录删除 DSL 测试 |

## 风险 Risks

- 统计口径扩大，历史看板文件数和贡献人数会上升。
- 收藏空间旧记录需要等待一次全量投影或对应空间增量任务完成清理。

## 需求质量门 Requirements Quality Gate

- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a verification method.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
