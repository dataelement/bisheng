# 通用图像生成：需求发现

状态：用户已确认规格，并于 2026-11-09 要求去掉 Azure、参考 DSH 简化；当前范围见 [spec.md](./spec.md)。尚未开始图像工具代码改动。

## 已确认需求

- 将 Dalle3 绘画重构为通用 `image_generation` 工具。
- 管理员可以替换 provider 和模型。
- 只支持 OpenAI 兼容图片接口（自定义 Base URL 和模型），去掉 Azure。
- 遵循本轮用户对小功能的要求：优先复用现有配置、工具加载和存储能力，保持文件和核心测试数量精简。

## 当前实现证据

- `src/backend/bisheng_langchain/gpts/load_tools.py` 的 `_get_dalle_image_generator` 将 OpenAI 模型写死为 `dall-e-3`，根据 `azure_endpoint` 判断 Azure，注册键为 `dalle_image_generator`。
- `src/backend/bisheng_langchain/gpts/tools/dalle_image_generator/tool.py` 的工具输入为 `query`，直接返回旧 LangChain DALL-E wrapper 的输出。
- `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/Dalle3.tsx` 只有 OpenAI/Azure 配置，未提供模型输入；保存时也未持久化显式 provider 字段。
- `ToolSet.tsx` 根据 `Dalle3绘画` 名称选择设置表单；预置工具数据及翻译仍有旧名称/键。
- 因此仅在 UI 增加模型输入不足以完成重构，须同时处理加载、配置、显示及历史兼容。

## 已确认的产品范围

1. 工具统一显示为“图像生成”，新工具能力名为 `image_generation`；现有应用保存的 `dalle_image_generator` 引用继续可用，不要求用户重新添加工具。
2. 通过配置服务地址、凭据和模型切换 provider，不新增协议选择。
3. 首版只做文字生成图片；暂不扩展图片编辑、局部重绘、多轮图片对话或厂商异步任务。
4. 用户输入沿用现有 `query`，应用无需为切换服务商修改输入参数。
5. 同时兼容图片 URL 和 Base64 返回，使生成结果能在现有聊天里正常展示；不把大段 Base64 作为工具文本返回。
6. 历史 OpenAI 配置未设置模型时继续按旧默认处理；历史 Azure 配置提示重新配置，不自动回退其他服务。
7. 调用或响应解析失败须明确报错，不将失败伪装成成功或空图片。

## 协议边界

- 首版 OpenAI 兼容指 Images API 的 `POST /v1/images/generations`，不是承诺兼容所有宣称 OpenAI 兼容的聊天接口。
- OpenAI 官方还提供 Responses API 内置 image generation 工具；这是另一种调用流程，首版不作为第二套图像生成入口。
- Gemini 原生、多厂商原生/异步接口及 ComfyUI 等自托管工作流需要各自适配，不靠更换模型名实现。
- 图片参数和返回形态受具体模型影响，不统一强塞 DALL-E 的 size/quality/response_format 默认值。

官方参考（2026-11-09 已读取）：https://developers.openai.com/api/docs/guides/image-generation

参考实现：`/Users/alex/Documents/Code/dataelem/dsh-desktop/packages/dsh-image-generation/lib/provider.js` 与 `index.js`，已读取。仅借鉴兼容协议的调用、地址规范化和结果/错误处理；不引入其桌面插件体系。

## 下一步

按根 AGENTS.md §6 和 docs/SDD-Guide.md §3，需求发现确认后再形成 spec；spec 和设计分别确认后开始实现。正式发布版本/编号尚未分配，本文件放在 local 草稿目录，不修改发布契约。
