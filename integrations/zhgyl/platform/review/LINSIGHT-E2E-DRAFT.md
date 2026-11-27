# 真实 Linsight API 补充验收草案

**尚未执行。** 本稿只做语法与 Ruff 检查；主 Agent 审核并通知执行后才可加 `--execute`。它补充批量边界，不替代浏览器五场景操作，也不能用已完成任务状态代替业务正确性。

当前真实前端链路为 `useAiChat.ts:625` → `useAiChatSSE.ts` → `POST /api/v1/workstation/chat/completions`，不是旧独立 `/linsight/workbench/submit`。

提交体核心字段：

```json
{
  "text": "待最终业务验收清单确认的自然语言问题",
  "clientTimestamp": "2026-11-26T18:00:00",
  "conversationId": null,
  "parentMessageId": null,
  "model": "新平台注册的实际模型ID",
  "tools": [{"id": 123, "tool_key": "实际已授权工具key", "type": "tool"}],
  "task_mode": true,
  "skills": ["本次唯一Skill名称"],
  "files": [],
  "use_knowledge_base": {
    "personal_knowledge_enabled": false,
    "organization_knowledge_ids": [],
    "knowledge_space_ids": []
  }
}
```

API会创建真实会话、用户消息、版本并自动排队。SSE返回：

```text
data: {"event":"linsight_task_handoff","data":{"session_version_id":"真实版本ID","chat_id":"真实会话ID"}}
```

前端随后调用 `POST /api/v1/linsight/workbench/start-execute`，JSON `{"linsight_session_version_id":"真实版本ID"}`，作为自动排队失败的补偿。已运行时为幂等成功；极快已完成时可能拒绝，应先查持久化终态，不能盲目重试或重新提交。

轮询 `GET /api/v1/linsight/workbench/session-version-list?session_id=<chat_id>`，从 `data[]` 找 `id==session_version_id`，读取 `status`、`skills`、`model`、`output_result.answer`。终态为 `completed/failed/terminated/sop_generation_failed`。`waiting_for_user_input` 不是成功；草案不会自动代答，按失败结束并请求取消。

真实原始证据入口：

- `GET /api/v1/linsight/workbench/execute-task-detail?session_version_id=<id>`，`data[].history[]` 为实际持久化执行记录，包含 `name/params/output/step_type/status/call_id`。
- `GET /api/v1/workstation/messages/<chat_id>/agent`，返回该用户有权读取的真实消息及任务行。
- 可选 WS `/api/v1/linsight/workbench/task-message-stream?session_version_id=<id>`，终态事件 `final_result/error_message/task_terminated`；本草案使用持久化轮询，避免增加WS依赖。
- 超时/人工打断取消：`POST /api/v1/linsight/workbench/terminate-execute`，JSON `{"linsight_session_version_id":"真实版本ID"}`。只取消自己本次实际创建的任务，不删除会话。

`UserPayload.get_login_user`使用原生 `access_token_cookie`。草案只接收正常人工登录后保存的私密JSON，支持 `{"cookie":"access_token_cookie=..."}` 或原生会话JWT字段 `access_token_cookie/token/access_token`（转换为该Cookie）；不能传模型或业务服务API Key。它不会登录、生成JWT、绕过验证码或访问D。

草案 `linsight_e2e_draft.py` 默认零网络请求；执行前从当前用户的 `/linsight/skill/selectable`、`/llm/workbench`、`/workstation/config` 目录确认单Skill、明确模型ID和真实工具，不写死D数字ID/key。Case文件结构：

```json
{
  "skill": "procurement-history",
  "model_id": "由主注册脚本返回的新ID",
  "tool_names": ["query_procurement_history", "bisheng_code_interpreter"],
  "question": "最终业务清单确认后的问题",
  "skill_md_path": "/private/runtime/skills/procurement-history/SKILL.md",
  "expected_answer_fragments": ["本轮应出现的业务事实片段"]
}
```

其他场景的工具选择：运输 `transport_execute`；报关/订单 `bisheng_code_interpreter`；预测 `forecast_execute`。预测还须由其页面/业务API创建真实冻结run并绑定后台完成监督；本草案不会伪造这些前置状态，不能单凭一次Chat宣称预测报告完成。

预算为15–300秒（默认180）、最多180个HTTP请求、每次请求不超过10秒，预算后最多额外一次10秒取消。成功/失败真实终态会拉取原始版本、任务记录和消息；若预算已耗尽或提交前失败，只保留已取得ID/安全摘要，不延长预算无限取证。需要后续取证时用上述GET入口读取已知ID，不新建替代任务。

证据目录必须是仓库外新建0700目录，各JSON0600。原始问题、工具参数可能携带预测run capability，因此不外发、不打印正文；stdout仅安全摘要、回答哈希/长度、任务状态、完成工具名称及断言布尔。不存在明确业务断言时，不判passed。基础通过还必须确认单Skill/模型匹配、所选业务工具实际执行、Skill实际read_file记录（参数路径或完整编号正文hash）。

业务输入矩阵仍等“中航采购场景”会话验收后由主 Agent 更新；此稿未导入在研业务引擎或修改Skill正文。
