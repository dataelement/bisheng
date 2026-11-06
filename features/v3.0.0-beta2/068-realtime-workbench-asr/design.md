# 实现设计

历史开发基线：3007 源码 225995a246a64985ab0613e46c6f5680b9d5f5ab；F068@54d0719e 仅作已审阅参考。遵循 docs/constitution.md 的分层、租户、限流及凭据规则。

1. 用户要求界面简化。一个 ASR 配置和一个语音按钮，已登记的实时型号自动使用 WebSocket。暂停立即停止采集，内部完成协议收尾；期间普通麦克风暂时禁用，收尾后可继续下一次录音。发送动作在该次识别完成后开放，保留手动发送。
2. Paraformer 与 Qwen 使用独立协议映射，统一输出带分段 ID 的全文片段事件。供应商识别完成标志先于资源关闭；发送完成指令后继续读最终结果。旧实现先等待结果再发停止，会丢失最后一句。
3. 流式模型同样提供文件转写桥接：沿用 BaseASRClient 的 ffmpeg 标准化，按实时协议发送 PCM 并收集最终文字。这使原检测、知识库文件识别及旧 POST 仍可使用同一配置，避免双配置的迁移成本。检测要求有效最终文本；正常用户无语音得到空字符串。
4. 模型能力精确登记；模型名称含 realtime 不能推导协议。16 kHz 型号通过 capabilities.py 登记：阿里 paraformer-realtime-v2/v1、qwen3-asr-flash-realtime；火山 bigmodel；百度 1537/15372/15376/1737/17372；腾讯官方列出的 16k 引擎。供应商地址从现有 Base URL 解析，北京旧域名/业务空间域名及 Qwen 海外地域按配置使用。
5. 两个前端共用纯 TypeScript 音频和会话模块，保留各自请求包装及组件。每次开始绑定独立插入范围；中间结果替换该范围，最终结果幂等提交。手工编辑范围外的内容平移锚点；编辑范围内的内容交还用户并停止录音。
6. 3007 HTTP 内网入口受浏览器麦克风安全上下文约束；部署健康与协议测试不能代替真实浏览器及真实模型验证。
7. 两个前端统一通过 `getAsrWebSocketUrl` 构造同源识别地址，先规范化部署前缀，再连接 API 路径，并保留访问端口。Client 的实际 `BASE_URL` 为 `/workspace`，直接拼接 `api/...` 曾产生 `/workspaceapi/...`，被页面路由接收并使 WebSocket 握手失败；回归覆盖前缀有无尾斜杠、平台根路径及 HTTPS。

协议参考：
- https://help.aliyun.com/zh/model-studio/websocket-for-paraformer-real-time-service
- https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-client-events
- https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-server-events

## 多厂商适配

- 保留现有 qwen、volcengine、qianfan、tencent 服务商类型。语音凭据使用 server.config 的 speech_* 字段，LLM 与 ASR 分别读取各自凭据。数据库结构保持现状。
- 连接对象分别实现供应商的 start/send_audio/finish/events，统一复用流式收尾、文件桥接和取消清理。工作台接口继续输出 partial/final/completed。
- 火山：bigmodel_async 双向流式端点；实现大端长度、gzip、序号和终帧标记。请求 result_type=full，整段累计文本绑定同一 segment_id，允许服务商修订此前文本。以最终服务器帧结束，解析器校验长度和解压上限。
- 火山新控制台使用 speech_api_key，旧控制台选择 app_key 模式后使用 speech_app_id/speech_access_key；speech_resource_id 对应已开通的 bigasr 或 seedasr 时长/并发资源。
- 百度：使用语音应用 speech_app_id/speech_api_key，发送 START、PCM、FINISH；按 sn 区分句子并去重。FINISH 后收到最终句子及正常 1000 关闭才成功，异常关闭和遗留中间句明确报错。15376 自动附带 user 参数。
- 腾讯：speech_app_id/speech_secret_id/speech_secret_key 生成 HMAC-SHA1 签名，签名前原文排序，签名后 URL 编码。先校验握手，按 index/slice_type 合并句子，收到 final=1 后完成。每个连接独立 voice_id，并按音频时长控制发送节奏，消化浏览器握手期间积压的数据。
- 新语音密钥纳入 JsonFieldMasker 的脱敏与编辑回填规则。配置页仅含 ASR 时展示语音字段，同时存在其他类型时分别展示通用字段和语音字段。火山/腾讯只增加 ASR 能力，TTS 入口沿用已有范围。
- 模型配置组件拆分到 600 行以内，原中文文案提取到三语资源；高级参数模板仅作编辑提示，打开对话框保持已保存参数，用户保存时提交。

官方协议依据（2026-09-20 查阅）：
- 火山：https://docs.volcengine.com/docs/DoubaoVoice/LargemodelstreamingautomaticspeechrecognitionAPI?lang=zh
- 百度：https://ai.baidu.com/ai-doc/SPEECH/jlbxejt2i
- 腾讯：https://cloud.tencent.com/document/product/1093/48982

实际账号的权限、额度和识别质量需要分别验证。当前接入边界是以上原生协议和登记的型号。


## 2026-10-15 合入当前 3.0

目标基线为 `upstream/feat/3.0.0@fbb9bc60651d4b60d5b40eda8f538be207958cc5`。从 3007 分支选取 `2bd865d69`（流式及连续输入）、`b3a0e3e07`（WebSocket 地址）、`044bbd241`（三家厂商扩展），按当前接口整合。

- 四家流式适配实现当前 `BaseASRClient.transcribe_file()` 合同，返回 `ASRTranscript`，保留句子文本并沿用公共文本拼接规则。当前统一事件提供文本分段，时间字段保持空值。文件转写覆写型号时创建独立客户端并保持原有地域和凭据，已绑定的客户端保持原配置。
- 公共 ASR 厂商能力判断与客户端工厂使用同一映射，知识媒体文件转写可识别新增厂商。原 OpenAI 代理规范化保持当前行为。
- Client 通过现有 `useVoiceTarget` / `transcribeVoice` 路由文件转写。发布应用访客沿用带 `flow_id` 的 v3 接口；登录工作台按模型能力选择 v1 实时或文件接口。实时接口沿用登录依赖、租户中间件、配置绑定与限流。
- 模型配置保留当前 `ModelItem` 拆分、型号去空格、高级参数和服务商默认字段。新增独立语音配置区；仅 ASR 的厂商校验语音凭据，混合配置同时校验通用字段。
- 输入框保留当前附件类型、视觉模型与上传状态校验。语音识别期间先完成本次识别，再开放手动发送。
- 数据库结构和既有配置继续兼容。代码回退可恢复原语音入口，新增的 `speech_*` 配置字段可保留在服务商配置中。
