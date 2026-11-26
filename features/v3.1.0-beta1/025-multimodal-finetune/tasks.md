# Tasks: 多模型多模态微调闭环

**关联规格**: [spec.md](./spec.md)
**版本**: v3.1.0-beta1（F025）

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| Discovery（数据集迭代） | ✅ 已确认 | 2026-11-25 用户确认 D1—D5 |
| spec.md | ✅ 已评审 | 2026-11-26 用户确认本轮规格；AC-40—AC-52 及 AC-09/24/26/27/29 修订 |
| design.md | ✅ 已评审 | 2026-11-26 用户确认数据集迭代设计 |
| tasks.md | ✅ 已拆解 | 11月3日新增已确认的数据集版本与远程导入任务 |
| 实现 | 🟨 进行中 | 2026-11-19：远程数据直达训练服务和 2 GB 本地上传已在两机环境实测通过；旧训练方式去留、GPU 数据副本清理待用户决定 |

---

## Tasks

### Wave 1：契约与基础设施

- [x] **T001**: FT 模型能力目录与 schema
  **文件**: companion `development/bisheng-ft/src/sft_server/model_capabilities.json`, `development/bisheng-ft/src/sft_server/capabilities.py`
  **逻辑**: 定义版本化能力条目；首批登记两个真实 GPU 已验证组合，旧模型标 legacy，新增文本/图文/视频能力，音频排除；精确 ID 匹配，不按名称猜测。
  **依赖**: 无

- [x] **T002**: 平台任务持久化扩展与迁移
  **文件**: `src/backend/bisheng/finetune/domain/models/finetune.py`, `src/backend/bisheng/core/database/alembic/versions/v3_1_0b1_f025_multimodal_finetune.py`
  **逻辑**: 增加 data_type、stage、capability_snapshot、dataset_report、artifact_report、inference_validation；使用 dialect helper；旧行字段为空表示 legacy/未知；downgrade 只删除本 revision 新列。
  **依赖**: 无

- [x] **T003**: 平台 DTO 与错误码
  **文件**: `src/backend/bisheng/finetune/schemas.py`, `src/backend/bisheng/common/errcode/finetune.py`
  **逻辑**: 增加能力、预检和推理验证请求；扩展创建请求；定义不兼容、预检失败、数据包错误和验证失败的可观测错误。
  **依赖**: 无

### Wave 2：训练服务（Test-First）

- [x] **T004**: FT 能力与预检测试
  **文件**: companion `development/bisheng-ft/tests/sft_server/test_capabilities.py`, `development/bisheng-ft/tests/sft_server/test_preflight.py`
  **逻辑**: 测试精确条目、未知模型、unverified 门禁、模型文件、GPU/依赖、参数上下限和容器设备映射。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-10, AC-11, AC-22
  **依赖**: T001

- [x] **T005**: FT 预检实现
  **文件**: companion `development/bisheng-ft/src/sft_server/preflight.py`, `development/bisheng-ft/src/sft_server/main.py`
  **逻辑**: 提供 `/v2.1/sft/capabilities` 与 `/v2.1/sft/preflight`；逐项返回模型、方法、模态、依赖和 GPU 检查；兼容 common ingress。
  **测试**: T004 全部通过
  **依赖**: T001, T004

- [x] **T006**: FT 数据包与产物测试
  **文件**: companion `development/bisheng-ft/tests/sft_server/test_dataset_package.py`, `development/bisheng-ft/tests/sft_server/test_artifacts.py`
  **逻辑**: 覆盖文本 JSON、图文 ZIP、路径穿越、符号链接、缺媒体、图片损坏、adapter/processor 产物和 SHA-256。
  **覆盖 AC**: AC-06, AC-07, AC-08, AC-13, AC-15, AC-16, AC-20
  **依赖**: T001

- [x] **T007**: FT 数据准备与产物实现
  **文件**: companion `development/bisheng-ft/src/sft_server/dataset_package.py`, `development/bisheng-ft/src/sft_server/artifacts.py`
  **逻辑**: 安全解包/规范化数据和生成产物清单；不把退出码单独视为成功。
  **测试**: T006 全部通过
  **依赖**: T006

- [ ] **T008**: FT 任务与独立推理契约测试
  **文件**: companion `development/bisheng-ft/tests/sft_server/test_job_contract.py`, `development/bisheng-ft/tests/sft_server/test_inference_contract.py`
  **逻辑**: mock 训练/推理子进程，覆盖 v2 创建、阶段、取消、产物失败、文本/图片/视频推理和失败不伪造结果。
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-15, AC-17, AC-18, AC-19, AC-20
  **依赖**: T005, T007

- [ ] **T009**: FT 任务与推理实现
  **文件**: companion `development/bisheng-ft/src/sft_server/sft_manage.py`, `development/bisheng-ft/src/sft_server/main.py`
  **逻辑**: 扩展 contract_version=2、阶段、数据准备、产物门禁、取消和 `/job/infer`；执行参数不拼接用户输入到 shell。
  **测试**: T008 全部通过
  **依赖**: T005, T007, T008

### Wave 3：毕昇后端（Test-First）

- [ ] **T010**: SFT adapter 单元测试
  **文件**: `src/backend/test/finetune/test_sft_backend_capabilities.py`, `src/backend/test/finetune/test_sft_backend_preflight.py`
  **逻辑**: mock HTTP client，覆盖新 FT 成功、legacy 404 fallback、业务错误和不可达。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-10, AC-11, AC-22
  **依赖**: T003, T005

- [x] **T011**: SFT adapter 实现
  **文件**: `src/backend/bisheng/finetune/domain/sft_backend.py`
  **逻辑**: 增加 capabilities、preflight、artifacts 和 inference 方法，保持旧方法不变。
  **测试**: T010 全部通过
  **依赖**: T010

- [x] **T012**: 平台数据与领域服务测试
  **文件**: `src/backend/test/finetune/test_finetune_multimodal_service.py`, `src/backend/test/finetune/test_finetune_dataset_package.py`
  **逻辑**: mock DAO/MinIO/FT，覆盖能力匹配、legacy 文本、数据报告、提交前复检、能力快照、产物/推理记录和租户隔离。
  **覆盖 AC**: AC-02, AC-04, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22
  **依赖**: T002, T003, T011

- [x] **T013**: 平台领域服务实现
  **文件**: `src/backend/bisheng/finetune/domain/services/finetune.py`, `src/backend/bisheng/finetune/domain/services/finetune_file.py`
  **逻辑**: 编排能力、上传检测、预检、v2 创建、状态/产物同步和独立推理验证；旧文本路径保持兼容。
  **测试**: T012 全部通过
  **依赖**: T012

- [ ] **T014**: 平台 API 测试与端点
  **文件**: `src/backend/test/finetune/test_finetune_multimodal_api.py`, `src/backend/bisheng/finetune/api/finetune.py`
  **逻辑**: TestClient/直接 endpoint 测试并实现 capabilities、preflight、job validate；认证沿用 tenant admin，endpoint 只委托 Service。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-10, AC-11, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22
  **依赖**: T013

### Wave 4：Platform 前端与闭环

- [x] **T015**: Platform API 类型与创建页测试
  **文件**: `src/frontend/platform/src/controllers/API/finetuneV2.ts`, `src/frontend/platform/src/pages/ModelPage/components/finetuneV2.test.tsx`
  **逻辑**: 定义能力/预检/创建类型；组件测试覆盖动态模型/模态过滤、未验证能力禁用、数据类型不匹配阻断、预检先于提交及 v2 payload；实际API端到端另验。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-22
  **依赖**: T014

- [ ] **T016**: Platform 创建页、详情页与 i18n
  **文件**: `src/frontend/platform/src/pages/ModelPage/components/CreateTask.tsx`, `src/frontend/platform/src/pages/ModelPage/components/CreateTaskList.tsx`, `src/frontend/platform/src/pages/ModelPage/components/FinetuneDetail.tsx`, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/model.json`
  **逻辑**: 单页分区表单由 data_type 驱动；展示能力和预检；图文 ZIP 上传提示；详情显示阶段、能力、产物和真实验证；所有文案三语同步。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-22
  **手动验证（待验收）**: 在测试平台打开模型微调页，分别完成文本/图文/视频切换、错误数据阻断、已有版本复用、已验证模型预检、任务详情恢复与真实推理。创建/详情源码及三语文案已经实现，仍不将完整浏览器验收标完成。
  **依赖**: T015

### Wave 5：验证与回归

- [ ] **T017**: 自动化回归与架构检查
  **文件**: 无新增文件
  **逻辑**: 运行 FT pytest、平台 finetune pytest、ruff、前端 Vitest/typecheck/lint、`scripts/arch-guard.sh`；失败后修复并重跑。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22
  **依赖**: T009, T014, T016

- [ ] **T018**: 真实 GPU 最小 E2E
  **文件**: 测试证据写回 `validation.md`
  **逻辑**: 刷新 已分配GPU 占用；隔离 Docker 运行文本、图文和视频小任务；检查 adapter、干净进程重载、新文本/新图/新视频推理、取消和 GPU 释放；只记录真实结果。
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-22
  **依赖**: T017

---

## 实际偏差记录

- 早期 FT mock 进程测试与独立验证服务不能代替正式平台验收。11月2日正式 FT HTTP 适配器证据已补齐，未在本轮擅自把所有旧任务勾选完成。
- Platform 创建页、详情、日志、取消、产物和新样本推理组件已实现，组件测试已完成；T015 标记完成，T016 的完整浏览器验收仍待执行。
- 正式平台登录、数据库、MinIO、训练服务、前端之间的完整 E2E 尚待测试环境确认，T017、T018、T022 保持未完成；实际 GPU 和连接器证据按各自边界记录。

## 11月2日平台后端交付补充

- 正式后端实现已补齐三种数据类型、不可变上传版本、服务端报告复核、能力自动登记、完整参数传递、媒体推理上传、状态/日志/配置/产物同步、基座与adapter实际输出分别保存。
- 新增文本JSON/JSONL/ZIP以及图文/视频ZIP格式校验；视频结构初验不等同于FT端真实解码。音频请求被拒绝。
- 当前租户的服务和文件通过严格租户查询隔离；移除旧共享server缓存。现有tenant-admin权限入口沿用，完整非管理员及跨租户部署验收仍需独立执行。
- 实际测试文件为 `test/finetune/test_finetune_multimodal_contract.py`、`test_finetune_upload_validation.py`、`test_three_modal_delivery.py`；脚本 `live_ft_contract.py` 使用正式生产HTTP适配器直连FT。
- 真实HTTP适配器测试读取正式FT文本、图文和视频任务的成功状态、产物、真实日志及指标，执行可用性预检并完成一次文本adapter新进程推理。证据 `src/backend/test/finetune/evidence/formal-ft-http-20261102.json`。这不代替完整平台登录、数据库和MinIO联调。


## Wave 6：11月3日确认的数据集方案

本轮范围由用户确认：保留单页创建任务，在训练数据区选择已有版本或通过弹窗导入；支持本地 JSON/JSONL/ZIP、FTP/显式 FTPS、S3/MinIO，连接与媒体根目录只填一次。没有新增独立数据集管理页、持久凭据、自动同步、SFTP、音频或模型发布能力。

- [x] **T019**: 数据集版本 API 与正式远程导入器
  **文件**: `src/backend/bisheng/finetune/schemas.py`, `domain/services/datasets.py`, `domain/services/remote_dataset.py`, `domain/repositories/dataset.py`, `api/finetune.py`, `src/backend/test/finetune/test_dataset_import.py`（省略前缀均相对 `src/backend/bisheng/finetune/`）。
  **逻辑**: 模态过滤和分页列表；远端清单/ZIP或本地JSON/JSONL清单；相对媒体根；有界读取；沿用安全校验和不可变版本持久化；同源受鉴权预览；专用请求解析器避免全局422回显凭据。
  **验证**: 后端四个测试文件合并66项通过，Ruff与差异空白检查通过；完整认证、数据库/MinIO链路由T022验收。
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30
  **依赖**: T002, T003, T013

- [x] **T020**: 单页版本选择、导入弹窗和预览
  **文件**: `src/frontend/platform/src/controllers/API/finetuneDatasets.ts`, `finetuneDatasets.test.ts`, `src/frontend/platform/src/pages/ModelPage/components/CreateTaskList.tsx`, `DatasetImportDialog.tsx`, `DatasetPreview.tsx`, `SavedDatasetPreview.tsx`, `finetuneV2.test.tsx`（组件省略前缀均相对同一components目录）。
  **逻辑**: 已有版本选择/刷新/加载更多；本地/FTP/S3弹窗；连接凭据只留当前内存和POST体；导入成功替换当前选择；权威报告与前三条样本预览；Bearer鉴权媒体Blob及卸载清理；错误内联显示、凭据脱敏；三语言同步。
  **验证**: 16项组件/辅助函数测试与4项API测试共20项通过；565个严格类型文件、增量ESLint、三语和diff检查通过。platform与client生产构建通过并提供静态资产；这些测试不宣称浏览器E2E完成。
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30
  **依赖**: T015, T019

- [x] **T021**: 正式连接器真实协议读取与校验
  **文件**: `src/backend/test/finetune/evidence/formal-dataset-import-20261103.json`, `backend-validation.md`。
  **逻辑**: 在授权沙箱的独立测试数据上，用正式导入器验证FTP与S3各三种模态、清单加媒体及完整ZIP，共12次真实读取和校验。
  **验证**: 12次通过；FTPS证书握手、外部S3端口映射及平台版本持久化不在该证据范围内。
  **覆盖 AC**: AC-25, AC-27, AC-30（仅连接器部分）
  **依赖**: T019

- [ ] **T022**: 完整平台登录、数据版本与训练浏览器E2E
  **文件**: 验收结果由root补充到本feature证据。
  **逻辑**: 测试环境正式页面完成本地/FTP/S3导入→服务端校验与MinIO/数据库版本落地→刷新/重新创建复用版本→文本/图片/视频样本预览→模型预检→实际训练→状态日志/取消→产物与新样本推理；验证错误包拒绝、无权限与跨租户访问限制。
  **当前状态**: 待root完成，不得用66项后端测试、20项前端测试或12次连接器读取替代该验收。
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-17, AC-18, AC-19, AC-20, AC-21, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30
  **依赖**: T016, T018, T019, T020, T021

## 11月3日接口核对与证据

- 只读核对正式前端 `finetuneDatasets.ts`、导入弹窗和创建请求，与后端DTO、专用导入解析、列表、预览、媒体及提交前版本复核一致；未发现阻断性字段或响应不一致。
- `/datasets/import` 仍收原JSON body，不增加嵌套层；成功返回单个TrainingFile。清单字段为 `manifest_path` 或 `manifest_text + manifest_filename` 二选一。坏请求使用10129安全错误，不把凭据交给旧全局422处理器。
- 列表返回 `{data,total}`，版本包含 `id/version_id/name/url/dataset_report/create_time/num`；选中对象直接作为唯一train_data，后端按当前租户重查数据版本并覆盖权威报告。
- 预览返回样本messages和media；媒体URL与前端同源路径检查匹配，并通过封装请求下载Blob携带身份。凭据不进入这些URL或版本记录。
- 前端证据：`frontend-validation.md`、`evidence/frontend/dataset-import-20261103/`。后端证据：`backend-validation.md`、上述真实连接器JSON。

## Wave 7：数据直传、SFTP 与两机实测（2026-11-18 用户确认）

- [x] **T023**: FT 直传接口与运行时
  **文件**: companion `bisheng-ft/src/sft_server/uploads.py`、`multimodal_service.py`、`v2_runtime.py`、`inference_runner.py`、`tests/sft_server/test_uploads.py`、`tests/sft_server/test_v2_runtime.py`
  **逻辑**: `PUT /v2.1/sft/files/{sha256}` 按哈希落盘（校验哈希与大小上限、已存在则复用、半截文件不留）；`POST /v2.1/sft/probe` 试下载平台链接；数据集和验证媒体支持 `ft-file://` 引用；`/health` 报告 `transfer_modes`；推理提示词已带占位符时不重复添加。
  **验证**: FT 测试 29 项通过（新增 5 项）。
  **覆盖 AC**: AC-31, AC-32

- [x] **T024**: 平台拉取 / 直传自动选择
  **文件**: `src/backend/bisheng/finetune/domain/services/transfer.py`、`domain/sft_backend.py`、`domain/services/finetune.py`、`domain/services/multimodal.py`、`common/errcode/finetune.py`（10131）、`test/finetune/test_dataset_transfer.py`；前端 `FinetuneDetail.tsx` 显示「数据传输方式」
  **验证**: 新增 7 项后端测试；去掉探测直接用链接的变异会让 3 项失败。
  **覆盖 AC**: AC-31, AC-32

- [x] **T025**: SFTP 导入
  **文件**: `domain/services/remote_dataset.py`、`schemas.py`、`pyproject.toml` / `uv.lock`（paramiko 3.5.1）、`test/finetune/test_dataset_import.py`；前端 `DatasetImportDialog.tsx`、`finetuneDatasets.ts`、三语 `model.json`
  **验证**: 新增 4 项后端测试（去掉指纹校验的变异会失败）和 1 项前端测试。
  **覆盖 AC**: AC-24, AC-25, AC-33

- [x] **T026**: 两机真实环境验证（毕昇在本机 Mac，FT 在 GPU 服务器 7 号卡，GPU 无法访问 Mac）
  **逻辑**: 本机全新库 `alembic upgrade head` → 管理员登录 → 登记 FT → 文本 / 图文 / 视频各上传示例包、预检、训练、产物检查，并用未参与训练的新文本、新图片、新视频分别跑微调模型与基础模型推理；FTP、SFTP、S3 三种来源各导入 4 种组合（图文清单 + 媒体、视频清单 + 媒体、图文完整 ZIP、文本完整 ZIP），并用 SFTP 导入的视频版本完成一次训练与验证；SFTP 指纹不符、FTP 密码错误、S3 媒体缺失均被拦下且不回显凭据；网页上核对导入弹窗与任务详情。
  **验证**: 全部数据自动走直传；三类训练 15–30 秒完成（各 4 步），新进程推理完成。推理结果只证明链路，4 步小样本训练不构成效果结论（视频方向判断错误）。
  **未覆盖**: 拉取模式在两机环境下的实测（需要 GPU 能访问平台存储的部署，计划在 119 上做）、达梦、Windows、跨租户与非管理员账号、取消与重启恢复。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-06, AC-07, AC-12, AC-13, AC-16, AC-17, AC-18, AC-19, AC-23, AC-24, AC-25, AC-27, AC-28, AC-31, AC-33

## Wave 8：远程数据直达训练服务与 2 GB 本地上传（2026-11-19 用户确认）

- [x] **T027**: FT 直连数据源下载
  **文件**: companion `bisheng-ft/src/sft_server/remote_source.py`（新）、`multimodal_service.py`、`v2_runtime.py`、`dataset_package.py`、`uploads.py`、`deploy/multimodal/{Dockerfile,constraints.txt,README.md}`、`tests/sft_server/test_remote_source.py`
  **逻辑**: 任务带 `dataset_source` 时先登录并读一个文件再接任务；按计划下载、核对大小、检查文件数/总大小/磁盘空间，取消可中断；状态文件只存去掉密钥的连接信息；422 不回显请求体；新增 `POST /v2.1/sft/source/check`。顺带修复只有 instruction/output 的文本行训练报 `KeyError: 'input'`。
  **验证**: FT 测试 43 项通过。
  **覆盖 AC**: AC-28, AC-35, AC-36

- [x] **T028**: 平台远程计划与每次训练重输凭据
  **文件**: `domain/services/remote_dataset.py`（会话改为读文件 + 列大小，`build_remote_plan` / `public_source`）、`datasets.py`（计划与预览存储、预览走预览包）、`dataset_validation.py`、`finetune_file.py`（2 GiB 流式哈希与检查、预览包）、`transfer.py`（`remote_source` / `check_source`）、`finetune.py`、`sft_backend.py`、`schemas.py`（`DatasetCredentials`）、`api/finetune.py`（创建任务专用解析）、`common/errcode/finetune.py`（10132）、`test/finetune/test_dataset_import.py`、`test_dataset_transfer.py`
  **验证**: `test/finetune` 92 项通过。
  **覆盖 AC**: AC-28, AC-34, AC-35, AC-37

- [x] **T029**: 前端、错误码与部署配置
  **文件**: `DatasetSourceCredentials.tsx`（新）、`CreateTask.tsx`、`CreateTaskList.tsx`、`DatasetImportDialog.tsx`、`TrainingArtifacts.tsx`、`finetuneV2.ts`、删除 `DatasetPreview.tsx`（浏览器读整包预览，2 GB 包会占满内存；改用服务端预览包）和不再使用的 `jszip` 依赖；三语 `model.json`、`api_errors` 10132；`docker/nginx/conf.d/default.conf`、`src/frontend/nginx.conf`、helm `configmap-nginx.yaml` 给 `/api/v1/finetune/job(/file)` 单独 2100m / 1800 秒
  **验证**: 创建页相关前端测试 22 项通过；两份 nginx 配置 `nginx -t` 通过，并用本机 nginx 容器实传 1.5 GB；helm 模板本机未渲染。
  **覆盖 AC**: AC-35, AC-37

- [x] **T030**: 两机真实环境验证（毕昇在本机 Mac；FT 和临时 FTP/SFTP/S3 数据源在 GPU 服务器）
  **逻辑**: 6 种导入（SFTP 0.9 GB / 1700 张图清单、FTP 图文清单、S3 视频清单、FTP 图文远程 ZIP、S3 文本远程 ZIP、SFTP 文本清单）各训练一次；提交时错误密码、缺 SFTP 密码、导入后改动来源文件；1.5 GB / 2700 条本地包经 nginx 上传并训练；浏览器走一遍远程版本的提交流程。
  **验证**: 0.9 GB 数据集导入 6.8 秒，FTP 日志显示平台只读了清单和 3 张预览图；全部训练成功（0.9 GB 一项含下载 157 秒）。错误密码 / 缺密码在建任务前报 10132 且未留下任务；改动来源文件的任务报「changed after import」失败。1.5 GB 包上传加检查 21 秒，首次提交直传约 230 秒。GPU 上 28 个任务目录、FT 日志、本地后端日志均未发现数据源密码。
  **未覆盖**: FTPS 证书握手、真实 OSS 账号、商业版网关的上传大小和超时、helm 渲染、达梦、非管理员账号。
  **覆盖 AC**: AC-24, AC-27, AC-28, AC-34, AC-35, AC-36, AC-37

## Wave 9：恢复 Freeze 和全量（2026-11-20 用户确认）

- [x] **T031**: FT 训练方式扩展
  **文件**: companion `model_capabilities.json`（文本 `lora/freeze/full`、图文视频 `lora/freeze`，新增 `freeze_trainable_layers`）、`v2_runtime.py`、`artifacts.py`、`inference_runner.py`、`multimodal_service.py`、`tests/sft_server/test_v2_runtime.py`、`test_artifacts.py`
  **验证**: FT 测试 47 项通过。
  **覆盖 AC**: AC-38

- [x] **T032**: 平台训练方式选择与过旧提示
  **文件**: `TrainingMethodField.tsx`（新）、`CreateTask.tsx`、`FinetuneDetail.tsx`、`finetuneHelpers.ts`、`finetuneV2.ts`、三语 `model.json`；后端 `multimodal.py`、`sft_backend.py`、`common/errcode/finetune.py`（10133）、`test_finetune_multimodal_contract.py`
  **验证**: 后端 `test/finetune` 93 项、前端 ModelPage 与 API 测试除 1 项原有失败外全部通过；真机：Qwen3-0.6B 全量、Freeze 和 Qwen2.5-VL-3B 图文 Freeze 各训练 4 步并完成新样本推理（30 / 30 / 46 秒）。
  **未覆盖**: Qwen2.5-1.5B、Qwen2-VL-2B 和视频的 Freeze / 全量，效果评估。
  **覆盖 AC**: AC-38, AC-39


## 数据集迭代实施（2026-11-26 设计已确认）

以下为本次增量，旧波次状态不自动改为通过。业务实现仅改 Platform 与平台后端；Client 只同步生成的错误码，Worker、FT 不改。自动检查通过与目标环境联合验收分别记录。

- [x] **T033** [基础设施] 目录/任务模型与 DDL
  **文件**: `src/backend/bisheng/finetune/domain/models/preset_train.py`、`finetune.py`（同目录）；`src/backend/bisheng/core/database/alembic/versions/v3_1_0_f025_dataset_catalog.py`
  **逻辑**: 分类、来源、版本/来源关联、软删除及唯一上传 ID；接当前唯一 head。应用回退保留新增列与原数据，不执行删列 downgrade；结构 downgrade 仅去掉本 revision 新字段/索引。

- [x] **T042** [基础设施] 错误码及三语生成
  **文件**: `src/backend/bisheng/common/errcode/finetune.py`、`src/frontend/packages/locales/src/api_errors/{en,ja,zh-Hans}.json` 及生成产物
  **逻辑**: 核对 10134/10135 无占用后定义；单一来源生成两端语言包，无 Client 业务修改。

- [x] **T050** [基础设施] 上传代理配置适配
  **文件**: `docker/nginx/conf.d/default.conf`、`src/frontend/nginx.conf`、`docker/helm/bisheng/templates/configmap-nginx.yaml`
  **逻辑**: 新目录 files/import/convert 路由沿用任务上传的 2100m/1800s/关闭请求缓冲；修改同一条规则，不新增 location 体系。三份匹配与反例校验通过，真实 Nginx/网关验收见 T051。

- [x] **T034** [后端 Domain · 测试] 目录与转换
  **文件**: `src/backend/test/finetune/test_dataset_catalog.py`
  **逻辑**: 会话保留、坏格式位置、SQL 分类分页、目录/版本事务、软删除、错误租户版本关联及历史登记 dry-run/重复执行。
  **覆盖 AC**: AC-40, AC-41, AC-42, AC-43, AC-44, AC-45
  **依赖**: T033, T042

- [x] **T035** [后端 Domain] 格式转换与目录仓储
  **文件**: `src/backend/bisheng/finetune/domain/services/legacy_dataset.py`、`src/backend/bisheng/finetune/domain/repositories/dataset_catalog.py`
  **逻辑**: 纯函数 classify/convert，保留 system/history/input；Repository 提供 list/find/save/delete 与历史分页，严格租户作用域及目录/版本同事务。
  **依赖**: T034

- [x] **T036** [后端 Domain] 持久导入与旧入口
  **文件**: `src/backend/bisheng/finetune/domain/services/datasets.py`、`finetune_file.py`（同目录）
  **逻辑**: 按预期分类复核本地/远程内容；旧格式只保存目录，显式转换生成新文本；旧本地加入与 QA 调用保存新版 messages，原权限检查保留。
  **依赖**: T035

- [x] **T037** [后端 Domain · 测试] 临时上传与重试
  **文件**: `src/backend/test/finetune/test_task_uploads.py`；重试 HTTP 断言见 T049
  **逻辑**: 真实格式检查，断言不调用两个数据表 save；用户归属、过期、空名称失败后重试、重复提交与不同配置拒绝。
  **覆盖 AC**: AC-29, AC-46, AC-47, AC-48, AC-51, AC-52
  **依赖**: T033, T042

- [x] **T038** [后端 Domain] 临时凭证与权威解析
  **文件**: `src/backend/bisheng/finetune/domain/services/task_uploads.py`、`multimodal.py`（同目录）
  **逻辑**: 私有对象及 Redis 24h 凭证绑定 tenant/user；返回 upload_id；任务提交按 upload_id 或活动 catalog/version 重查，覆盖浏览器报告。
  **依赖**: T036, T037

- [x] **T039** [后端 Domain] 创建幂等
  **文件**: `src/backend/bisheng/finetune/domain/services/finetune.py`
  **逻辑**: 同上传、同用户、同配置返回已创建任务；不同配置 10135；唯一上传约束解决并发写入冲突，复查当前服务归属后返回，FT 不重复创建。
  **依赖**: T038

- [x] **T040** [后端 API · 测试] API 权限与响应
  **文件**: `src/backend/test/finetune/test_dataset_catalog_api.py`；既有 `test_dataset_menu_api.py` 与 `test_finetune_menu_api.py` 仅调整对应目录/临时契约夹具
  **逻辑**: 数据集/模型菜单允许拒绝配对，列表响应、跨租户、临时归属；普通用户作用域和软删除不受伪造客户端字段影响。
  **覆盖 AC**: AC-24, AC-26, AC-27, AC-29, AC-40, AC-45, AC-46, AC-49, AC-50, AC-52
  **依赖**: T039

- [x] **T041** [后端 API] 目录与临时路由
  **文件**: `src/backend/bisheng/finetune/api/finetune.py`、`src/backend/bisheng/finetune/schemas.py`
  **逻辑**: dataset-catalog 列表/持久导入/转换/删除/预览/下载用数据集权限；job/file 与 task-uploads 预览用任务权限；旧接口兼容与安全解析沿用。
  **依赖**: T040

- [x] **T043** [后端 Domain] 兼容登记脚本
  **文件**: `src/backend/scripts/register_f025_dataset_catalog.py`、`src/backend/scripts/README.md`
  **逻辑**: 默认 dry-run，显式 tenant-id，--apply 才写；分页检查真实格式与哈希，只登记 training，不复活删除项；保留原文件，错误按 ID 输出并退出非零。测试见 T034。
  **依赖**: T036

- [x] **T044** [前端 Platform] HTTP 类型与选数来源
  **文件**: `src/frontend/platform/src/controllers/API/finetuneDatasets.ts`、`finetuneV2.ts`（同目录）；`src/frontend/packages/api-client/src/requestScopeRoutes.json` 为官方脚本生成产物
  **逻辑**: 目录数据与临时凭证类型、保存/临时 API 分开；scope 清单新增 10 条路由，原条目不变。旧 preset POST 去掉尾部空格。
  **依赖**: T041

- [x] **T045** [前端 Platform] 目录页面
  **文件**: `src/frontend/platform/src/pages/DataSetPage/index.tsx`
  **逻辑**: 四分类及独立来源标签、筛选、显式转换、预览/下载/删除；保留 CreateDataSet 本地/QA 入口，管理作用域切换撤销旧响应与确认回调。
  **依赖**: T044

- [x] **T046** [前端 Platform] 任务临时上传与预览
  **文件**: `src/frontend/platform/src/pages/ModelPage/components/CreateTaskList.tsx`、`TemporaryDatasetUpload.tsx`、`SavedDatasetPreview.tsx`
  **逻辑**: 下拉只加载保存的匹配类型目录；临时本地上传独立卡片/预览，不加入候选数组；类型切换清空旧选择，保留鉴权 Blob 与卸载清理。
  **依赖**: T044

- [x] **T047** [前端 Platform] 持久导入及三语文案
  **文件**: `src/frontend/platform/src/pages/ModelPage/components/DatasetImportDialog.tsx`、`src/frontend/platform/public/locales/{en-US,ja,zh-Hans}/model.json`
  **逻辑**: 目录页复用现有连接器表单，四类选择；任务临时弹窗不承诺复用；三语分类、来源与转换提示齐全。
  **依赖**: T045, T046

- [x] **T048** [前端 Platform · 测试] 目录与任务交互
  **文件**: `src/frontend/platform/src/pages/DataSetPage/index.test.tsx`、`src/frontend/platform/src/pages/ModelPage/components/finetuneV2.test.tsx`；已有 API 测试复用
  **逻辑**: 分类筛选、显式转换后旧数据保留、临时不进入候选、类型切换、错误重试和旧作用域撤销。
  **覆盖 AC**: AC-40, AC-41, AC-43, AC-45, AC-46, AC-47, AC-49, AC-50, AC-51
  **依赖**: T047

- [x] **T049** [后端 API · 自动验收] 隔离 HTTP E2E 与质量检查
  **文件**: `src/backend/test/e2e/test_e2e_f025_datasets.py`；`dataset-iteration-validation.md`、`dataset-iteration-code-review.md`
  **逻辑**: SQLite/真实 Service/ASGI，受控对象与缓存、菜单普通用户；测试前缀及独立库自动销毁。覆盖转换、无入库、失败重试、凭证过期后的任务快照及幂等；ruff/arch-guard/lint/typecheck/i18n/build 与七维复核。明确不是登录/真实 MinIO/GPU 验收。
  **覆盖 AC**: AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52
  **依赖**: T043, T048, T050

- [ ] **T051** [前端 Platform · 联合验收] 目标环境浏览器与部署配置
  **文件**: `e2e-checklist.md`、`test-cases.md`（本目录）
  **逻辑**: 更新指定走查项目后执行迁移/兼容登记核对、真实四类/来源导入、旧本地/QA 入口、普通用户/跨租户、真实大文件代理和 FT 三类训练；MySQL/DM8 部署回归分别留证。当前未更新 109/20，不以本地测试冒充完成。
  **覆盖 AC**: AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52
  **依赖**: T049
