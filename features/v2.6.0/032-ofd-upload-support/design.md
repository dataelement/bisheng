# Design: 全平台 OFD 文件上传支持（OFD → PDF）

- 版本：v2.6.0 · Feature F032
- 状态：✅ 已评审（/sdd-review design 通过，无 high/medium）
- 负责人：GuoQing Zhang
- 关联：[spec.md](./spec.md) · [release-contract](../release-contract.md)

## 1. 目标与非目标

**目标**：让知识库、知识空间、工作流、日常对话四个上传入口接受 `.ofd` 文件；后端解析时把 OFD 转成 PDF，复用既有 PDF 解析 / 预览 / 检索链路。OFD 是源文件，预览是 PDF。

**非目标（防误扩范围）**：
- 不动 Linsight 灵思、Report 模板、QA 导入等其它入口。
- 不为 OFD 另存独立 PDF 源文件（原始仍是 `.ofd`，PDF 仅作预览）。
- 不支持反向生成 OFD（PDF → OFD）。
- 不做电子签章 / 印章的法律有效性校验，不保证复杂 OFD 的像素级保真。

## 2. 关键约束 + Constitution Check

**本功能特有约束**：
- 上游数据格式：OFD（GB/T 33190）本质是 zip 包（版式 XML + 资源），转换依赖其结构合法。
- 转换时机：在 `knowledge_celery` 解析 Worker 内**同步**执行（不在上传 HTTP 请求内）。
- 转换引擎：easyofd，**进程内**（纯 Python），无独立服务 / JVM / 新镜像。
- 体积：净增 ≈ 12 MB（仅 `reportlab` + `xmltodict` + easyofd 本体；其余依赖项目已有，详 §3 决策 1 / §6）。

**Constitution Check（C1–C7，门禁）**：方案不违反任一条。
- **C1 分层**：新增 loader（`knowledge/rag/pipeline/loader/ofd.py`）与转换工具（`.../loader/utils/ofd_converter.py`）落在 RAG pipeline 层，复用既有 `_init_pdf_loader`；不跨层、不新增 DAO。
- **C5 错误码**：新增 `OfdConvertError = 10917`，5 位 `MMMEE`，模块 109（knowledge）；不与既有 10915/10916/10962 冲突（已登记 release-contract）。
- **C2 双 DB / C3 多租户 / C4 权限**：不新增表、不新增领域对象，OFD 文件走既有知识文件的多租户与权限链路，无新增面。
- **C6 密钥 / C7 前端 store**：无密钥；前端仅改 accept 列表与预览取 url，不在 store 直连 HTTP。

## 3. 方案对比与选定（最高价值章节）

### 决策 1：转换引擎 = easyofd（进程内）

| 备选 | 评估 | 结论 |
|------|------|------|
| **easyofd**（纯 Python，进程内） | 净增 ≈ 12 MB（仅 reportlab + xmltodict + 本体 73 KB；PyMuPDF/fontTools/loguru/pyasn1 项目已有）；零新服务 / CI | **选定** |
| ofdrw / ofdrw-converter（Java，Apache-2.0，高保真） | `ofdrw-converter` 仅是库、**无现成 HTTP 服务、无官方镜像**，须自研 Java web 封装 + 自维护 ~200 MB JVM 镜像 + 新 `ofd-*` tag CI + 多一个服务运维 | 否决 |
| 自研 fitz/Pillow 渲染 | 许可与依赖最干净，但工作量最大、保真度靠投入 | 否决 |

- **原因（证据）**：实测 easyofd 净增仅 ~12 MB（见 §6 依赖）；ofdrw 无官方镜像、运维代价远大于收益；普通图文 OFD easyofd 足够。
- **何时该推翻**：① 复杂 OFD（印章 / 签章 / 矢量图）真实样本回归保真度不达标；或 ② 法务否决 easyofd 的 **AGPL-3.0** 许可。任一成立 → 切 ofdrw 外部转换服务（自研 Java 服务 + 镜像 + `ofd-*` CI）。

### 决策 2：转换时机 = 解析 Worker 内同步

- **选定**：在 `knowledge_celery` 的 loader `load()` 内同步转 PDF，与 `ppt`/信创 `x_create` 转换时机完全一致。
- **备选（否决）**：上传 HTTP 接口内同步转——会阻塞请求、大文件超时。
- **原因**：天然跑在后台解析线程；与既有转换型 loader 同构，复用其失败 / 状态机。
- **何时推翻**：若转换成为 `knowledge_celery` 吞吐瓶颈 → 考虑拆独立队列。

### 决策 3：OFD 为源文件 + 预览 PDF

- **选定**：原始存 `.ofd`，转出的 PDF 落 `preview/{file_id}.pdf`（与 ppt 同分支）。
- **备选（否决）**：用 PDF 替换源文件——会丢失原始 OFD。
- **原因**：产品口径「OFD 是源文件」；复刻 ppt 预览模式，前端 PDF viewer 零改造。
- **何时推翻**：需求改为不保留 OFD 原件。

### 决策 4：默认支持，无配置开关

- **选定**：OFD 与 pdf/docx 同级，静态默认支持。
- **备选（否决）**：config 开关 gate（曾因「外部服务模式」考虑过 `enableOfd`）——引擎改为进程内常驻后，无外部依赖可缺失，开关失去意义。
- **原因**：easyofd 进程内，不存在「服务未配置」态。
- **何时推翻**：若按决策 1 的推翻路径切回 ofdrw 外部服务 → 需恢复「未配置即不支持」的 gate（`/env` 条件透出 + 前端 `enableOfd` + 上传校验）。

### 决策 5：OfdLoader 委托既有 PDF loader，不重复解析逻辑

- **选定**：`OfdLoader` 转 PDF 后委托 `_build_pdf_loader(pdf)`（从 `_init_pdf_loader` 抽出），复用 ETL4LM/MinerU/PaddleOCR/LocalPDF 的 config 选择。
- **备选（否决）**：在 OfdLoader 内复制 PDF loader 选择逻辑——会造成 config 选择两处来源。
- **原因**：镜像 `XinChuangFormatterLoader`；PDF loader 选择保持单一真相。

## 4. 系统现状

### 4.1 复用的既有模式

- `knowledge/rag/pipeline/loader/ppt.py:48-50` — PPT 转 PDF，`self.preview_file_path = pdf_file_path`，预览落 `preview/{id}.pdf`。
- `knowledge/rag/pipeline/loader/x_create.py` — 信创格式转标准格式后**委托**对应 loader 并设 `preview_file_path`（OfdLoader 的直接模板）。
- `knowledge/rag/base_file_pipeline.py:24` `FileExtensionMap` — 扩展名 → loader 工厂唯一路由表。
- `knowledge/domain/services/knowledge_utils.py` `get_knowledge_preview_file_object_name` / `get_tmp_preview_file_object_name` — 扩展名 → 预览对象路径（`ppt/pptx/dps → preview/{id}.pdf`）。
- `knowledge/rag/pipeline/transformer/extra_file.py` — 把 `loader.preview_file_path` 上传到 MinIO 预览对象。
- `api/v1/endpoints.py GET /env` 的 `uns_support` → 前端 `contexts/locationContext.tsx` 映射 `libAccepts`。

### 4.2 数据流（输入 → 输出主线）

```text
上传(.ofd) ──存原始文件(.ofd)──▶ MinIO
                                     │
            knowledge_celery 解析 ───┤
                                     ▼
      FileExtensionMap["ofd"] → _init_ofd_loader → OfdLoader.load():
          1. easyofd 进程内: ofd → pdf (写入 tmp_dir)        [失败→ OfdConvertError]
          2. preview_file_path = 转出的 pdf
          3. 委托 _build_pdf_loader(pdf) 解析（ETL4LM/MinerU/PaddleOCR/LocalPDF）
                                     │
                                     ▼
      extra_file transformer 上传 preview_file_path → preview/{file_id}.pdf
                                     ▼
      前端预览：源文件 ofd → 取 preview_url(pdf) → 既有 PDF viewer
```

### 4.3 后端改动

| # | 文件 | 做什么 / 不做什么 |
|---|------|------|
| B0 | `common/errcode/knowledge.py` | 新增 `OfdConvertError`，`Code=10917`，`Msg='OFD file is corrupted or has an invalid format'`。前端按 10917 翻译为「OFD 文件损坏或格式非法」。 |
| B1 | `knowledge/rag/pipeline/loader/utils/ofd_converter.py`（新增） | `convert_ofd_to_pdf(input_path, output_dir) -> str`：easyofd 进程内转 PDF；解析/渲染失败 `raise OfdConvertError()`。**不**负责上传 / 预览路径。 |
| B2 | `knowledge/rag/pipeline/loader/ofd.py`（新增） | `OfdLoader`：`load()` 调 B1 → 设 `preview_file_path=pdf` → 委托 PDF loader 回传 `documents`/`bbox_list`/`local_image_dir`。镜像 `XinChuangFormatterLoader`。 |
| B3 | `knowledge/rag/base_file_pipeline.py` | `FileExtensionMap` 加 `"ofd"`→`_init_ofd_loader`；抽 `_build_pdf_loader(file_path)` 供委托（PDF loader 选择单一来源）。 |
| B4 | `knowledge/domain/services/knowledge_utils.py` | `get_knowledge_preview_file_object_name` / `get_tmp_preview_file_object_name`：`ofd` → `preview/{id}.pdf`（同 ppt 分支）。 |
| B5 | `api/v1/endpoints.py GET /env` | 把广告给前端的支持格式抽成模块常量 `UNS_SUPPORT_FORMATS`（含 `'ofd'`），`get_env` 用它构建 `uns_support`。 |
| B6 | ~~上传校验白名单~~ | **取消**：文档上传端点不做扩展名白名单校验，后端门禁只在 parse-time（`FileExtensionMap` 命不中 → `KnowledgeFileNotSupportedError`）。`_upload_file(file_supports=['jpeg','jpg','png'])` 是图标上传，与文档无关，不动。见偏差记录。 |
| B7 | `knowledge/domain/models/knowledge_space_file.py` | 扩展名排序：`_EXT_PRIORITIES` 常量 + `order_field_text` 内的 SQL 副本各加 `('ofd', 16)`（追加末位，不重排，避免扰动 F027 cursor 排序）。 |
| B8 | `pyproject.toml` + `uv.lock` | 新增 `easyofd` 依赖。 |

### 4.4 前端改动（各入口 accept 静态加 `.ofd`）

| # | 文件 | 做什么 |
|---|------|------|
| F1 | `platform/.../knowledgeUploadComponent/DropZone.tsx` | accept 加 `.OFD`（知识库 + 知识空间）。 |
| F2 | `platform/.../BuildPage/flow/FlowChat/ChatInput.tsx` | `ALL`/`FILE` 加 `.OFD`。`ChatFiles.tsx` 的 `checkFileType` 由传入 accepts 推导，**无需改**。 |
| F3 | `client/.../appChat/useAreaText.ts` + `client/.../common/index.ts` | 日常对话 `ALL`/`FILE` + `File_Accept.Default` 加 `ofd`。`InputFiles.tsx` checkFileType 由 accepts 推导，无需改。 |
| F4 | `client/.../knowledge/knowledgeUtils.ts` | `ALLOWED_EXTENSIONS` / `ALLOWED_EXTENSIONS_NO_ETL4LM` 加 ofd（`FILE_INPUT_ACCEPT` 派生自动含）；`getFileTypeFromName` 加 `case "ofd" → FileType.PDF`。 |
| F5 | `platform/.../CitationSourceIcon.tsx` | `normalizeFileType` 把 ofd 归一为 `pdf`（复用 PDF 图标）。 |
| F6 | 预览 | **无需改**：`FilePreviewPage` 已 `preview_url \|\| original_url`，ofd 后端返回 preview_url(pdf) + 类型映射为 PDF → 自动走 PDF viewer。见偏差记录。 |

## 5. 已知坑 / 反直觉事实

1. **OFD 预览必须取 `preview_url`（转出的 pdf），不能取 original_url** — 原始文件是 `.ofd`，浏览器 PDF viewer 无法渲染。不知道 → 预览空白 / 报错。处理：B4（预览对象路径）+ F6（前端取 url）。
2. **`_init_image_loader` 会拒绝 `LocalPdfLoader`**（图片仅外部 OCR 支持）。OFD 委托必须走 `_build_pdf_loader`（普通 PDF 路径），不可误入 image 分支。处理：B3。
3. **转换发生在解析 Worker，不在上传时** — 上传 HTTP 秒回，OFD 是否可用要等 `knowledge_celery` 解析阶段才知道；失败表现为文件状态 FAILED + 10917，不是上传报错。处理：B1/B2。
4. **easyofd 把 OFD 当 zip 解析** — 后缀伪造 / 损坏（非法 zip）会从 easyofd 内部抛异常；B1 必须捕获并转成 `OfdConvertError`，**不得**让原始异常冒泡成裸 500（遵循后端错误处理规范）。处理：B1。
5. **easyofd 解析会往 `os.getcwd()` 写 scratch 文件 `{pid}_{uuid}.ofd`（+ 同名 unzip 目录）** —（源码 `parser_ofd/file_deal.py:35`：`FileRead.zip_path = f"{os.getcwd()}/{name}"`，无目录参数）。成功时自清理，**损坏 OFD 解析失败时跳过清理 → 泄漏到 worker cwd**。knowledge worker 是 `-P threads`，`os.chdir` 进程级不安全。不知道 → 每个坏 OFD 上传都在 src/backend 留垃圾。处理：B1 一次性 hook `FileRead.__init__`，让它把 `zip_path` 指向**线程本地**的目标目录（= 本次 pipeline 的 `tmp_dir`/`output_dir`）；scratch 随该临时目录自动回收，不动全局 cwd，线程间隔离。
6. **easyofd 的 `pdf2ofd`（反向）会 `shutil.rmtree('./test')`** —（`draw/ofdtemplate.py` 用硬编码相对目录 `./test`）。生产**不用** pdf2ofd（只用正向 read+to_pdf）；它**仅用于生成测试 fixture**，且必须在隔离 cwd（如 `/tmp`）下运行——**严禁从 `src/backend` 跑**，否则会删掉真实 `test/` 目录。fixture 已提交（`test/knowledge/fixtures/sample.ofd`），无需再生成。

## 6. 对外契约与依赖

**Outgoing（我提供给别人）**：
- 错误码 `OfdConvertError=10917`（HTTP 可观测）：前端按码做 i18n。**风险点**：改码号会破坏前端翻译映射。
- 预览对象路径 `preview/{file_id}.pdf`（ofd 复用 ppt 分支）：**风险点**：改路径破坏前端预览取 url。
- 内部 Python 接口：`convert_ofd_to_pdf(input_path, output_dir) -> str`、`OfdLoader`、`FileExtensionMap["ofd"]`。
- `/env.uns_support` 含 `'ofd'`：前端各入口 accept 依赖此 + 本地静态列表。

**Incoming（我依赖别人）**：
- 第三方 `easyofd`（**AGPL-3.0**）：**风险点** = 许可合规 / 复杂 OFD 保真度 / 上游维护活跃度。失真不报错，损坏须抛 `OfdConvertError`。
- `PyMuPDF`（项目已有）：easyofd 与既有 PDF loader 共用，版本须兼容。
- 既有 PDF loader 链路（`_init_pdf_loader` 选出的 ETL4LM/MinerU/PaddleOCR/LocalPDF）：**风险点** = 其构造签名变更时 `_build_pdf_loader` 委托需同步。
- OFD 文件格式（GB/T 33190 zip 结构）：上游数据契约。
- 依赖体积：新增 `reportlab`（~11 MB）+ `xmltodict`（<100 KB）+ easyofd（73 KB）≈ **12 MB**；PyMuPDF/fontTools/loguru/pyasn1 项目已有。

## 7. 测试与可观测

- **单元**：`test/knowledge/test_ofd_converter.py`（转换成功 / 损坏文件抛 `OfdConvertError`）；`test_ofd_loader.py`（委托 + `preview_file_path` 设置 + 失败抛错）。覆盖 AC-02 / AC-04。
- **集成 / e2e**：四入口上传真实 OFD 样本（纯文本 / 图文 / 印章）→ 解析成功 → 预览为 PDF；损坏样本 → FAILED + 10917。覆盖 AC-01/02/03/04/05。
- **手动验证一遍**：知识库上传一份真实 `.ofd` → 等解析成功 → 点预览应渲染出 PDF；再传一份改名的非法文件 → 应解析失败并提示「OFD 文件损坏或格式非法」。

## 8. 后续改进

- **保真度**：若复杂 OFD（印章 / 签章 / 矢量图）失真成为问题 → 走 §3 决策 1 的推翻路径（切 ofdrw 外部服务）。不在本期做，避免一开始就背 JVM 服务运维。
- **入口扩展**：Linsight / Report / QA 导入入口本期明确不做（spec out-of-scope），防重复提议。
- **反向生成 OFD / 签章校验**：明确不做。

## 修订历史

| 日期 | 变更 |
|------|------|
| 2026-06-08 | 初版：easyofd 进程内转换、默认支持、四入口；§3 记录 easyofd vs ofdrw 决策；登记 release-contract F032。 |
