# Feature: MCP 知识空间九工具

- Feature ID: `078-mcp-knowledge-tools`
- Status: `IMPLEMENTED_LOCAL`
- Confirmed: `2026-10-16`，用户：“确认，按调整后的限制开始实施图片中的九个 MCP 工具。”
- Created: `2026-10-16`
- 所属版本：`v2.5.0-sg`
- 关联 PRD：[本次截图需求与确认记录](spec-discovery.md)；继承 [首钢版本契约](../release-contract.md) 与 [基础版本契约](../../v2.5.0/release-contract.md)。

## 1. 目标与边界

外部 MCP 客户端能够发现有权访问的知识空间、浏览目录和文件、搜索和读取内容、取得有权访问的来源入口，并把生成文本或本地文件保存到指定知识空间/目录。

用户已确认只覆盖知识空间（`KnowledgeTypeEnum.SPACE=3`），上传采用 Base64。包括公共、部门、团队、科室和已有个人空间；“我的收藏”等特殊空间仅暴露其现有能力，不因 MCP 获得上传权。

新增截图中的九工具，保留 `search_knowledge`。新工具不支持传统文档库或 QA 库；旧 `search_knowledge` 的范围和参数兼容性保留。保留 `/mcp`、`/mcp/`、默认开启、现有 MCP 跨域策略与可选关闭开关。

不增加创建空间/目录、删除、覆盖、版本替换、发布、分享、外部身份代理、URL 拉取、任意服务器路径读取、网页转存、模型答案或新管理页面。

## 2. 认证和协议

继续使用 `X-Developer-Token`，2026-10-16 用户确认与通用 Token 路由语义统一：未配置或空白名单不启用路由过滤，非空时必须匹配 `/mcp` 及当前方法。绑定用户决定所有资源权限和租户。所有新工具禁止 `external_id`、`user_id`、`tenant_id`、`skip_approval`、`file_path` 等未声明参数。

`tools/list` 最终返回十个名称。读工具标记 `readOnlyHint=true`；`create_document`、`upload_file` 为 `readOnlyHint=false`，且不提供覆盖行为。工具注解只向客户端描述行为，不能替代服务端授权。

现有 Token 白名单只区分 HTTP 路由，不区分工具。发布本功能后，已有 `/mcp` Token 的绑定用户若有上传权，即可写入有权位置。此能力扩展是本次规格确认的一部分，不额外引入默认必填配置。

使用 MCP 原生 `CallToolResult` 和结构化业务结果，不套 REST 的 `UnifiedResponseModel`。空结果为正常成功；参数、资源拒绝和下游失败为 `isError=true`，不返回原始异常、无权资源信息或签名链接到日志。

## 3. 公共参数与结果

- 新工具统一使用 `knowledge_id` 表示空间 ID。`folder_id` 兼容正整数和纯 ASCII 数字的正数字符串，进入业务逻辑前转为整数；允许前导零。顶层 `folder_id=null` 或省略表示根目录，嵌套 `folder_scope.folder_id` 必填且非空。其他资源 ID 仍为严格正整数；拒绝布尔值、空字符串、非数字和非正数。
- 列表与搜索：`page_size` 默认 20、范围 1～100；使用 `cursor`。结果含 `data`、`page_size`、`has_more`、`next_cursor`，不返回未经权限过滤的总数。
- 游标绑定用户、租户、工具、空间/目录、过滤和排序；条件不匹配或失效明确报错。
- 文件列表排序限定 `file_name`、`update_time`，`order` 为 `asc` / `desc`，默认 `update_time desc`；同值以 ID 保持稳定。
- 状态使用现有枚举：1 处理中、2 成功、3 失败、4 重建中、5 排队、6 超时、7 内容违规。筛选不能让调用者看到原本无权查看的状态或文件。
- 列表默认只返回当前活动入口和当前主版本。返回字段采用明确白名单，不直接序列化完整 ORM 对象、存储 object_name、内部错误详情或其他入口的管理信息。

## 4. 工具契约

| 名称 | 主要输入（除公共分页参数外） | 主要输出及行为 |
|---|---|---|
| `list_knowledge` | `name?`、`writable_only=false` | 空间 `id/name/space_level/description`，`can_upload_to_root`、`has_writable_folders`；可写筛选包含根可写或至少一个可访问目录可写的空间 |
| `list_folders` | `knowledge_id`、`folder_id?` | 当前层目录 `id/name/parent_id/path_ids/path_names/can_upload`；不一次展开全树，路径只包含有权展示的层级 |
| `list_files` | `knowledge_id`、`folder_id?`、`statuses?`、`sort_by?`、`order?` | 当前目录直接子文件 `id/name/size/status/update_time/parent_id` 和安全的版本标识；不混入文件夹 |
| `search_files` | `keyword`、`knowledge_ids?`、`folder_scope?`、`search_mode=all` | `search_mode=name/content/all`，返回匹配文件、空间和有权路径；`folder_scope={knowledge_id,folder_id}` 为该目录及子目录；无显式空间时仅搜索可读空间 |
| `get_file_detail` | `knowledge_id`、`file_id`、`include_content=true`、`content_format=text`、`max_chars=20000`、`cursor?` | 安全文件元数据、解析状态、正文页、实际内容格式、内容版本及下一游标；`max_chars` 为 1～50000；未解析完成时正文为空且 `content_ready=false` |
| `get_file_source` | `knowledge_id`、`file_id`、`source_type=auto` | `source_type=auto/preview/original`，返回有权签发的 `preview_url` / `original_url` 及失效时间（可计算时）；原件不可用时返回安全原因，显式 original 请求被拒绝时为工具错误 |
| `retrieve_chunks` | `query`、`knowledge_base_ids`、`top_k=5`、`max_content=15000`、`filters?` | 沿用现有 `RetrieveResp={chunks,total}`；query 1～2000 字符、1～20 个空间、top_k 1～50、max_content 1～15000；不生成答案 |
| `create_document` | `knowledge_id`、`folder_id?`、`file_name`、`content`、`content_format=markdown`、可选分类/业务域/标签 | UTF-8 文本保存为 `.txt` 或 `.md`，返回写入结果；不自动建目录、改名或覆盖 |
| `upload_file` | `knowledge_id`、`folder_id?`、`file_name`、`content_base64`、可选分类/业务域/标签 | 严格 Base64 解码并使用知识空间现有上传链路；返回同一写入结果；不接受 URL、data URL 或服务端文件路径 |

补充约束：

1. 搜索关键词去除首尾空白后为 1～200 字符，显式空间范围最多 20 个；`folder_scope.knowledge_id` 必须在显式空间集合中。存在目录范围时只搜索该空间子树，不把多空间集合拼成含糊的目录约束。显式请求无权空间或跨空间目录时失败，不扩大或悄悄替换范围。
2. `search_files` 返回文件检索结果，不返回 RAG 片段；匹配文件名和正文并集在权限检查后按入口 ID 去重。同一 canonical 文档在不同有权空间的入口可分别保留，供客户端选择位置。
3. 正文读取先验证入口，再确定当前 canonical 文档、版本和内容代次；后续分页中内容已变化时拒绝旧游标，要求重新读取。不能因无正文而去掉空间/代次过滤。
4. `content_format` 为 `text/markdown`；若没有原生 Markdown，只能返回真实可用文本并标明实际格式，不能声称无损还原文档排版。
5. `get_file_source` 的 `auto` 优先预览。原件必须通过下载权限、入口限制和 Owner 当前下载政策；只有预览权不能签发原件。若当前政策仅允许水印 PDF，返回预览及 `original_unavailable_reason`，不新增原件例外或匿名下载通道。预览来源复用现有 Owner：原生文本、PDF、图片可使用页面已授权的原生预览地址；Office 缺少预览时不回退原件。`original_url` 保持为空，显式 original 仍拒绝。
6. 新 `retrieve_chunks` 在调用共享检索前验证全部目标均为有权知识空间。旧 `search_knowledge` 不改变；两者共享检索核心，不复制检索算法。
7. 分类/标签参数使用现有语义：`file_category_code`、`file_subcategory_code`、`business_domain_code`、`manual_tag_ids`、`manual_tag_names`；不从文件名或模型输出猜测分类，不改变标签审核和业务域校验规则。
8. `search_files` 排序固定为 `update_time desc, id desc`；排序针对最终去重后的文件入口，不把分块相关度当文件列表排序。`statuses` 只属于 `list_files`，搜索结果仅包含可读的当前成功文件。`get_file_detail` 的 `cursor` 为正文续页游标，不与列表游标混用。

### 写入结果与限制

成功写入结果至少包含 `file_id`、`knowledge_id`、`folder_id`、`file_name`、`status`、`accepted`、`content_ready`。仅在文件创建及解析投递已确认后返回 `accepted=true`；状态沿用实际结果，不固定写成成功。客户端通过 `get_file_detail` 或 `list_files` 查询后续结果。

文件名为 1～200 字符的文件基名，禁止路径分隔符、路径穿越和控制字符。`create_document` 非空正文最多 10 MiB UTF-8，格式与后缀必须一致。`upload_file` 非空解码文件最多 50 MiB；扩展名复用 `upload_extensions.py`。文件大小上限对齐当前普通文档上传的源码默认值；实际限制仍取 MCP 上限与现有上传规则、租户/角色配额中的较严格约束，不自动提高系统配置。

对 MCP HTTP 实际请求体设置 80 MiB 上限，在 SDK 解析完整 JSON 前执行；不能仅信任 `Content-Length`。50 MiB 文件转成 Base64 约为 66.7 MiB；10 MiB 文本在 JSON 中使用字符转义时也可能放大，均须给协议和元数据留出空间。传输超限返回 HTTP 413，工具内 Base64 不合法/解码超限为输入错误。Base64 只作字节传输，客户端声明不等于可信文件类型。

目标位置必须已存在且允许上传；写入前与提交时校验资源归属、`upload_file_to_space` / `upload_file_to_folder` 以及配额。根目录可写和子目录可写独立判断，不通过 FGA 原始 relation 猜测业务上传权。

沿用知识领域去重规则，同名或同内容冲突不得覆盖旧文件，也不能把已有文件 ID 伪装成新上传成功。冲突响应不披露无权旧文件。第一版不承诺跨网络故障的 exactly-once 写入；超时/断连后的不确定结果必须先查询确认，服务端不能自动重放写请求。

取消、失败的清理以副作用阶段为界：尚未写入的临时文件必须释放；已确认入队的文件不能因连接断开被删除；投递结果不确定时不得伪称已经回滚，应留下可定位的文件/任务审计信息。沿用 Owner 清理及失败恢复边界。

### 调用示例

```json
{"name":"create_document","arguments":{"knowledge_id":118,"folder_id":305,"file_name":"会议纪要.md","content_format":"markdown","content":"# 会议纪要\n\n待办事项。"}}
```

```json
{"name":"upload_file","arguments":{"knowledge_id":118,"file_name":"hello.txt","content_base64":"aGVsbG8="}}
```

这里是 `tools/call` 的 params 示例；HTTP 地址仍为 `/mcp`，Token 放在请求头。

写入受理后的 `structuredContent` 示例（状态 5 表示排队，不代表解析成功）：

```json
{"file_id":901,"knowledge_id":118,"folder_id":305,"file_name":"会议纪要.md","status":5,"accepted":true,"content_ready":false}
```

列表空结果的 `structuredContent` 示例：

```json
{"data":[],"page_size":20,"has_more":false,"next_cursor":null}
```

## 5. 失败契约

| 类别 | 既有业务码或协议结果 | 关联验收 |
|---|---|---|
| 缺失/无效/禁用 Token | HTTP 401；19801～19803 | AC-01 |
| IP/路由拒绝 | HTTP 403；19804 / 19812 | AC-01 |
| 限流/限流不可用 | HTTP 429 / 503；19805 / 19806 | AC-01 |
| 无空间/目录/文件 | 内部复用 18000 / 18010 / 18020；对外固定安全错误，不透露无权对象是否存在 | AC-04、AC-07、AC-17 |
| 无资源权限/原件下载被拒绝 | 内部复用 18040 / 18097；`isError=true` | AC-09、AC-17 |
| 重名/同内容冲突、配额超限 | 复用 18021 / 18023 / 18024 及现有配额错误；`isError=true`，不得写成功 | AC-14 |
| 文件类型不支持 | 复用 10914；`isError=true` | AC-13 |
| 游标无效/内容已变化 | 复用 18070 / 10991 / 18098；`isError=true`，要求重新获取 | AC-05、AC-08 |
| 请求体超限 | HTTP 413 | AC-13 |
| 参数/Base64 不合法 | SDK 参数校验或统一安全 `ToolError`；`isError=true` | AC-13、AC-17 |
| 超时/下游不可用/投递失败 | 安全工具错误；已知部分结果包含可定位 ID 和真实状态，不透出栈、SQL、路径或凭证 | AC-15 |

不为工具传输错误申请新的数据库模型或复制业务错误码体系；业务层仍使用已有 `BaseErrorCode`，新校验由严格 schema/MCP 适配负责。

## 6. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|---|---|---|---|
| AC-01 | 接入方 | 握手、列工具及调用工具时提供不同 Token | 延续每请求鉴权、统一路由/IP/限流；空白名单不限制路由、非空规则必须匹配；拒绝时不执行资源访问 |
| AC-02 | 既有/新客户端 | 列工具及调用两种检索名称 | 十个名称齐全；旧工具契约保留，新工具限定知识空间 |
| AC-03 | 绑定用户 | 按名称、可写筛选列空间 | 仅有权空间；根上传权与子目录上传能力分别标明，过滤后正常分页 |
| AC-04 | 绑定用户 | 列根/子目录及伪造跨空间目录 | 有权目录带路径和上传权；跨空间目录拒绝，不泄漏其他路径 |
| AC-05 | 绑定用户 | 对文件列表排序、状态筛选及翻页 | 仅直接子文件、当前活动入口/主版本；权限和状态过滤后分页；无解析状态修正副作用 |
| AC-06 | 绑定用户 | 文件名/正文关键词限定空间及子树搜索 | 仅范围内有权文件；只返回文件，分页准确，不使用门户发现范围放宽权限 |
| AC-07 | 绑定用户 | 查询成功、处理中、失败文件详情 | 元数据及正文符合当前权限和可见状态；未完成解析显式 `content_ready=false` |
| AC-08 | 绑定用户 | 读取长正文和翻页期间改变内容 | 有限正文和可继续游标；正文属于授权入口当前 canonical 代次；变化时旧游标失败 |
| AC-09 | 绑定用户 | 获取有预览权、无下载权或受分发策略限制的来源 | 只返回允许链接；原件不绕过下载权、水印政策和分享限制 |
| AC-10 | 绑定用户 | 使用新检索工具查询有权空间或无命中问题 | 复用现有片段/出处结构；空结果成功；不生成答案 |
| AC-11 | 写入用户 | 将文本/Markdown 保存到根或指定目录 | 正确文件名、编码、目录、归属与真实队列状态；不能执行覆盖 |
| AC-12 | 写入用户 | 上传合法 Base64 文件 | 字节完整，走同一知识空间入库/版本/权限/解析链路 |
| AC-13 | 调用者 | 发送非法编码、类型、名称、超过 50 MiB 的解码文件、超过 10 MiB 的 UTF-8 文本或无长度头且超过 80 MiB 的请求 | 按阶段拒绝，不进入业务写入；对应上限以内的合法输入不被旧限制误拒绝，临时资源释放 |
| AC-14 | 调用者 | 无上传权、跨空间、只读收藏、配额不足、同名/同内容或并发重复写入 | 不覆盖已有内容；权限/配额失败不生成可用新文件，不把已有文件当新成功 |
| AC-15 | 调用者 | 遇到断连、超时、授权元组或解析投递失败 | 可确认阶段清理正确；入队文件保留；未知投递状态如实报告，不自动重复投递 |
| AC-16 | 多租户接入方 | 不同 Token 并发读写并取消部分请求 | 用户/租户/缓存/会话隔离，工具实际任务身份正确，资源和上下文复位 |
| AC-17 | 未授权调用者 | 注入身份字段、伪造 ID/游标、触发业务异常 | 拒绝未知字段；不泄漏无权元数据、正文、内部异常或签名 URL 到日志 |
| AC-18 | 既有接入方 | 调用原 Filelib、MCP 与其他 REST | 旧身份/覆盖/来源/返回契约、默认开关及 MCP 与 REST 的 CORS 隔离保持 |

验收追溯见 [requirements.md](requirements.md)，实际本地证据、存量失败和真实环境待验收项见 [verification.md](verification.md)。实现已完成本地交付，不代表已经部署。

## 7. 影响、回退与确认点

新增能力通过原 `/mcp` 生效，业务写入继续由 knowledge Owner 完成，不新增表、迁移、依赖或逐工具配置。不改变已有 Token 或资源权限数据。

回退应用版本可移除新增工具，旧检索继续可用；已成功创建的业务文件会保留，回退代码不会撤销这些文件。需要停止整个 MCP 时仍可使用既有关闭开关。

用户已确认本规格及调整后的限制，授权生成 `tasks.md`、任务评审、连续实施、端到端和相关回归验证。本次不自动提交、推送或部署。
