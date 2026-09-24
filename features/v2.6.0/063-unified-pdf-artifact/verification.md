# 验证记录 Verification: 知识文件统一 PDF 产物

## 阅读摘要

- 本文档记录 F063 实际执行过的验证命令、验收覆盖和未验证项。
- T017 已通过真实 Dash → Bash 运行时回归，`sh entrypoint.sh` 不再解析 Bash 专属语法。
- 功能代码、状态机、触发链路、删除所有权和现有下载兼容测试通过；完整套件仍有一条当前 `HEAD` 已存在的 Worker 聚合行为与部署契约断言不一致。
- 14 种范围内扩展名已用本机真实 LibreOffice、Playwright Chromium、Pillow 和 PyMuPDF 完成转换/校验。
- Office/Text/Image 代表性复杂语料视觉对比、真实 MySQL/DM8、Celery/MinIO 联调及独立 Worker 的资源/网络运行时仍需预发布环境人工验收，因此不声称全量生产验证完成。

## 元信息 Metadata

- Feature ID: `063-unified-pdf-artifact`
- Status: `not_verified`
- Related requirements: `features/v2.6.0/063-unified-pdf-artifact/requirements.md`
- Related tasks: `features/v2.6.0/063-unified-pdf-artifact/tasks.md`
- Created: `2026-07-20`
- Updated: `2026-07-21`

## 验证摘要 Verification Summary

- Overall status: `NOT_VERIFIED`
- Status rule: Overall status uses `VERIFIED | NOT_VERIFIED | MANUAL_VERIFY_REQUIRED`; acceptance status uses `PASS | FAIL | MANUAL_REQUIRED | NOT_RUN`.
- Completed tasks: `T001-T017`
- Remaining tasks: `本次启动 Bugfix 无剩余代码任务；T014 Worker 聚合拓扑契约漂移需另行确认`
- Blocked tasks: `无`

## 已执行命令 Commands Run

| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| `uv run pytest test/knowledge/test_pdf_artifact_model.py test/knowledge/test_pdf_artifact_repository.py test/knowledge/pdf -q` | F063 模型、Repository、转换、Service、Worker、接线、删除和部署契约 | 1 | FAIL | `1 failed, 65 passed, 39 warnings`；失败为当前 `HEAD` 同时包含 `run_background start_pdf` 与“bundle 不含 start_pdf”断言 |
| `uv run pytest test/knowledge/pdf/test_pdf_artifact_deployment_contracts.py::test_backend_entrypoint_switches_from_posix_shell_to_bash -q` | T017 Shell 运行时回归 | 0 | PASS | `1 passed` |
| `uv run pytest test/test_knowledge_space_service.py -k "batch_download or get_file_download" -q` | 现有单文件/批量下载兼容 | 0 | PASS | `9 passed, 193 deselected` |
| `uv run pytest test/test_file_worker_copy_normal.py test/knowledge/test_knowledge_retry_file_category.py test/knowledge/test_web_link_import_service.py test/knowledge/test_space_migrate_async_bridge.py test/test_space_migrate_worker.py -q` | 复制、覆盖重试、Web 导入和空间迁移回归 | 0 | PASS | `22 passed` |
| `uv run pytest` 三个空间删除节点与四个历史版本删除节点 | 单文件/目录/批量/版本删除快照回归 | 0 | PASS | `7 passed` |
| `uv run ruff check <F063 new modules and tests>` | 新建功能文件静态检查 | 0 | PASS | `All checks passed!` |
| `uv run ruff format --check <F063 new modules and tests>` | 新建功能文件格式 | 0 | PASS | `17 files already formatted` |
| 基于 `git diff --unified=0` 过滤 Ruff JSON 诊断 | 仅检查旧服务文件的 F063 新增行 | 0 | PASS | `changed_line_diagnostics=0` |
| `uv run python -m compileall -q <F063 touched Python modules>` | 所有受影响 Python 模块语法/导入编译 | 0 | PASS | 无错误输出 |
| `uv run alembic heads` | 迁移链单一 head | 0 | PASS | `f063_knowledge_file_pdf_artifact (head)` |
| disposable SQLite `MigrationContext + Operations` 调用 F063 `upgrade/downgrade` | 实际创建表/索引并回滚 | 0 | PASS | `columns=18`; 两个索引存在；`upgrade_downgrade=pass` |
| 临时样本调用 `PdfConverterRegistry` 转换 14 种扩展名 | 真实转换运行时 | 0 | PASS | `pdf/doc/docx/ppt/pptx/xls/xlsx/csv/txt/md/html/png/jpg/jpeg` 均为 1 页有效 PDF |
| 本地计数 HTTP Server + 恶意 HTML 真实 Playwright 转换 | 证明外部网络请求未发出 | 0 | PASS | `blocked_requests=0 pages=1` |
| `bash -n src/backend/entrypoint.sh`; `bash -n docker/bisheng/entrypoint.sh` | 两份 PDF Worker 入口语法 | 0 | PASS | 无错误输出 |
| `/bin/dash src/backend/entrypoint.sh syntax-smoke`（设置 `APP_HOME`） | 模拟镜像使用 POSIX shell 调用 Bash entrypoint | 1（预期无效模式） | PASS | 进入 Bash 模式分派并输出 `Invalid start mode: syntax-smoke`，无 `pipefail`/数组语法错误 |
| `git diff --exit-code HEAD -- docker/docker-compose.yml` | 确认 F063 不修改项目 Docker Compose | 0 | PASS | 无差异输出 |
| `git diff --exit-code HEAD -- src/backend/base.Dockerfile` | 确认 F063 复用现有镜像且不修改基础 Dockerfile | 0 | PASS | 无差异输出 |
| Python 导入 `bisheng.worker` 并检查 task registry/route | Celery 任务注册和显式队列 | 0 | PASS | `registered=True`; `route={'queue': 'knowledge_pdf_celery'}` |
| Git 变更路径和新增行架构 guard | 无前端、Router、API、Beat、`pyproject.toml` 或 `uv.lock` 功能变更 | 0 | PASS | `forbidden_dependency_frontend_router_changes=0`; `new_api_router_beat_additions=0` |
| `git diff --check` | 空白符和冲突标记 | 0 | PASS | 无输出 |
| `uv run ruff check` 整份受影响旧服务文件 | 了解全文件 lint 基线 | non-zero | FAIL | 旧文件共 `410 errors`；HEAD 已含 `knowledge_space_service.py` 四个 F821；F063 新增行单独过滤为 0 |

## 验收覆盖 Acceptance Coverage

| Acceptance ID | Requirement | Verification Method | Evidence | Status |
|---|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | V-AC-REQ-001-01 | 14 扩展名真实转换 + PDF suite | PASS |
| AC-REQ-001-02 | REQ-001 | V-AC-REQ-001-02 | Worker 原始 PDF 直引/无复制/校验失败测试 | PASS |
| AC-REQ-001-03 | REQ-001 | V-AC-REQ-001-03 | 7 种 Office 真实转换结构有效；复杂样本视觉对比未执行 | MANUAL_REQUIRED |
| AC-REQ-001-04 | REQ-001 | V-AC-REQ-001-04 | TXT/MD/HTML 真实转换和结构/清洗自动测试；视觉对比未执行 | MANUAL_REQUIRED |
| AC-REQ-001-05 | REQ-001 | V-AC-REQ-001-05 | PNG/JPG/JPEG 真实转换与方向/比例自动测试；人工清晰度检查未执行 | MANUAL_REQUIRED |
| AC-REQ-001-06 | REQ-001 | V-AC-REQ-001-06 | 预览 provenance、有效直引、过期/损坏回退测试 | PASS |
| AC-REQ-002-01 | REQ-002 | V-AC-REQ-002-01 | 独立表与 WAITING/PROCESSING/SUCCESS/FAILED 状态机测试 | PASS |
| AC-REQ-002-02 | REQ-002 | V-AC-REQ-002-02 | Processor 不修改解析 status/remark/update_time 回归 | PASS |
| AC-REQ-002-03 | REQ-002 | V-AC-REQ-002-03 | SQLite 父文件行前后实际对比 `update_time/status/remark` | PASS |
| AC-REQ-002-04 | REQ-002 | V-AC-REQ-002-04 | Repository complete 必填字段与 Domain accessor 测试 | PASS |
| AC-REQ-003-01 | REQ-003 | V-AC-REQ-003-01 | 同步解析 finally 与 Celery parse/retry finally 接线契约 | PASS |
| AC-REQ-003-02 | REQ-003 | V-AC-REQ-003-02 | 普通覆盖/Web 覆盖/重解析顺序测试 | PASS |
| AC-REQ-003-03 | REQ-003 | V-AC-REQ-003-03 | `copy_normal` 目标对象/预览去继承 + 迁移回归 | PASS |
| AC-REQ-003-04 | REQ-003 | V-AC-REQ-003-04 | 迁移源码无 insert/扫描 + disposable DB 实际升降级 | PASS |
| AC-REQ-003-05 | REQ-003 | V-AC-REQ-003-05 | 目录/收藏引用/缺对象/不支持扩展名参数化测试 | PASS |
| AC-REQ-003-06 | REQ-003 | V-AC-REQ-003-06 | 无解析 add_file 直投与复制直投契约 | PASS |
| AC-REQ-004-01 | REQ-004 | V-AC-REQ-004-01 | 默认 3 次重试决策与 Celery `retry(max_retries=3)` 调用测试 | PASS |
| AC-REQ-004-02 | REQ-004 | V-AC-REQ-004-02 | mark_retry/fail_generation/attempt_count/脱敏摘要测试 | PASS |
| AC-REQ-004-03 | REQ-004 | V-AC-REQ-004-03 | broker OperationalError 补偿为 FAILED 且返回 False | PASS |
| AC-REQ-004-04 | REQ-004 | V-AC-REQ-004-04 | attempt 日志包含 tenant/file/generation/format/attempt，错误仅类型 | PASS |
| AC-REQ-004-05 | REQ-004 | V-AC-REQ-004-05 | 架构 guard 无 API/Router/Beat/人工重试入口 | PASS |
| AC-REQ-005-01 | REQ-005 | V-AC-REQ-005-01 | 同代重复 claim/complete first-success-wins | PASS |
| AC-REQ-005-02 | REQ-005 | V-AC-REQ-005-02 | N/N+1 交错、过期提交和 GENERATED 候选回收测试 | PASS |
| AC-REQ-005-03 | REQ-005 | V-AC-REQ-005-03 | `find_available` + 源快照 Domain accessor 契约 | PASS |
| AC-REQ-005-04 | REQ-005 | V-AC-REQ-005-04 | 单文件/目录/批量/整库/版本快照、去重、NotFound 幂等测试 | PASS |
| AC-REQ-005-05 | REQ-005 | V-AC-REQ-005-05 | 候选上传后条件提交失败的 GENERATED 回收测试 | PASS |
| AC-REQ-005-06 | REQ-005 | V-AC-REQ-005-06 | ORIGINAL/PARSE_PREVIEW 不作为 Artifact owner 删除测试 | PASS |
| AC-REQ-006-01 | REQ-006 | V-AC-REQ-006-01 | 旧预览字段保留，仅新增内部 provenance；删除 owner 分流 | PASS |
| AC-REQ-006-02 | REQ-006 | V-AC-REQ-006-02 | 单文件/批量下载定向回归 `9 passed` | PASS |
| AC-REQ-006-03 | REQ-006 | V-AC-REQ-006-03 | 无前端/下载 API/权限改动，下载权限测试通过 | PASS |
| AC-REQ-006-04 | REQ-006 | V-AC-REQ-006-04 | `pyproject.toml`/`uv.lock` 无改动，已有依赖真实运行 | PASS |
| AC-REQ-007-01 | REQ-007 | V-AC-REQ-007-01 | 显式 route/queue、任务注册和默认并发 2 部署契约 | PASS |
| AC-REQ-007-02 | REQ-007 | V-AC-REQ-007-02 | `TemporaryDirectory`、LibreOffice/Playwright timeout、异常回收测试 | PASS |
| AC-REQ-007-03 | REQ-007 | V-AC-REQ-007-03 | 禁 JS/路由阻断/清洗测试 + 真实 HTTP 请求数 0 | PASS |
| AC-REQ-007-04 | REQ-007 | V-AC-REQ-007-04 | 显式 tenant header/arg、上下文不匹配拒绝和 tenant-scoped Repository | PASS |
| AC-REQ-007-05 | REQ-007 | V-AC-REQ-007-05 | DB/日志/Celery retry 及失败状态写回异常均仅保留错误类型，秘密字符串不出现 | PASS |
| AC-REQ-007-06 | REQ-007 | V-AC-REQ-007-06 | Dockerfile/Compose 均无改动，但当前 `HEAD` 的后端 `worker` bundle 包含 `start_pdf`，与独立服务契约断言不一致 | FAIL |
| AC-REQ-007-07 | REQ-007 | V-AC-REQ-007-07 | 修复前 Dash 返回 2 并报 `Illegal option -o pipefail`；修复后以原参数进入 Bash 分派，目标测试 `1 passed` | PASS |

## 人工验证 Manual Verification

| Acceptance ID | Manual Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| AC-REQ-001-03 | 在预发布使用含多页、表格、图片、复杂布局的 7 种 Office 样本转换，逐页与原文档打印预览对比 | 正文/表格/图片/分页可读，无整页缺失或严重裁切 | 未执行 | NOT_RUN |
| AC-REQ-001-04 | 使用中文长行 TXT、含列表/表格/代码块的 Markdown 和允许标签 HTML 逐页对比 | 内容完整、空白与结构可读，无严重裁切 | 未执行 | NOT_RUN |
| AC-REQ-001-05 | 使用 EXIF 旋转、竖图、横图和边界尺寸 PNG/JPG/JPEG 渲染页面并人工检查 | 方向正确、比例不变，图像完整清晰 | 未执行 | NOT_RUN |
| AC-REQ-007-06 | 使用项目实际部署方式独立运行 `sh entrypoint.sh pdf`；核对 CPU/内存/PID/临时空间限制；验证公网连接失败且 DB/Redis/MinIO 可达 | Chromium/LibreOffice 成功转换，仅必需内部端点可达，资源限制实际生效 | 未执行 | NOT_RUN |

## 失败与缺口 Failures and Gaps

- 当前 `HEAD` 的 `src/backend/entrypoint.sh` 在 `start_all_workers()` 中执行 `run_background start_pdf`，而同一 `HEAD` 的部署契约测试断言 PDF Worker 不加入该 bundle。该漂移与 T017 的 Shell 语法修复无关，且涉及是否与现有 Worker 容器混跑的部署决策，未在本 Bugfix 中擅自调整。
- 首次真实 Playwright smoke 因本机缺少 `chromium_headless_shell-1200` 失败；执行 `uv run playwright install chromium` 后重试通过。这是本机缓存缺口，Dockerfile 已包含对应安装命令。
- 未在实际部署环境独立运行 PDF Worker，因此出站网络和运行资源限制仍需预发布验收；F063 不修改基础 Dockerfile，也不提供 Docker Compose 服务，非 root 运行加固留给后续部署设计。
- 未在真实 MySQL/DM8 执行 migration；已完成 Alembic 链检查、源码方言审查和 disposable SQLite 实际升降级。生产 downgrade 会删表，不应在含正式数据的环境直接执行。
- 未连接真实 Celery broker、MinIO 和数据库完成端到端上传、重试、generation 竞争和删除对象核对；相同分支已用 mock/SQLite 自动化覆盖。
- 整份旧服务文件 Ruff 基线非绿：本次运行报告 410 个旧问题，其中 HEAD 本身已含 `knowledge_space_service.py` 四个 F821。F063 新文件 Ruff 全部通过，旧文件的本次新增行诊断为 0；未越界修复全库历史 lint 债务。

## 验证质量门 Verification Quality Gate

- [x] Every acceptance criterion has a status.
- [x] Every completion claim is backed by fresh evidence.
- [x] Test/build/lint/smoke commands include actual result summaries.
- [x] Manual-required checks include clear steps.
- [x] Failures are reported without claiming success.
