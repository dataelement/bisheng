# Design: 通用图像生成工具

**关联**：[spec.md](./spec.md) · [tasks.md](./tasks.md)
**状态**：按用户最新要求简化，用户已确认；实施与验证状态见 tasks.md。
**版本**：v3.1.0-beta1，F018。
**更新**：2026-11-09。

## 1. 目标与范围

一套 OpenAI Images 兼容调用，通过修改 API 地址、Key 和模型切换服务。去掉 Azure 协议，保留旧 `dalle_image_generator` 引用及 `query` 输入，支持 URL/Base64 图片结果。

## 2. 约束与参考

遵循 [constitution.md](../../../docs/constitution.md) C1–C8 和 [发布契约](../release-contract.md)。复用现有配置、权限、脱敏和对象存储；不新增表、路由或 provider 框架。

已读取参考仓库 `/Users/alex/Documents/Code/dataelem/dsh-desktop/packages/dsh-image-generation/`：`lib/provider.js` 集中处理地址规范化、`/images/generations` 请求、响应限量和安全错误；`index.js` 在调用时读取当前配置，随后保存图片。借鉴这条调用链及处理方式，不复制其模型目录、在线连接探测、凭据 profiles、本地资产提交及预览服务。

DSH 当前生成函数只接收第一张 Base64 图片并保存到本地工作区；毕昇沿用已确认需求，接收 URL/Base64 和多张图片，通过平台存储交付 Base64 图片。

## 3. 关键取舍

| 选择 | 原因与未采用方案 | 重新考虑条件 |
|---|---|---|
| 一个运行模块，直接发 HTTP 请求 | 沿用 DSH 的统一 Images 请求方式；已有 httpx 足够，无须继续继承 DALL-E wrapper 或引入 provider 基类。 | 真正需要另一种协议或异步任务时。 |
| 地址、Key、模型就是服务配置 | 只有一种协议，无须 provider 下拉、适配器注册表或多份 profile；换服务即换这三个值。 | 需要同时保存多家服务配置时。 |
| 复用既有存储 | URL 直接返回，Base64 上传 MinIO；不复制 DSH 本地工作区、资产 hash 和预览链路。 | 平台统一生成附件生命周期时。 |

## 4. 实现方式

### 当前实现

- `gpts/load_tools.py` 为新旧工具键注册同一 Images 工厂；model、上传回调及旧协议识别字段均登记为可选参数。历史默认 `dall-e-3` 仅用于兼容。
- `ImageGeneration.tsx` 替换 `image_generation.tsx`，提供地址、Key、模型和代理；ToolSet 按新旧工具键分发，名称翻译保留旧键。
- `ToolServices.update_tool_config` 复用 Key 掩码合并后规范化图像配置，无效配置使用工具错误码 15033；ToolExecutor 每次图像调用先走现有执行权限检查，再创建局部实例。
- MinIO 已支持 bytes 上传和签名链接；上传时需要调用方使用既有租户前缀能力，不会自动补前缀。

### 配置与请求

沿用 `openai_api_base`、`openai_api_key` 和历史可选 `openai_proxy`，增加 `model`。前端表单只展示地址、Key、模型及原代理设置，不再展示 Azure/provider 选择。

参考 DSH 接受 Base URL 或完整 `/images/generations` 地址：去掉重复后缀和末尾斜杠，再追加一次 `/images/generations`。允许 HTTP(S)，必须有 host，拒绝 userinfo、query、fragment。Key 与模型必填；历史 OpenAI 配置缺模型时保留 `dall-e-3` 默认值，缺地址时保留 OpenAI 默认地址。保存不调用上游，不产生图片费用。

服务端继续用 JsonFieldMasker 保留合法的已存 Key，随后校验地址/模型。改地址 host 时要求重新录入 Key；只改模型可保留。新配置按白名单保存，Azure 字段不写入。若历史配置声明 Azure 或有有效 Azure endpoint，则明确拒绝生成并提示改成 OpenAI 兼容配置，不静默改用其他地址。旧记录在成功重新配置前保持原样。

生成流程：读取已授权的当前配置副本 → POST（Bearer Key，JSON `{model, prompt: query}`）→ 校验 `data[]` → 返回图片链接。同步使用 httpx 流式请求，异步通过 `asyncio.to_thread` 复用同一实现。只发送基本参数，不照搬 DSH 中特定模型的 size/quality/output_format/watermark 参数，不做模型目录或硬编码模型白名单。

每次图像调用在现有 ToolExecutor 入口重新读取工具和分类，完成 tool/use 检查后用已有工厂创建本次调用的局部实例；不回写共享实例，不引入后台刷新或配置缓存。正在执行的请求保留自己的配置快照。独立包调用者使用其传入配置。

### 结果与存储

有效 HTTP(S) `url` 直接输出，不额外下载。`b64_json` 严格解码并用已有 Pillow 校验 PNG/JPEG/WebP，随后通过注入的简单上传函数 `upload_image(bytes, content_type) -> str` 使用平台存储；运行包不导入 `bisheng`。

上传函数放在现有 executor 模块，绑定当前调用用户和租户，复用 `TenantDao.get_by_id`、`get_minio_prefix`、`build_chat_object_name`、`put_object_sync`。配置 `open_api.public_base_url` 时，将该对外平台地址与 `get_share_link_sync()` 的签名相对路径拼接；保留签名查询串及内部签名 host，由既有前端 Nginx 代理访问 MinIO。未配置平台对外地址时使用 `get_share_link_sync(clear_host=False)`，此时运维必须确保 MinIO sharepoint 可被调用方访问。不返回相对路径，也不从未经信任的请求 Host 推断持久链接。不新建存储服务或 bucket。签名沿用平台默认 7 天，不承诺历史链接永久有效。

每张图片输出一条 `![image N](URL)`，按上游顺序保留。空结果或无效图片明确失败，不返回 Base64 文本。先校验全部图片再上传；存储失败不返回成功，已上传的孤立文件本期不新增清理任务。

参考 DSH 使用 180 秒调用超时、单张图片 20 MiB 限制；响应流在解析前限量，单次响应上限 64 MiB，超限整次失败而非截断。请求不自动重发，不切换返回格式。错误保留 HTTP 状态、安全格式的错误码及 request ID，不转发原始响应或异常文本。

### 代码边界

- 运行逻辑集中到新 `gpts/tools/image_generation/tool.py`，替换旧 DALL-E 工具和 Azure wrapper；新旧工具键共用同一工厂。旧键保留原调用名，新键使用 `image_generation`。
- 现有 load_tools、ToolServices、ToolExecutor 只增加必要接入；模型列表/详情继续用既有 JsonFieldMasker，包括历史图像子项 extra 的脱敏。配置无效复用工具模块错误机制，不新增错误体系。
- `image_generation.tsx` 改名为 `ImageGeneration.tsx`，现有 ToolSet 和工具列表按新旧 tool_key 识别。原应用无需重新添加工具；保存失败保留草稿。
- 新安装种子使用新键，现有 DB ID/旧键不迁移；新旧翻译键都显示“图像生成”。修改共享 locale 源文件后构建产物，不逐份手工维护。

## 5. 已知坑

| 事实 | 后果与处理 |
|---|---|
| 旧 Azure Key 不能当 OpenAI Key 自动使用 | 检测旧 Azure 配置并要求重新配置，避免误发。 |
| 工厂会过滤未声明参数 | model 和上传函数必须登记；用实际加载链路测试。 |
| 直接改底层工具名会改变历史调用名 | 旧键只作别名加载，保留名称；不另建一份实现。 |
| MinIO sharepoint 可能是容器内部地址，而相对路径仅在浏览器同源可用 | 对外 API 图片需完整 URL；设置平台 public_base_url，经前端代理下载并保留存储签名。 |
| DSH 写本地文件，毕昇可能多节点运行 | 只参考协议处理，图片交付复用 MinIO。 |

## 6. 对外契约与依赖

保留现有配置 HTTP API，工具输入 `{query: string}`，输出 Markdown 图片文本；新增 `image_generation`，保留 `dalle_image_generator` 别名。依赖现有 httpx、Pillow、MinIO、租户上下文及工具权限，无新中间件或二进制依赖。

新模型配置不保证旧 DALL-E 代码能运行；部署时 API/Worker 使用同一代码版本，回滚前恢复兼容旧模型的配置。归属 v3.1.0-beta1 / F018。

## 7. 验证

所有新增后端核心场景放在 `test/tool/test_image_generation.py`：更换地址和模型、旧键及默认值、旧 Azure 拒绝、保存/掩码保留、URL/Base64 与失败、当前调用读取新配置和权限/租户隔离。使用本地 HTTP 上游和假存储验证完整调用链，不逐个测试私有函数。

前端更新现有 sharedSelection 引用，运行全量 lint/typecheck、i18n 检查；按既有 `/e2e-test` 执行接口场景和页面检查。人工在 `/build/tools` 配置 → 保存重开 → 原应用生成 → 切换服务/模型后再次生成；无权账号检查拒绝。真实上游及 MinIO 未验证时明确记录，不以 mock 通过代替验收。沿用 ToolExecutor 遥测，不新增监控系统。

## 8. 后续边界

本次不做 Azure、其他原生协议、多 provider 配置管理、自动获取模型、连接探测、生成资产管理和链接续期。需要时再按具体需求扩展。

## 修订历史

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-09 | 去掉 Azure，参考 DSH 收敛为单一兼容协议 | 用户要求避免过度设计。 |
| 2026-11-09 | 完成单模块实现、现有平台接入及本地验证 | 同步实际代码和验证边界，见 verification-local.md。 |

| 2026-11-11 | 生成图片使用完整对外下载地址，复用 public_base_url 与签名代理路径 | 修复相对图片链接在独立 API 调用方无法下载的问题。 |
