# 模型配置统一更新：3006 部署记录

## 当前模型行对齐发布（2026-10-16）

发布 `model-config-alignment-20261016`，基线 `chat-sidebar-clean-20261016-r1`，功能提交 `3326e4dd3393838f363627a6d0045ba2664e61ca`。

模型名称、类型及参数操作区采用各行一致的尺寸，搜索位置单独保留，使 LLM 和 Embedding 的列位置统一。搜索开关增加三语言用途提示：使用供应商内置联网搜索，需模型支持。已只读核对当前百炼后端 enable_web_search → extra_body.enable_search 映射。现有按供应商展示规则沿用，具体型号的搜索能力依赖供应商支持。

112 项相关检查、目标 ESLint、架构守卫和平台构建通过。整体类型检查基线与候选各 4 项，整体源码 Lint 各 13 项，新增均为 0。仅更新 frontend，其他 41 个容器身份保持一致。五个入口、Nginx、Docker healthy、发现接口匿名 401、三语言资源与平台 index 哈希通过，index SHA-256 `3c07b3c293aacef1cfccc2f4e71b78b2a90e99b2de68dc6712538914b0b42ec2`。

回滚目标 `chat-sidebar-clean-20261016-r1`，切回发布链接后重建 frontend。浏览器视觉及实际业务保存验收 NOT_RUN，业务配置保留原值。记录位于 `outputs/model-config-alignment-20261016/`。


## 前一轮紧凑布局与类型名称发布（2026-10-16）

当前发布：`model-config-compact-20261016`；基线 `chat-platform-nav-20261016-r1`；功能提交 `3115b38ea2c99a379632e8e0529d9d798830649c`。

三种语言的类型名称统一为 LLM、Embedding、Rerank、ASR、TTS。模型名称、类型、网络搜索和高级参数按可用宽度同排，空间收窄时自动换行。已有 max_tokens 带入高级参数、确认转换、取消保留及显式重置逻辑沿用。

本地 23 项定向检查、目标 ESLint、架构守卫，服务器 112 项相关检查、平台构建通过。整体类型检查为基线 4 项、候选 4 项，整体源码 Lint 为基线 13 项、候选 13 项，新增均为 0。

本次仅重建 frontend 服务，其他 41 个容器保持原身份。模型管理、DSH、workspace、env、health 入口、Nginx 配置、Docker healthy、发现接口匿名 401、三语言资源与平台 index 哈希核对通过。平台 index SHA-256：`ca8024f00d3bd154a63494503e4ca0f48f9d85fb67acdcfe40302cd23a548539`。回滚目标为 `chat-platform-nav-20261016-r1`，切回链接并重建 frontend 服务。

浏览器视觉、实际业务保存验收：NOT_RUN。业务配置保留原值。记录位于 `outputs/model-config-compact-20261016/`。


2026-10-16 已更新至 http://192.168.106.119:3006/model/management 。

## 前一轮参数布局发布（2026-10-16）

当前发布目录：`/data/bs119/deployments/f054-unified-agent-3006/releases/model-config-parameters-20261016`；基线 `chat-work-beta4-20261016-r5`；功能提交 `1f01a430722e6529d443574768ef1f1a611c34c8`。

展开区第一行包含模型名称、可用供应商的网络搜索开关和高级参数入口，第二行包含模型类型。独立 Token 输入框已移除；旧有效值在高级编辑器中展示，确认修改后移除旧字段并统一保存 user_kwargs；取消只丢弃草稿，显式清空恢复高级参数默认值。Ollama 延续 num_ctx 上下文长度语义。模型配置仍由页底保存统一持久化，本次部署继续保留已有业务配置。

112 项前端相关检查、8 项供应商参数单元检查、当前镜像内 OpenAI、百炼、Ollama、星火参数传递预检、目标文件 ESLint、后端 Ruff 与平台构建通过。类型检查基线与候选均 4 个既有错误；全量源码 Lint 基线与候选均 13 个既有问题；本次新增均为 0。

五个页面/API 入口、Nginx、Docker healthy、三语言资源、发现请求匿名 401、平台 index 哈希通过。平台 index SHA-256：`e86f893f5740e3640e969a8805f03c5219403885803497c2233377aa0230bb5d`。更新 backend、backend_worker、backend_linsight、frontend，当前镜像与部署配置继续沿用基线；其他 38 个容器保持一致。回滚目标为 chat-work-beta4-20261016-r5，切回发布链接后重建这四个服务。

浏览器操作及保存、全部供应商真实推理：NOT_RUN。记录位于 `outputs/model-config-parameters-20261016/`。



前一轮弹窗发布：`/data/bs119/deployments/f054-unified-agent-3006/releases/model-config-dialog-20261016-r2`；基线：`chat-work-beta4-20261016-r2`。分支 `codex/model-discovery-3006`，UI 提交 `b53822674a826009dfb1d1bc865da96d0292cc19`，后端发现功能源自同分支 `3e59137b668a9becb8941b718d12f7d47d572d66`。候选使用当前发布加本功能闭包的组合源码，逐文件哈希见 `outputs/model-config-dialog-20261016/candidate-hashes.json`。

## 本次交互

填写完整 API 后自动打开模型选择弹窗。弹窗提供搜索、类型筛选、当前结果全选、已选计数、已添加状态、未知类型确认及重新获取；确认添加后收起。页面以紧凑列表展示已添加模型、类型与参数摘要，点击【配置】展开名称、类型和参数，手动新增空模型默认展开；服务设置位于列表之后，页底统一保存。

## 实现与环境核对

检查期间 3006 先后发布 chat-work-beta4-20261016-r1、r2。平台和共享 packages 有效源码逐文件一致，沿用在 r1 完整源码加本功能上构建的已测平台制品；候选重新复制 r2 全目录，保留最新 client 制品和其他后端内容。

当前后端缺失模型发现模块，发布前真实请求返回 404。已恢复发现路由、服务、错误码、Anthropic 密钥脱敏与原值复用；LLMService 三方合并保留现有 usable_proxy_url 处理。当前运行与 Compose 的镜像、环境值一致；使用当前镜像预检路由导入、类型识别及代理空值处理通过。四个业务服务重建，其他 38 个容器身份保持一致。

## 检查结果

- 前端相关 96 项检查、三种语言真实资源渲染、目标组件 ESLint、平台构建和架构守卫通过。
- 后端模型发现 44 项隔离单元检查、正确后端配置下的 Ruff、候选路由导入预检通过。
- 全量严格类型检查为基线 4 个既有错误、候选 4 个，新增 0。全量 Lint 为基线 43 个既有问题、候选 43 个，新增 0；其中包括发布目录遗留的 macOS 元数据解析错误。历史 build-* 制品备份已从扫描范围排除；测试运行排除 ._* 元数据，完整源码测试为 13 个文件、96 项通过。
- 模型管理、DSH、workspace、env、health 入口，Nginx、Docker healthy、发现接口匿名请求 401，三种语言资源逐字节一致性全部通过。
- 线上平台 index SHA-256：`a48c545685196dcc021346bad23f172082f44c53f1ed4468090d7e0e740ef7bb`，与候选构建一致。
- 真实 HTTP 只读发现通过：现有连接返回 135 个模型，99 个 LLM、8 个 Embedding、12 个待确认类型、16 个待适配类型。查询通过正常鉴权与保存密钥复用，业务模型配置保持原样。

浏览器操作与保存业务数据：`NOT_RUN`；全供应商兼容性和真实 ASR/TTS 调用：`NOT_RUN`。本次模型配置改动的业务数据迁移范围为空。

## 发布与回滚

后端镜像健康探针间隔 90 秒。首次发布在 API 已就绪、Docker 状态仍为 starting 时提前检查，自动回滚。已修正为同时等待 Docker healthy 与真实 API，最终发布通过。回滚目标 `chat-work-beta4-20261016-r2`；切回链接后重建 backend、backend_worker、backend_linsight、frontend 四个服务。

本次发布保留最终部署日志、候选源码哈希、质量对照结果及真实发现结果。只读辅助脚本结束时出现 aiomysql 连接析构的 Event loop is closed 提示；模型发现请求及结果断言通过，辅助进程退出码为 0。

## 先前发布

2026-10-13：模型发现、类型识别与批量配置发布至 model-discovery-20261013-r2；翻译 namespace 修正提交 26663998e4e67851a6ac28b8111cb077297e88c8，随后以平台前端更新发布至 model-discovery-20261013-r3。当时通过 44 项后端、91 项前端检查与只读模型发现，真实浏览器保存为 NOT_RUN。本次交互改造已替代发现面板布局。
