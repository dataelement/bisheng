# MinerU 4.0 独立提供方接入技术方案

- 日期：2026-10-12
- 状态：历史技术方案草案；当前实施设计以 `features/v3.0.0/076-mineru-v4/design.md` 为准。本文保留为讨论背景，其中缓存、队列和任务恢复边界已按后续用户决定更新到 SDD 文档
- 工作分支：`feat/mineru_4.0`，基线 `origin/feat/3.0.0` 的 `eb86a1017267753de76c5c661bb45d0e3178874a`
- 范围：毕昇的文档解析接入；MinerU 服务的部署和模型选型由部署环境负责

## 1. 结论与边界

新增 `mineru_v4` 提供方、`MineruV4Loader` 和独立配置块。保留现有 `mineru` 提供方及 `MineruLoader`，不通过 URL 探测或失败后自动切换协议。两个 Loader 都从 `BaseFilePipeline._build_pdf_loader()` 进入现有的 Load → Transform → Ingest 管线。

本方案覆盖 PDF、图片及当前先转 PDF 的 OFD；不把 Office、HTML、表格文件改走 MinerU 4.0，尽管 MinerU 4.0 本身支持更多格式。知识库文件解析、文件预览和临时解析共用同一选择逻辑。历史文件不批量重解析、不迁移已有 `parse_type` 或存储产物。解析失败时保留真实失败，不自动退回旧 MinerU 或本地 PDF Loader。

这是跨后端配置、解析协议和前端预览契约的功能，实施阶段按 `docs/SDD-Guide.md` 的完整 SDD 流程补齐并确认需求、设计与任务；本文先固定技术方向和待验证的上游产物契约。

## 2. 现状与升级原因

### 2.1 毕昇现状

| 环节 | 当前行为 | 代码位置 |
|---|---|---|
| 提供方选择 | `KnowledgeConf.loader_provider` 从 DB 中的 `initdb_config.knowledges` 读取；`_build_pdf_loader()` 选择 PDF Loader，图片和 OFD 复用此入口 | `core/config/settings.py`、`common/services/config_service.py`、`knowledge/rag/base_file_pipeline.py` |
| 旧 MinerU 请求 | 对配置中的完整 URL 执行一次 multipart `POST`，传 `return_content_list`、`return_middle_json`、`return_images` 等旧参数 | `knowledge/rag/pipeline/loader/mineru.py:MineruLoader.load` |
| 旧 MinerU 结果 | 从 `results[*].content_list`、`middle_json.pdf_info` 和 base64 `images` 生成 `Document`、页码、bbox 与图片引用 | `knowledge/rag/pipeline/loader/mineru.py` |
| 图片与版面 | Loader 暂存图片并先写最终引用，`ImageUploadTransformer` 上传；`ExtraFileTransformer` 写 bbox；`metadata.indexes` 必须对应替换图片引用后的正文 | `knowledge/rag/pipeline/loader/base.py`、`knowledge/rag/pipeline/transformer/` |
| 解析标识 | 持久文件记 `parse_type=mineru`；预览接口返回 Loader 类名 | `knowledge/domain/models/knowledge_file.py`、`knowledge/domain/services/knowledge_service.py` |

旧版测试 `test/knowledge/rag/test_mineru.py` 直接连一台固定服务和本机绝对路径，不能作为 4.0 协议或可重复回归的证明。

### 2.2 上游 4.0 契约

MinerU 4.0 自部署解析 API 以 `/v1` 为路径前缀，服务根地址不含 `/v1`。一次请求需要创建上传、上传字节、完成上传、创建解析任务、轮询终态，并按 `output_files` 的文件 ID 下载产物；旧 `/file_parse` 不再提供。任务状态包括 `queued`、`running`、`completed`、`partial`、`failed` 和 `canceled`。V1 ZIP 包含结构化结果及图片素材；单独的 Middle JSON 不保证携带图片字节。新版 Middle JSON 以序列化字段 `schema=docvortex.middle`、`schema_version=2.0` 标识，页面使用 `pages[].blocks[]`，不能按旧 `pdf_info` 读取。

以上依据：[4.0 迁移指南](https://mineru.atomgit.com/zh/reference/migration_4.html)、[V1 HTTP API 与经过测试的脚本](https://mineru.atomgit.com/zh/usage/http_api.html)、[输出格式与结果协议](https://mineru.atomgit.com/zh/reference/output_files.html)。实现前须以目标服务的 `/v1/health`、`/v1/tiers` 和实际 ZIP 样本核对，因为部署可用档位和输出格式以服务声明为准。

## 3. 关键决策

### D1：以独立提供方隔离协议

- **选定**：`loader_provider=mineru_v4`，新增 `MineruV4Conf` 与 `MineruV4Loader`；旧 `mineru` 配置、类和行为不改。
- **原因**：旧配置的 `url` 是完整 `/file_parse` 地址，4.0 的 `api_url` 是服务根地址；请求、状态、产物和 JSON 结构也各不相同。独立提供方使回滚只需切回原配置，且便于核对实际解析版本。
- **不采用**：在旧 `mineru` 中增加 `api_version` 并把两种协议放进同一个 `load()`；不按健康检查或 HTTP 错误自动判断版本。
- **重新考虑条件**：若未来多个 MinerU 版本共享了经官方承诺的同一解析 API，再提取公共客户端接口，不预先抽象两种不同协议。

### D2：继续调用独立 MinerU 服务，使用毕昇已有 HTTP 依赖

- **选定**：在毕昇内实现薄 V1 HTTP 客户端，由 `MineruV4Loader` 负责调用；使用项目已有的 `httpx`，不在毕昇 API/Celery 环境安装 MinerU 推理包。
- **原因**：现有接入就是服务间调用。4.0 Python SDK 的 `MinerUApiParser` 可以完成上传、轮询与下载，但引入 `mineru` 包会把解析运行时依赖和硬件组合带进毕昇后端；独立服务的镜像与模型版本应由 MinerU 部署维护。[Python SDK 文档](https://mineru.atomgit.com/zh/usage/sdk_api.html)
- **不采用**：直接在毕昇 Worker 内运行 4.0 模型、调用 CLI，或把 VLM 的 OpenAI 兼容地址当作文档解析 API。
- **重新考虑条件**：若官方提供轻量、独立的 V1 客户端包并满足毕昇依赖与许可要求，可改用官方客户端以减少协议维护。

### D3：只接受可完整消费的 ZIP 结果

- **选定**：新提供方要求服务支持 `zip`，创建任务时请求 `output_formats=["zip"]`；从 ZIP 读取当前 Middle JSON、Markdown 与实际引用的 `images/` 素材。能力缺失、产物缺失或协议身份不符均报解析失败。
- **原因**：BiSheng 需要正文、页码、bbox 与图片字节同时成立。仅下载 Markdown 无法可靠建立块到 bbox 的映射；仅下载 Middle JSON 无法保证图片素材可用。[输出协议](https://mineru.atomgit.com/zh/reference/output_files.html)
- **不采用**：把 4.0 JSON 当成旧 `pdf_info`、从文件名猜图片路径、在缺素材时生成正常样式的失效图片链接。
- **重新考虑条件**：若目标服务提供同等完整且有明确版本约束的非 ZIP 产物，再评估精简下载。

## 4. 配置与选择

新增的配置位于现有 DB 配置的 `knowledges` 节点，不向启动 `config.yaml` 增加顶层键：

```yaml
knowledges:
  loader_provider: "mineru_v4"  # 切换时显式修改；默认仍为 etl4lm
  mineru_v4:
    api_url: "http://mineru-v4.example:8000"  # /v1 之前的根地址
    api_key_env: "MINERU_V4_API_KEY"           # 只存环境变量名；匿名内网服务可留空
    tier: "standard"                          # 上线时按目标硬件显式选择
    ocr_mode: "auto"
    connect_timeout_seconds: 10
    request_timeout_seconds: 60
    transfer_timeout_seconds: 300
    job_timeout_seconds: 1800
    poll_interval_seconds: 3
```

`api_url`、`tier`、各超时和轮询间隔应有类型与范围校验。`api_key_env` 只表示密钥所在环境变量名，API 进程和知识 Celery Worker 都需要能读取该变量；若配置了变量名但运行时未设置，立即报配置错误。不要把明文 Key 写入仓库、DB 系统配置或日志。`MineruV4Conf` 字段默认值应使旧 DB 配置无需新增节点也能被读取，但选择 `mineru_v4` 后，空 `api_url` 或不可用档位必须明确失败，不能悄悄退到 `LocalPdfLoader`。

`initdb_config.yaml` 中加入默认禁用的 `mineru_v4` 示例块。既有安装由 `ConfigService.merge_missing_config()` 向 `knowledges` 补入缺失的子块，不覆盖旧值；实际切换需更新 DB 配置中的 `loader_provider`。读取路径有约 100 秒 Redis 缓存，部署验证必须确认最终生效值。`KnowledgeConf.image_parser_enabled` 增加 `mineru_v4` 判断；`_build_pdf_loader()` 增加一条显式分支。旧 `mineru` 节点和默认提供方不变。

## 5. V1 请求生命周期

```text
本地输入文件
  → GET /v1/health、GET /v1/tiers：核对 zip、来源和配置的 tier
  → POST /v1/uploads：文件名、长度、MIME、SHA-256、purpose=parse
  → pending 时按返回的 method / URL / headers 上传字节，再 complete
    completed 时使用服务返回的 file_id，跳过字节上传
  → POST /v1/parse/jobs：file_id、tier、ocr_mode、output_formats=[zip]
  → GET /v1/parse/jobs/{job_id}：有界轮询至终态
  → GET /v1/files/{output_file_id}/content：下载 ZIP
  → 校验、转换为 BiSheng Document / bbox_list / local_image_dir
```

每个文件只提交一个 parse job。PDF 默认全页，不传默认前 10 页的文档库 CLI 语义；文件规则 `force_ocr=1` 时将单次任务的 `ocr_mode` 设为 `ocr`，否则使用提供方配置的 `ocr_mode`。图片和 OFD→PDF 沿用 `_build_pdf_loader()` 的现有路由，OFD 预览仍由 `OfdLoader` 保留转换后的 PDF。

状态与重试规则：

1. 校验每一步的 HTTP 状态和 JSON 结构，`upload_id`、`file_id`、`job_id`、终态文件及 ZIP 产物 ID 必须非空；HTTP 200 本身不是成功。
2. 单文件任务只有 `completed` 且对应文件 `completed`、ZIP 完整下载并通过校验才成功。`partial`、`failed`、`canceled`、缺失产物均失败，记录上游结构化错误码；不把 `partial` 的正文写成成功文件。
3. 分开连接、普通请求、传输与整个任务等待上限。读超时或轮询预算耗尽时记录 job ID 和阶段；不假定远端任务已取消。`POST /v1/parse/jobs` 响应不明时不自动重发，以免产生重复任务。
4. 服务返回的上传 URL 可能是同源路径，也可能是跨源预签名地址。保留 `upload_headers`；只对同源上传发送 MinerU Bearer Key，跨源上传及下载重定向不转发 Key。日志不打印 Key 或预签名 URL。[HTTP API 安全规则](https://mineru.atomgit.com/zh/usage/http_api.html)
5. 自部署 V1 服务的上传/文件/任务索引在进程内，服务重启后旧 ID 不保证可恢复。毕昇不把远端 job ID 当作持久状态；失败后由现有文件重解析操作发起新任务，不承诺断点续跑。[部署边界](https://mineru.atomgit.com/zh/usage/http_api.html)

## 6. 结果到毕昇的映射

`MineruV4Loader` 只接受识别出的当前 Middle JSON 协议身份，按源 `pages[].page_idx` 与块顺序转换。不能复用旧 Loader 的 `merge_pdf_info()` 或 `merge_conten_list()`。具体文本、标题、公式、表格和图片块的转换函数须用目标 4.0 ZIP 样本固化；文档中的简化 JSON 示例不足以证明所有块形态。

| 上游数据 | BiSheng 产物 | 约束 |
|---|---|---|
| 页面及语义块 | 单个 `Document.page_content`，`metadata.pages/types/bboxes/indexes` | 保持上游块顺序与原始零基 `page_idx`；`indexes` 以最终正文计算 |
| 有效四坐标 bbox | `loader.bbox_list` 的 `TextBbox` | 缺失或不合法 bbox 不伪造；正文仍可保留，记录无定位块数 |
| 表格、公式与标题 | 可读 Markdown 文本 | 以真实 ZIP 样本核对渲染，不能把复杂块静默丢弃 |
| ZIP 中实际引用的图片 | `loader.local_image_dir` 中的平铺文件及正文最终链接 | 对 ZIP 路径做安全校验、防重复覆盖；先写最终链接再计算 `indexes` |

`ImageUploadTransformer` 只扫描平铺目录，因此 ZIP 的 `images/...` 路径要安全地映射到文档内唯一文件名，并同步替换正文引用。`retain_images=0` 时正文不能留下未上传的本地路径；`retain_images=1` 且引用的素材缺失时解析失败。页眉页脚过滤在计算 `indexes` 前对规范化块进行；bbox 为空的块不得进入当前 `ExtraFileTransformer` 的四坐标键生成。全文为空则保留现有 `KnowledgeFileEmptyError` 语义。

这些适配均在 Loader 中完成，已有摘要、分块、图片上传、bbox 上传与向量写入管线不另建分支。临时解析的本地图片只在当前任务的临时目录使用，不作为跨 API/Worker 节点的持久共享状态；遵循 `docs/constitution.md` C8。

## 7. 兼容与前端消费

- **旧部署**：`loader_provider=mineru` 时仍用旧 URL、旧参数及旧解析逻辑；升级毕昇镜像不会自动切换到 V1。MinerU 官方对部分 AMD/国产加速卡仍要求 `<4` 的旧平台适配，保留旧提供方有实际部署价值。[旧平台适配](https://mineru.atomgit.com/zh/usage/compatibility.html)
- **历史文件**：原 `parse_type=mineru` 和毕昇已保存的正文、图片、bbox 不做迁移。显式重解析时才按当时的当前提供方生成新结果；切回旧提供方也不改写历史文件。
- **新文件**：`ParseType` 新增 `MINERU_V4="mineru_v4"`，明确保存来源；文件分享和预览逻辑需将该值视为外部解析提供方，核对 preview URL、bbox 和图片链接。
- **聊天引用预览**：平台 `src/frontend/platform/src/controllers/API/index.ts` 与客户端 `src/frontend/client/src/api/apps.ts` 当前仅将 `etl4lm/un_etl4lm` 映射到新版预览 URL，`mineru` 本身也未覆盖。新增 `mineru_v4` 时应在同一处把 `mineru` 和 `mineru_v4` 一并纳入“有外部解析预览”的判断，避免解析成功但引用列表的 `fileUrl` 为空；对应文件查看组件也要使用一致的判断。这里只改消费条件，不改变视觉样式；正式 UI 修改前遵循 `src/frontend/packages/ui/docs/` 的设计规范。

## 8. 交付步骤与验证

1. **协议样本**：在目标 4.0 服务和硬件上记录版本、`/v1/health`、`/v1/tiers`；取得原生 PDF、扫描 PDF、图片及带表格/公式/多图的 ZIP 样本，确认 `zip`、bbox、素材和目标 tier。样本脱敏后成为测试夹具。
2. **后端实现**：新增独立配置、V1 客户端及 Loader；在唯一 PDF 选择入口接线；扩展 `ParseType` 与图片能力判断；保持旧 Loader 的输入输出测试不变。
3. **消费端修复**：核对知识文件分享、预览接口、平台与客户端聊天引用的 `parse_type` 分支，使旧版和 4.0 文件都能取得可用预览地址。
4. **可重复测试**：模拟上传命中/未命中、同源/跨源凭据、成功/四种终态、结构错误、任务超时、下载失败、恶意 ZIP 路径与缺失图片；对 PDF/OFD/图片校验正文、页码、bbox、最终图片引用、`metadata.indexes` 和分块结果。将原依赖固定内网服务的旧测试改为可重复的协议测试，真实服务测试单独运行。
5. **环境验收**：先在独立 MinerU 4.0 环境以显式 `mineru_v4` 配置解析上述样本，核对知识库文件终态、预览、问答引用与 MinIO 图片；再扩大到目标硬件上的并发、长任务、重启场景。回滚时显式切回原 `loader_provider`，不回滚历史文件数据。

观测日志至少包含 provider、阶段、耗时、job ID、终态、上游错误码、ZIP 校验结果和产出块/图片数，不包含文档正文、Key 或带签名的 URL。验收同时核对任务是否真正到终态，不能只看接口返回或文件入队。

## 9. 待确认的实现输入

| 项目 | 为什么需要 | 建议默认处理 |
|---|---|---|
| 目标 MinerU 4.0 具体版本、服务镜像和硬件 | 决定 tier、模型准备和产物实际形态 | 先在隔离服务抓真实样本，不依据旧模型目录推断 |
| 自部署 V1 API 的鉴权和网络拓扑 | 决定 Key 注入、上传 URL 与重定向策略 | 用环境变量注入 Key；校验同源边界 |
| 质量档位与任务最长等待时间 | 直接影响解析质量、Worker 占用和预览等待 | 部署时显式配置 `tier`，按样本耗时确定 job 超时 |
| 是否需要对历史文件统一重解析 | 会引入额外任务量与结果差异 | 本方案不做；如需要单独定义迁移计划 |

## 参考

- [MinerU 4.0 主页](https://mineru.atomgit.com/zh/index.html)
- [从 3.x 迁移到 4.0](https://mineru.atomgit.com/zh/reference/migration_4.html)
- [V1 HTTP API 完整示例](https://mineru.atomgit.com/zh/usage/http_api.html)
- [Python SDK](https://mineru.atomgit.com/zh/usage/sdk_api.html)
- [输出格式与结果协议](https://mineru.atomgit.com/zh/reference/output_files.html)
- [旧平台适配](https://mineru.atomgit.com/zh/usage/compatibility.html)
