# 验证记录：文件相似度两套规则

- Feature ID: `076-file-similarity-metadata-modes`
- Status: `implemented-local-verified`
- Created: `2026-10-15`
- Overall status: `MANUAL_VERIFY_REQUIRED`
- Code state: `feat/2.5.0-sg`本地未提交变更，业务代码与新增测试已落盘；T001至T004本地完成。

## 实际证据

| Evidence | 实际执行检查 | 结果与边界 |
|---|---|---|
| E-001 | 实现前执行新增业务候选用例，日志`/tmp/similarity-modes-red.log` | 4项预期失败：缓存推荐、发布推荐、通用目标库推荐不识别两套阈值，发布未做正文复核。该日志的另外3项校验用例后来加强为明确断言落库前不读取数据库，不使用原3项通过充当校验红灯证据 |
| E-002 | 下方最终定向回归命令，日志`/tmp/similarity-modes-final.log` | 85 passed、2 deselected、290 warnings，pytest退出码0，3.98秒；不是全量测试通过 |
| E-003 | 内存中加载Git HEAD原版KnowledgeVersionService，只运行两项争议旧断言；日志`/tmp/similarity-modes-baseline2.log` | 修改前同样2 failed，确认是原有预期与实现不符；未替换磁盘业务文件 |
| E-004 | `ruff check`及`ruff format --check`针对新增策略与新增测试 | 通过。既有6个修改文件与HEAD逐条诊断计数比较，无新增诊断；见`/tmp/similarity-modes-lint-baseline.json`，不声称既有文件全量lint清零 |
| E-005 | `py_compile`检查5个业务/脚本Python文件，`git diff --check`及改动业务文件架构守卫 | 语法和diff检查通过。架构守卫只有settings.py既有RULE-7告警，命中未改动的原有密钥辅助代码；没有新增密钥或新增架构违规 |
| E-006 | 实际SimilarDocumentDialog＋后端SQLite计算快照＋本地Vite API替身，在127.0.0.1:4130验收 | 一致组较宽松只展示file200；不一致组较宽松展示201/202/203/204/206；跨分类、缺失分类候选、原百分比显示和不关联后空态均可用。测试快照显式limit=10覆盖全部组别，未改变生产默认库内3条/发布10条 |
| E-PLAN-001 | 规划文件链接、验收映射与未完成状态检查 | 规划阶段通过；实现后更新完成状态并重新做文档引用检查 |

## 最终回归命令

工作目录为仓库的`src/backend`，复用现有`.venv`，没有安装或调整依赖。

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_file_similarity_metadata_modes.py \
  test/knowledge/test_version_management_config.py \
  test/knowledge/test_knowledge_version_service_similar_scan.py \
  test/knowledge/test_backfill_file_similarity_candidates_script.py \
  test/knowledge/test_async_similarity_tokens.py \
  test/knowledge/test_chunking_config.py \
  test/knowledge/test_simhash_utils.py \
  test/knowledge/test_simhash_transformer.py \
  test/knowledge/test_knowledge_file_similar_queries.py \
  test/knowledge/test_knowledge_version_endpoint_similar.py \
  test/knowledge/test_knowledge_version_service_similar_dismiss.py \
  test/approval/test_shougang_approval_service.py::test_file_publish_query_requires_publish_permissions \
  test/approval/test_shougang_approval_service.py::test_file_publish_similar_candidates_filters_by_file_view_permission \
  -k 'not (skip_cached_multi_version_candidates or list_pending_clears_status_when_only_cached_candidates_are_multi_version)' \
  -q --disable-warnings --tb=short
```

新增测试证明配置保存失败发生在数据库读取/写入之前，合法配置原样保存并清除原Redis配置缓存。实际跨库复核测试走原`_fetch_chunk_texts`，校验租户共享索引、content_file_id和各自knowledge_ids过滤；被拒绝的文件不进入正文读取。Redis连接失败时使用真实本地分词，缺失ES正文时保持原降级。

## 验收覆盖

| Acceptance | Verification | Evidence | 本地状态 |
|---|---|---|---|
| AC-01 | V-001/V-003 三字段分组、不同/缺失、大小写/空白 | E-002 | PASS |
| AC-02 | V-001 旧参数逐字段回退、显式false/0、缺组 | E-002 | PASS |
| AC-03 | V-002 非法配置保存前拒绝、合法配置保存 | E-002 | PASS |
| AC-04 | V-003 三个入口分组阈值和独立复核开关/阈值 | E-001、E-002 | PASS |
| AC-05 | V-003 实际ES查询组装、源/目标库、权限回调 | E-002 | PASS |
| AC-06 | V-003 跨分类实际合并为V2主版本、公司拒绝、原force用例 | E-002 | PASS |
| AC-07 | V-003 二级分类变化触发重算、状态2不重开、缓存读取与数量限制原回归 | E-002 | PASS |
| AC-08 | V-004 分类缺失补算、dry-run不写、显式apply替身 | E-002 | PASS |
| AC-09 | V-003 公司/租户拒绝、发布权限拒绝、ES缺失和Redis故障 | E-002 | PASS |
| 页面可用 | V-005 实际组件与后端结果快照 | E-006 | PASS（本地模拟） |

## 排除的基线问题

1. `test_version_recommendations_skip_cached_multi_version_candidates`
2. `test_list_pending_clears_status_when_only_cached_candidates_are_multi_version`

两项都要求隐藏多版本目标，但HEAD原代码允许此类目标。E-003证实这不是本次引入的回归。本次不顺带修改多版本候选业务，因此保留断言并显式排除；不能将最终结果称为原测试集全部通过。

## 界面验收与清理

- 本地实际组件检查两组候选和原加权百分比；点击不关联后显示“暂无待处理的相似文档”。
- 默认窄视口只能确认交互状态，另在1280×800桌面断点检查弹窗；未修改前端响应式样式。
- 截图：`/tmp/similarity-metadata-modes.png`。页面使用模拟API，不能作为真实ES/生产接口端到端证据。
- 临时8个预览文件已清理、开发服务已停止、临时标签页已关闭、视口已恢复。

## 未验证与上线边界

- 未提交、推送、部署、修改线上系统配置，未执行真实历史补算。
- 未运行无关全量测试和前端构建；没有前端业务源码变更。
- MySQL/DM8、真实ES/Redis及生产规模性能需要部署环境验收，本地SQLite和替身不能代替。
- 发布推荐新增正文复核计算量；ES每次最多10000分段的原上限和正文缺失降级仍在。
- 修改分组参数不会自动重算历史缓存；如需历史结果同步，新代码上线后应先预览补算范围，再另行授权apply。
- 代码回退不自动还原已保存的候选；没有新增Schema需要回退。
