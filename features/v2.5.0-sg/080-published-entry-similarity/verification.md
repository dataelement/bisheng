# 验证

- Status: `LOCAL_VERIFIED / MANUAL_REQUIRED`
- 日期：2026-10-21。已完成本地实现及相关回归，未提交、推送、部署或操作线上数据。

## 复现与覆盖

E-001：修改前使用项目现有解释器，在内存 SQLite 中创建管理文件 100（库 1）、文档 10/版本 20，以及有效就绪发布入口 101（库 2）。调用真实 `find_main_version_files_in_space(knowledge_id=2)` 返回 `[]`，复现发布入口被主版本关联查询漏选。新增回归在修复前出现候选缺失、就绪后无刷新任务四项失败。

E-002：`test/knowledge/test_published_entry_similarity.py` 使用真实仓储、版本服务和后台任务持久状态，覆盖跨来源库第二次发布、目标库缓存/徽标、撤回、当前主版本切换、计算中候选变化、目标入口权限拒绝且不清理全局待处理状态、无效/跨租户入口排除，以及原有合法发布版本目标。发布入口自身不带 SimHash，断言使用当前正文身份。

E-003：同一后端测试文件覆盖管理/发布入口就绪与刷新意图同事务、回滚、重复就绪结果不重复登记、任务暂时失败后重试成功、重复投递和新代次不重开已处理状态。正文查询使用受控 ES 替身，断言实际 content_file_id 与目标库 membership 过滤，不等同于真实 ES 验收。

E-004：实际 `FilePublishDialog`、`SimilarDocumentDialog` 组件测试验证只读相似提示、禁止非法版本关联，以及预览使用目标库入口而非来源物理文件。未执行部署后的浏览器端到端验收。

| Acceptance | 本地状态 | 证据 |
|---|---|---|
| AC-01 | PASS | E-002：第二个文件发布前命中已发布入口，权限检查使用入口 ID |
| AC-02 | PASS | E-002/E-003：刷新缓存及徽标，持久任务、重试及幂等 |
| AC-03 | PASS | E-002/E-004：主版本变更、正文过滤、目标入口预览 |
| AC-04 | PASS | E-002/E-003：同文档、无效入口、权限、租户及既有配置回归 |
| AC-05 | PASS | E-002/E-004：只读候选不能关联，原合法物理目标仍可选 |

## 实际执行

后端工作目录：`src/backend`，使用已有 `.venv`，未安装依赖。最新业务代码执行以下相关回归，结果 **128 passed, 2 deselected，7.49 秒**：

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_published_entry_similarity.py \
  test/knowledge/test_file_similarity_metadata_modes.py \
  test/knowledge/test_knowledge_file_similar_queries.py \
  test/knowledge/test_knowledge_version_service_similar_scan.py \
  test/knowledge/test_knowledge_document_projection_service.py \
  test/knowledge/test_shared_space_projection.py \
  test/knowledge/test_shared_space_projection_batch.py \
  test/knowledge/test_share_revoke_projection.py \
  test/knowledge/test_background_jobs.py \
  test/knowledge/test_knowledge_version_service_similar_dismiss.py \
  test/knowledge/test_knowledge_version_endpoint_similar.py \
  test/approval/test_shougang_approval_service.py::test_file_publish_similar_candidates_filters_by_file_view_permission \
  -k 'not (test_version_recommendations_skip_cached_multi_version_candidates or test_list_pending_clears_status_when_only_cached_candidates_are_multi_version)' \
  -q --disable-warnings --tb=short
```

排除的两项分别位于 `test_knowledge_version_service_similar_scan.py` 和 `test_knowledge_version_service_similar_dismiss.py`，断言多版本缓存候选必须隐藏。已通过在独立进程加载修改前 HEAD 的版本服务源码复测，**两项同样失败**；没有替换工作区文件，未将基线失败计作通过。日志：`/tmp/published-similarity-baseline.log`。最终回归日志：`/tmp/published-similarity-final.log`。

前端工作目录：`src/frontend/client`：

```bash
node_modules/.bin/jest --runInBand --watch=false --coverage=false \
  src/pages/knowledge/SpaceDetail/FilePublishDialog.test.tsx \
  src/pages/knowledge/SpaceDetail/SimilarDocumentDialog.test.tsx
npm run build
```

结果：**2 suites、26 tests passed**；生产构建成功，24.76 秒。日志分别为 `/tmp/published-similarity-ui.log`、`/tmp/published-similarity-build.log`。后续仅修改后端的非正数 limit 兼容守卫及规格文档，前端证据仍适用。

静态检查：11 个变更 Python 文件全部通过 `py_compile`；新增文件 Ruff 无问题，既有文件按诊断代码及信息与 HEAD 比较无新增 Ruff 问题；架构守卫无输出；`git diff --check` 通过。未声称整个项目 lint 或全量测试通过。

## 上线前待验证与回退

- `MANUAL_REQUIRED`：MySQL、DM8、真实 ES/OpenFGA 及 Celery Beat/默认 worker 组合，以及部署后双账号浏览器端到端验收。本地 SQLite、替身存储和权限解析器验证不能替代这些证据。
- 部署后用隔离测试文件 A/B 验证：A 先发布，B 选择同库有相似提示；B 发布就绪后目标库有待处理项，预览地址使用目标入口；撤回、更新主版本和无权限账号不能读到旧结果；后台失败重试最终完成。
- 不重算历史发布文件，不重开已处理提醒。后台沿用最多八次失败预算，耗尽进入失败终态，仍需现有恢复流程；不保证无限自动重试。
- 没有表结构迁移。候选和快照分步提交期间，读端隐藏不匹配结果，任务重试可恢复；应检查失败任务而非认定空列表就是已处理完成。
- 前端、后端和默认 worker 需兼容更新。回退前暂停新增 `refresh_similarity` 派发或保留兼容处理器；持久记录保留供恢复，不批量删除缓存或数据。
