# 设计说明 Design: 首钢门户普通文件持久引用解析修复

## 根因 Root Cause

`KnowledgeDocumentDurableReferenceResolver.resolve` 当前把“存在版本记录”等同于“必须通过分发入口访问”。
普通上传已经创建逻辑文档和主版本 V1，但文件在首次分发前仍是普通入口，因此该判断错误地跳过了
`KnowledgeDocumentEntryResolver` 已有的普通主版本校验，随后因找不到
`manager/publish/share` 入口而失败。

门户后端捕获该解析异常并返回 `data=null`，所以首页推荐、检索结果和文件列表虽然传递了正确的
`space_id + file_id`，详情页仍显示“文档不存在”。

## 修复策略

持久引用解析采用两阶段策略：
1. 先把传入文件 ID 作为请求空间中的直接入口交给 `KnowledgeDocumentEntryResolver`。
2. 仅当直接入口因结构或状态不合法而解析失败时，才沿现有逻辑文档关系查找请求空间内唯一有效分发入口。

直接解析成功后立即执行查看权限校验；权限失败不能触发回退，避免用同一文档的其他入口绕过授权。
直接解析失败且文件有关联版本时，继续保留现有历史引用重定向能力。

## 数据完整性加固

直接解析普通版本文件时，逻辑文档必须：
- 存在且属于当前租户；
- 属于请求知识空间；
- 生命周期为有效状态；
- `primary_version_id` 指向该文件版本；
- 该版本标记为主版本。

任何不一致均失败关闭，不把异常版本关系当作普通兼容文件放行。

## 调用链影响

中心解析器当前被以下功能复用：
- 首钢门户详情、预览、文件分块和关联文件；
- 门户下载引用解析；
- 收藏持久目标解析；
- 旧分享链接验证；
- 问答显式文件范围。

修复放在中心解析器内，不修改这些调用方的接口、返回模型或异常映射。

## 回归测试设计

主回归用例构造“普通文件 + 逻辑文档 + 当前主版本 V1 + 无分发入口”，调用真实持久引用解析器并断言返回文件自身。
保留并运行现有历史物理版本映射、无唯一分发入口、跨租户和权限拒绝测试。
增加异常版本指向缺失逻辑文档的失败用例，防止直接入口优先策略扩大访问边界。

## 风险与回滚

- 风险：直接入口优先可能误放行损坏的版本关系；通过完整逻辑文档身份校验和失败回归测试控制。
- 兼容性：普通未分发文件由失败变为可访问；历史分发文件和权限失败行为保持不变。
- 数据：无迁移、无数据回写。
- 回滚：恢复解析器和对应测试即可，不涉及持久化结构回退。

## 文件范围
- `src/backend/bisheng/knowledge/domain/services/knowledge_document_entry_resolver.py`
- `src/backend/test/knowledge/test_knowledge_document_entry_resolver.py`
- `specs/048-shougang-portal-file-resolution/*`

## 可追踪性 Traceability
| Requirement | Components |
|---|---|
| REQ-001 | `KnowledgeDocumentDurableReferenceResolver.resolve`、普通主版本回归测试 |
| REQ-002 | 持久引用回退分支、既有历史版本测试 |
| REQ-003 | `KnowledgeDocumentEntryResolver._resolve_normal`、权限与异常关系测试 |
| REQ-004 | 所有持久解析器调用点静态审计 |
