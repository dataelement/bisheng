# Tasks: 全平台 OFD 文件上传支持

**关联规格**: [spec.md](./spec.md)
**设计真相**: [design.md](./design.md)
**版本**: v2.6.0 · Feature F032

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | /sdd-review spec 通过（borderline How 作产品口径接受） |
| design.md | ✅ 已评审 | /sdd-review design 通过（无 high/medium）；接手第一入口 |
| tasks.md | ✅ 已拆解 | /sdd-review tasks 通过（LGTM，无 high/medium） |
| 实现 | 🟡 进行中 | 13 / 14 完成（Wave 1-6 ✅；后端测试全绿，前端代码改完且 tsc 无新增报错）。剩 T014 端到端手动验证（需运行全栈）。 |

---

## 开发模式

- **后端 Test-First**：转换工具与 OfdLoader 先写测试再实现；中间件 / e2e 在 CI 跑。
- **前端**：手动验证（每个任务附步骤）。
- **自包含**：任务内联文件 / 逻辑 / AC；设计论证指向 design §X 不复制。

---

## Tasks

### Wave 1 — 基础（无依赖，可并行）

- [x] **T001**: 错误码 `OfdConvertError`
  **文件**: `src/backend/bisheng/common/errcode/knowledge.py`
  **逻辑**: 新增 `OfdConvertError(BaseErrorCode)`，`Code=10917`，`Msg='OFD file is corrupted or has an invalid format'`。release-contract 已登记（109 段，不与 10915/10916/10962 冲突）。
  **覆盖 AC**: AC-04
  **设计**: design §4.3 B0 / §2 Constitution C5
  **依赖**: 无

- [x] **T002**: 引入 easyofd 依赖
  **文件**: `src/backend/pyproject.toml` + `uv.lock`
  **逻辑**: 加 `easyofd`；`uv sync` 更新 lock。校验净增仅 reportlab + xmltodict（PyMuPDF/fontTools/loguru/pyasn1 已有）。
  **设计**: design §4.3 B8 / §6 依赖体积
  **依赖**: 无

### Wave 2 — 转换工具（Test-First）

- [x] **T003**: `convert_ofd_to_pdf` 单元测试
  **文件**: `src/backend/test/knowledge/test_ofd_converter.py`
  **逻辑**: `test_convert_valid_ofd_returns_pdf`（真实/构造样本 → 输出 pdf 存在）→ AC-02；`test_convert_corrupt_raises`（损坏 / 后缀伪造的非法 zip → 抛 `OfdConvertError`）→ AC-04。如 `test/knowledge/` 无 conftest，本任务补基础 fixture。
  **覆盖 AC**: AC-02, AC-04
  **依赖**: T002

- [x] **T004**: `convert_ofd_to_pdf` 实现
  **文件**: `src/backend/bisheng/knowledge/rag/pipeline/loader/utils/ofd_converter.py`（新增）
  **逻辑**: `convert_ofd_to_pdf(input_path, output_dir) -> str`：easyofd 进程内读 OFD → 生成 PDF 写入 `output_dir` 返回路径；捕获 easyofd 内部异常转 `raise OfdConvertError()`（不得让裸异常冒泡成 500）。不负责上传 / 预览路径。
  **测试**: T003 全绿
  **覆盖 AC**: AC-02, AC-04
  **设计**: design §4.3 B1 / §5 坑 4
  **依赖**: T001, T003

### Wave 3 — OfdLoader 接线（Test-First）

- [x] **T005**: `OfdLoader` 单元测试
  **文件**: `src/backend/test/knowledge/test_ofd_loader.py`
  **逻辑**: `test_load_delegates_and_sets_preview`（mock `convert_ofd_to_pdf` + 委托 PDF loader：返回 documents、`preview_file_path` == 转出 pdf、回传 bbox/image_dir）→ AC-02；`test_convert_failure_propagates`（转换抛错时 load 抛 `OfdConvertError`）→ AC-04。
  **覆盖 AC**: AC-02, AC-04
  **依赖**: T001, T002

- [x] **T006**: `OfdLoader` 实现 + pipeline 路由
  **文件**: `src/backend/bisheng/knowledge/rag/pipeline/loader/ofd.py`（新增）、`src/backend/bisheng/knowledge/rag/base_file_pipeline.py`
  **逻辑**: `OfdLoader(BaseBishengLoader)`：`load()` 调 T004 转 pdf → 设 `self.preview_file_path=pdf` → 委托 `_build_pdf_loader(pdf)` 回传 `documents`/`bbox_list`/`local_image_dir`（镜像 `XinChuangFormatterLoader`）。`base_file_pipeline.py`：`FileExtensionMap` 加 `"ofd"`→`_init_ofd_loader`；从 `_init_pdf_loader` 抽 `_build_pdf_loader(file_path)` 单一来源；确保走普通 PDF 路径、不误入 image 分支。
  **测试**: T005 全绿
  **覆盖 AC**: AC-02
  **设计**: design §4.3 B2/B3 / §3 决策5 / §5 坑 2
  **依赖**: T004, T005

### Wave 4 — 后端集成点（Test-First）

- [x] **T007**: 后端集成测试
  **文件**: `src/backend/test/knowledge/test_ofd_pipeline_integration.py`
  **逻辑**: 断言 ① 上传 .ofd 经 `FileExtensionMap` 路由到 `_init_ofd_loader`；② `GET /env` 的 `uns_support` 静态含 `'ofd'`（无开关条件 = AC-06）。预览对象路径断言移除——harness 在 sys.modules stub 了 `knowledge_utils`，无法单测（见偏差记录），AC-03/AC-05 由 T014 手动覆盖。
  **覆盖 AC**: AC-01, AC-06
  **依赖**: T006

- [x] **T008**: 预览对象路径 + 扩展名排序
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_utils.py`、`src/backend/bisheng/knowledge/domain/models/knowledge_space_file.py`
  **逻辑**: `get_knowledge_preview_file_object_name` / `get_tmp_preview_file_object_name` 把 `ofd` 归入 `preview/{id}.pdf` 分支（同 ppt）；排序元组加 `('ofd', N)`。
  **测试**: T007 相关断言转绿
  **覆盖 AC**: AC-03, AC-05
  **设计**: design §4.3 B4/B7 / §5 坑 1
  **依赖**: T007

- [x] **T009**: uns_support 广告格式（静态，无开关）
  **文件**: `src/backend/bisheng/api/v1/endpoints.py`
  **逻辑**: 把 `GET /env` 的支持格式抽成模块常量 `UNS_SUPPORT_FORMATS`（含 `'ofd'`），`get_env` 用它构建 `uns_support`。**偏差**：文档上传端点本就无扩展名白名单（门禁在 parse-time `FileExtensionMap`），`_upload_file.file_supports` 是图标上传，与 OFD 无关，不改（见偏差记录）。
  **测试**: T007 `test_ofd_advertised_without_gate` 转绿
  **覆盖 AC**: AC-01, AC-06
  **设计**: design §4.3 B5/B6 / §3 决策4
  **依赖**: T007

### Wave 5 — 前端 Platform（手动验证）

- [x] **T010**: Platform 入口 accept（知识库 / 知识空间 / 工作流）
  **文件**: `src/frontend/platform/src/components/bs-comp/knowledgeUploadComponent/DropZone.tsx`、`src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatInput.tsx`（含同目录 `ChatFiles.tsx` 的 `checkFileType`）
  **逻辑**: accept 列表静态追加 `.OFD`（DropZone 两分支）；ChatInput 的 `ALL`/`FILE` 加 `ofd`，`checkFileType` 放行 ofd。
  **覆盖 AC**: AC-01
  **手动验证**: 知识库 / 知识空间 / 工作流对话各上传一份 `.ofd`，被接受、进入解析。
  **设计**: design §4.4 F1/F2
  **依赖**: T009

- [x] **T011**: Platform 图标 + 预览取 preview_url
  **文件**: `src/frontend/platform/src/components/bs-comp/chatComponent/CitationSourceIcon.tsx`（图标映射）、`src/frontend/platform/src/components/bs-comp/FileView.tsx`
  **逻辑**: ofd 复用 PDF 图标；预览时 ofd 取 **preview_url（pdf）** 而非 original_url。
  **覆盖 AC**: AC-03
  **手动验证**: Platform 侧打开已解析成功的 ofd 预览，渲染出 PDF（非空白 / 非报错）。
  **设计**: design §4.4 F5/F6 / §5 坑 1
  **依赖**: T009

### Wave 6 — 前端 Client（手动验证）

- [x] **T012**: Client 对话入口 accept
  **文件**: `src/frontend/client/src/pages/appChat/useAreaText.ts`（含 `InputFiles.tsx` 的 `checkFileType`）、`src/frontend/client/src/common/index.ts`
  **逻辑**: 对话 `ALL`/`FILE`/`Default` 加 `ofd`，`checkFileType` 放行 ofd。
  **覆盖 AC**: AC-01
  **手动验证**: 日常对话上传 `.ofd` 被接受、进入解析。
  **设计**: design §4.4 F3
  **依赖**: T009

- [x] **T013**: Client 知识库 accept / 类型 + 预览取 url
  **文件**: `src/frontend/client/src/pages/knowledge/knowledgeUtils.ts`、`src/frontend/client/src/components/PreviewFile/FileView.tsx`
  **逻辑**: `ALLOWED_EXTENSIONS`/`FILE_INPUT_ACCEPT` 加 ofd，`getFileType` 把 ofd 映射为可预览类型；预览时 ofd 取 **preview_url（pdf）**。
  **覆盖 AC**: AC-01, AC-03
  **手动验证**: client 知识库 accept 含 .ofd；ofd 预览渲染出 PDF。
  **设计**: design §4.4 F4/F6 / §5 坑 1
  **依赖**: T009

### Wave 7 — 全链路验证

- [ ] **T014**: 端到端手动验证
  **逻辑**: 四入口各上传一份真实 OFD（纯文本 / 图文 / 含印章）→ 解析成功 → 预览为 PDF → 检索命中与引用溯源正常；再传一份改名的非法文件 → 文件 FAILED + 提示「OFD 文件损坏或格式非法」。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06
  **依赖**: T010, T011, T012, T013

---

## 实际偏差记录

> 只留一行指针，论证在 design.md（决策 / 坑），这里不重复。
> 推翻已 ★ 确认的决策（如切回 ofdrw）时，先停下与用户重新确认，再记录。

- T009 偏离 → 更新 design B6：文档上传端点无扩展名白名单，后端门禁只在 parse-time（`FileExtensionMap`）；`_upload_file` 的 `file_supports` 仅用于图标上传，与 OFD 无关，故不改。T009 实际改为把 `uns_support` 抽成 `UNS_SUPPORT_FORMATS` 常量并加 `ofd`。
- T011/T013 偏离 → 更新 design F6：预览取 url **无需改代码**。`FilePreviewPage` 已 `preview_url || original_url`；ofd 后端返回 preview_url(pdf) + `getFileTypeFromName`→PDF，自动走既有 PDF viewer。`ChatFiles`/`InputFiles` 的 checkFileType 由传入 accepts 推导，也无需改。
- T003/T004 加固 → 新增 design §5 坑 5/6：easyofd 解析向 cwd 写 scratch 文件、损坏文件泄漏。`convert_ofd_to_pdf` 一次性 hook `FileRead.__init__` 使 `zip_path` 指向线程本地的 `output_dir`（不用 chdir/全局 cwd，线程隔离，scratch 随临时目录回收）。坑 6：`pdf2ofd` 会 rmtree `./test`，fixture 生成须隔离 cwd（已提交 fixture，勿再生成）。
- T007 调整 → 预览对象路径断言移除（harness 在 sys.modules stub 了 `knowledge_utils`，无法单测），AC-03/AC-05 由 T014 手动覆盖；T007 保留路由 + uns_support 断言（AC-01/AC-06）。
