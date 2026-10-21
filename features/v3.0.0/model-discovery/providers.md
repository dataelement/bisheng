# 模型目录厂商适配

核对日期：2026-10-21。范围为新增服务商表单中的 18 种格式；内部 bishengRT 沿用原配置入口。

| 格式 | 默认获取方式与保存对象 | 官方依据 |
| --- | --- | --- |
| OpenAI | Bearer Key，GET /v1/models，模型 ID | [Models](https://developers.openai.com/api/reference/resources/models/methods/list) |
| Azure OpenAI | api-key，GET /openai/v1/models；补充实际部署名称。可选 ARM 资源 ID + Entra Token，分页读取成功部署 | [Models](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/models)、[Deployments](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/deployments/list?view=rest-aiservices-accountmanagement-2024-10-01) |
| Ollama | GET /api/tags，已安装模型名称 | [Tags](https://docs.ollama.com/api/tags) |
| Xinference | GET /v1/models，运行模型 UID 与类型 | [Client](https://inference.readthedocs.io/en/stable/reference/generated/xinference.client.Client.html) |
| llama.cpp | GET /v1/models，服务加载的模型 | [Server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) |
| vLLM | GET /v1/models，服务暴露的模型 ID | [Serving](https://docs.vllm.ai/en/stable/serving/online_serving/) |
| 阿里云百炼 | 原生 /api/v1/models，分页与 capabilities；北京地区补充 Workspace ID；可指定目录 URL | [模型列表](https://help.aliyun.com/zh/model-studio/list-models) |
| DeepSeek | Bearer Key，GET /v1/models | [List models](https://api-docs.deepseek.com/api/list-models/) |
| 硅基流动 | GET /v1/models；按 sub_type 补全聊天、向量、重排、语音识别、图像与视频能力 | [Models](https://api-docs.siliconflow.cn/docs/api/models-get) |
| 火山引擎 | 北京管理接口 ListEndpoints，AK/SK V4 签名，可带 Session Token/项目；分页读取 Running 接入点 ID | [ListEndpoints](https://docs.volcengine.com/docs/ark/list-endpoints-api?lang=zh)、[鉴权](https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=zh) |
| 智谱 AI | 官方连接使用预置目录；自定义兼容地址可实时获取 | [模型概览](https://docs.bigmodel.cn/cn/guide/start/model-overview) |
| 讯飞星火 | 官方连接使用预置目录；兼容查询沿用原连接 API Key/Secret 鉴权组合 | [HTTP API](https://www.xfyun.cn/doc/spark/HTTP调用文档.html) |
| 腾讯混元 | 当前 Hunyuan 官方连接使用预置目录；自定义兼容地址可实时获取 | [OpenAI 兼容](https://cloud.tencent.com/document/product/1729/111007) |
| Moonshot | Bearer Key，GET /v1/models | [API troubleshooting](https://www.kimi.com/help/kimi-api/api-troubleshooting) |
| 百度千帆 | Bearer Key，GET /v2/models | [模型列表](https://cloud.baidu.com/doc/qianfan-api/s/Dmba8k71y) |
| MiniMax | 官方连接使用预置目录；自定义兼容地址可实时获取 | [OpenAI API](https://platform.minimax.io/docs/api-reference/text-openai-api) |
| Anthropic | x-api-key + anthropic-version，GET /v1/models，after_id 游标 | [Models](https://platform.claude.com/docs/en/api/models/list) |
| MindIE | GET /v1/models，部署模型 ID | [模型查询](https://www.hiascend.com/doc_center/source/zh/mindie/300/mindiellm/llmdev/mindie_service0320.html) |

预置目录是带日期的部分官方型号快照，账户开通范围以厂商为准；四家厂商公开统一列表合同尚待确认。页面明确标注目录来源，保留手动添加和兼容实时获取。实时接口鉴权、超时和格式错误按具体原因反馈。

实时结果代表接口可见范围。类型优先采用能力元数据，再匹配已知型号族；未知能力需要手动确认。模型发现与推理适配分开校验，当前运行适配器支持的类型才可添加。图片、视频和待适配能力保留展示。

## 验证边界

使用模拟 HTTP 传输覆盖全部格式、认证头、原生分页、重复页、跨源分页拒绝、管理凭据隔离、Azure 部署映射、类型归一化和错误脱敏。页面检查覆盖新增入口、来源切换、凭据清除与迟到结果作废。真实厂商 Key、全型号推理和各地区权限差异留待后续联调。本轮只更新源码和 PR，3006 部署状态独立记录。
