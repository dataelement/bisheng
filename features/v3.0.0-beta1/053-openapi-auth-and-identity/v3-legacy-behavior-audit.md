# v3 与迁移前 v2 免登录链接行为核对

核对日期：2026-09-16。基线为 `b184ad55d`（`284ea1188^`），即开放 API 鉴权迁移之前；当时 `router_rpc = APIRouter(prefix='/api/v2')` 未挂密钥鉴权依赖。对照当前注册的全部 7 个 HTTP、2 个 WebSocket 入口。这里比较的是旧匿名 v2，而不是现在已要求密钥的 v2。代码检查不能替代真实浏览器、语音供应商和商业网关的端到端验证。

## 本次恢复的行为

| 入口 | 迁移前 v2 | 修复前 v3 | 本次处理 |
|---|---|---|---|
| `GET /api/v3/chat/history` | 不存在会话返回成功和空数组 | `get_subject_session` 要求会话必须存在，直接业务 404 | 通过应用发布准入后允许会话不存在，返回 `data=[]`；已有会话仍校验归属 |
| `POST /api/v3/chat/gen_title` | 等待 5 秒；不存在会话返回 `New Chat` | 先要求会话存在，再最多轮询标题 30 秒；不存在直接业务 404 | 恢复 5 秒等待和默认标题；存在会话仍验证公开来源、所属资源、租户和删除状态 |
| 全部 v3 HTTP/WS 的身份头 | 旧匿名端点不解析 `X-On-Behalf-Of` / `X-End-User`，详情/执行按默认操作员处理 | 新增拒绝依赖，带这些头就返回 26104/关闭 WS | 移除拒绝依赖，不判断这些身份头是否出现；不据此切换身份 |
| 全局 HTTP/WS 中间件 | 旧端点不依赖调用方登录，但共用中间件本身仍会读取 Cookie/JWT | 只为 v2 HTTP 跳过了浏览器身份，v3 仍会受旧 JWT 干扰 | 按用户明确的“token 无作用”要求，HTTP/WS 都跳过 v3 浏览器身份解析；v1 登录验证和 v2 密钥验证保持 |

原因：client 的 `useStandaloneSidebar.createNewChat` 先生成草稿 ID，`appChat.init` 随即请求历史；工作流服务在 WebSocket `check_status` 时才持久化该会话。不存在的草稿没有历史，不应因为版本迁移成为错误。

历史和标题两处不兼容，以及 v3 身份头拒绝检查，均由 `284ea1188`（highway，2026-09-04，`feat(api): 开放 API 鉴权与身份传递功能代码初步提交`）引入。全局 JWT 中间件早于该提交存在，本次按匿名请求不受调用方凭据影响的要求一并修正。

修改位置：

- `src/backend/bisheng/public_endpoints/api/endpoints/chat.py`
- `src/backend/bisheng/chat_session/domain/chat.py`
- 回归测试：`src/backend/test/public_endpoints/test_chat_compatibility.py`
- v3 路由与 guest policy 移除身份头拒绝，删除 `public_endpoints/api/dependencies.py`；`utils/http_middleware.py` 跳过 v3 调用方登录态。
- 凭据无关性回归：`src/backend/test/public_endpoints/test_anonymous_identity.py`，包含真实 HTTP/WS 中间件、两个详情入口、两个聊天入口和默认操作员身份断言。

## 其余 v3 入口

| 入口 | 保持的业务路径 | 已存在的迁移差异；本次未回退 |
|---|---|---|
| `GET /assistant/info/{assistant_id}` | 仍由默认操作员调用 `AssistantService.get_assistant_info`，仍检查 visible | 在调用前固定到资源租户、检查上线/删除及操作员状态；返回 `can_share=false` |
| `GET /flows/{flow_id}` | 仍由默认操作员调用 `FlowService.get_one_flow`，仍检查 visible | 同上，限定工作流类型并检查上线；返回 `can_share=false` |
| `WS /assistant/chat/{assistant_id}` | 仍进入 `chat_manager.dispatch_client`，使用 GPTS 客户端 | 新增发布准入、已有会话的公开来源/租户/应用校验；新会话允许不存在，并写入 `public_v3` 来源 |
| `WS /workflow/chat/{workflow_id}` | 仍进入 `chat_manager.dispatch_client`，使用工作流客户端和执行引擎 | 同上；向后台任务传递绑定资源租户和操作员的执行快照 |
| `GET /llm/workbench` | 通过 `LLMService.get_workbench_llm` 查询语音配置 | 这是新增的公开配置入口，旧 v2 无对应项；要求 `flow_id`，仅输出 ASR/TTS 模型 ID |
| `POST /llm/workbench/asr` | 仍由 `LLMService.invoke_workbench_asr` 执行，成功结果为识别文本 | 新增必填 query `flow_id` 并按应用限定租户；multipart `file` 由可省略改为必填 |
| `POST /llm/workbench/tts` | 仍由 `LLMService.invoke_workbench_tts` 执行，JSON `text` 及音频 URL 结果保持 | 新增必填 query `flow_id` 并按应用限定租户 |

语音的 `flow_id` 已由当前 client 的 guest 调用链传递。API 访问文档中的密钥 RPC（例如 `workflow/invoke`）属于 v2，不在匿名 v3 的允许列表里。

## 需要明确保留的边界差异

- **免登录不变**：v3 不要求 JWT/API Key，也不从它们继承权限。执行身份仍为 `default_operator.user`。其真实角色/超管身份已由 `500e71fa4`（LineWalker，2026-09-14）恢复，本次没有再次改变身份逻辑。
- **资源及操作员状态**：v3 在公共入口统一检查应用上线、guest 开关、操作员有效且在资源租户中有活跃成员关系、租户有效。旧 v2 的详情检查 guest 开关，但 history/title/语音及 WS 并未全部执行同一套入口检查。v3 的租户来自资源，旧默认操作员解析来自操作员当前激活租户。
- **已有会话归属**：`public_v3` 来源、租户、应用及删除状态检查继续保留。旧会话如果 `api_subject_type` 为 NULL，不会因为这次草稿兼容修复而自动变成公开会话。这是存量会话迁移问题，不能仅凭 NULL 或相同用户 ID 认定其来自旧匿名链接；普通登录会话也可能具有相同字段。
- **调用方身份**：Authorization、API Key、Cookie、`X-On-Behalf-Of`、`X-End-User` 和额外 token/用户身份参数在 v3 不参与身份解析、不触发拒绝，统一按默认操作员与发布资源决定执行身份。这不包括 `X-Trace-ID` 等与鉴权无关的业务/追踪头，不能将其解释为“所有 X- 开头的头都被删除”。
- **分页校验**：history 默认仍为 20 条，当前前端传 40；v3 新增 `1 <= page_size <= 1000`，不合法页大小仍按参数错误处理。
- **错误呈现**：发布资源不存在/下线为真实 HTTP 404（26101/26102），guest 关闭为 HTTP 403（26103）；26104 不再由 v3 返回，错误码和旧文案仅保留兼容。已有会话归属错误仍走旧业务 404 信封。草稿为空不能与这些错误合并处理。
- **匿名分享能力**：详情返回 `can_share=false` 是匿名入口的能力标识，未移除 visible 检查。

因此，正常新会话的空历史和默认标题可以恢复旧结果；“所有边界行为完全相同”并不符合当前实现。此次未发现其余注册入口有同样的“缺少草稿即报错”问题，也没有取消会话隔离、扩大匿名入口范围或改动工作流/助手执行算法。

## 105 部署边界

此前已补齐 105 商业网关的 v3 HTTP/WS 路由并重启，HTTP 可到达后端。运行中的 Java 网关仍在自定义 WebSocket Filter 中仅识别 `api/v2/` 为匿名入口，v3 匿名连接会进入用户组处理并触发空指针异常。这需要网关代码修复，不能用 history 空数组修复替代。

本次为仓库源代码修复；未替换 105 后端容器文件，未重启后端。上线后应通过 3001 复验草稿 history 返回成功空数组，并在网关 WebSocket 修复后验证首次发送、续聊和标题生成。

## 验证与代码审查

已执行公开入口全套、v2 会话隔离/路由矩阵/真实路由错误/身份头/依赖/凭据生命周期，以及管理范围与 JWT 中间件回归：**306 passed**。其中聊天兼容新增 21 项，凭据无关性新增 46 项；后者覆盖两个 HTTP 详情、两个 WS 聊天、无凭据/错误 Bearer/SAK/PAT/旧 Cookie/单独或组合身份头、额外 query 身份参数，断言默认操作员及租户不变、JWT 解码未被调用，同时验证 v1 仍拒绝已撤销登录态、v2 无密钥仍 401。测试使用真实会话匹配、公开身份上下文、HTTP/WS 路由、中间件和异常处理，替换数据访问及外部依赖；没有调用 105 数据库或模型供应商。配置加载使用本地测试占位环境变量。Ruff、改动文件的 arch-guard 和 `git diff --check` 均通过。

按项目 `code-review` skill 对本次工作区 diff 自查（基线 `feat/3.0.0-beta1`）：

| 维度 | 结果 | 核对重点 |
|---|---|---|
| 边界条件 | PASS | 不存在、空历史、空标题、等待期间创建、分页透传 |
| 权限与认证 | PASS | 已有会话继续检查来源/租户/应用/删除状态；v3 忽略调用方凭据，默认操作员不变；发布准入及 v1/v2 鉴权保留 |
| 并发安全 | PASS | 标题在等待后读取；资源上下文内重新校验会话；无新增写操作 |
| 信息泄漏 | PASS | 不存在会话只返回空数组或固定标题；不返回其它会话数据 |
| 测试覆盖 | PASS | 正常及拒绝路径的 HTTP 回归；公开入口和会话隔离测试通过 |
| 代码风格 | PASS | 复用现有可选会话检查，移除不再使用的标题轮询函数，格式和架构检查通过 |
| 文档同步 | PASS | design.md F3、已知坑和修订记录已同步；其余迁移差异明确列出 |

Overall: **PASS**。这是源码和模拟依赖下的回归结论，未执行部署后的浏览器聊天或真实 ASR/TTS 验证。
