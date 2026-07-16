# 需求说明 Requirements: Filelib Fixed-Rule File Sync

## 元信息 Metadata
- Feature ID: `047-filelib-file-sync`
- Status: `implemented`
- Mode: `spec-then-implement`
- Created: `2026-07-16`
- Updated: `2026-07-16`
- Source: `docs/api/filelib-file-sync-split.md` 与本任务澄清结论

## 范围 Scope

### 包含 Includes
- 新增 `/api/v2/filelib/file/sync/{03,04,05,06,07,09,10,11,12,14,15}` 11 个固定规则上传接口。
- 使用开发者 Token 识别调用人并校验目标知识空间根目录上传权限。
- 按责任人、主责单位、固定公共库或固定部门库解析目标知识空间和业务域。
- 从门户配置校验一级/二级文件分类和业务域，并校验业务域已绑定目标知识空间。
- 在提交 Celery 解析前同步生成文件编码、写入规范化元数据并返回排队状态。
- 将 `external_file_id` 与同步接口编号一起写入文件元数据并在响应中原样返回，不执行唯一性校验。

### 不包含 Excludes
- 不新增查询同步状态接口。
- 不改变普通知识空间上传接口的默认行为。
- 不修改全局异常处理器或现有开发者 Token 认证错误的响应约定。
- 不实现跨数据库与消息队列的分布式事务。
- 不提供基于 `external_file_id` 的幂等、去重或同步历史查询。

## 需求列表 Requirements

### REQ-001: 固定接口规则
系统 SHALL 为 11 个字面量路由应用文档定义的一级分类、二级分类、业务域来源和目标空间来源；二级分类中的 `/` SHALL 作为名称字符处理。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: 11 个 POST 路由均可独立注册并映射到唯一规则。
- `AC-REQ-001-02`: 分类名称必须在门户 `document_types` 中精确匹配一级和二级配置，否则返回 HTTP 404。
- `AC-REQ-001-03`: 固定业务域按名称精确匹配启用配置；动态业务域按责任人主部门关联关系匹配，多个匹配项取门户配置顺序第一项。
- `AC-REQ-001-04`: 业务域不存在或未绑定目标空间时返回 HTTP 404。

### REQ-002: 人员与部门归一化
系统 SHALL 以 ID 为权威解析责任人和主责单位；同时提供名称时必须匹配；缺省值使用调用人及其主部门。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: 未提供责任人 ID 时责任人为调用人；只提供其他责任人名称时因名称不匹配返回 HTTP 400。
- `AC-REQ-002-02`: `/03` 未提供 `department_id` 时使用调用人主部门；指定非调用人主部门时必须提供 ID。
- `AC-REQ-002-03`: ID 对应资源不存在返回 HTTP 404，ID 与名称不一致返回 HTTP 400。
- `AC-REQ-002-04`: 最终责任人、主责单位及其 ID 写入 `KnowledgeFile.user_metadata`。

### REQ-003: 目标空间解析
系统 SHALL 按接口规则解析目标知识空间并将文件写入根目录。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: `/03` 从主责单位开始沿部门祖先链查找最近绑定的部门知识空间。
- `AC-REQ-003-02`: `/04` 至 `/07` 从责任人主部门开始沿祖先链查找最近绑定的部门知识空间。
- `AC-REQ-003-03`: 固定公共库按当前租户、`public` 层级和精确名称查找。
- `AC-REQ-003-04`: 固定部门库按当前租户精确部门名及其直接绑定查找。
- `AC-REQ-003-05`: 目标空间不存在返回 HTTP 404；调用人无根目录上传权限返回 HTTP 403。

### REQ-004: 文件来源与文件编码
系统 SHALL 将调用方提供的 `external_file_id` 与当前同步接口编号共同记录为文件来源信息，并在解析任务入队前生成最终文件编码；系统 SHALL NOT 使用 `external_file_id` 执行幂等或唯一性校验。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: 相同或不同租户通过任意接口重复、并发提交相同 `external_file_id` 时，不得仅因该字段重复返回 HTTP 409。
- `AC-REQ-004-02`: `KnowledgeFile.user_metadata` 同时包含原样的 `external_file_id` 和当前 `filelib_sync_endpoint`，成功响应原样返回 `external_file_id`。
- `AC-REQ-004-03`: 编码格式为 `SGGF-{一级分类编码}-{业务域编码}-{YYYYMM}{8位序号}`。
- `AC-REQ-004-04`: 序号范围为目标知识空间内同月文件顺序；不同空间允许产生相同编码。
- `AC-REQ-004-05`: 二级分类编码独立写入 `file_subcategory_code`，不参与文件编码。

### REQ-005: 上传编排与响应
系统 SHALL 在文件记录、逻辑文档、权限、元数据和编码完成后提交现有知识解析任务，并直接绕过审批流程。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: 成功响应使用 HTTP 200 和统一响应体，包含 external_file_id、file_id、file_encoding、knowledge_id、knowledge_name、status=5。
- `AC-REQ-005-02`: 缺少 multipart `file` 或 `params` 返回实际 HTTP 422；JSON/字段/名称映射错误返回 HTTP 400。
- `AC-REQ-005-03`: 接口复用现有文件类型、重名、容量、安全词和权限校验，不降低安全边界。
- `AC-REQ-005-04`: 普通知识空间上传仍按原方式自动入队，不受新增延迟入队参数影响。

## 澄清记录 Clarifications
- 科室等同部门。
- `/03` 的目标由主责单位决定，业务域仍由责任人主部门决定。
- 动态目标空间允许沿部门树向上查找最近绑定；固定部门库只使用命名部门的直接绑定。
- `external_file_id` 不参与租户隔离或唯一性校验，仅与当前接口编号共同标识文件来源。
- 同一接口重复或并发提交相同 `external_file_id` 均允许进入正常上传流程；调用方自行处理重复文件。
- 外部同步绕过审批，但必须检查调用人上传权限。
- 错误提示中的“行份”统一修正为“首钢股份”。

## 验证矩阵 Verification Methods
| Acceptance | Method |
|---|---|
| AC-REQ-001-* | 规则表单元测试、配置解析单元测试、路由检查 |
| AC-REQ-002-* | Pydantic 校验与人员/部门解析单元测试 |
| AC-REQ-003-* | Repository/Service mock 测试与权限拒绝测试 |
| AC-REQ-004-* | 重复 ID 编排测试、元数据断言、响应断言、编码测试 |
| AC-REQ-005-* | FastAPI 接口测试、知识上传回归测试、ruff/arch-guard |
