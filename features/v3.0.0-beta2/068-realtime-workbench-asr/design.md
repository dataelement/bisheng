# 实现设计

基线：3007 当前源码 225995a246a64985ab0613e46c6f5680b9d5f5ab；F068@54d0719e 仅作已审阅参考。遵循 docs/constitution.md 的分层、租户、限流及凭据规则。

1. 用户要求界面简化。一个 ASR 配置和一个语音按钮，已登记的实时型号自动使用 WebSocket。暂停立即停止采集，内部完成协议收尾；期间普通麦克风暂时禁用，收尾后可继续下一次录音。发送动作在该次识别完成后开放，保留手动发送。
2. Paraformer 与 Qwen 使用独立协议映射，统一输出带分段 ID 的全文片段事件。供应商识别完成标志先于资源关闭；发送完成指令后继续读最终结果。旧实现先等待结果再发停止，会丢失最后一句。
3. 流式模型同样提供文件转写桥接：沿用 BaseASRClient 的 ffmpeg 标准化，按实时协议发送 PCM 并收集最终文字。这使原检测、知识库文件识别及旧 POST 仍可使用同一配置，避免双配置的迁移成本。检测要求有效最终文本；正常用户无语音得到空字符串。
4. 模型能力精确登记；模型名称含 realtime 不能推导协议。首批 16 kHz：paraformer-realtime-v2/v1、qwen3-asr-flash-realtime。供应商地址从现有 Base URL 解析，北京旧域名/业务空间域名及 Qwen 海外地域按配置使用。
5. 两个前端共用纯 TypeScript 音频和会话模块，保留各自请求包装及组件。每次开始绑定独立插入范围；中间结果替换该范围，最终结果幂等提交。手工编辑范围外的内容平移锚点；编辑范围内的内容交还用户并停止录音。
6. 3007 HTTP 内网入口受浏览器麦克风安全上下文约束；部署健康与协议测试不能代替真实浏览器及真实模型验证。
7. 两个前端统一通过 `getAsrWebSocketUrl` 构造同源识别地址，先规范化部署前缀，再连接 API 路径，并保留访问端口。Client 的实际 `BASE_URL` 为 `/workspace`，直接拼接 `api/...` 曾产生 `/workspaceapi/...`，被页面路由接收并使 WebSocket 握手失败；回归覆盖前缀有无尾斜杠、平台根路径及 HTTPS。

协议参考：
- https://help.aliyun.com/zh/model-studio/websocket-for-paraformer-real-time-service
- https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-client-events
- https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-server-events
