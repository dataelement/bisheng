# 验证报告 Verification: 首钢门户普通文件持久引用解析修复

## 元信息 Metadata
- Feature ID: `048-shougang-portal-file-resolution`
- Status: `verified-with-known-test-infrastructure-gap`
- Verified: `2026-07-28`
- Verification level: `V2 模块/集成`

## 结论 Summary

普通上传形成的“普通文件 + 逻辑文档 + 当前主版本 V1 + 无分发入口”现在可以通过持久引用解析为文件自身。
历史物理版本仍只允许映射到请求空间内唯一有效分发入口；权限拒绝、租户隔离、空间隔离和异常文档关系继续失败关闭。

首页推荐、检索结果、文件列表、门户详情/预览/分块/关联文件、下载、收藏、旧分享链接和问答显式文件范围复用同一中心解析器，
不需要在各调用方复制修复逻辑。

## 红测证据 Regression Reproduction

修复前执行：

```bash
uv run pytest -q test/knowledge/test_knowledge_document_entry_resolver.py \
  -k 'durable_reference_resolves_ordinary_primary_without_distribution or ordinary_version_rejects_invalid_document_identity'
```

结果：`4 failed, 5 deselected`。

- 普通主版本失败原因为 `durable reference has no unique active entry in requested space`。
- 缺失、跨租户和跨空间逻辑文档的普通版本均未按预期抛出解析异常。

## 修复后证据 Verification Evidence

| Command | Result | Coverage |
|---|---|---|
| `uv run pytest -q test/knowledge/test_knowledge_document_entry_resolver.py` | `9 passed` | 普通主版本、历史映射、分发入口、权限、租户/空间/状态和异常关系 |
| `uv run pytest -q test/knowledge/test_portal_share_download_grant.py test/knowledge/test_knowledge_document_search_dedupe.py test/knowledge/test_portal_qa_tree_selection.py test/knowledge/test_knowledge_space_download_endpoint.py` | `52 passed` | 分享下载、门户深链、搜索去重、问答范围和下载端点 |
| `uv run ruff check bisheng/knowledge/domain/services/knowledge_document_entry_resolver.py test/knowledge/test_knowledge_document_entry_resolver.py` | passed | Python 静态检查 |
| `git diff --check` | passed | diff 空白与格式 |
| 生产模块直接导入并检查继承 | `KnowledgeUtils True` | 证明生产 `KnowledgeSpaceService` 仍具有分类归一化能力 |

## 验收映射 Acceptance Traceability

| Acceptance | Status | Evidence |
|---|---|---|
| AC-REQ-001-01/02 | passed | 普通主版本持久引用回归测试 |
| AC-REQ-001-03 | passed at service contract | 三个前端入口传递相同 `space_id + file_id`，门户详情复用已修复解析器 |
| AC-REQ-002-01/02/03 | passed | 既有历史物理 ID、唯一有效入口和失效入口测试 |
| AC-REQ-003-01 | passed | 持久引用权限拒绝测试 |
| AC-REQ-003-02/03/04 | passed | 异常文档关系参数化测试及既有历史/租户测试 |
| AC-REQ-004-01/02 | passed | 五类中心解析调用点静态审计和 52 项相关模块回归 |

## 同类问题审计 Similar-Issue Audit

### 已由中心修复覆盖
- 门户文件详情、预览、分块和关联文件：解析失败原先统一表现为“文档不存在”。
- 门户文件下载：同一问题原先映射为文件不存在。
- 旧分享链接：同一问题原先在验证时映射为资源不存在。
- 问答显式文件范围：同一问题原先会静默跳过所选文件。
- 收藏持久目标：同一问题原先会退回原始文件 ID，缺失规范文档 ID。

### 未发现重复实现
仓库内其他同时查询版本和分发入口的位置属于版本合并、分发生命周期、投影或删除编排，
不承担持久访问引用解析，不存在第二套与本次根因相同的访问算法。

### 后续改进项
1. `test/knowledge/test_add_file_creates_document_v1.py` 当前因测试预加载的
   `_KnowledgeUtilsPlaceholder` 缺少 `normalize_file_category_code` 而失败；生产类实际继承
   `KnowledgeUtils` 且该方法存在。这是既有测试基础设施漂移，不是本次运行时代码回归，本次未扩大范围修改。
2. 收藏、问答范围和门户详情等调用方会把解析异常转换为回退、跳过或空数据且不记录具体结构错误。
   这不会影响本次修复后的正常文件，但未来数据不一致仍可能再次只表现为“文档不存在”，建议后续增加带
   `tenant_id/space_id/file_id/reason` 的结构化告警。

## 未执行项 Limitations

- 未启动完整门户和 BiSheng 服务执行浏览器端到端点击；当前环境使用真实解析器测试及调用方模块回归验证服务契约。
- 未修改或运行全仓库无关测试。
