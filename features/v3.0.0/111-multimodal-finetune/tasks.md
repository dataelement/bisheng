# Tasks: 多模型多模态微调闭环

**关联规格**: [spec.md](./spec.md)
**版本**: v3.0.0

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户已确认 |
| design.md | ✅ 已评审 | 用户已确认；接手时第一入口 |
| tasks.md | ✅ 已拆解 | 11月3日新增已确认的数据集版本与远程导入任务 |
| 实现 | 🟨 进行中 | 数据集版本与导入代码、契约和真实连接器读取已验证；完整平台浏览器/E2E仍待测试环境验收 |

---

## Tasks

### Wave 1：契约与基础设施

- [x] **T001**: FT 模型能力目录与 schema
  **文件**: companion `development/bisheng-ft/src/sft_server/model_capabilities.json`, `development/bisheng-ft/src/sft_server/capabilities.py`
  **逻辑**: 定义版本化能力条目；首批登记两个真实 GPU 已验证组合，旧模型标 legacy，新增文本/图文/视频能力，音频排除；精确 ID 匹配，不按名称猜测。
  **依赖**: 无

- [x] **T002**: 平台任务持久化扩展与迁移
  **文件**: `src/backend/bisheng/finetune/domain/models/finetune.py`, `src/backend/bisheng/core/database/alembic/versions/v3_0_0_f111_multimodal_finetune.py`
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
