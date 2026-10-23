# Qwen Embedding 客户端切换说明

状态：后端实现及离线自动化测试已完成，真实网关联调与知识库召回验收待执行。

适用分支：`feat/3.0.0`。实施基线：`111268ba77b3fac37cbcc8fb809181e65d9560c5`，核对日期：2026-10-21。

## 目标与修改范围

将模型管理中 Qwen 文本向量模型的客户端由 `DashScopeEmbeddings` 切换为 `langchain_openai.OpenAIEmbeddings`，使用阿里云的 OpenAI 兼容接口，并让界面填写的 Base URL 实际控制请求地址。Qwen LLM 已有的地址与凭证映射方式是本次实现参考。

继续使用 `BishengEmbedding` 对外提供的向量接口，保留模型名称、模型 ID、上线状态检查、调用限制和向量归一化逻辑。服务商类型仍为 `qwen`，用户无需把服务商改成 OpenAI。

本次涉及现有后端适配和针对性测试；界面已经有地址输入和保存能力，无需新增字段，也不涉及数据库结构迁移。Qwen LLM、rerank、ASR、TTS 及其他服务商的协议与默认值不在修改范围内。

## 修改前的链路与根因

### 界面配置已经保存

模型管理界面的 Qwen 配置包含以下字段：

| 界面字段 | 保存字段 | 当前默认值 |
| --- | --- | --- |
| Base URL | `LLMServer.config.openai_api_base` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| API Key | `LLMServer.config.openai_api_key` | 由用户填写 |

实际调用链为：

```text
modelProviderFields.ts 定义 Qwen 字段
→ CustomForm.getData 返回配置
→ ModelConfig.handleSave 将配置放入 config
→ finetune.ts 调用 POST 或 PUT /api/v1/llm
→ LLMService 保存 LLMServer.config
→ BishengBase.get_server_info_config 读取配置
→ embedding._get_qwen_params 组装客户端参数
```

新增和修改服务商时，服务层已经对地址、凭证等字符串清理首尾空白。问题出在最后一步：embedding 的 Qwen 参数处理只将 `openai_api_key` 映射为 `dashscope_api_key`，没有读取服务商的 `openai_api_base` 或 `base_url`；客户端映射也仍指向 `DashScopeEmbeddings`。

因此，界面虽然能保存地址，该地址却没有通过这条参数链传入 embedding 客户端。该结论来自代码及参数函数的隔离执行，不能据此推断某个已部署环境的实际出站地址。

### LLM 已有可参考实现

`llm.py` 的 `_get_qwen_params` 先调用本模块的 `_get_openai_params`，完成凭证与地址映射，再在未配置地址时补充 Qwen 默认地址。客户端为 `ChatQwen`，其父类为 `ChatOpenAICompatible`。

embedding 应参考这一组装方式，复用 **embedding 模块自己的** `_get_openai_params`。LLM 中的 `stream_usage`、联网搜索和流式输出参数属于聊天能力，不应带入向量请求。

## 阿里云接口依据

依据用户提供的[阿里云向量化文档](https://help.aliyun.com/zh/model-studio/embedding)，文本向量支持 OpenAI 兼容调用。配套[同步接口 API 文档](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)说明，SDK 接收 Base URL，请求发送至其下的 `/embeddings`；例如北京地域当前示例为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。部署时应填写实际业务空间和地域对应的地址。

界面填写的是 API 根地址，不是带 `/embeddings` 的完整接口地址，也不是 DashScope 原生 `/api/v1/services/embeddings/...` 地址。自建网关同样需要提供 OpenAI 兼容的文本向量接口。

## 后端实现

### 客户端映射

在 `src/backend/bisheng/llm/domain/llm/embedding.py` 中：

1. 将 `_node_type[LLMServerType.QWEN.value]["client"]` 改为已有的 `OpenAIEmbeddings`。
2. 移除该文件不再使用的 `DashScopeEmbeddings` 导入。
3. 改写 `_get_qwen_params`，复用本文件的 OpenAI 参数处理，并补齐 Qwen 默认值。

保留 LangChain 的 `Embeddings` 接口，底层由 OpenAI Python SDK 发起请求；无需另写直接使用 `openai.OpenAI` 的适配器。仓库已依赖这些组件，不需要为了本次切换升级依赖或删除全局 DashScope 依赖。

### 地址与凭证优先级

| 参数 | 处理规则 |
| --- | --- |
| `model` | 使用已保存的 `LLMModel.model_name`，保持现有优先级 |
| `base_url` | 服务商 `openai_api_base` → 服务商 `base_url` → Qwen 默认地址 |
| `api_key` | 服务商 `openai_api_key` → 服务商 `api_key` → 现有 OpenAI 适配的 `"empty"` 占位值 |
| `openai_proxy` | 复用现有 `usable_proxy_url` 的过滤与传递逻辑 |
| `check_embedding_ctx_length` | 保持现有 OpenAI embedding 适配的 `False`，发送原始文本 |
| `chunk_size` | 按模型名称选择默认值和上限，见下文批量规则；未知型号默认 `10` |
| `encoding_format` | 在 `model_kwargs` 中默认设为 `"float"` |

Qwen 默认地址继续与现有 LLM 保持一致：`https://dashscope.aliyuncs.com/compatible-mode/v1`。这是项目的兼容默认值，不代表所有地域和业务空间都应使用该地址；界面显式配置始终优先。

组装时需要处理缺失值、空字符串和 `None`，并去掉地址末尾的 `/`。当前 embedding 通用 OpenAI helper 对部分空值直接执行 `.rstrip()`，Qwen 路径应先在配置副本中准备有效地址，再复用该 helper，避免扩大到其他服务商的行为修改。

服务商凭证、地址和模型名称优先于模型高级参数 `user_kwargs` 中的同名配置。其他高级参数继续透传，支持现有的字典与 JSON 字符串形式；例如 `dimensions`、超时和重试参数遵守客户端及服务端约束。Qwen 专用默认值使用补缺方式，不覆盖用户有效的显式设置；其中 `chunk_size` 还须通过下文的批量上限校验。组装过程中不得修改持有的服务商或模型配置对象，包括嵌套的 `user_kwargs` 与 `model_kwargs`。

不再生成或发送 `dashscope_api_key`。缺少真实 API Key 时，`"empty"` 只是沿用的客户端占位规则，不能视为阿里云认证可用。

### 批量与返回格式

旧 `DashScopeEmbeddings` 会自行拆分请求。锁定版本 `langchain-community==0.4.2` 中，v1、v2 每批 25 条，v3、v4 每批 10 条；直接换用 `OpenAIEmbeddings` 会失去该默认策略。新适配应按模型区分批大小，既避免超过接口上限，也保留各型号的批量效率。

依据阿里云当前[同步接口文档](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)，建立 Qwen 文本向量模型的批量映射：

| 模型名称 | 默认每批条数 | 已知单次请求上限 |
| --- | --- | --- |
| `text-embedding-v1` | 25 | 25 |
| `text-embedding-v2` | 25 | 25 |
| `text-embedding-v3` | 10 | 10 |
| `text-embedding-v4` | 10 | 10 |
| `qwen3.7-text-embedding` | 20 | 20 |
| `qwen3.7-text-embedding-flash` | 20 | 20 |
| 未知型号或网关自定义别名 | 10 | 未知，不能把默认值当作已确认上限 |

处理规则如下：

1. 以已保存的实际 `model_name` 精确匹配。只有明确列入映射的型号才使用对应上限，不通过宽泛前缀猜测新版本的能力。
2. 未配置 `user_kwargs.chunk_size` 时，使用表中的默认批大小。
3. 显式配置必须是正整数，布尔值、字符串、`None`、零和负数均在客户端初始化前拒绝，并明确指出参数无效。已知型号允许调小；超过型号上限时报错，提示模型名称与允许上限，不静默截断或发送超限请求。
4. 未知型号默认每批 10 条。用户可按实际服务能力显式设置正整数，但这不是平台确认该型号支持此批大小；若网关不接受请求，应显式报告失败，不自动缩批重试。
5. 自定义 Base URL 不改变已知型号的上限。如果网关限制更小，可显式调小批次；网关别名按照未知型号规则处理。
6. 将最终批大小传入 `OpenAIEmbeddings.chunk_size`，由客户端按输入顺序拆批。这里限制的是每次请求的文本条数，不是文件切片长度；单条文本的 Token 上限仍由实际模型约束，不按字符数截断文本。

批量验收至少覆盖以下边界，均检查返回数量及输入顺序：

| 模型 | 输入条数 | 未覆盖默认值时的请求批次 |
| --- | --- | --- |
| v1、v2 | 26 | `25 + 1` |
| v3、v4 | 21 | `10 + 10 + 1` |
| qwen3.7 标准与 flash | 21 | `20 + 1` |
| 未知型号 | 11 | `10 + 1` |

另须检查恰好达到上限时只有一次请求，以及显式调小批次后的拆分结果。

显式使用 `encoding_format="float"` 可以避免依赖不同网关的 base64 返回行为；阿里云[接口文档](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)说明新旧网关的实际返回格式存在差异。向量仍交给 `BishengEmbedding` 执行现有归一化处理。

## 兼容影响

### 查询语义需要回归

旧客户端的 `embed_documents` 显式传递 `text_type="document"`，`embed_query` 显式传递 `text_type="query"`。阿里云[向量化文档](https://help.aliyun.com/zh/model-studio/embedding)将 `text_type` 列为 DashScope SDK 和 API 专有能力。

改用 OpenAI 兼容接口后，不应宣称查询向量与旧调用逐值一致，也不应把 `text_type` 塞入 `extra_body` 后就假定它生效。需要使用既有知识库的固定问题集比较召回结果，确认新查询向量与已有文档向量的匹配效果。

不自动重建知识库。模型名称、实际模型版本、输出维度和召回结果验证一致后，再判断能否继续使用存量向量；若需要重建或调整模型，另行确定迁移方案。仅维度相同不足以证明向量空间兼容。

### 高级参数与模型类型

`dimensions` 使用 OpenAI 兼容接口的复数名称，不把 DashScope 的 `dimension` 静默等同处理。已有高级参数若使用原生协议字段，需要核对后调整，不能承诺任意旧参数都可直接迁移。

本次仅覆盖文本稠密向量。阿里云[向量化文档](https://help.aliyun.com/zh/model-studio/embedding)中，多模态向量属于另一条接口能力，不纳入此次客户端切换的支持声明。

## 验收要求

以下为实施后的检查项，尚未执行产品验收。

| 编号 | 场景 | 预期 |
| --- | --- | --- |
| AC-QE-01 | Qwen embedding 创建客户端 | 实际使用 `OpenAIEmbeddings`，不走 `DashScopeEmbeddings` |
| AC-QE-02 | 界面填写自定义 Base URL 并保存 | 查询和文档向量请求均发送至该地址下的 `/embeddings` |
| AC-QE-03 | 两个地址字段同时存在 | `openai_api_base` 优先；末尾斜杠不导致路径重复 |
| AC-QE-04 | 地址缺失、空字符串或 `None` | 使用项目 Qwen 默认地址，不因 `.rstrip()` 抛错 |
| AC-QE-05 | 凭证与高级参数冲突 | 服务商凭证、地址和保存的模型名称生效，不生成 `dashscope_api_key` |
| AC-QE-06 | 高级参数分别使用字典和 JSON 字符串 | 有效参数保留，输入配置及嵌套对象不被修改 |
| AC-QE-07 | 各型号按默认批次执行边界输入 | v1、v2 为 25；v3、v4 为 10；qwen3.7 标准与 flash 为 20；拆批结果符合上表，返回数量及顺序正确 |
| AC-QE-08 | 检查实际 HTTP 请求体 | `input` 为原始文本，默认 `encoding_format` 为 `float`，无聊天专用参数 |
| AC-QE-09 | 同步接口及模型探测所走的异步接口 | 返回合法向量；既有归一化与失败状态处理保持有效 |
| AC-QE-10 | 自定义地址不可达、凭证无效或模型无效 | 显式报告失败，不改走默认地址或其他客户端 |
| AC-QE-11 | 其他 embedding 服务商及 Qwen LLM | 客户端映射与已有参数行为不变 |
| AC-QE-12 | 存量知识库与新增文件 | 完成上传向量化、召回对比和回答引用检查，记录模型与向量维度 |
| AC-QE-13 | 已知型号显式配置批大小 | 正整数且不超过上限时按配置拆批；超过上限或类型、取值无效时，在发起请求前报错 |
| AC-QE-14 | 未知型号或自定义别名 | 未配置时每批 10 条；有效显式正整数按配置执行，不猜测型号上限，不因失败自动缩批重试 |
| AC-QE-15 | 自定义 Base URL 配合已知型号 | 继续执行型号批量上限；允许按网关要求显式调小，同步与异步调用拆批规则一致 |

新增后端测试位于 `src/backend/test/llm/test_qwen_embedding_provider.py`，覆盖参数组装、客户端选择与基于 mock HTTP transport 的请求行为。离线测试成功只能证明客户端行为，真实网关地址、阿里云模型权限和检索效果还需联调。

联调时在界面保存自定义地址，通过网关访问记录核对 `/embeddings` 请求；再执行单条查询、超过一批的文档向量化及知识库检索。模型验证接口 `POST /api/v1/llm/verify` 即使探测失败也可能返回 HTTP 200，必须检查业务返回中的 `status`、`remark` 和实际调用结果。

## 实施文件与代码索引

| 文件 | 用途 |
| --- | --- |
| [embedding.py](../../../src/backend/bisheng/llm/domain/llm/embedding.py) | 核心修改点；客户端映射、Qwen 参数、统一向量封装 |
| [llm.py](../../../src/backend/bisheng/llm/domain/llm/llm.py) | 参考 `_get_openai_params` 与 `_get_qwen_params` 的地址和凭证处理 |
| [chat_qwen.py](../../../src/backend/bisheng/core/ai/llm/chat_qwen.py) | Qwen LLM 的 OpenAI 兼容客户端继承关系 |
| [modelProviderFields.ts](../../../src/frontend/platform/src/pages/ModelPage/manage/modelProviderFields.ts) | Qwen 界面字段及默认地址 |
| [ModelConfig.tsx](../../../src/frontend/platform/src/pages/ModelPage/manage/ModelConfig.tsx) | 实际界面保存入口 |
| [finetune.ts](../../../src/frontend/platform/src/controllers/API/finetune.ts) | 界面实际使用的服务商新增和更新请求 |
| [llm 服务](../../../src/backend/bisheng/llm/domain/services/llm.py) | 配置保存、空白清理和模型探测 |
| [base.py](../../../src/backend/bisheng/llm/domain/llm/base.py) | 服务商与模型配置读取 |
| [uv.lock](../../../src/backend/uv.lock) | 已有依赖：`langchain-openai==1.2.2`、`openai==2.41.0`、`langchain-community==0.4.2` |

## 验证结果

2026-10-21 完成以下离线验证：

- 新增 Qwen embedding 测试 140 项，覆盖已知型号、未知别名、参数冲突与配置对象不变性，以及真实 LangChain 和 OpenAI SDK 通过 mock HTTP transport 发出的请求。
- 每个型号分别验证恰好一批、超过一批一条、超过两批一条，并覆盖同步封装、异步封装和底层 SDK 异步接口。请求地址、认证、原始文本、浮点格式、输出数量和顺序均验证通过。
- 认证错误、无效请求、模型不存在、限流、服务端错误和连接失败均向上报告；未发生地址回退或自动缩批。
- 与 Qwen LLM、其他聊天客户端、推理内容兼容、模型探测和共享模型读取测试合并执行，结果为 **192 passed，1 skipped**。跳过项为需要真实 `QWEN_API_KEY` 的 Qwen LLM 在线调用。
- Ruff、格式检查、架构守卫及差异空白检查通过。

复现测试选择，在 `src/backend` 下执行：

```bash
python -m pytest \
  test/llm/test_qwen_embedding_provider.py \
  test/llm/test_qwen_provider.py \
  test/llm/test_provider_chatmodels.py \
  test/llm/test_reasoning_content_compat.py \
  test/llm/test_model_status_verify.py \
  test/llm/test_llm_share_fallback.py -q --disable-warnings
```

本地验证复用了主检出的 `.venv`，通过 `PYTHONPATH` 指向本工作目录源码，并以 `config` 环境变量指定已有配置文件，没有复制或修改运行配置。HTTP 请求被 mock transport 接管，测试未调用付费模型接口。

相关的 `test_qwen_provider.py` 原先通过 AST 提取函数，遗漏了 `usable_proxy_url` 依赖；干净实施基线复现相同的 3 项失败。该测试现已改为直接导入实际参数函数，3 项均恢复通过，Qwen LLM 业务代码未修改。

AC-QE-02 的请求地址传递部分已自动验证，界面保存与真实网关访问记录仍需联调；AC-QE-12 的存量知识库、上传和检索效果尚未验收。尚未部署。
