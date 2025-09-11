## 事件流转说明
##### 发送消息
- 1.聊天窗口发送消息（ChatInput & useAreaText）-> 生成提交数据（submitDataState）-> 触发监听，发送ws(useWebSocket)
- 2.表单提交（InputForm）-> 触发监听，重复步骤1（useAreaText）
##### 接收消息
- ws监听收到消息(useWebSocket) -> 处理消息分类（useChatHelpers）-> 更新消息（chatsState[chatId].messages）
