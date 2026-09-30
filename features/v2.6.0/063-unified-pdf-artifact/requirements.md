# 需求 Requirements：知识文件统一 PDF 产物

## 阅读摘要

- 本文档定义知识文件统一 PDF 产物的业务边界、状态语义、触发范围、失败策略和验收方式。
- 当前状态：`approved`，已确认进入实现。
- 本阶段只为后续水印下载建立可靠 PDF 输入引用，不切换现有下载或预览链路，也不处理历史全量补齐。
- 已确认约束：独立 PDF 状态不得影响知识解析；所有门户当前上传格式均需覆盖；原始/预览只有经来源匹配和统一校验才可复用；失败自动重试后独立进入 `FAILED`。

## 元信息 Metadata

- Feature ID: `063-unified-pdf-artifact`
- Status: `approved`
- Mode: `spec-then-implement`
- Created: `2026-07-20`
- Updated: `2026-07-21`
- Version: `v2.6.0`
- Source request: 为门户知识库后续“下载文件动态加水印”建立统一 PDF 产物，先完成新文件和重新处理文件的 PDF 基线。

## 需求入口摘要 Intake Summary

- 问题 Problem: 当前 PDF 预览由部分 Word/PPT Loader 尽力生成，Excel、文本、HTML、图片、分层 Word 等路径没有统一、可靠的 PDF 产物，无法作为水印下载的共同输入。
- 当前状态 Current state: `KnowledgeFile.status` 只表示知识解析状态；`pdf_preview_object_name` 是可选预览元数据；当前单文件和批量下载仍读取原始文件。
- 目标结果 Target outcome: 每个符合范围的新建或重新处理的物理知识文件都有独立、可追踪、可重试的 PDF Artifact 状态，成功后关联一个经过统一校验的有效 PDF 对象引用；引用可以复用原始 PDF、当前解析预览 PDF，或指向新生成对象。
- 影响对象 Affected systems: Knowledge 文件模型与服务、Celery Worker、MinIO、LibreOffice/Chromium/PyMuPDF 转换环境、文件删除清理链路。
- Requested stopping point: 当前先停在 `spec` 评审；评审确认后再生成 `tasks.md`，生产代码实现需再次获得确认。

## 现状证据 Current Evidence

- 门户当前允许上传 `pdf/txt/doc/docx/ppt/pptx/md/html/xls/xlsx/csv/png/jpg/jpeg`。
- `ExtraFileTransformer` 只有在 Loader 已产生 PDF 路径时才上传 `pdf_preview_object_name`，没有独立失败状态。
- 普通 Word Loader 会尽力生成 PDF，失败时保留知识解析成功；分层 Word Loader没有相同产物。
- PPT Loader 尝试生成 PDF；Excel、文本、HTML、图片 Loader 没有统一 PDF 生成能力。
- `parse_knowledge_file_celery`、`retry_knowledge_file_celery`、`copy_normal` 和空间迁移是当前主要文件处理入口。
- 当前镜像基线已经包含 LibreOffice、Chromium、PyMuPDF、Pillow 和基础中文字体，无需为本 Feature 新增 Python 第三方依赖。
- 现有 `md_to_pdf.py` 已提供 Markdown 转 HTML、`sanitize_html_for_pdf` 和 Playwright `page.pdf()` 参考实现；但现有浏览器路径只拦截 `file://`，不能直接作为不可信 HTML 的完整网络与脚本隔离边界。

## 范围 Scope

### 包含 Includes

- 覆盖门户当前允许上传的全部格式：
  - `pdf`
  - `txt`
  - `doc`、`docx`
  - `ppt`、`pptx`
  - `xls`、`xlsx`、`csv`
  - `md`、`html`
  - `png`、`jpg`、`jpeg`
- 保留原始文件，为物理知识文件建立独立 PDF Artifact 记录和独立处理状态；Artifact 是逻辑事实源，不要求其 PDF 字节必须存放在独立对象中。
- 文件原始内容持久化后建立或失效当前 Artifact generation；有解析任务的路径在本次解析尝试结束并持久化状态后投递 PDF 任务，不要求解析成功；不执行解析的路径直接投递。
- 原始文件为合格 PDF 时直接引用原始对象；当前解析流程存在可证明与源内容一致的合格 PDF 预览时优先复用；其余情况从原始对象生成新 PDF。
- 覆盖新上传、覆盖重试、重新解析、文件复制、知识空间迁移和 Web 链接重新导入。
- PDF 生成使用独立异步任务；失败采用固定上限自动重试，最终失败仅影响 PDF 状态。
- 通过数据库状态和结构化日志提供可观察性。
- 删除文件、替换当前产物和任务竞争时维护对象存储一致性，避免将旧产物识别为当前产物。
- 在独立低并发 Worker 中运行转换任务，避免直接占用现有知识解析工作池。
- 将用户上传内容视为不可信输入：转换子进程使用隔离临时目录、最小环境变量和受限网络/资源，不执行宏、脚本或外部链接更新。

### 不包含 Excludes

- 不自动扫描、调度或转换上线前的全部历史文件。
- 不实现历史文件批量补齐脚本、定时补偿扫描或运营后台。
- 不实现水印、加密、签章或下载权限变化。
- 不修改当前单文件下载、批量 ZIP 下载、预览 URL 或前端展示行为。
- 不提供 PDF 状态查询 API、页面状态、告警页面或专用人工重试接口。
- 不因 Artifact 生成而替换或删除现有 `preview_file_object_name`、`pdf_preview_object_name` 和其他解析附加产物；知识文件自身删除时仍按既有对象生命周期清理。
- 不覆盖后端额外支持但门户当前不允许上传的 `wps/et/dps/bmp`、音频和视频格式。
- 不对图片执行 OCR；图片只需完整、清晰地封装为 PDF 页面。
- 不承诺与 Microsoft Office 像素级一致，也不在本 Feature 分发未经授权的专有字体。
- 不修改项目 `docker/docker-compose.yml`；PDF Worker 由 Compose 之外的实际部署方式独立启动。
- 不修改 `src/backend/base.Dockerfile`；现有镜像已经包含 LibreOffice、Playwright Chromium、PyMuPDF、Pillow 和中文字体，本 Feature 直接复用该运行基线。

## 需求列表 Requirements

### REQ-001: 全格式统一 PDF 产物

作为后续水印下载链路，我需要所有范围内的物理知识文件都能解析为统一、有效的 PDF Artifact 引用，以便后续逻辑不再区分原始文件格式或 PDF 的物理来源。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 任一范围内格式的新物理知识文件进入统一 PDF 处理 THEN 系统 SHALL 在成功后关联一个可打开、非加密、页数大于零且来源可追踪的 PDF 对象引用；该引用 MAY 指向原始 PDF、当前解析预览 PDF 或本 Feature 新生成对象。
- `AC-REQ-001-02`: WHEN 原始文件本身为 PDF 且通过统一校验 THEN 系统 SHALL 直接把当前原始对象登记为统一 PDF 引用，并记录来源和内容摘要，不额外复制一份相同 PDF；WHEN 校验失败 THEN Artifact SHALL 不进入 `SUCCESS`。
- `AC-REQ-001-03`: WHEN `doc/docx/ppt/pptx/xls/xlsx/csv` 代表性样本的统一 PDF 处理成功 THEN 输出 SHALL 保留全部可打印内容，正文、表格、图片和分页可读，不出现整页缺失或严重裁切。
- `AC-REQ-001-04`: WHEN `txt/md/html` 代表性样本转换成功 THEN 输出 SHALL 完整呈现可打印输入内容，中文可读；TXT 的换行和有意义空白 SHALL 保留且长行可换行，Markdown 的标题、列表、表格和代码块 SHALL 可读，安全清洗后允许的 HTML 正文与内联样式 SHALL 不出现整段缺失或严重裁切。
- `AC-REQ-001-05`: WHEN `png/jpg/jpeg` 代表性样本转换成功 THEN 输出 SHALL 完整、清晰地呈现图片，方向正确且不发生非预期拉伸或裁切。
- `AC-REQ-001-06`: WHEN 当前源内容存在由本次解析或同一源内容既有解析产生、且通过统一校验的 PDF 预览 THEN 系统 SHALL 优先直接引用该预览；WHEN 预览缺失、来源无法证明、内容过期或校验失败 THEN 系统 SHALL 回退到从当前原始对象生成 PDF，不得把不合格预览登记为 `SUCCESS`。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | integration test | 14 种扩展名转换矩阵；PyMuPDF 校验输出格式、加密状态和页数 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | automated test | 合格原始 PDF 的 Artifact 对象名等于当前 `KnowledgeFile.object_name`，不发生 MinIO 复制；失败样本不进入 SUCCESS |
| AC-REQ-001-03 | V-AC-REQ-001-03 | slow integration + manual visual QA | LibreOffice 样本语料；检查页数、关键文本、表格/图片和人工版式清单 |
| AC-REQ-001-04 | V-AC-REQ-001-04 | integration + manual visual QA | TXT/Markdown/HTML 样本；断言关键内容、空白与结构，并渲染页面人工比对 |
| AC-REQ-001-05 | V-AC-REQ-001-05 | integration + manual visual QA | 图片方向、比例、边界和页面渲染人工比对 |
| AC-REQ-001-06 | V-AC-REQ-001-06 | integration + fallback test | 当前预览直接引用；缺失、旧源摘要、不合法/加密预览均回退生成并通过统一校验 |

### REQ-002: 独立状态与解析隔离

作为知识库使用者，我需要 PDF 生成独立于知识解析和搜索，以便转换失败不会让已可用的知识内容变为不可用。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN 文件进入 PDF 处理链路 THEN 系统 SHALL 通过独立记录区分 `WAITING`、`PROCESSING`、`SUCCESS` 和 `FAILED`，历史未调度文件以“无记录”表示。
- `AC-REQ-002-02`: WHEN PDF 转换、校验、上传或状态持久化失败 THEN 系统 SHALL 不修改 `KnowledgeFile.status`、解析 `remark`、向量数据或搜索可用性。
- `AC-REQ-002-03`: WHEN PDF 状态发生变化 THEN 系统 SHALL 不因为状态写入而改变知识文件的业务 `update_time`、排序或现有解析结果。
- `AC-REQ-002-04`: WHEN PDF 状态变为 `SUCCESS` THEN 当前记录 SHALL 至少关联源对象快照、源内容标识、PDF 对象名、Artifact 来源、PDF 内容摘要、完成时间、页数和产物大小。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | repository/service test | 状态机转换和历史无记录语义测试 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | regression test | 注入各阶段异常，断言 `KnowledgeFile` 解析字段和值保持不变 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | database integration test | 状态更新前后 `knowledgefile.update_time` 与排序字段不变 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | repository test | 成功记录必填字段、`ORIGINAL/PARSE_PREVIEW/GENERATED` 来源、内容摘要、对象存在性和 PDF 元数据断言 |

### REQ-003: 新增与重新处理触发范围

作为系统维护者，我需要所有会产生新物理文件或重新处理现有物理文件的入口一致触发 PDF 生成，避免不同入口形成产物缺口。

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`: WHEN 新上传或新导入文件需要执行知识解析 THEN 系统 SHALL 在原始对象持久化后建立 `WAITING` Artifact，并在本次解析尝试的最终状态持久化后投递 PDF 任务；解析结果为 `SUCCESS`、`FAILED`、`TIMEOUT` 或 `VIOLATION` 均不得阻止投递。
- `AC-REQ-003-02`: WHEN 用户确认覆盖重名文件、重新导入 Web 链接或重新解析文件 THEN 系统 SHALL 在任何固定原始/预览对象被覆盖前使旧 Artifact 不可用并开启新 generation，避免旧 `SUCCESS` 引用读取到尚未校验的新字节。
- `AC-REQ-003-03`: WHEN 文件复制或知识空间迁移创建新的物理 `KnowledgeFile` 和原始对象 THEN 系统 SHALL 为目标文件调度独立 PDF 处理，不把源文件的现有预览当作目标统一产物。
- `AC-REQ-003-04`: WHEN 数据库迁移部署到含历史文件的环境 THEN 系统 SHALL 不为历史文件创建 PDF 记录或自动投递转换任务。
- `AC-REQ-003-05`: WHEN 记录是目录、收藏引用、缺少持久原始对象或扩展名不在本 Feature 范围 THEN 系统 SHALL 不调度转换，并记录可诊断的跳过原因。
- `AC-REQ-003-06`: WHEN 上传入口明确不执行知识解析、或复制/迁移路径不创建解析任务 THEN 系统 SHALL 在原始对象和文件记录持久化完成后直接投递 PDF 任务，不得因缺少解析完成事件而永久停留在未调度状态。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | service/worker integration test | 新上传在解析最终状态落库后恰好投递一次；解析成功、失败、超时和违规均覆盖 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | ordering + regression test | 覆盖、Web 链接重导入、解析重试先失效旧引用并递增 generation，再覆盖固定对象和投递任务 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | worker/service test | `copy_normal` 与空间迁移目标文件产生独立记录和任务 |
| AC-REQ-003-04 | V-AC-REQ-003-04 | migration test | 迁移前置历史行数量与迁移后 PDF 记录数量对比为 0 增量 |
| AC-REQ-003-05 | V-AC-REQ-003-05 | parameterized unit test | 目录、引用、缺对象、额外扩展名均不投递并包含跳过日志 |
| AC-REQ-003-06 | V-AC-REQ-003-06 | service/worker integration test | `enqueue_processing=false`、`copy_normal` 和空间迁移无解析路径均直接投递且不重复 |

### REQ-004: 有上限自动重试与可观察失败

作为运维人员，我需要转换失败自动重试并留下稳定状态和日志，以便在没有管理页面的第一阶段仍能定位问题。

#### 验收标准 Acceptance Criteria

- `AC-REQ-004-01`: WHEN PDF 任务任一处理阶段抛出失败 THEN 系统 SHALL 按配置的固定重试上限自动重试；默认上限为 3 次重试，不包含首次执行。
- `AC-REQ-004-02`: WHEN 重试额度尚未耗尽 THEN 当前记录 SHALL 回到 `WAITING`，累计尝试次数并保存脱敏错误摘要；WHEN 重试耗尽 THEN 状态 SHALL 变为 `FAILED`。
- `AC-REQ-004-03`: WHEN 数据库记录已建立但 Celery 发布失败 THEN 系统 SHALL 将本次 generation 标为 `FAILED` 并记录发布错误，不让上传、复制或解析主流程失败。
- `AC-REQ-004-04`: WHEN 运维人员检查数据库与日志 THEN SHALL 能根据 `tenant_id`、`knowledge_file_id`、`generation`、格式、尝试次数和错误类型关联同一次处理。
- `AC-REQ-004-05`: WHEN 本 Feature 第一阶段上线 THEN 系统 SHALL 不新增状态 API、专用人工重试入口或定时失败扫描任务；重新解析现有文件可作为已有业务入口触发新 generation。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | Celery task unit test | mock 连续失败，断言首次执行加 3 次重试及配置覆盖行为 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | state-machine test | 每次失败后的状态、attempt_count、last_error 与最终 `FAILED` |
| AC-REQ-004-03 | V-AC-REQ-004-03 | service test | mock `apply_async` 发布异常，断言主流程不抛出且记录为 `FAILED` |
| AC-REQ-004-04 | V-AC-REQ-004-04 | log capture test | `caplog`/结构化日志字段与数据库 generation 对齐 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | source scan + route review | 无新增 Router/API/Beat 扫描任务；现有重解析触发测试通过 |

### REQ-005: 幂等、代次一致性与对象生命周期

作为系统维护者，我需要重复投递、文件重处理和删除场景不会产生错误的当前产物或无限孤立对象。

#### 验收标准 Acceptance Criteria

- `AC-REQ-005-01`: WHEN 同一 `knowledge_file_id + generation` 任务被重复投递或重投 THEN 系统 SHALL 幂等处理，最终最多只有一个当前 PDF 对象被记录。
- `AC-REQ-005-02`: WHEN generation N 运行期间文件进入 generation N+1 THEN generation N SHALL 不得把状态或对象指针覆盖到 N+1；其已上传且由 Artifact 拥有的非当前对象 SHALL 被尽力清理，共享原始/预览引用 SHALL 不被 Artifact 清理。
- `AC-REQ-005-03`: WHEN 文件重新处理后当前状态为 `WAITING`、`PROCESSING` 或 `FAILED` THEN 旧 PDF SHALL 不得被识别为当前可用产物，即使旧对象暂时仍存在于 MinIO。
- `AC-REQ-005-04`: WHEN 知识文件被删除且存在统一 PDF 引用 THEN 删除链路 SHALL 根据对象归属删除对象和对应记录：生成对象由 Artifact 生命周期清理，原始/预览共享对象由其既有所有者清理；同一路径最多删除一次，对象不存在 SHALL 视为幂等成功。
- `AC-REQ-005-05`: WHEN 新生成 PDF 对象上传成功但当前 generation 条件更新失败 THEN 系统 SHALL 不登记该对象为当前产物并尽力回收该对象。
- `AC-REQ-005-06`: WHEN Artifact 来源为原始 PDF 或解析预览 PDF THEN generation 替换、任务竞争、失败回滚和普通 Artifact 清理 SHALL 不得删除共享对象；只有知识文件或预览自身删除链路可以删除它。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | concurrent service test | 重复 claim/complete，断言唯一记录与唯一当前对象名 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | race regression test | generation N/N+1 交错完成，断言 N+1 状态和指针不被覆盖；只回收 GENERATED 候选 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | repository test | 只有当前 generation 且 `SUCCESS` 才返回可用对象 |
| AC-REQ-005-04 | V-AC-REQ-005-04 | deletion integration test | 三种来源删除成功/NotFound；共享路径去重且由正确所有者删除 |
| AC-REQ-005-05 | V-AC-REQ-005-05 | worker test | mock 条件提交失败，断言上传对象进入回收且数据库不引用 |
| AC-REQ-005-06 | V-AC-REQ-005-06 | ownership regression test | reprocess、stale completion、retry exhaustion 不删除 ORIGINAL/PARSE_PREVIEW 对象 |

### REQ-006: 现有预览与下载兼容

作为门户使用者，我需要统一 PDF 基线在第一阶段不可见，以避免尚未完成历史补齐和水印链路时改变现有使用行为。

#### 验收标准 Acceptance Criteria

- `AC-REQ-006-01`: WHEN 统一 PDF 处理成功或失败 THEN 原始对象、`preview_file_object_name`、`pdf_preview_object_name` 和现有预览降级逻辑 SHALL 保持不变；系统 MAY 在 `user_metadata` 增加不对外暴露的 PDF 预览源 provenance 字段。
- `AC-REQ-006-02`: WHEN 用户执行现有单文件下载或批量 ZIP 下载 THEN 系统 SHALL 继续按当前原始文件/既有回退规则返回内容，不读取统一 PDF 产物。
- `AC-REQ-006-03`: WHEN 本 Feature 部署 THEN 门户前端、客户端前端、现有下载 API 响应结构和权限检查 SHALL 不发生变化。
- `AC-REQ-006-04`: WHEN 构建本 Feature THEN 系统 SHALL 优先复用已有 LibreOffice、Chromium、PyMuPDF、Pillow 和 Markdown 依赖，不新增 Python 运行时依赖。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | regression test | 转换前后现有预览字段、metadata 值和 Loader 降级行为保持一致；仅允许新增内部 provenance 键 |
| AC-REQ-006-02 | V-AC-REQ-006-02 | existing download regression | 单文件和批量下载测试断言仍访问原始 `object_name` |
| AC-REQ-006-03 | V-AC-REQ-006-03 | diff review + API tests | 无前端/API schema/router/permission 变更 |
| AC-REQ-006-04 | V-AC-REQ-006-04 | lockfile/diff review | `pyproject.toml`、`uv.lock` 无新增依赖 |

### REQ-007: 运行隔离、安全和资源边界

作为平台运维人员，我需要 PDF 转换在受控资源和安全边界内执行，避免复杂文件影响解析 Worker 或访问不受信任资源。

#### 验收标准 Acceptance Criteria

- `AC-REQ-007-01`: WHEN PDF 任务被投递 THEN 任务 SHALL 路由到独立 `knowledge_pdf_celery` 队列，并由可配置低并发 Worker 消费；默认并发数 SHALL 为 2。
- `AC-REQ-007-02`: WHEN 转换成功、失败或超时退出 THEN 本地临时源文件、中间文件和输出文件 SHALL 被清理；转换子进程和页面渲染 SHALL 有明确超时。
- `AC-REQ-007-03`: WHEN 渲染用户提供的 HTML 或 Markdown THEN 渲染环境 SHALL 禁用 JavaScript、阻断外部网络请求和非预期本地文件访问。
- `AC-REQ-007-04`: WHEN 多租户文件被调度和处理 THEN 任务 SHALL 显式携带并恢复该文件的 `tenant_id`，数据库读写和 MinIO 路径 SHALL 使用对应租户上下文。
- `AC-REQ-007-05`: WHEN 记录失败日志 THEN 日志 SHALL 不包含文件正文、凭据、完整远程响应或未限制长度的异常输出。
- `AC-REQ-007-06`: WHEN 生产环境部署 PDF Worker 和转换子进程 THEN 系统 SHALL 使用独立服务/进程，不与 API 或高并发解析 Worker 混跑；转换子进程 SHALL 使用最小环境变量，资源和临时目录受限，外部网络默认拒绝且仅允许 Worker 访问数据库、Celery broker 和 MinIO 必需端点。本 Feature 不新增镜像用户，非 root 运行加固由后续部署设计独立落实。
- `AC-REQ-007-07`: WHEN 镜像或部署配置使用 `sh entrypoint.sh <mode>` 启动后端 THEN Bash 脚本 SHALL 在执行任何 Bash 专属选项、数组或进程管理语法前切换到 Bash，并完整保留原始启动参数；API、Worker 和 PDF 启动 SHALL 不出现 `pipefail` 或 `Syntax error: "(" unexpected`。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-007-01 | V-AC-REQ-007-01 | routing test + deployment smoke | 断言 `apply_async(queue=knowledge_pdf_celery)`；独立 Worker 消费测试任务 |
| AC-REQ-007-02 | V-AC-REQ-007-02 | unit/integration test | 成功、异常、超时后临时目录为空，subprocess/browser 超时生效 |
| AC-REQ-007-03 | V-AC-REQ-007-03 | security regression test | 测试 HTML 的脚本、HTTP URL 和 `file://` 引用均未执行/加载 |
| AC-REQ-007-04 | V-AC-REQ-007-04 | multi-tenant worker test | 不同 tenant header 并发处理，记录与对象不串租户 |
| AC-REQ-007-05 | V-AC-REQ-007-05 | log capture + source review | 日志字段白名单、错误摘要长度和敏感内容缺失断言 |
| AC-REQ-007-06 | V-AC-REQ-007-06 | deployment config review + security smoke | 独立 PDF Worker、CPU/内存/PID/临时空间限制；子进程环境无应用密钥；恶意样本无法访问公网和非临时本地文件；`base.Dockerfile` 无差异 |
| AC-REQ-007-07 | V-AC-REQ-007-07 | shell runtime regression | 使用 `/bin/dash` 或 `/bin/sh` 调用后端 entrypoint 的无副作用 smoke 模式，断言进入 Bash 后的启动模式分派且无 Shell 解析错误 |

## 非功能需求 Non-Functional Requirements

- `NFR-001`: 新表、索引和查询必须兼容 MySQL 与 DM8；本地 SQLite 用于无外部数据库的自动化验证。
- `NFR-002`: PDF 任务不得依赖 Milvus、Elasticsearch、Embedding 或知识解析成功状态。
- `NFR-003`: 单个任务的资源消耗必须受 Worker 并发、转换超时和现有上传大小限制共同约束。
- `NFR-004`: 状态写入必须使用 Repository；Service 不直接编写 ORM 查询，不新增 legacy DAO 入口。
- `NFR-005`: 关键状态机、竞争条件、失败隔离和格式路由必须有自动化测试；版式质量允许使用受控样本进行人工验收。
- `NFR-006`: 日志使用稳定事件名和有限字段；异常边界保留 traceback，但不得静默吞掉关键失败。
- `NFR-007`: 发布必须按“数据库迁移 → PDF Worker → 调度代码”的顺序执行，回滚时先关闭调度，不要求立即删除新表或已有 PDF 对象。
- `NFR-008`: 所有转换输入均按不可信文件处理；文件扩展名、大小和实际可解析格式必须校验，用户文件名不得直接参与本地路径、shell 或对象路径拼接。

## 澄清记录 Clarifications

### Session 2026-07-20

- Q: 格式范围如何确定？ -> A: 覆盖门户当前允许上传的全部 14 种扩展名。
- Q: 历史文件是否本阶段全量补齐？ -> A: 分阶段；本阶段保证新文件，历史补齐作为后续独立阶段。
- Q: PDF 失败是否影响知识解析？ -> A: 不影响；采用独立 PDF 状态并允许重试。
- Q: 本阶段是否切换下载？ -> A: 不切换；历史补齐和水印链路完成后再切换。
- Q: PDF 与原文件及现有预览是什么关系？ -> A: 保留原文件和现有预览，新增独立 Artifact 记录；Artifact 优先引用合格原始 PDF 或当前预览，仅在不能安全复用时新建 PDF 对象。
- Q: 质量目标是什么？ -> A: Office 尽量保持打印版式；文本、网页、表格和图片要求完整可读。
- Q: 哪些业务入口触发？ -> A: 新上传、覆盖重试、重解析、复制和迁移；Web 链接重新导入按同一原则处理。
- Q: PDF 是否独立异步？ -> A: 是；有解析任务时在解析尝试结束后投递独立 PDF 任务，解析不等待 PDF；无解析任务的路径直接投递。
- Q: 第一阶段提供哪些操作入口？ -> A: 仅数据库状态和日志，不提供查询 API 或专用人工重试入口。
- Q: 转换失败如何重试？ -> A: 固定次数自动重试，耗尽后进入 `FAILED`。
- Q: `txt/md/html` 是否统一使用 Playwright 转 PDF？ -> A: 是；三类输入先规范化为受控 HTML，再由禁用脚本、阻断外部资源的 Chromium 打印。复用现有 sanitizer、Markdown 解析和样式能力，但不直接复用现有浏览器安全实现。
- Q: 原始文件本身是 PDF 时是否复制？ -> A: 不复制；统一校验通过后直接引用原始对象，并记录来源与内容摘要。
- Q: 解析生成的 PDF 预览是否复用？ -> A: 条件复用；只有来源可证明与当前源内容一致且通过统一校验时直接引用，否则回退到从原始对象生成。

### Session 2026-07-21

- Q: 是否在项目 Docker Compose 中新增 PDF Worker 服务？ -> A: 否；`docker/docker-compose.yml` 保持不变，仅保留独立队列和 `entrypoint.sh pdf` 启动能力，实际资源与网络隔离由 Compose 之外的部署环境落实。
- Q: 是否需要修改 `src/backend/base.Dockerfile` 提供 PDF Worker 专用非 root 用户？ -> A: 否；现有镜像已具备全部转换依赖，F063 撤销 Dockerfile 改动。独立队列和 `entrypoint.sh pdf` 保留，非 root 运行加固不在本 Feature 中实现。
- Q: `sh entrypoint.sh` 启动时报 `Syntax error: "(" unexpected` 如何处理？ -> A: 保持 Dockerfile 与 Compose 不变，由后端 Bash entrypoint 在首个 Bash 专属语法前检测执行器；不是 Bash 时使用 `exec bash "$0" "$@"` 原参数重启自身。

## 假设 Assumptions

- 自动重试次数是技术参数；默认采用 3 次重试并允许通过配置调整，不改变业务范围。
- 独立 PDF Worker 默认并发数为 2，实际生产值允许按 CPU、内存和文件规模通过部署配置调整。
- 现有上传大小限制继续作为输入上限；本 Feature 不降低用户当前可上传的文件大小。
- 代表性版式样本由项目测试资产提供；专有字体缺失导致的可接受字体替换不判定为内容丢失。

## 风险 Risks

- LibreOffice 字体替换可能改变分页和字符宽度；缺少宋体、微软雅黑等字体时不能承诺像素级版式一致。
- 大型表格、长 HTML 和高分辨率图片可能产生较大 PDF，独立 Worker 仍需在真实数据规模下压测。
- 第一阶段明确不建设定时补偿扫描；Broker 在发布成功后极端丢失消息时，记录可能长期停留在 `WAITING`，只能通过数据库和日志发现。
- Worker 在候选对象上传成功、状态提交前发生不可捕获硬退出时，可能留下未被数据库引用的 generation/attempt 对象；第一阶段通过独立路径和日志保留可诊断性，但不承诺后台自动回收。
- LibreOffice、Chromium、PyMuPDF 和 Pillow 都位于不可信文档解析面；如果生产部署未落实独立进程、最小子进程环境和网络/资源限制，恶意文件可能扩大为凭据泄露或服务拒绝风险，安全 smoke 未通过时不得开启调度。
- 使用同一 `KnowledgeFile` 行覆盖 Web 链接时存在旧任务晚到风险，必须由 generation 条件更新阻断。
- 原始对象和预览 PDF 使用固定 `file_id` 路径；若覆盖前未先失效旧 Artifact，旧 `SUCCESS` 引用可能短暂读取到未经校验的新字节，因此覆盖顺序和并发回归属于阻断验证。
- 共享对象存在多所有者误删风险；Artifact 必须按来源区分对象归属，并对原始、预览和生成对象执行不同清理策略。
- 数据库回滚如果直接删除新表会丢失 PDF 对象引用；生产回滚应保留表和对象，清理必须作为单独、经确认的操作。
- 当前工作区存在与本 Feature 无关的未提交修改，后续实施不得覆盖或格式化这些文件。

## 需求质量门 Requirements Quality Gate

- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid unconfirmed implementation details; configurable defaults are recorded as assumptions.
