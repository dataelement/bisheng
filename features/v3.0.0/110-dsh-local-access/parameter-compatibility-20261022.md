# DSH 模型参数提前拦截修复与验证

日期：2026-10-22。分支：`feat/bisheng-work-110`，修改基线：`7e573b3a6`。

## 问题与修复

`model_capabilities()` 原来只为 `openai`、`azure_openai` 开启 `max_completion_tokens`。DSH 在模型调用前根据该标志拒绝请求，Qwen 请求因此无法到达已经实现参数转换的 `ChatQwen → ChatOpenAICompatible`。

现在根据注册客户端是否继承 `BaseChatOpenAI` 推导这项能力，表示适配器能够接受这个输入。DSH 保留原始参数名和值，将参数交给既有 SDK 适配器：Qwen 等兼容客户端沿用 `max_completion_tokens → max_tokens` 的现有转换，OpenAI 客户端沿用自身的请求构造逻辑。没有新增第二套参数转换。

同时修正内部能力字段的说明，区分“适配器能接受输入”与“供应商原生接受同名字段”。模型是否接受具体参数值仍由模型配置上限和上游服务约束。

涉及生产文件仅有 `model_capabilities.py` 和能力字段描述 `domain/schemas/chat.py`。没有修改数据库结构、认证、授权、额度或审计实现。

## 类似提前校验排查

| 校验点 | 结论与处理 |
| --- | --- |
| `max_completion_tokens` 提供商白名单 | 确认是本次缺陷。修复覆盖 Qwen、千帆、星火、腾讯、硅基流动、MindIE、MiniMax、Moonshot、火山、Xinference、llama.cpp、vLLM、DeepSeek 等已注册 OpenAI SDK 客户端。 |
| 流式调用 | Qwen 支持。Moonshot 参数处理器当前强制非流式，其对应保护保留。 |
| 工具调用 | 能力来自注册客户端的 `bind_tools` 实现；保留校验。 |
| `stop`、`temperature`、`top_p` | 生产能力默认允许；没有发现同类提供商白名单拦截。显式声明不支持时继续拒绝，新增测试覆盖。 |
| 图片、`reasoning_content` | 保留现有视觉声明与消息格式校验，相关回归通过。 |
| `reasoning_effort` | 当前仍限定 OpenAI/Azure 及管理员声明的档位；本次未扩展其他提供商的推理强度协议或映射。 |
| Responses、`prompt_cache_key` | 保留现有协议协商与提供商范围；不因令牌参数兼容而自动开放另一类 API 或缓存字段。 |
| 模型授权、月度额度、模型输出上限、两个 token 参数互斥 | 全部保留；未直接删除前置校验。 |

没有发现另一处已经实现相同参数转换、却仍被 DSH 提前阻断的独立路径。以上保留项不代表已经验证其他提供商的全部上游能力。

## 本地回归

新增 `src/backend/test/dsh/test_parameter_compatibility.py`：48 项通过。修复前选出的 6 个 Qwen 用例均复现失败，包括真实 FastAPI 路由返回 `400 / unsupported_parameter`；修复后通过。

自动化覆盖：

- 15 类已注册 OpenAI SDK 客户端接受 `max_completion_tokens`，其他 SDK 保持拒绝。
- 真实 FastAPI 路由 → DSH 模型服务 → `BishengLLM` → Qwen/千帆/OpenAI SDK → mock HTTP 上游请求体。
- 两种参数名、6500/9000 两种值、流式与非流式组合；确认参数只存在一次且数值不变。
- JSON/SSE 正文、`[DONE]`、usage 与额度结算；采样参数不丢失，审计上下文不作为模型输入。
- 模型输出上限与独立能力校验仍然生效。

相关协议、模型服务、视觉、Responses、审计回归合计 **172 passed，2 skipped**。Ruff 格式、检查、F821、架构守卫及 `git diff --check` 通过。

```bash
cd src/backend
config=/path/to/local/config.yaml PYTHONPATH=. /path/to/venv/bin/python -m pytest \
  test/dsh/test_parameter_compatibility.py test/dsh/test_protocol.py \
  test/dsh/test_enterprise_protocol.py test/dsh/test_models_api.py \
  test/dsh/test_model_service.py test/dsh/test_native_responses.py \
  test/dsh/test_vision.py test/dsh/test_model_audit_flow.py \
  test/dsh/test_audit_response_diagnostics.py -q --tb=short
```

Mock HTTP 用例证明协议链路与参数构造；真实供应商证据见下一节。

## 109 真实上游验证

验证方式：在 `dsh-backend` 容器内启动独立 Python/ASGI 进程，仅在该进程内加载分支修复。使用原生 PKCE 登录、真实 DSH 模型服务、现有授权/额度、真实 Qwen 上游、真实审计和额度投影。没有替换运行服务的源文件、升级镜像或重启 API/Worker。

同一独立进程加载修复前：返回 `400 / unsupported_parameter`，上游请求数为 0。加载修复后，对 `bisheng:2 / qwen-max` 传入 `max_completion_tokens`，捕获到现有适配器发出的 `max_tokens`，值保持一致。

| 传入上限 | 调用方式 | HTTP/正文 | 计量 | Request ID |
| --- | --- | --- | --- | --- |
| 6500 | 非流式 | 200，`QWEN_COMPAT_OK` | 26 Token | `36ded2db-f861-4c55-bbc5-fb1fcf70c30c` |
| 6500 | 流式 | 200，正文正常且含 `[DONE]` | 26 Token | `337f4fca-ce7a-4a78-b5f6-de23e11b104a` |
| 8192 | 非流式 | 200，`QWEN_COMPAT_OK` | 26 Token | `195bcc7e-3ddb-4e8f-b898-578e15c68b54` |
| 8192 | 流式 | 200，正文正常且含 `[DONE]` | 26 Token | `1712a4ea-72c5-42ae-ac3c-5346a2e7cd24` |

SQL 回读确认这些请求的审计状态为 `SUCCEEDED / COMPLETED / SETTLED / COMPLETE`，调用账本成功且总计 26 Token。另有两条首次 6500 验证的成功记录，重复验证总计 156 Token。

### 独立限制与验证边界

- `qwen-max` 传入 9000 已到达供应商，上游返回 `400 / invalid_parameter_error`，原因为 `Range of max_tokens should be [1, 8192]`。非流式平台返回 502；流式 HTTP 已建立，正文返回错误事件。这是模型自身的上限，不能计为调用成功，也不应静默裁剪用户参数。对应审计失败记录已落库。
- 当前 `bisheng:3` 对该管理员账号返回 `429 / monthly_token_limit_exceeded`，上游请求数为 0。因此本轮没有验证其实际供应商调用成功，也没有为测试修改现有授权或额度。
- 此次完成的是隔离进程的修复前后对照与真实上游验证。109 对外运行中的服务仍是旧代码，尚未部署本次修复。运行文件 SHA-256 与修改前 HEAD 完全一致，API/Worker 重启次数均为 0。
- 三个本轮测试会话均已撤销。独立探测进程已退出，测试调用及审计证据保留。
- 本轮验证没有启动桌面客户端，也不包含 DM8 或其他提供商的真实请求验证。

脱敏证据：[live-results.json](evidence/parameter-compatibility-20261022/live-results.json)、[database.tsv](evidence/parameter-compatibility-20261022/database.tsv)。
