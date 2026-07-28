# 需求说明 Requirements: 首钢门户普通文件持久引用解析修复

## 元信息 Metadata
- Feature ID: `048-shougang-portal-file-resolution`
- Status: `implemented`
- Mode: `bugfix`
- Created: `2026-07-28`
- Updated: `2026-07-28`
- Source: 门户首页“知识推荐 · 最新精选”、检索结果和文件列表点击普通文件后显示“文档不存在”

## 问题与复现 Problem and Reproduction

普通上传会同时创建 `KnowledgeFile`、`KnowledgeDocument` 和主版本 V1，但普通文件仍保持
`entry_type=NULL`、`reference_document_id=NULL`。门户详情等入口使用
`KnowledgeDocumentDurableReferenceResolver` 解析该文件时，只要发现版本记录便改为查找
`manager/publish/share` 分发入口；未经过分发的普通主版本没有这些入口，因此解析失败并被调用方转换为
空数据，前端最终显示“文档不存在”。

稳定复现条件：
1. 在知识空间上传一个尚未分发的普通文件。
2. 文件已存在逻辑文档和主版本 V1。
3. 使用文件自身 ID 和所在知识空间 ID 调用首钢门户详情接口。
4. 当前实现返回 HTTP 200 且 `data=null`，前端显示“文档不存在”。

## 范围 Scope

### 包含 Includes
- 修复持久文件引用对“普通文件 + 当前主版本 V1”的解析。
- 保持历史物理版本向当前空间唯一有效 `manager/publish/share` 入口的映射。
- 保持租户、空间、生命周期和查看权限校验的失败关闭行为。
- 审计所有使用同一持久引用解析器的下载、收藏、分享链接、问答文件范围和门户详情入口。

### 不包含 Excludes
- 不修改门户前端展示和路由参数。
- 不修改数据库结构、历史数据或上传流程。
- 不放宽已删除、处理中、历史版本、跨租户、跨空间或无查看权限文件的访问。
- 不重构各调用方现有错误响应约定。

## 需求列表 Requirements

### REQ-001: 普通主版本直接解析
系统 SHALL 将请求空间内、当前租户下、处于有效状态的普通文件当前主版本解析为文件自身入口，
即使该文件已经具有 `KnowledgeDocument` 和版本 V1 但尚未产生分发入口。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: 普通文件为其逻辑文档当前主版本且没有分发入口时，持久引用解析成功。
- `AC-REQ-001-02`: 解析结果的入口文件 ID 和内容文件 ID 均为请求中的普通文件 ID。
- `AC-REQ-001-03`: 门户首页推荐、检索结果和文件列表使用相同的 `space_id + file_id` 打开详情时，不再因该数据形态返回空数据。

### REQ-002: 历史引用兼容
系统 SHALL 在文件自身不能作为当前有效入口解析时，继续按逻辑文档在请求空间内查找唯一有效分发入口。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: 历史物理版本 ID 仍映射到请求空间内唯一有效的发布或分享入口。
- `AC-REQ-002-02`: 请求空间内没有唯一有效分发入口时仍拒绝解析，不回退到历史文件内容。
- `AC-REQ-002-03`: 已删除、删除中或其他非有效分发入口不得参与回退候选。

### REQ-003: 安全与数据完整性
系统 SHALL 在直接解析和回退解析两条路径上保持租户、空间、逻辑文档、当前主版本和查看权限约束。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: `require_view_permission=True` 且入口无查看权限时解析失败。
- `AC-REQ-003-02`: 版本指向不存在、跨租户或跨空间逻辑文档时解析失败。
- `AC-REQ-003-03`: 非当前主版本不得通过普通文件直接解析。
- `AC-REQ-003-04`: 不存在文件或文件租户不匹配时解析失败。

### REQ-004: 同类调用一致性
所有使用 `KnowledgeDocumentDurableReferenceResolver` 的调用方 SHALL 复用修复后的中心契约，不为各入口复制单独兼容逻辑。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: 门户详情/预览/分块/关联文件、下载、收藏、分享链接验证和问答文件范围继续调用同一解析器。
- `AC-REQ-004-02`: 本次修复不改变上述调用方的 API 路径、请求参数和错误响应结构。

## 验证矩阵 Verification Methods
| Acceptance | Method |
|---|---|
| AC-REQ-001-* | 持久引用解析器普通主版本回归测试 |
| AC-REQ-002-* | 既有历史版本映射、无唯一入口和失效入口测试 |
| AC-REQ-003-* | 权限拒绝、租户隔离、历史版本与异常文档关系测试 |
| AC-REQ-004-* | 调用点静态审计与知识模块定向测试 |
