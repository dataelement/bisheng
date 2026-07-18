# 毕昇后端代码

* Dockerfile 使用 uv 进行 Python 依赖管理

## 调试开关

### `BISHENG_AGENT_DUMP` — 工作台 Agent 聊天 payload 落盘

用于排查"送给大模型的数据是否正确"类问题。开启后，`/api/v1/workstation/chat/completions` 每次调用都会把**完整、未截断**的 payload（system prompt + 工具列表 + 历史消息 + 当前消息）写一份 JSON 到本地磁盘，便于肉眼核对 / 发给协作方。

**默认关闭**，不开启时无任何 I/O 开销。

#### 开启方式

任选一种：

```bash
# 方式一：当前 shell 临时导出后再启动服务
export BISHENG_AGENT_DUMP=1
PYTHONPATH="./" uv run uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --reload

# 方式二：单次启动时带环境变量
BISHENG_AGENT_DUMP=1 PYTHONPATH="./" uv run uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --reload
```

接受的真值（大小写不敏感）：`1` / `true` / `yes` / `on`。其他值视为关闭。

#### 关闭方式

```bash
unset BISHENG_AGENT_DUMP
# 或重启服务不再带该变量
```

#### 输出位置

```
/tmp/bisheng_agent_dumps/<trace_id>.json
```

其中 `<trace_id>` 可以在后端日志 `[agent_chat][dump] wrote full payload -> /tmp/bisheng_agent_dumps/<trace_id>.json` 行中找到，也可以在请求响应头 / 前端 trace 工具里对应到同一次请求。

#### 文件结构

```json
{
  "trace_id": "...",
  "user_id": 3,
  "conversation_id": "4a7c2901cbc24794bd86362ed0e379ce",
  "tool_count": 0,
  "tool_names": [],
  "kb_count": 0,
  "system_prompt": "# 角色\n你是 BISHENG AI 助手...",
  "messages": [
    { "role": "HumanMessage", "content": "..." },
    { "role": "AIMessage",    "content": "..." },
    { "role": "HumanMessage", "content": "..." }
  ]
}
```

说明：
- `system_prompt` 为最终下发给模型的完整系统提示词
- `messages` 严格按下发顺序列出，最后一条为当前用户输入
- 图像类内容（`image_url`）会被替换为 `<base64 omitted>` 占位，避免文件过大

#### 相关代码位置

- 开关与 dump 逻辑：`src/backend/bisheng/workstation/domain/services/chat_service.py` 中搜索 `BISHENG_AGENT_DUMP`
- 调试完毕可手动清理：`rm -rf /tmp/bisheng_agent_dumps`

#### 注意事项

- 该开关仅用于**本地开发 / 线下排查**，切勿在生产环境长期开启——会持续落盘用户对话原文，既占磁盘也有隐私风险
- dump 目录位于 `/tmp`，容器重启或系统清理会自动消失，不作为持久化存档使用
