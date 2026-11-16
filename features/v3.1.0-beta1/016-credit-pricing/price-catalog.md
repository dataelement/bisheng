# 内置价格表维护说明（版本 2026-11-16）

文件：`src/backend/bisheng/llm/domain/pricing/catalog.json`。随版本发布，不联网更新；只用于添加模型时带出价格和「选择模型」列表，已保存的模型价格不随它变化。

## 收录范围

13 家、87 个模型，按厂商分组，组内新型号在前：

| 厂商 | 币种 | 服务商类型（另加 OpenAI 兼容） | 条数 |
|---|---|---|---|
| DeepSeek | 人民币 | deepseek | 2 |
| 阿里千问 | 人民币 | qwen | 15 |
| 字节豆包 | 人民币 | volcengine | 6 |
| 智谱 | 人民币（国内站） | zhipu | 4 |
| Kimi | 人民币 | moonshot | 3 |
| MiniMax | 人民币（国内站） | minimax | 2 |
| 百度文心 | 人民币 | qianfan | 2 |
| 腾讯混元 | 人民币 | tencent | 3 |
| 讯飞星火 | 人民币 | spark | 2 |
| OpenAI | 美元 | openai、azure_openai | 20 |
| Anthropic | 美元 | anthropic | 14 |
| Google | 美元 | 无（只走 OpenAI 兼容） | 9 |
| xAI | 美元 | 无（只走 OpenAI 兼容） | 5 |

每条都带 `openai_compatible`，所以「OpenAI 兼容」的选择模型列表能看到全部厂商（有测试保证）。

## 取价规则

- **原价**：限时折扣、活动价不算，取折扣前的价格。MiniMax-M3 官方写的是「永久五折」，按五折后价格。
- **分档取第一档**：千问取最小上下文档、非思考输出价；文心取 ≤32K；智谱 GLM-4.7 取「输入 <32K、输出 >200」档；Gemini 3.1 Pro 取 ≤200K。
- **分时段取高峰价**：DeepSeek、文心空闲时段打折，表里是高峰（原价）。
- **缓存命中**：千问按隐式缓存（输入价 20%）；官网没写缓存价的按不打折（等于输入价）：千问 3.8 Max / 3.8 Flash、文心 5.1、星火 X2.6 / X2.5。
- **缓存写入**：Anthropic 取 5 分钟写入价；千问取显式缓存创建价（输入价 125%）；Kimi 官网写的等于输入价；其余不填（按输入价计）。OpenAI 的 30 分钟写入价没收，默认缓存不收写入费。
- **型号名**：取官方 API 的 model 参数。豆包方舟的调用名是横杠加日期（`doubao-seed-2-1-pro-260915`），把已知的几个日期版本逐个列为别名，再加上不带日期的横杠写法和中转站常用的点号写法。Claude 另收 OpenRouter 的点号写法（`claude-opus-4.5`）。
- **匹配**：先按全名精确匹配；没有时去掉最后一个 `/` 之前的厂商前缀再匹配（`openai/gpt-5.5`、`deepseek-ai/DeepSeek-V4-Pro`），这种匹配会提示管理员核对。日期后缀不去，因为快照可能另有价格。

## 核对情况

- **直接读官网页面**：DeepSeek、阿里千问、OpenAI、Anthropic、Google、xAI。
- **本机连不上官网，按检索摘要（引用官网定价页）整理，发布前要在国内网络打开官网再核一遍**：字节豆包、智谱、Kimi、MiniMax、百度文心、腾讯混元、讯飞星火。其中这几项最不确定：
  - 讯飞星火 X2.6 / X2.5 的 model 名（只查到 `spark-x2.6`）和折扣前的缓存价；
  - MiniMax 国内站定价页的具体地址（`source_url` 暂填平台首页）；
  - 文心 5.1 的缓存价。

## 已知会变的价格

- Google Gemini 4 Carbon / Argon：2026-12-01 起从 2 / 10 美元涨到 4 / 20 美元（每百万 token 输入 / 输出），表里是现价。
- Gemini 3.8 Flash：2027-01-01 起从 0.75 / 3.75 美元涨到 1.5 / 7.5 美元。
- 腾讯混元 Hy4 目前 5 折到 2026-12-31，表里是原价 6 / 18 元。
- 文心 5.5 Flash Preview 目前 5 折到 2026-11-30，表里是原价 2 / 8 元。

## 更新步骤

1. 按上面的规则改 `catalog.json`，`version` 和每条的 `verified_at` 改成核对当天。
2. 跑 `test/llm/test_model_pricing_catalog.py`、`test_price_catalog_api.py`（版本号写在测试里）。
3. 同一服务商类型下别名不能重复，加载时会报错。
