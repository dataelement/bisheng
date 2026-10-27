# Design: MinerU 4.0 独立解析提供方

> 状态：设计已由用户确认，代码已在 `feat/mineru_4.0` 工作树实施；离线验证通过，目标 MinerU 服务与页面验收待执行。本文不代表功能已上线。
>
> [spec.md](./spec.md) 定义 What；本文记录 Why/How；后续 [tasks.md](./tasks.md) 记录执行。实现中的细节变更覆盖更新本文；若推翻已确认的规格或设计决策，按 `docs/SDD-Guide.md` §3 重新确认。

**版本**：v3.0.0 · F076-mineru-v4
**最后更新**：2026-10-13
**基线**：`feat/mineru_4.0` 从 `origin/feat/3.0.0` 的 `eb86a1017267753de76c5c661bb45d0e3178874a` 建立；当前实现见 §4，验收边界见 §7。

## 1. 目标与非目标

新增可显式启用的 MinerU 4.0 解析提供方，把其 V1 异步任务和 ZIP 产物适配到现有知识文件 Load → Transform → Ingest 管线，同时保留旧 MinerU 协议和历史文件。覆盖 PDF、图片及先转 PDF 的 OFD，并让预览和聊天引用可消费新结果。

不在本期部署 MinerU 模型、不迁移历史文件、不扩展 Office/HTML/表格的解析路由、不引入按租户/知识库选择或远端任务恢复。

## 2. 关键约束

- 遵循 [架构宪章](../../../docs/constitution.md) C1–C8 和 [版本契约](../release-contract.md)。本特性不新增数据库表；解析字节在 API、Celery、MinIO 之间传递时，不能依赖跨节点共享本地目录（C8）。
- [MinerU 4.0 V1 API](https://mineru.atomgit.com/zh/usage/http_api.html) 是上传、提交、轮询、下载的异步流程，不提供旧 `/file_parse`；自部署资源索引保存在服务进程内，服务重启后旧任务 ID 不保证可恢复。
- 当前 V1 ZIP 结果包含 Middle JSON 与图片素材；Middle JSON 用 `schema=docvortex.middle`、`schema_version=2.0` 标识，页面是 `pages[].blocks[]`，源页号从 0 开始。具体 ZIP 成员和块形态须以目标版本的真实样本为准。[输出协议](https://mineru.atomgit.com/zh/reference/output_files.html)
- V1 解析任务提供 `ocr_mode`，未提供与毕昇现有 `enable_formula` 完全等价的单次开关；公式效果由实际 tier 和服务能力决定。不能声称旧选项在新提供方上仍有相同语义。[任务参数](https://mineru.atomgit.com/next/api/parse-jobs.html)
- 目标服务、硬件、可用 tier、鉴权方式尚未提供。实施使用可重复的协议夹具；真实服务验收前不得宣称某 tier、图片或 bbox 已在目标环境验证。服务能力以 `/v1/health`、`/v1/tiers` 为准。
- 预览缓存与全局配置切换的现有语义已由用户确认：缓存正文可以跨提供方复用；无缓存时，以任务执行时读到的全局提供方为准。允许配置切换窗口和缓存命中带来的小概率来源差异，不新增入队时的提供方快照或预览任务持久恢复。

## 3. 方案对比与选定

### 决策 1：独立提供方隔离 3.x 与 4.0

- **备选**：A. 在旧 `MineruLoader` 加版本分支；B. 新增 `mineru_v4` 配置和 `MineruV4Loader`；C. 运行时探测协议并自动切换。
- **选定**：B。旧 `mineru` 的配置、请求和结果转换保持原样，新增 `ParseType.MINERU_V4` 与一条显式选择分支。
- **原因**：旧配置的 `url` 指向完整旧接口，4.0 `api_url` 是 V1 服务根地址；请求周期和 JSON 结构均不同。隔离后能够单独验证与回滚，失败不会掩盖在自动降级中。[迁移指南](https://mineru.atomgit.com/zh/reference/migration_4.html)
- **何时重新考虑**：若后续版本共享官方承诺的稳定解析接口，再提取共同客户端接口。

### 决策 2：调用外部 V1 服务，使用已有 `httpx`

- **备选**：A. 在毕昇 Worker 安装 MinerU 推理/SDK 包；B. 以 `httpx` 实现薄 V1 客户端，模型运行由独立服务负责。
- **选定**：B。客户端负责协议校验与有限等待，不在毕昇镜像运行模型。
- **原因**：现有接入是服务间调用；直接依赖 MinerU 包会把模型和硬件运行时带入 API/Celery 镜像。[官方 SDK](https://mineru.atomgit.com/zh/usage/sdk_api.html)可作协议参考，但不强制安装。
- **何时重新考虑**：官方提供无推理依赖的稳定轻量客户端，且依赖与许可符合毕昇打包要求。

### 决策 3：只接受完整 ZIP 产物

- **备选**：A. 只消费 Markdown；B. 单独消费 Middle JSON；C. 请求并消费 ZIP。
- **选定**：C，创建任务时要求 `output_formats=["zip"]`，根据远端返回的产物文件 ID 下载。
- **原因**：正文、块到 bbox 的映射和图片字节需要同时可用；单独 Markdown 缺定位，单独 Middle JSON 不保证带素材。缺必需产物或协议身份不符即失败，不生成失效引用。
- **何时重新考虑**：目标服务提供同等完整、版本明确的其他产物形式。

### 决策 4：保留预览正文复用与执行时选择语义

- **备选**：A. 把提供方/版本加入缓存键并重算旧预览；B. 沿用现有缓存键和正文复用机制。
- **选定**：B。缓存命中时入库正文以用户已看到并可编辑的预览分块为准；缓存未命中时由执行中的管线读取当前全局配置。
- **原因**：用户明确接受预览缓存期内沿用旧解析正文，要求入库正文与所见一致；也接受入队和实际执行之间全局提供方发生变化。强制重算会改变已确认内容。
- **何时重新考虑**：产品要求正文、解析标识、bbox 和图片素材跨提供方切换时都严格同版；届时需要扩展预览快照与素材转存契约，而非仅改缓存键。

### 决策 5：OFD 与 PDF 共享 OCR 队列判定

- **备选**：A. OFD 一律进普通知识队列；B. OFD 在外部解析提供方可用时与 PDF 采用相同专用队列判定。
- **选定**：B。`needs_ocr_queue()` 已在本分支将 `ofd` 与 `pdf` 同列；关闭专用队列仍进普通知识队列。
- **原因**：`OfdLoader` 先转 PDF，再调用相同的 PDF Loader；解析耗时和外部服务占用应按 PDF 隔离。定向测试 13 个通过。
- **何时重新考虑**：OFD 改为不经过 PDF Loader 的独立解析流程。

### 决策 6：`request_kwargs` 透传创建任务的附加参数

- **备选**：A. 把每个 MinerU V1 可选字段都建成独立配置；B. 与现有 MinerU/PaddleOCR Loader 一样提供 `request_kwargs`，合入解析请求体；C. 把它直接传给 `httpx.post(**request_kwargs)`。
- **选定**：B。`knowledges.mineru_v4.request_kwargs` 默认 `{}`，只浅合并到 `POST /v1/parse/jobs` 的 JSON 顶层；不作用于上传、健康检查、轮询、下载，也不是 HTTP headers、URL、超时等传输参数。
- **原因**：现有两个 Loader 的同名字段都是接口请求体参数，管理员可据目标服务能力补充可选字段而无需每次改配置模型。V1 创建任务有明确的 JSON 顶层与文件级字段；把额外字段当 HTTP 客户端参数会改变含义或直接报错。[现有 MinerU 实现](../../../src/backend/bisheng/knowledge/rag/pipeline/loader/mineru.py)、[V1 任务参数](https://mineru.atomgit.com/next/api/parse-jobs.html)
- **何时重新考虑**：上游出现需要毕昇单独解释的稳定选项，或需要配置文件级参数时，再增加有类型的配置/映射；不能靠顶层浅合并修改 `files[]`。

## 4. 系统现状与目标接线

### 4.1 数据流

**当前基线**：文件上传或预览 → `BaseFilePipeline._build_pdf_loader()` 从 DB 配置选择 ETL4LM/旧 MinerU/PaddleOCR/本地 PDF → `OfdLoader` 先转 PDF、图片复用 PDF 选择入口 → Loader 产出 `Document` 和可选 bbox/图片 → Transformer 处理分块、图片、bbox → 知识文件入库或预览缓存 → 平台/客户端按 `parse_type` 打开引用。

**已实施**：在唯一选择入口新增 `mineru_v4` → `MineruV4Client` 调 V1 上传、解析任务和 ZIP 下载 → `MineruV4Loader` 将 Middle JSON/素材转成既有 Loader 契约 → 沿用 Transformer 与入库链路。预览、持久文件和临时解析共用选择入口；不建平行入库管线。

`KnowledgeService.get_preview_file_chunk()` 根据文件及分段规则生成 Redis 缓存键，缓存命中会直接返回旧分块；正式入库的 `PreviewCacheTransformer` 也会以缓存分块覆盖新解析分块。队列仅传文件 ID 等上下文，Worker 开始后才构建 Loader；这两点决定了 §3 决策 4 的实际边界。

### 4.2 配置、协议与产物契约

| 结构 / 字段 | 当前或目标值 | 消费方与含义 |
|---|---|---|
| `knowledges.loader_provider` | 现有全局 DB 配置；新增显式值 `mineru_v4`，默认仍 `etl4lm` | `BaseFilePipeline._build_pdf_loader()` 在任务执行时读取；Redis 配置缓存约 100 秒 |
| `knowledges.mineru_v4` | 新增 `api_url`、`api_key_env`、`tier`、`ocr_mode`、`request_kwargs: dict[str, JSON value] = {}`、连接/请求/传输/总任务超时、轮询间隔 | `MineruV4Conf` 校验字段；只存环境变量名，不存明文 Key；空地址或无效档位明确失败 |
| `KnowledgeFile.parse_type` | 新值 `mineru_v4`；旧值 `mineru` 不变 | 历史文件、文件分享、引用预览；OFD 持久文件的委托解析来源须单独核对 |
| V1 上传/任务 | `/v1/uploads` → 字节上传/完成 → `/v1/parse/jobs` → 轮询任务 → `/v1/files/{id}/content` | 新 HTTP 客户端；只以远端返回的文件 ID 下载 ZIP，不能用旧 `/file_parse` |
| V1 任务状态 | `queued`、`running`、`completed`、`partial`、`failed`、`canceled` | 单文件任务及文件均 `completed` 且 ZIP 校验成功才算成功；其余终态失败 |
| Middle JSON | `schema=docvortex.middle`、`schema_version=2.0`、`pages[].page_idx/blocks[]` | 新 Loader；源页号 0 基；文本、标题、表格、公式、图片块按真实样本映射 |
| `Document` 与 Loader 侧产物 | 正文及 `metadata.pages/types/bboxes/indexes`；`bbox_list`、平铺的 `local_image_dir`、`preview_file_path`；bbox 在 Loader 内缩放到页面坐标后统一用 `int()` 截断，元数据与 `bbox_list` 使用相同整数坐标值 | 分块、`ImageUploadTransformer`、`ExtraFileTransformer`；图片引用替换完毕后计算 `indexes` |
| `/api/v1/knowledge/preview` 与 `/preview/status` | 既有创建任务/轮询接口，无新增前端路由 | 预览页面；进程中断后刷新重新提交会拿到新任务 ID |

建议配置形态（`api_url` 为 `/v1` 之前的服务根地址；部署值以目标环境为准）：

```yaml
knowledges:
  loader_provider: mineru_v4
  mineru_v4:
    api_url: http://mineru-v4.example:8000
    api_key_env: MINERU_V4_API_KEY
    tier: standard
    ocr_mode: auto
    request_kwargs: {}
    connect_timeout_seconds: 10
    request_timeout_seconds: 60
    transfer_timeout_seconds: 300
    job_timeout_seconds: 1800
    poll_interval_seconds: 3
```

新配置块加入 `src/backend/bisheng/initdb_config.yaml`，旧安装由 `ConfigService.merge_missing_config()` 补入缺失子块；不向启动 `config.yaml` 加新顶层键。`force_ocr=1` 对单次任务覆盖为 `ocr_mode=ocr`；默认解析全部页面。配置的 API Key 环境变量在 API 和知识 Worker 进程都须可读。

`request_kwargs` 仅提供创建任务的**其他顶层 JSON 字段**，要求是可 JSON 序列化的映射；构造请求时先合入附加字段，再写入由适配器管理的 `files`、`tier`、`ocr_mode`、`output_formats=["zip"]`。配置若与这四个保留键冲突，直接报配置错误，不默默覆盖。`files[]` 中的 `page_range` 是文件级字段，不能通过此顶层浅合并设置；需要时另设计文件级配置。未知字段由目标 MinerU 服务校验，上游拒绝时按 AC-10/AC-06 报解析失败，不自动切换提供方。`request_kwargs` 不承载 API Key，配置样例和日志均不得包含回调密钥等凭据；`enable_formula` 也不能借透传字段伪装成 V1 已支持的逐任务开关。

ZIP 下载先写受大小限制的临时文件；解包时限制成员数、单成员及总解压字节数，拒绝绝对路径、`..` 路径、符号链接和重复目标名。额度应结合毕昇上传限制和目标服务样本定值，避免大文件或异常 ZIP 耗尽 API/Worker 内存与磁盘。

文件分段规则的 `retain_images` 同时传给新 Loader 与既有 `ImageUploadTransformer`。关闭时 Loader 不暂存素材、不生成图片 Markdown 引用，保留可读文字与图注；开启时按完整 `images/...` 相对路径（含可选 `./` 前缀和子目录）查找 ZIP 素材，展平文件名并在计算 `indexes` 前替换为最终 URL。

### 4.3 关键模块职责

| 模块 / 文件 | 负责 | 不负责 |
|---|---|---|
| `core/config/settings.py`、`initdb_config.yaml` | 新提供方配置校验、图片解析能力声明和默认禁用示例 | 不存明文 Key，不自动改全局提供方 |
| `knowledge/rag/base_file_pipeline.py` | 唯一 PDF/图片/OFD 委托 Loader 选择入口；传递 `retain_images`；为新提供方明确失败 | 不实现 V1 HTTP 协议 |
| `knowledge/rag/pipeline/loader/mineru_v4_client.py` | V1 上传、任务轮询、ZIP 下载、同源鉴权与阶段/总时限 | 不转换 Middle JSON，不把 Key 发给跨源地址 |
| `knowledge/rag/pipeline/loader/mineru_v4.py` | 安全读取 ZIP、Middle JSON 块到 Document/bbox/图片转换；图片流式写入平铺暂存目录 | 不写数据库或跨节点本地状态，不复用旧 `pdf_info` 转换 |
| `knowledge/rag/pipeline/loader/mineru.py` | 旧 MinerU 协议 | 不承载 4.0 分支 |
| `worker/knowledge/scheduler.py` | OCR 专用队列路由，包含 OFD | 不决定最终解析提供方 |
| `knowledge/domain/services/knowledge_service.py` 与 `pipeline/transformer/` | 保持现有预览缓存、图片/bbox 上传与入库流程 | 不新增第二条解析管线 |
| 平台 `controllers/API/index.ts`、客户端 `api/apps.ts` 及文件查看组件 | 让旧 MinerU 和 `mineru_v4` 都获取可用引用预览 URL | 不改变 UI 视觉样式 |

## 5. 已知坑与反直觉事实

| # | 事实 | 如果忽略会怎样 | 处理位置 |
|---|---|---|---|
| 1 | 旧 MinerU 是一次 multipart 请求，4.0 是有状态的 V1 上传与异步任务；自部署服务重启会丢资源索引 | 旧 URL 或重试策略会重复提交、无限轮询或拿不到产物 | `MineruV4Loader` 的阶段校验、总超时和结构化日志；不把 job ID 当持久续跑状态 |
| 2 | 官方上传 URL 可能跨源，下载可重定向；Bearer Key 只可发给同源 API/上传目标 | Key 随预签名 URL 泄露给对象存储 | V1 客户端按 scheme、host、有效端口比较同源，保留远端上传头，不跨源转发 Key；见[官方示例](https://mineru.atomgit.com/zh/usage/http_api.html) |
| 3 | `ImageUploadTransformer` 仅扫描平铺目录；`metadata.indexes` 与最终正文字符位置绑定 | ZIP 子目录图片不上传，后改 URL 会令引用定位偏移 | `MineruV4Loader` 展平安全文件名、先写最终引用再算 indexes |
| 4 | 预览缓存键不含提供方，正式入库仍运行当次 Loader，最后由缓存覆盖分块正文 | 切换窗口可能出现旧正文与当次 `parse_type`、bbox 或图片来源不同；正文以用户所见缓存为准，但不能声称所有产物严格同版 | `KnowledgeUtils.preview_cache_key_for_split_rule()`、`PreviewCacheTransformer`；本期接受此边界，验证链接可用 |
| 5 | `OfdLoader` 先转 PDF 后委托 PDF Loader，预览仍用转换后的 PDF；原队列只把 PDF/图片送 OCR 队列 | OFD 长任务占用普通队列，且误以为新 Loader 需直接接收 OFD | `OfdLoader`、`BaseFilePipeline._init_ofd_loader()`、`scheduler.needs_ocr_queue()`；本分支已修复路由 |
| 6 | 平台和客户端聊天引用只把 `etl4lm/un_etl4lm` 视作新版预览来源 | 旧 `mineru` 与新增 `mineru_v4` 的引用 `fileUrl` 为空 | 两端 API 映射和文件查看组件统一识别；修改 UI 前读 `src/frontend/packages/ui/docs/` |
| 7 | 现有预览任务运行在 API 后台任务中，状态为 Redis `processing`；刷新页面可重新发起任务 | 进程中断后旧任务 ID 不会恢复；本期不做任务持久化 | `knowledge/api/endpoints/knowledge.py` 与前端预览创建/轮询逻辑 |
| 8 | 旧请求中的 `enable_formula` 没有 V1 逐任务等价参数 | 若静默透传或假定关闭生效，用户会误判解析效果 | 新 Loader 不发送虚构参数；以 tier/样本说明效果，并在测试中覆盖旧选项的兼容行为 |
| 9 | 旧 Loader 的 `request_kwargs` 合入业务请求体，V1 则有上传、建任务等多个请求 | 误把配置展开为 `httpx` 参数、或注入上传/轮询，会让参数失效或改变鉴权与传输行为 | `MineruV4Conf` 和 `MineruV4Loader` 只在建任务 JSON 中浅合并，并拒绝与 `files/tier/ocr_mode/output_formats` 冲突 |
| 10 | ZIP 中图片可累计数百 MiB，且素材路径可嵌入 `./images/...` 或带子目录 | 全量读入内存会放大占用，平铺文件名碰撞或引用截断会导致错误链接或误报缺素材 | `MineruV4Loader` 限制成员及解压规模、逐块写图片、拒绝平铺碰撞、按完整相对路径替换引用 |
| 11 | `ImageUploadTransformer` 在 `retain_images=0` 时跳过上传 | Loader 若仍写最终 URL，预览和入库正文会留下从未上传的失效链接 | `BaseFilePipeline` 将开关传给新 Loader；Loader 同步省略图片暂存与引用，保留文字和图注 |
| 12 | 文件与预览的 bbox 标识按整数坐标生成，前端按分块坐标拼接标识；小数坐标会导致标识不匹配（116 真实文件已核验，离线回归覆盖 Loader → 分块 → bbox 上传） | 坐标存在但分段无法激活定位框 | `MineruV4Loader._bbox()` 统一产出整数坐标值，后续匹配逻辑不变；旧文件及预览缓存中的小数坐标需重新解析后更新；图片维持现有预览，不新增定位功能 |

## 6. 对外契约与依赖

### 6.1 我提供给别人的

| 契约 | 形式 | 消费方 |
|---|---|---|
| `mineru_v4` 解析来源 | 现有知识文件/引用响应的 `parse_type` 新枚举值 | API、平台和客户端预览、排查日志 |
| 正文、页码、定位、图片引用 | 既有 `Document` 元数据与 Loader 侧产物 | 分块、图片/bbox 上传、问答引用 |
| 文件预览和状态 | 既有 `/api/v1/knowledge/preview`、`/preview/status` 响应形态不变 | 知识库页面 |
| `BaseFilePipeline._build_pdf_loader()` | 内部 Python 接口增加显式新分支 | PDF、图片、OFD、预览和临时解析管线 |
| `knowledges.mineru_v4.request_kwargs` | DB 配置中的 JSON 映射；仅作为 V1 创建任务顶层附加字段 | 管理员配置、`MineruV4Conf`、`MineruV4Loader` |

### 6.2 我依赖别人的

| 依赖 | 形式 | 风险点 |
|---|---|---|
| MinerU 4.0 V1 服务 | HTTP、`/v1/health`、`/v1/tiers`、上传/任务/产物接口 | 部署可能不提供 ZIP 或目标 tier；实际能力必须验收 |
| Middle JSON 2.0 和 ZIP 素材 | 上游序列化协议 | 块类型、素材命名与可选字段可能随服务版本变动；需版本/样本夹具 |
| OFD 转 PDF | 现有 `OfdLoader` / easyofd 转换 | 转换失败或空 PDF 不能伪装为解析成功 |
| Redis 预览缓存与 DB 配置 | 现有服务 | 配置缓存约 100 秒；缓存命中可跨提供方，见 §5-4 |
| MinIO | 既有图片和预览对象存储 | 图片引用与实际上传对象必须对应；不能依赖 API/Worker 本地路径共享 |
| 平台/客户端文件查看 | 现有 `parse_type` 分支 | 漏掉新值会产生空预览 URL；旧 MinerU 也须补齐 |

## 7. 测试与可观测

- **协议单测**：离线 V1 响应、ZIP 夹具和协议到 Document 的集成测试覆盖上传秒传/普通上传、同源/跨源授权、成功与失败终态、超时、缺产物、非法路径、缺图片、Middle JSON 块形态和结构错误；`request_kwargs` 只进入建任务 JSON，非映射/不可序列化值及保留键冲突明确失败。补充覆盖 `retain_images=0`、缺素材及带子目录素材引用后，当前定向测试 44 项通过。旧 MinerU 的固定内网测试未作为本特性通过条件。
- **管线验证**：检查 PDF、图片、OFD 的正文、页号、bbox、表格/公式、图片链接、`metadata.indexes`、分块和失败终态；验证缓存命中沿用预览正文，以及专用队列开/关与 Loader 配置组合。OFD 路由的 13 个定向测试已在本分支通过。
- **环境验收**：在有目标服务的环境执行 `curl -fsS "$MINERU_V4_API_URL/v1/health"` 和 `/v1/tiers`，记录服务版本、可用 ZIP/tier；用脱敏的原生 PDF、扫描 PDF、图片、OFD 登录测试知识库，依次检查预览、入库终态、问答引用与 MinIO 素材；最后验证并发、长任务及服务重启。当前无目标服务，详见 [e2e-checklist.md](./e2e-checklist.md)，不能声称真实服务和页面已验收。
- **可观测**：记录提供方、阶段、耗时、job ID、终态、上游错误码、ZIP 校验及块/图片数量；不记录正文、Key 或预签名 URL。成功判据是知识文件最终状态及可用引用，不是上传/建任务 HTTP 200。

## 8. 后续改进与未投入事项

- 不做按知识库或租户的渐进开关；本版使用全局配置，执行前切换窗口的差异由用户接受。需要细粒度灰度时再定义选择优先级和配置归属。
- 不把提供方写入预览缓存键，也不保证跨提供方切换时 bbox、图片与缓存正文严格同版。若业务要求所有产物严格一致，需设计完整预览快照及素材转存，不能只改缓存键。
- 不持久恢复 MinerU 远端 job 或 API 预览后台任务；用户可重新发起预览，知识文件失败后可走现有重解析。
- 不扩展 Office/HTML/表格的解析范围，也不把模型推理运行时装入毕昇后端。
- 不承诺 `enable_formula=0` 能关闭 MinerU 4.0 的公式识别；上游 V1 没有该等价开关。若产品要求保留此操作语义，需另行确定 UI 呈现或上游能力支持方式。

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-13 | 初版设计草案：独立提供方、V1 ZIP、缓存/执行时语义、OFD 队列与旧版兼容 | 规格确认及技术方案评审决定 |
| 2026-10-13 | 明确 `request_kwargs` 的建任务请求体透传、保留键与验证边界 | 用户要求沿用其他 Loader 的配置扩展方式 |
| 2026-10-13 | 实施独立 V1 客户端、流式 ZIP 适配、提供方接线、OFD 队列与两端引用；记录 39 项离线测试及待验收清单 | 设计获用户确认，进入任务拆分与实施 |
| 2026-10-13 | 同步修复 `retain_images=0` 时的失效图片链接和子目录素材路径截断；定向测试增至 44 项 | MinerU 4.0 功能代码评审的两条反馈 |
