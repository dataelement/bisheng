# E2E 验证清单：F053 开放 API 鉴权与身份传递

**自动化入口**：`F053_E2E=1 ... pytest test/e2e/test_e2e_f053_openapi_auth_identity.py -v`。专用环境可通过 `E2E_ADMIN_TOKEN` / `F053_E2E_USER_TOKEN` 注入短期测试 JWT，避免在命令历史中写管理员明文密码。

**2026-09-09 环境证据**：在 `192.168.106.116:7861` 真实 MySQL、Redis、OpenFGA 环境完成 11/11 API E2E；QA 样本 47296 的拒绝测试前后内容 SHA-256 一致，测试服务账号残留为 0。`192.168.106.116:3001` 是前端入口，`/openapi.json` 不走 API 代理，且当前公开 v3 请求被商业许可证过期码 11001 拦截，浏览器 guest 验收须先续期许可证。

**专用环境前置条件**：完成三条 F053 迁移；OpenFGA 已发布包含 `service_account` 的兼容模型；部署级 PAT 和 guest access 已开启；准备同租户普通用户、已发布工作流、已发布知识助手及至少一个可用模型。

## Platform：服务账号与 API 密钥

- [ ] 以全局超管或当前租户管理员登录 Platform，进入“系统管理 → 服务账号”。
- [ ] 列表可分页并显示有效密钥数、委托范围、资源归属人、最后调用、创建人/时间；零密钥、长期未调用和归属人失效分别有就地提示。
- [ ] 创建名称以 `e2e-f053-openapi-` 开头的服务账号并通过组织用户选择器选择同租户自然人作为资源归属人；创建成功 Toast 出现，并直接进入 API 密钥标签页、打开首把密钥签发弹窗。
- [ ] 确认数据库未为该服务账号新增 `user` 或 `user_tenant` 行。
- [ ] 签发 API 密钥，仅出现“基本信息、权限位、委托配置”三组；无网络、IP、配额、限流或分享配置。
- [ ] 勾选 `delegate` 后使用用户多选和部门树选择范围；用户与部门都未选择时不能提交，页面不要求输入 `user:<id>` / `department:<id>` 格式文本。
- [ ] 密钥明文只显示一次；未勾选“已安全保存”时弹窗不能关闭，刷新后只能看到掩码。
- [ ] 复制密钥或 curl 示例后出现成功 Toast；编辑密钥可修改名称、有效期、权限位及多用户/多部门委托范围，去掉 `delegate` 并保存后重新打开，委托范围为空。
- [ ] 进入资源授权页，确认顶部展示有效密钥及其权限位；存在 `delegate` 密钥时显示“委托调用按被代表用户权限判定”的提示。
- [ ] 点击“添加资源授权”：通过资源类型下拉、名称/ID 搜索、单项或多项资源勾选和权限模型下拉完成授权；页面和弹窗均没有资源类型/资源 ID 文本输入框，写入主体固定为 `service_account:<id>`。
- [ ] 来源列正确区分管理员授予与创建时自动回授；自动回授可经风险确认后单条撤销，“全部撤销”只撤管理员授予并保留自动回授，protected 项保持只读。
- [ ] 给 SA 授予 viewer/editor 后用同一 SAK 验证对应读/写动作；撤权后 v2 立即返回 HTTP 403 与原业务码，不能再出现“授权台账有记录但动作仍报 18040”。
- [ ] 启用、停用、删除、签发和吊销期间按钮不可重复提交，成功有 Toast，失败由统一错误提示反馈；停用后已有密钥在 5 秒内返回 401，重新启用恢复未吊销密钥及原资源授权。
- [ ] 删除确认弹窗逐项列出管理员授予和自动回授；确认后密钥与全部授权失效，资源本身及资源归属人保持不变。
- [ ] 非管理员账号看不到“服务账号”和“个人访问令牌”页签；直接访问 API 也被拒绝。

## Platform：PAT 台账与租户设置

- [ ] 进入“个人访问令牌”，确认列表只有持有人、掩码、权限位、时间、状态和管理员风险提示，没有明文。
- [ ] 部署级开关关闭时租户开关置灰；重新开启部署级开关后可设置租户 `enabled` 与 TTL。
- [ ] 关闭租户开关后，既有 PAT 数据仍在台账中，但 5 秒内无法调用 v2；重新开启且令牌未过期时恢复。
- [ ] 分别执行单 token 吊销和按持有人吊销；刷新列表验证最终状态。
- [ ] 切换到另一租户后看不到原租户台账数据。

## Client：个人访问令牌

- [ ] PAT 开关关闭时个人设置页不显示入口；开启后显示状态和操作入口。
- [ ] 首次获取或重新获取后只显示一次明文，必须确认已保存才能关闭；刷新页面后只显示掩码。
- [ ] 复制安装提示词，确认下载 URL 指向当前实例的 `bisheng-knowledge-search` 技能包，提示使用 `BISHENG_API_KEY`。
- [ ] 删除 PAT 后状态刷新为未获取；旧 token 在 5 秒内返回 401。
- [ ] 管理员持有人获取 PAT 时出现风险提示，过期时间不超过部署级管理员 TTL。
- [ ] 将 PAT 持有人切换到另一活跃租户后，原 token 不被吊销，在新租户按新权限生效且不能访问旧租户；审计含 `open_api.pat.tenant_migrate` 及旧/新 tenant id。

## Client：v3 匿名发布面

- [ ] 使用无痕窗口打开已发布工作流和知识助手 guest 页面，不携带 JWT、API Key 或分享参数。
- [ ] Network 中详情、invoke/stop、history/gen_title 全部使用 `/api/v3/**`，两个 WebSocket 也使用 `/api/v3/**`；不得出现 guest `/api/v2/**`。
- [ ] 页面能够建立新会话、续聊、读取历史并生成标题；工作流等待输入字段对外为 `input`。
- [ ] 猜测另一个资源、租户或来源的 `chat_id` 执行 history/title/stop/续聊，均得到同形 404。
- [ ] guest 请求携带 `X-On-Behalf-Of` 或 `X-End-User` 时被拒绝；`/api/v3/assistant/list` 为真 404。
- [ ] 关闭 guest access 或下线资源后，HTTP 与 WebSocket 均无法继续建立新调用。

## Client：AC-R9 发布页语音补漏（2026-09-10）

- [ ] 清空浏览器 cookie、localStorage 和查询缓存，分别打开工作流、助手免登录链接。
- [ ] 输入框挂载只请求 `GET /api/v3/llm/workbench?flow_id=<当前应用>`；响应仅含 `asr_model.id` / `tts_model.id`；不请求 v1/v2 的语音配置或转换接口。
- [ ] 配置了 ASR 后录音按钮可用，录音结束才发送 `POST /api/v3/llm/workbench/asr?flow_id=<当前应用>`（multipart `file`），识别文字回填输入框。
- [ ] 配置了 TTS 后回答出现朗读按钮，点击才发送 `POST /api/v3/llm/workbench/tts?flow_id=<当前应用>`（JSON `text`），返回音频可播放、暂停；绝对音频 URL 不被错误添加页面路径前缀。
- [ ] 同一浏览器先登录、再打开 guest；或在两个应用间切换，语音配置不串用登录态缓存或其他应用的缓存。
- [ ] 关闭 guest / 下线应用后，三类请求分别按既有发布规则拒绝；不携带应用 ID 返回 422；身份传递头仍被拒绝。
- [ ] 站内原语音入口仍可使用；v2 ASR/TTS 仍保持原密钥鉴权，本轮不删除。

本轮自动化：`test/public_endpoints/test_voice.py` 覆盖真实路由、发布策略与租户上下文（替身模型服务）；client 测试覆盖通道、缓存隔离及朗读按钮调用。真实模型 E2E 入口为 `test/e2e/test_e2e_f053_public_voice.py`，需设置 `F053_VOICE_E2E=1`、`E2E_API_BASE`、两个应用 ID，以及 ASR 测试录音路径；未提供专用环境时跳过，不记为通过。

2026-09-10 本地结果：后端 public_endpoints + v2 路由矩阵 35 项通过；client 相关 4 个测试文件共 20 项通过；工作区 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`、backend Ruff 与架构守卫通过。后端单元测试使用临时空配置和既有外部服务替身，无需连接真实中间件；Jest 本地缺少可选 native canvas 构建产物，通过临时 preload 将其标记为不可用后执行，未修改仓库测试环境。真实模型 E2E 9 项因未提供专用部署参数而跳过，上述浏览器清单尚未实测。

## v2 日常会话与身份传递

- [ ] 仅携带具有 `chat:invoke` 的 SAK，依次调用 config、chat/list、chat/info、knowledge/upload、workstation/chat/completions；不需要 JWT。
- [ ] config 只含 `models[]`、`tools[]`；SSE 事件顺序、终态和持久化消息与 v1 日常会话一致。
- [ ] 请求保留 `files`；传 `task_mode`、`use_knowledge_base`、异步意图或其它未知字段时明确 400，不静默降级。
- [ ] 模式 S 的会话按服务账号与 `X-End-User` 隔离；模式 D/PAT 会话归属自然人；跨主体 chat/file 统一 404。
- [ ] SAK 使用合法 `X-On-Behalf-Of` 时权限完全按目标用户计算；SA 有权而目标无权时拒绝，反向场景允许。
- [ ] 旧品牌身份头及 query/JSON/urlencoded 裸 `user_id` 明确返回 HTTP 400 / `26019`。
- [ ] 调用 multipart 文件上传时附加废弃的 `user_id` 表单字段，确认在文件处理前返回 HTTP 400 / `26019`；相同文件不带该字段时正常进入业务流程。
- [ ] 使用 PAT 和合法代表用户调用 `GET /api/v2/filelib/?type=3`，非空空间列表包含 `user_name` 与 `actions`，没有 DTO 序列化异常。
- [ ] 使用无知识库权限的用户/SA 按 QA ID 调用 detail/update/delete/append；读取按防枚举策略返回 404、写入拒绝返回 403/404，随后核对数据库答案、索引与异步任务均无变化。

## WebSocket、审计与回归

- [ ] v2 工作流/知识助手 WebSocket 只接受 `Authorization: Bearer <API Key>` header；query key、JWT 和无 key 均以 1008 关闭。
- [ ] 已连接后撤销密钥或停用主体，5 秒内关闭连接；两个不同租户连续执行后 ContextVar 不串。
- [ ] `audit_log` 中管理操作 action 可见；逐调用 action 固定为 `open_api.call`，metadata 有 actor/subject 双归属、HTTP 状态、业务错误码和 SSE 最终结果，且无 Authorization、明文密钥、请求体或文件内容。
- [ ] 配对验证 v2 错误状态：权限拒绝 HTTP 403、防枚举 HTTP 404、权限依赖故障 HTTP 503；业务错误码保留。SSE 失败终态在审计中为 `failed`，不能按初始 HTTP 200 记成功。
- [ ] v3 发布示例全部匿名且为 v3；v2 密钥示例全部带 Bearer；既有 ChatLink 创建、打开、撤销流程及参数保持不变。
- [ ] 商业版网关分别验证 v3 HTTP 与 WS 可达，且 v3 不被登录或 API Key 网关拦截。

## 清理

- [ ] 删除本次所有 `e2e-f053-openapi-` 服务账号和临时资源；恢复测试前 PAT/guest 设置。
- [ ] 确认非测试数据、既有分享链接和其它租户数据未变化。
