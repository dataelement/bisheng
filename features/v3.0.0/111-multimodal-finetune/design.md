# Design: 多模型多模态微调闭环

> **本文档定位 — 现状快照（Why this How）**
>
> `spec.md` 定义需求和验收口径；本文记录本功能选定的实现边界、契约和已知坑；`tasks.md` 记录实际执行。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.0
**最后更新**: 11月3日

---

## 1. 目标与非目标

- **目标**：在保留旧文本任务的前提下，把毕昇微调入口改造成由训练服务能力驱动的文本/图文/视频 LoRA 闭环；平台负责租户、数据、任务和事实展示，训练服务负责模型适配、GPU 预检、训练、产物检查和独立样本推理。
- **非目标**：本功能不建设通用训练编排平台，不建设独立数据集管理页、长期凭据库、定时同步或 SFTP 连接器，不开放音频、视频音轨、QLoRA 或大规模训练，不改变在线推理服务的发布协议，也不部署生产环境。

---

## 2. 关键约束

- 遵循 [`docs/constitution.md`](../../../docs/constitution.md) C1–C8；平台 API 保持 Router → Service → DAO/外部适配器，新增数据库字段使用双数据库兼容类型，租户继续由现有上下文自动注入。
- 主平台和 `bisheng-ft` 是两个独立仓库、两个部署单元；跨边界只能依赖版本化 HTTP 契约，不能 import 对方源码。
- 模型能力以“训练服务 + 精确基础模型标识 + 权重版本”为作用域；一次 GPU 实测不能升级为所有同名或同系列模型均支持。
- 本次能力组合增加 `Qwen/Qwen3-0.6B + text + lora` 和 `Qwen/Qwen2.5-VL-3B-Instruct + image_text/video_text + lora`；验证状态由对应正式 FT 运行证据决定。旧文本白名单保留兼容状态，但不伪装为本轮重新验证。
- 本轮目标环境是 Docker 内可见的 NVIDIA GPU；宿主分配卡 5、7，容器内编号可能重映射，页面不得把宿主编号当作稳定设备标识。
- 每项任务使用一个不可变数据版本。文本支持 JSON/JSONL/ZIP；图文和视频最终形成 ZIP，根清单接受 `train.json`、`train.jsonl`、`data.json` 或 `data.jsonl`，媒体使用包内安全相对路径，不限定 `media/` 目录。解压后总量、路径穿越、符号链接、缺失媒体和图片解码必须在提交前检查。
- 本地验证允许 FT 节点使用隔离任务目录作为执行工作区；该目录不是生产共享真相。正式多节点发布前，adapter 字节必须转存对象存储并通过内容哈希引用，符合 C8。
- 真实 GPU 训练和推理测试只证明链路；合成小数据集不得形成效果、容量或稳定性承诺。

---

## 3. 方案对比与选定

### 决策 1：模型支持范围由训练服务能力目录驱动

- **备选**：
  - A. 在 React 页面维护模型名称数组 — 改动小，但平台会凭名称猜测能力，新模型需要重新发前端。
  - B. 从模型目录自动扫描并按名称/架构推断 — 能发现模型，但无法证明模板、LoRA 目标、GPU 和推理重载已经验证。
  - C. 训练服务返回显式能力目录，平台保存任务时冻结能力快照 — 新模型通过数据登记扩展，验证状态可追溯。
- **选定**：C。
- **原因**：现有页面只有 `sft_support` 布尔值，旧 wrapper 只有十个精确名称；真实验证已经证明两个新模型可用，但没有证据支持整系列自动放行。显式目录同时解决扩展性和“不把模拟/推断当实测”。
- **何时该重新考虑**：模型注册统一归入平台模型中心，并能为每个训练服务维护同等完整的能力和验证证据时，可由平台作为目录真相；FT 仍需在提交时复核。

### 决策 2：保持旧接口并新增能力、预检和验证契约

- **备选**：
  - A. 原地替换 `/v2.1/sft/job` 的请求和状态 — 契约整洁，但会破坏现有文本任务和旧训练镜像。
  - B. 保留旧 job 契约，增加 capabilities/preflight/inference/artifacts，并让新任务携带版本字段 — 可滚动兼容，平台可识别旧服务。
  - C. 主平台直接 SSH/执行训练 CLI — 绕过服务契约，无法正确处理权限、状态和多实例。
- **选定**：B。
- **原因**：PRD 要求旧文本回归；当前平台已经通过 `SFTBackend` 隔离训练服务。扩展同一边界的风险小于跨越边界直接执行命令。
- **何时该重新考虑**：所有部署都升级到新契约且历史任务完成迁移后，可另起版本删除 legacy adapter；不能在本 feature 内静默删除。

### 决策 3：本地与远程数据统一形成不可变版本

- **备选**：
  - A. 浏览器分别上传 JSON 和任意数量图片，由页面维护对应关系 — 交互灵活，但刷新、重试和任务快照容易失配。
  - B. 上传包含清单和媒体的 ZIP，平台生成内容哈希及检测报告 — 数据版本天然不可变，便于训练节点一次拉取和复现。
  - C. 训练服务直接读取用户电脑目录 — 服务器不可达且破坏安全边界。
- **选定**：B；文本 JSON/JSONL 继续兼容。11月3日增加 FTP/显式 FTPS、S3/MinIO 一次性导入，由正式平台后端读取清单和相对媒体并收敛到同一上传校验及版本存储路径。
- **原因**：ZIP 保留清单和媒体关联，并在 MinIO 中形成单一不可变对象；复用版本无需每次重新连接来源。当前 20 MiB、500 个读取文件和 90 秒是小规模导入实现边界，不是客户规模承诺。
- **何时该重新考虑**：超大数据集、定时同步或长期数据源进入范围时，改用异步导入和对象清单；不能把本次有界同步读取扩展为无限制单包。

### 决策 4：现有任务表兼容扩展，不新建第二套任务系统

- **备选**：
  - A. 为多模态另建任务表和页面 — 隔离快，但产生两套状态、取消和发布逻辑。
  - B. 扩展 `Finetune`，增加数据类型、阶段、能力快照、数据检测、产物和推理验证字段；旧记录字段为空时按 legacy 展示。
  - C. 把所有新增事实塞进 `extra_params` — 无迁移，但查询、展示和长期契约不可控。
- **选定**：B。
- **原因**：现有任务已有租户、状态、日志、取消和发布生命周期。新增字段使用 `JsonType`/`LargeText`，可同时适配 MySQL 和 DM8，并能明确区分历史未知与本轮已验证。
- **何时该重新考虑**：本轮已使用独立 `FinetuneDataset` 保存数据版本；评测、多产物发布形成独立生命周期，或一项训练需要多个并行 trial 时，再拆分其余实体。

### 决策 5：成功由“进程 + 产物”共同决定，真实推理单独记录

- **备选**：
  - A. 训练进程退出码为 0 即成功 — 延续旧行为，但可能缺 adapter/processor。
  - B. 退出码为 0 且产物清单完整才进入训练成功；独立样本推理作为单独验证状态展示。
  - C. 推理效果必须达到统一准确率才成功 — 小样本和不同任务没有统一阈值，容易制造虚假指标。
- **选定**：B。
- **原因**：真实实验已经出现“产物重载”是独立必要步骤；同时本轮合成样本只能证明格式和链路，不能设通用效果阈值。
- **何时该重新考虑**：客户提供正式评测集和签字阈值后，新增任务级效果验收，但仍不能替代产物完整性检查。

### 决策 6：在创建任务内导入或复用数据，不增加复杂管理页面

- **备选**：独立数据集中心与长期数据源凭据；或在现有单页创建任务内完成一次性导入和版本选择。
- **选定**：后者，用户已于11月3日确认。训练数据区保留在单页表单，导入弹窗提供本地文件、FTP/显式 FTPS、S3/MinIO。远端连接和媒体根目录各填写一次，清单只含相对媒体路径。
- **原因**：本轮验证企业首次使用的小规模链路，版本可复用即可满足需求；长期数据源、自动同步和异步导入需要单独生命周期，不在本轮混入。
- **边界**：凭据只保留在本次请求；导入成功才保存不可变对象和校验报告。远端清单/ZIP 与本地清单二选一，完整 ZIP 自带媒体时忽略媒体根目录。FTPS 仅显式 TLS，不等同于 SFTP。
- **何时重新考虑**：客户明确需要大数据量、持久数据源、同步计划或后台进度恢复时，再扩展凭据保管、异步任务和对象清单。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

#### 能力发现

`创建页选择训练服务 → 平台 GET /api/v1/finetune/capabilities → FinetuneService → SFTBackend → FT GET /v2.1/sft/capabilities → 页面按 data_type/method/status 筛选`

- FT 从版本控制内的能力清单读取精确模型条目，并结合当前模型目录和运行依赖返回 `available` 与检查原因。
- 平台不缓存为第二份长期真相；创建任务时把当次条目冻结到 `capability_snapshot`。
- 老 FT 服务没有能力接口时，平台只返回 `legacy` 条目，不开放图文。

#### 数据上传与预检

`单页选择已有版本，或弹窗导入本地/FTP/S3 → 正式导入器读取清单和媒体 → FinetuneFileService 安全检查 → MinIO 对象 + FinetuneDataset 不可变版本 → 数据报告及预览 → POST /api/v1/finetune/preflight → FT 复核模型/GPU/模板/方法`

- 文本 JSON/JSONL 支持 Alpaca 和 `messages` 对话结构。ZIP 根清单支持 `train` 或 `data` 的 JSON/JSONL，媒体使用相对路径；平台拒绝绝对路径、`..`、符号链接、缺失媒体及不可解码图片。视频当前仅 MP4，平台先做结构检查，FT 再真实解码。
- `GET /datasets` 按模态列出当前租户版本；前端保留完整版本对象作为唯一 `train_data`，创建时后端按租户及对象 URL 重新读取报告。
- 导入请求以 JSON body 提交 `source`、`connection`、`manifest_path` 或 `manifest_text + manifest_filename`、`media_root`。凭据不进入 URL、存储记录或日志。
- 导入端点通过专用解析依赖读取有界请求体，使用 `model_validate_json` 校验；将错误转换为 10129 并排除 input/context，避免旧全局 422 处理器回显凭据。该解析不改变前端 JSON 字段结构。
- 已有及远端版本通过 `/datasets/{version_id}/preview` 返回前三条样本；媒体 URL 同源且受认证。前端封装请求下载 Blob 以携带 Bearer 身份，展示结束撤销 Blob URL，不把令牌加到媒体 URL。
- FT 在真正创建任务前再次检查能力和资源，避免页面检查后 GPU 状态变化。

#### 训练与验证

`POST /api/v1/finetune/job → 平台冻结快照并调用 FT → FT 准备数据并运行 LlamaFactory → 状态/日志轮询 → 产物清单 → 页面提交独立文本/图片 → FT 干净子进程重载并推理 → 平台保存验证记录`

- 旧文本任务继续走原 legacy 参数映射。
- 新任务使用 `contract_version=2`，训练服务使用参数数组或配置文件执行，不拼接用户输入到 shell 字符串。
- 平台的 `status` 保留旧五态兼容列表，新增 `stage` 表示 `preparing/training/checking_artifacts/validating/completed/failed/cancelled`。

### 4.2 关键数据结构 / 字段约定

#### 模型能力条目

| 字段 | 类型 / 格式 | 说明 | 消费方 |
|---|---|---|---|
| `capability_id` | string | 精确条目 ID，模型版本变化必须换 ID | 平台、FT、任务快照 |
| `model_name` | string | 模型管理中使用的精确名称 | 平台模型选择器 |
| `model_path` | string | FT 节点内配置路径；不返回浏览器 | FT |
| `input_types` | `string[]` | `text`、`image_text` 或 `video_text` | 页面筛选、预检 |
| `training_methods` | string[] | 本轮可开放 `lora`；legacy 可保留旧值 | 页面、预检 |
| `template` | string | LlamaFactory 模板 | FT adapter |
| `validation_status` | enum | `gpu_smoke_passed/legacy/unverified/blocked` | 页面、提交门禁 |
| `validation_evidence` | object | 环境、日期、基础模型版本和证据摘要 | 任务详情 |
| `parameter_schema` | object | 可公开参数、默认值和上下限 | 页面表单、服务端校验 |

#### 创建和预检请求

| 字段 | 类型 / 格式 | 说明 | 消费方 |
|---|---|---|---|
| `contract_version` | integer | 新任务固定为 `2`；缺失视为 legacy | 平台、FT |
| `data_type` | enum | `text` / `image_text` / `video_text` | 平台、FT |
| `capability_id` | string | 选择的精确能力条目 | 平台、FT |
| `dataset` | object | MinIO 对象、SHA-256、检测报告和样本数 | 平台、FT |
| `method` | enum | 本轮真实新组合只允许 `lora` | 平台、FT |
| `parameters` | object | 只包含能力 schema 允许的训练参数 | 平台、FT |
| `preflight` | object | `passed`、逐项 `checks` 和资源快照 | 页面、任务记录 |

#### 任务扩展字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `data_type` | string | 旧记录为空，显示为 legacy/未知，不推断 |
| `stage` | string | 细粒度阶段，不替换旧 `status` |
| `capability_snapshot` | JSON | 创建时冻结的能力事实 |
| `dataset_report` | JSON | 数据对象哈希、样本数、媒体数和检测结果 |
| `artifact_report` | JSON | 文件名、大小、SHA-256 和完整性结论 |
| `inference_validation` | JSON | 输入摘要、基础/适配器身份、生成参数、真实输出或失败原因 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `finetune/api/finetune.py` | 认证后的 HTTP 输入输出和 DTO 转换 | 不访问数据库、不拼训练命令 |
| `finetune/domain/services/finetune.py` | 编排能力、数据、预检、任务、产物和验证规则 | 不写 ORM 查询、不凭模型名推断能力 |
| `finetune/domain/services/finetune_file.py` | JSON/ZIP 安全检测、哈希和 MinIO 存储 | 不训练、不保存源凭证 |
| `finetune/domain/sft_backend.py` | 版本化 FT HTTP adapter 和错误翻译 | 不承担业务授权、不持久化任务 |
| `finetune/domain/models/finetune.py` | 任务持久化字段和 DAO | 不调用外部服务 |
| `controllers/API/finetuneV2.ts`、`finetuneDatasets.ts` | 新训练和数据集 HTTP 类型与请求边界 | 页面/store 不直接发 HTTP、不存连接凭据 |
| `finetune/domain/services/datasets.py`、`remote_dataset.py` | 版本列表/导入/预览；有界 FTP/S3 读取并统一校验 | 不读取未引用媒体、不保留来源凭据 |
| `ModelPage/components/DatasetImportDialog.tsx`、`SavedDatasetPreview.tsx` | 单页内导入和鉴权预览 | 不伪造校验报告、不创建独立管理页 |
| `ModelPage/components/CreateTask*` | 单页分区表单、能力筛选、检测和预检展示 | 不维护模型白名单、不伪造状态 |
| `bisheng-ft/sft_server/capabilities.py` | 加载和校验能力清单 | 不从相似名称自动放行模型 |
| `bisheng-ft/sft_server/preflight.py` | 检查模型文件、模板、依赖、GPU 和参数 | 不创建任务 |
| `bisheng-ft/sft_server/sft_manage.py` | 隔离任务目录、进程生命周期、状态和产物清单 | 不决定平台租户权限 |
| `bisheng-ft/llmtuner/wrapers/trainval.py` | 把能力条目和标准任务参数映射到 LlamaFactory | 不使用前端任意参数拼 shell |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 宿主 已分配GPU 在只映射指定设备的容器内通常显示为 0、1 | 把宿主编号传入容器会选错设备或报不存在 | FT `preflight.py` 返回 UUID 和容器编号；平台只回传能力结果 |
| 2 | 旧 `trainval.py` 的模型映射既是名称白名单又决定模板/LoRA target | 只改页面选项仍会在训练阶段报不支持 | FT `capabilities.py` 与 wrapper 统一从同一条目读取 |
| 3 | 旧 FT 使用 `ASCEND_RT_VISIBLE_DEVICES` 和 `npu-smi`，目标服务器是 NVIDIA | Docker 能看见 GPU 也不代表旧命令会用 CUDA | FT resource adapter 按运行时选择 NVIDIA，NPU legacy 路径不冒充通过 |
| 4 | 图文 JSON 上传成功不等于图片实际进入训练 | 训练可能只学文字，页面却显示图文成功 | `finetune_file.py` 检查引用；FT 数据准备再次检查解压目录 |
| 5 | 训练退出码 0 不保证 adapter、processor 或 tokenizer 完整 | 页面可能显示成功但干净进程无法加载 | FT artifact report + 平台 `artifact_report` 门禁 |
| 6 | LoRA adapter 绑定基础模型的精确版本 | 同系列权重替换后可能加载失败或结果失真 | `capability_snapshot` 和验证记录保存精确基础模型身份 |
| 7 | 现有 `status=4` 只表示旧“训练成功”，不能表达产物和推理验证 | 改旧枚举会破坏列表、发布与历史任务 | 保留 `status`，新增 `stage` 和两个报告字段 |
| 8 | 本地 20 MiB 和单 GPU 串行锁来自验证服务，不是产品容量 | 把原型数值写成承诺会导致错误验收 | 能力参数 schema 标为部署值；spec 明确不作容量承诺 |
| 9 | 旧任务新增字段全部为空是“历史未知”，不是“未验证失败” | 页面会错误否定历史成功任务 | DTO 和详情页显式渲染 legacy/未知 |
| 10 | 平台前端有中、英、日三套 model 文案 | 只补中文会造成其他语言 key 或回退文本暴露 | `locales/{zh,en,ja}/model.json` 同步更新 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/finetune/capabilities?server_id=` | HTTP API | platform 创建任务页 |
| `POST /api/v1/finetune/preflight` | HTTP API | platform 创建任务页 |
| `POST /api/v1/finetune/job` 扩展字段 | HTTP API，旧字段兼容 | platform、历史调用方 |
| `POST /api/v1/finetune/job/{job_id}/validate` | JSON HTTP API；媒体先通过 `/media` 上传 | platform 任务详情页 |
| `GET /api/v1/finetune/datasets?data_type=&page=&limit=` | `{data: TrainingFile[], total}` | 单页已有版本选择 |
| `POST /api/v1/finetune/datasets/import` | JSON body；返回单个 TrainingFile | 导入弹窗 |
| `GET /api/v1/finetune/datasets/{version_id}/preview` | `{samples:[{messages,media}],version_id,dataset_report}` | 版本样本预览 |
| `GET /api/v1/finetune/datasets/{version_id}/media?path=` | 同源鉴权媒体字节，private/no-store | 前端 Blob 预览 |
| `GET /v2.1/sft/capabilities` | FT HTTP API | 主平台 `SFTBackend` |
| `POST /v2.1/sft/preflight` | FT HTTP API | 主平台 `SFTBackend` |
| `/v2.1/sft/job/*` 的 v2 payload/response | FT HTTP API | 主平台任务编排 |
| 能力目录 JSON schema | 版本化数据格式 | FT 配置、平台任务快照、测试 |
| `FinetuneService.get_capabilities/preflight/validate_inference` | Python service API | finetune endpoints |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| 模型管理中的 `ModelDeploy.id/model/server` | 平台数据契约 | 模型改名或 server 归属变化会使能力匹配失败，必须显式报错 |
| MinIO 私有对象和临时分享链接 | 对象存储契约 | 链接过期、FT 网络不可达会使预检或数据准备失败 |
| MySQL/DM8 + tenant auto-filter | 平台基础设施 | 新字段/DAO 绕过 dialect helper 或租户上下文会违反 C2/C3 |
| Redis | FT 队列和任务状态 | Redis 丢失时不能把本地目录猜成任务成功 |
| `nvidia-smi`、CUDA、PyTorch | 系统二进制/运行时 | 容器只装驱动库但 PyTorch 架构不匹配时预检必须失败 |
| LlamaFactory 固定版本 | 第三方训练器 | 模板名、参数名或多模态数据格式升级会破坏 adapter |
| Transformers + PEFT | 产物重载和推理 | 基础模型类或 processor 版本不匹配时验证失败 |
| Qwen2.5-1.5B 与 Qwen2-VL-2B 权重 | 外部模型资产 | 路径存在不等于文件完整；能力条目必须配校验和/版本证据 |
| 平台 i18n `model` namespace | 前端契约 | 新文案缺任一语言会显示 key 或错误回退 |

---

## 7. 测试与可观测

- **单元测试**：平台覆盖能力筛选、旧服务 fallback、DTO/参数验证、ZIP 路径安全、状态转换和租户隔离；FT 覆盖目录 schema、预检、命令参数、产物清单和取消；前端覆盖数据类型切换、模型过滤、未验证禁用和提交 payload。
- **集成测试**：用假的 FT HTTP server 验证平台 Router → Service → adapter；用临时目录和伪 `nvidia-smi` 验证 FT，不要求 GPU。数据库相关测试至少在 SQLite 快测并由设计审查保证 MySQL/DM8 helper 使用正确，DM8 留中央回归。
- **页面测试**：启动本地平台后，创建页完成文本/图文切换、上传错误包、选择验证模型、预检失败/通过、提交和详情恢复。Playwright 尚未成为自动门禁时保留可重复手工清单。
- **真实 GPU E2E**：在隔离容器中只映射宿主 已分配GPU，依次跑 Qwen2.5-1.5B 文本 LoRA 与 Qwen2-VL-2B 图文 LoRA；每项使用未参与训练的样本执行新进程重载。运行前后执行 `nvidia-smi`，禁止并发占用。
- **可观测**：平台日志记录 tenant/job/capability/stage 和 FT 请求结果，不记录数据正文；FT 日志记录 job、模型精确 ID、GPU UUID、命令参数摘要、退出码和 artifact hash。页面只展示真实返回值，网络失败显示失败/未知。

手工入口：

```bash
# 平台后端（development/bisheng/src/backend）
uv run uvicorn bisheng.main:app --host 127.0.0.1 --port 7860 --workers 1 --no-access-log

# 平台前端（development/bisheng/src/frontend）
pnpm --filter platform dev

# FT 服务（development/bisheng-ft/src/sft_server）
python main.py 8000

# 快速契约检查
curl -s http://127.0.0.1:8000/v2.1/sft/capabilities
```

真实 GPU 的 Docker 镜像、模型挂载和命令以项目 `gpu-validation/` 的已验证配置为准；账号、口令和服务器地址不写入仓库。

---

## 8. 后续改进 / 不打算做的事

- 本轮已实现一次性、小规模 FTP/显式 FTPS、S3/MinIO 导入；持久凭据、后台大批量导入、重试恢复和定时同步仍需独立设计，SFTP 不在范围内。
- 视频必须完成模型、预处理、显存、产物重载和目标推理验证；音频及视频音轨明确不纳入本期。
- 大数据集应改为对象清单和流式准备，ZIP 只服务本次小规模闭环。
- 正式多节点部署必须把 adapter 和处理器转存对象存储；本地 FT 工作目录只可作为可丢弃缓存。
- 发布到现有 RT 推理服务仍沿用 legacy 路径，本轮只保证独立重载验证；目标 RT 支持多模态 adapter 后另行设计发布适配。
- 客户效果阈值、并发和容量在取得真实数据与压测结果前不进入默认配置。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 10月30日 | 初版：能力目录、兼容接口、数据包、任务扩展和验证闭环 | PRD 完成且文本/图文真实 GPU 可行性已通过 |
| 11月3日 | 纳入单页数据集版本复用、本地/FTP/显式 FTPS/S3 导入与鉴权预览；同步有界读取及422脱敏契约 | 用户确认数据集方案并授权测试环境部署 |

## 11月2日交付实现补充

- 正式 FT 独立入口 `multimodal_service:app` 提供现有 `/v2.1/sft` 与 common ingress；部署不需要旧版 Celery/Redis worker，使用固定新版 LlamaFactory。
- 平台查询服务能力时自动登记精确 `model_name` 对应的基础模型，模型配置位于 FT 能力目录；不要求管理员修改页面白名单。
- `FinetuneDataset` 记录不可变上传版本、MinIO URL、报告和租户；创建任务重新读取服务端记录，忽略浏览器伪造报告。视频上传只作结构初验，真实解码由 FT 执行并写入执行报告。
- `POST /api/v1/finetune/job/{id}/media` 上传新样本到该任务的对象空间；验证接口只接受本租户本任务登记的对象，不转发任意客户URL。`baseline=true` 可单独加载基础模型，结果分别记录。
- 任务ID先落库再向FT提交；网络中断保留同一任务供状态重查。完成状态必须带完整产物；取消以FT确认的CANCELLED为准。
- 服务端endpoint保留HTTPS和网关前缀；服务记录每次按当前租户查询，不用跨租户内存缓存。


## 11月3日验证状态

- 后端四个测试文件合并 **66 项通过**；前端组件与 API **20 项通过**，565 个严格类型文件通过，platform/client 两套生产资产已构建。详见 `backend-validation.md` 与 `frontend-validation.md`。
- 正式连接器通过真实 FTP 和 S3 各三种模态的清单加媒体、完整 ZIP 读取与校验，共 **12 次通过**；证据为 `src/backend/test/finetune/evidence/formal-dataset-import-20261103.json`。
- 这些结果分别证明代码契约和真实协议读取，**不表示完整平台浏览器/E2E 已完成**。平台登录、数据库/MinIO 版本持久化、浏览器版本复用、预览和训练提交链路仍由测试环境验收确认；FTPS证书握手与外部S3映射也未包含在上述12次验证中。
