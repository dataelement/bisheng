# 设计说明 Design: 门户智能问答与知识库工作台查看范围对齐

## 当前链路 Current Flow

登录用户打开智能问答选择器时，门户 BFF 调用 `list_visible_spaces(discovery_scope="public_and_department")`。
该范围会包含所有有效部门知识库。树节点、目录统计和文件名搜索随后调用 BiSheng 的首钢门户 QA 专用接口；
部门文件可被发现后再通过审批授权判定为可选或不可选。问答提交阶段也使用同一门户专用授权模型解析文件范围。

知识库工作台的标准链路不同：
- 知识库列表来自当前用户的 grouped/readable spaces；
- 根节点调用 `GET /knowledge/space/{space_id}/children`；
- 目录统计调用 `POST /knowledge/space/{space_id}/folder-stats`；
- 资源层通过 `view_space`、`view_folder` 和 `view_file` 失败关闭。

## 目标架构 Target Flow

### 门户 BFF

登录用户的 QA 路由改为工作台范围：
1. `/qa/tree/spaces` 使用默认 `legacy` 可见空间集合，即当前用户 grouped/readable spaces。
2. `/qa/tree/spaces/{id}/children` 通过 `KnowledgeService` 调用通用
   `/knowledge/space/{id}/children`，固定传入 `file_status=[SUCCESS]`、
   `enrich_files=false`、`folder_count_mode=shallow`，继续透传游标。
3. `/qa/tree/spaces/{id}/folder-stats` 调用通用
   `/knowledge/space/{id}/folder-stats`，固定传入 `file_status=[SUCCESS]`。
4. `/qa/files/search` 仅在当前工作台可读知识库集合中搜索，并使用 `legacy` 权限语义。
5. 问答代理对客户端 `knowledge_space_ids` 使用同一工作台可读集合做预检。

匿名请求继续使用原首钢门户公共 QA 专用接口，避免把系统客户端的权限模型误当作匿名工作台权限。

### 前端分类选择

`QAKnowledgeTreePicker` 的树懒加载逻辑不改。首页和智能应用页在调用通用分类浏览接口时，显式传入
选择器已获得的知识库 ID。这样只收紧智能问答分类选择，不改变通用门户浏览接口的默认发现范围。

### BiSheng 最终范围解析

门户问答最终解析器不再使用“全部有效部门库 + 部门文件审批授权”的发现模型，而复用工作台标准资源权限：
- 每个空间先执行 `_require_read_permission`；
- 显式文件解析持久引用后验证 `SUCCESS`、当前有效入口和 `view_file`；
- 目录验证空间归属和 `view_folder`，后代文件再经 `_filter_visible_child_items`；
- 整库模式加载 `SUCCESS` 当前文件，排除非主版本和回收站文件，再经 `_filter_visible_child_items`；
- 无权限或失效引用被过滤，最终为空时保持空上下文，不回退到全库。

## 搜索实现

QA 文件名搜索保留现有跨库分页响应。`discovery_scope="legacy"` 时：
- 空间集合由工作台可见空间服务确定；
- 候选文件固定 `SUCCESS`；
- 排除回收站和非主版本文件；
- 按空间调用标准 `_filter_visible_child_items`；
- 排序、映射和分页沿用现有 QA 搜索响应。

`public` 和 `public_and_department` 分支保留原行为，仅供匿名公共范围及其他既有调用兼容。

## 安全设计 Security

- 前端传入的 `space_ids` 仅作为缩小候选集，不能扩大服务端可见集合。
- BFF 与 BiSheng 分别校验空间范围，防止直接调用任一层绕过。
- BiSheng 对目录和文件执行资源级权限校验，不能仅依赖空间成员关系。
- `SUCCESS` 状态、当前主版本和回收站过滤在服务端执行。
- 权限异常失败关闭；不创建、不修改任何权限关系。

## 风险与回滚

- 行为变化：此前可发现但工作台不可读的部门知识库和“不可选文件”将完全不可见。
- 历史会话：保存了旧范围 ID 的重试请求可能被 BFF 拒绝，或在 BiSheng 解析为空上下文。
- 性能：跨库文件名搜索增加资源权限过滤；复用现有批量权限上下文并仅处理关键词候选控制开销。
- 数据：无迁移、无回写。
- 回滚：回退 BFF 路由/服务、前端范围参数和 BiSheng 解析器即可，数据库无需处理。

## 文件范围
- `shougang-group-knowledge-portal/backend/app/api/routes/knowledge.py`
- `shougang-group-knowledge-portal/backend/app/services/knowledge_service.py`
- `shougang-group-knowledge-portal/backend/app/services/chat_proxy_service.py`
- `shougang-group-knowledge-portal/frontend/src/pages/HomePage.tsx`
- `shougang-group-knowledge-portal/frontend/src/pages/QAPage.tsx`
- `bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
- 对应门户、知识和工作站测试

## 可追踪性 Traceability
| Requirement | Components |
|---|---|
| REQ-001 | QA spaces 路由、工作台 grouped spaces |
| REQ-002 | 通用 children/folder-stats、legacy QA search、分类范围接线 |
| REQ-003 | QA tree cursor 响应、前端现有 IntersectionObserver |
| REQ-004 | ChatProxyService、`resolve_shougang_portal_qa_scope_file_ids` |
| REQ-005 | 现有 API schema、通用 browse 默认行为 |
