# 内置价格表维护说明（版本 2026-11-25）

文件：`src/backend/bisheng/llm/domain/pricing/catalog.json`。随版本发布，不联网更新；只用于添加模型时带出价格和「选择模型」列表，已保存的模型价格不随它变化。

## 收录范围

13 家、108 个模型，按厂商分组，组内新型号在前（2026-11-25 在 11-16 的 87 个基础上新增 21 个，原有价格逐条核对、均未变）：

| 厂商 | 币种 | 服务商类型（另加 OpenAI 兼容） | 条数 |
|---|---|---|---|
| DeepSeek | 人民币 | deepseek | 2 |
| 阿里千问 | 人民币 | qwen | 15 |
| 字节豆包 | 人民币 | volcengine | 8 |
| 智谱 | 人民币（国内站） | zhipu | 6 |
| Kimi | 人民币 | moonshot | 3 |
| MiniMax | 人民币（国内站） | minimax | 2 |
| 百度文心 | 人民币 | qianfan | 2 |
| 腾讯混元 | 人民币 | tencent | 5 |
| 讯飞星火 | 人民币 | spark | 2 |
| OpenAI | 美元 | openai、azure_openai | 29 |
| Anthropic | 美元 | anthropic | 16 |
| Google | 美元 | 无（只走 OpenAI 兼容） | 12 |
| xAI | 美元 | 无（只走 OpenAI 兼容） | 6 |

每条都带 `openai_compatible`，所以「OpenAI 兼容」的选择模型列表能看到全部厂商（有测试保证）。

百炼（qwen）、火山方舟（volcengine）、千帆（qianfan）、腾讯 TokenHub（tencent）、硅基流动（silicon）和 OpenAI 兼容都转售别家模型（`catalog.py` 的 `MULTI_VENDOR_PROVIDER_TYPES`，接口也下发给前端）：「选择模型」拉不到服务商列表时列出全部厂商、自家排最前；别家模型按名字带出官方价，并提示管理员核对平台的名称和价格。DeepSeek、Kimi、智谱、MiniMax、讯飞、OpenAI、Anthropic 这类单一厂商接口只列、只匹配自家模型；本地部署类型（vLLM、Ollama 等）不匹配价格表。

## 取价规则

- **原价**：限时折扣、活动价不算，取折扣前的价格。MiniMax-M3 官方写的是「永久五折」，按五折后价格。
- **分档取第一档**：千问取最小上下文档、非思考输出价；文心取 ≤32K；智谱 GLM-4.7 取「输入 <32K、输出 >200」档；Gemini 3.1 Pro 取 ≤200K。
- **分时段取高峰价**：DeepSeek、文心空闲时段打折，表里是高峰（原价）。
- **缓存命中**：千问按隐式缓存（输入价 20%）；官网没写缓存价的按不打折（等于输入价）：千问 3.8 Max / 3.8 Flash、文心 5.1、星火 X2.6 / X2.5。
- **缓存写入**：Anthropic 取 5 分钟写入价；千问取显式缓存创建价（输入价 125%）；Kimi 官网写的等于输入价；其余不填（按输入价计）。OpenAI 的 30 分钟写入价没收，默认缓存不收写入费。
- **型号名**：取官方 API 的 model 参数。豆包方舟的调用名是横杠加日期（`doubao-seed-2-1-pro-260915`），把已知的几个日期版本逐个列为别名，再加上不带日期的横杠写法和中转站常用的点号写法。Claude 另收 OpenRouter 的点号写法（`claude-opus-4.5`）。
- **匹配**：先按全名精确匹配（转售平台还会匹配别家模型，算「按名字匹配」）；没有时去掉最后一个 `/` 之前的厂商前缀再匹配（`openai/gpt-5.5`、`deepseek-ai/DeepSeek-V4-Pro`），这种匹配会提示管理员核对。日期后缀不去，因为快照可能另有价格。

## 核对情况（2026-11-25）

- **直接读官网定价页**：OpenAI、Anthropic、Google、xAI、DeepSeek、阿里千问（含上下文缓存说明页）、字节豆包（ark.volcengine.com 模型价格页）。
- **官网页面本次打不开，按检索到的官网定价页内容整理**：智谱（docs.bigmodel.cn《API 定价》）、Kimi（platform.kimi.com，原 platform.moonshot.cn）、MiniMax（国内站按量计费页）、百度文心（千帆价格文档）、腾讯混元（TokenHub 模型价格页）、讯飞星火（星辰 MaaS 模型广场 / API 页）。发布前最好在国内网络打开这几家官网再看一眼。
- 11-16 的三个待确认项：讯飞的 model 名已确认是 `spark-x2.6` / `spark-x2.5`；MiniMax 定价页地址已找到（`source_url` 已改）；文心 5.1 的缓存价仍未公布，照旧按不打折。
- 这次没能重新核对、保留 11-16 日期的 4 条：`doubao-seed-1.6`、`grok-build-0.1`（官网价格页已不列出，可能下线）、`glm-4.7`、`glm-4.7-flash`（检索结果没覆盖到）。

### 2026-11-25 新增的 21 个

| 厂商 | 新增 | 说明 |
|---|---|---|
| OpenAI | gpt-6.2-astra、gpt-6.2-sol | 11-18 新发布 |
| OpenAI | gpt-5.2、gpt-5.1 | 仍在售、之前漏收 |
| OpenAI | gpt-5.5-pro、gpt-5.4-pro、gpt-5.2-pro、gpt-5-pro、o3-pro | 每百万输入 15–30 美元，漏收会按 0 免费扣，风险最大；官网没写缓存价，按不打折 |
| Anthropic | claude-fable-5 | 仍在售、之前漏收 |
| Anthropic | claude-opus-4-1 | 官方 API 已下线，但 Bedrock / Vertex 和中转站还在卖，且是最贵的 Claude |
| Google | gemini-4-neon | 11-18 新发布 |
| Google | gemini-2.5-pro、gemini-2.5-flash | 仍在售、之前漏收；官网写 12-01 起分别转到 3.8 Flash / 3.5 Flash-Lite |
| xAI | grok-4.20 | 别名含 `grok-4.20-0309-reasoning`、`-non-reasoning`、`grok-4.20-multi-agent(-0309)`，同价 |
| 字节豆包 | doubao-seed-2.0-lite、doubao-seed-2.0-mini | 官网价格页有、之前漏收；带日期的调用名未查到，只收了点号和横杠写法 |
| 智谱 | glm-5.3-flash、glm-5.3-flashx | 国内站价；`glm-5.3-flashx-legal` 同价，作为 FlashX 的别名 |
| 腾讯混元 | hy4-flash、hy4-preview | hy4-flash 11-16 发布 |

### 没收的

- 智谱 GLM-5.4（11-23 发布）：按量 API 还没开放、没有官方单价。开放后补。
- 智谱 GLM-5.3-Prime：智谱官网没有人民币单价（阿里云百炼上是 16 / 56 元）。
- Claude Mythos 5 / 5.1 / 5.2：限量开放，API 名未确认（价格与同代 Fable 相同）。
- 百度 ERNIE-Light-DT-1.0（输入 8、缓存 0.8、输出 28 元）：千帆调用名未确认。
- 千问 qwen4-max / qwen3.8-max / qwen3.8-flash 的缓存价：官方缓存说明写「非标准价格，需在控制台核对」，qwen3.8 两个照旧按不打折，qwen4-max 保留 11-16 的值。

## 已知会变的价格

- Google Gemini 4 Carbon / Argon：2026-12-01 起从 2 / 10 美元涨到 4 / 20 美元（每百万 token 输入 / 输出），表里是现价。
- Gemini 3.8 Flash、3.6 Flash：2027-01-01 起从 0.75 / 3.75 美元涨到 1.5 / 7.5 美元。
- 腾讯混元 Hy4 目前 5 折到 2026-12-31，表里是原价 6 / 18 元；Hy4 Flash 5 折到 2026-11-30 12:00，表里是原价 0.5 / 2 元。
- 文心 5.5 Flash Preview 目前 5 折到 2026-11-30，表里是原价 2 / 8 元。
- 讯飞星火 X2.6 限时 6 折、X2.5 限时 3 折（截止时间未公布），表里是原价。

## 更新步骤

1. 按上面的规则改 `catalog.json`，`version` 和每条的 `verified_at` 改成核对当天。
2. 跑 `test/llm/test_model_pricing_catalog.py`、`test_price_catalog_api.py`（版本号写在测试里）。
3. 同一服务商类型下别名不能重复，加载时会报错。
