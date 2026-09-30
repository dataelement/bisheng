# 本地验证

Status: VERIFIED_LOCAL
日期：2026-09-10
Code State：本任务工作区差异（共用 builder、问答 PDF 缓存服务、两个入口接入、知识库 processor 接回）。未提交或部署。

## 证据

命令均在 `src/backend`，使用已有 `.venv/bin/python`。

| Evidence | 步骤 | Result | 范围 |
|---|---|---|---|
| E-001 | `-m pytest test/knowledge/pdf/test_pdf_artifact_worker.py test/qa_expert/test_watermarked_download.py test/qa_expert/test_watermarked_download_api.py -q` | PASS：修改前 27 项 | 原行为基线 |
| E-002 | `-m pytest test/qa_expert/test_pdf_preview_cache.py -q`（实现前） | FAIL：两次请求调用转换 2 次，期望 1 次 | 原重复转换复现 |
| E-003 | 同上（最终实现） | PASS：18 项，2.34 秒 | 重复/跨实例复用、源快照隔离、损坏恢复、失败重试、并发取消、原文件删除拒绝、无水印缓存、真实 DOC |
| E-004 | 下方相关回归命令 | 核心 80 项全部 PASS；扩展门户下载 43 项中 16 项 FAIL、27 项 PASS | 知识库共享生成和问答兼容性 |
| E-005 | 对扩展门户下载测试临时隔离水印配置读取 | 41 PASS，2 FAIL（旧测试缺失异常类导入） | 排除外部配置读取后，下载行为回归 |
| E-006 | `ruff check` 新增文件与知识库 processor；问答既有下载文件忽略原有 RUF002/RUF003 中文标点规则；`git diff --check` | PASS | 静态检查 |

E-004 实际命令：

```sh
.venv/bin/python -m pytest test/qa_expert/test_pdf_preview_cache.py test/qa_expert/test_watermarked_download.py test/qa_expert/test_watermarked_download_api.py test/knowledge/pdf/test_pdf_artifact_worker.py test/knowledge/pdf/test_pdf_artifact_on_demand_service.py test/knowledge/pdf/test_pdf_artifact_service.py test/knowledge/pdf/test_unified_pdf_converter.py test/knowledge/pdf/test_portal_pdf_download_service.py -q
```

总计 123 项：107 PASS、16 FAIL。全部失败集中在本次未修改的 `test_portal_pdf_download_service.py`：14 项未隔离 `get_watermark_horizontal_text()` 的配置数据库读取，另 2 项引用未导入的 `PdfWatermarkWorkerTimeout`。

E-005 使用 `/tmp/qa-pdf-download-isolation.py` 的临时 pytest fixture 返回默认水印配置；测试自己设置的定制水印仍覆盖该 fixture。未修改旧测试文件或生产配置。剩余失败：

- `test_timeout_and_generation_error_cleanup_and_release_resources`
- `test_daily_limit_skips_increment_on_failure`

二者均为 `NameError: PdfWatermarkWorkerTimeout is not defined`。

原始日志：`/tmp/qa-pdf-baseline.log`、`/tmp/qa-pdf-red.log`、`/tmp/qa-pdf-real-tests.log`、`/tmp/qa-pdf-regression.log`、`/tmp/qa-pdf-download-isolation.log`。

## 验收映射

| Acceptance | 状态 | Evidence |
|---|---|---|
| AC-1 | PASS | E-003：预览/下载入口复用，用户水印独立；新实例读取已有 PDF |
| AC-2 | PASS | E-003：内容、租户、无租户上下文、桶、路径、格式隔离；源删除不读缓存 |
| AC-3 | PASS | E-003：取消首个请求后其他并发只转换一次；无效 PDF、失去锁、存储拒绝不发布 |
| AC-4 | PASS（本次受影响生成路径） | E-001/E-004；扩展下载套件限制见 E-005 |

真实格式测试先用 LibreOffice 从 DOCX 生成 OLE 二进制 DOC，断言文件头 `d0cf11e0a1b11ae1`，再调用生产统一转换器并检查 PDF 正文；第二次创建服务实例时禁止转换器再次被调用，仍得到相同 PDF。对象存储和 Redis 使用 fake，未声称真实 MinIO/Redis 跨容器联调通过。

## 部署边界和已知限制

- 测试环境 Docker、MinIO、Redis 及问题 121 的实际附件：MANUAL_REQUIRED。尚未部署，后续需把本次后端和前一轮前端一起发布，确认首次生成、再次预览/下载及跨实例命中。
- 基础 PDF 持久化到 MinIO；历史源版本产物不再命中，但未加入自动清理，可能累积存储。原附件不存在时接口仍先读原附件而拒绝返回缓存。
- 每次先读取原文件以计算内容摘要，避免同路径覆盖后误用旧 PDF；缓存消除 Office 转换开销，不消除原文件读取和个性化水印开销。
- 规格文件位于仓库惯用 `features/` 目录，该目录已被原有 `.gitignore` 忽略；未改 ignore 或暂存任何文件。
