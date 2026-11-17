# 统一 agent 内核技术验证（F004 前置）

这些脚本为 `features/v3.1.0-beta2/004-unified-agent-runtime/design.md` 提供实测依据。脚本不进生产路径，不读写任何业务数据。

## 运行环境

| 环境 | 用途 | 版本 |
|---|---|---|
| 后端 `.venv` | 0.6.12 基线 | deepagents 0.6.12 / langchain 1.3.11 / langgraph 1.2.10 |
| 独立 venv | 0.7 目标 | deepagents 0.7.39 / langchain 1.5.0 / langchain-core 1.8.1 / langgraph 1.2.22 |

建独立 venv（在仓库外的临时目录执行）：

```bash
uv venv --python 3.12 venv07 && uv pip install --python venv07/bin/python --only-binary cryptography "deepagents==0.7.39" langchain-openai fakeredis
```

所有脚本从 `src/backend/` 运行。模型是脚本内的 `ScriptedModel`（按固定剧本回放工具调用），所以结论只覆盖框架行为，不覆盖真实模型的服从度。

## 结论（2026-11-17 实测）

| 编号 | 脚本 | 结论 |
|---|---|---|
| S1 | `s1_todo_and_tool_output.py` | **通过。** 0.7.39 显式传入 `TodoListMiddleware()` 后，`todos` 状态增量仍由 `tools` 节点在 `stream_mode="updates"` 里发出，结构与 0.6.12 逐字段相同。`_diff_todos` 不需要改。 |
| S2 | `s1_todo_and_tool_output.py` + 符号核对 | **可升级，有四处行为差异。** ① `bisheng/` 与 `bisheng_langchain/` 从 deepagents / langgraph / langchain.agents 导入的 57 个符号在 0.7.39 全部存在，`BASE_AGENT_PROMPT` 已标记废弃（0.9 删除）。② 空目录 `ls` 由 `[]` 变为 `No files found`。③ `read_file` 由 `     1\tline1` 变为 `@@ lines 1-2 of 2 @@\nline1`。④ 多一个 `delete` 工具；默认系统提示词由 7588 字符降到 1421 字符。⑤ 0.7.39 要求 `langchain>=1.5.0`、`langchain-core>=1.8.1`，仓库现锁 1.3.11 / 1.4.8，升级 deepagents 必须连带升级这两个包。 |
| S3 | `s3_inbox_middleware.py` | **机制通过。** `before_model` 钩子返回 `{"messages": [HumanMessage]}` 即可把运行中收到的用户消息插到下一次模型调用之前；消息顺序在上一步工具结果之后；消息进入最终状态；最后一次模型调用期间到达的消息留在收件箱，不丢失。 |
| S3b | `s3b_diff_todos_alignment.py` | **发现一个既有缺陷。** 改写一条、末尾追加、删除中间一条，`_diff_todos` 都能保持 task id 对齐。**在中间插入一条时错位**：插入项按位置占用了下一条的 id，后面未改动的条目全部换 id。原因是“精确匹配”和“按位置匹配”在同一趟循环里交替执行。允许用户改计划之前必须改成两趟（先对全部条目做精确匹配，再对剩余条目按位置匹配）。 |
| S4 | `s4_async_subagent_transport.py` | **不部署 Agent Server 不可用。** `AsyncSubAgent` 省略 `url` 时，`langgraph_sdk.get_client()` 去 `import langgraph_api.server`。该包未安装时客户端退化为空 ASGI app，`threads.create()` 抛 `TypeError: 'NoneType' object is not callable`。`langgraph-api` 的许可证是 Elastic-2.0，不是开源许可证，引入前需要按 `src/backend/AGENTS.md` 的依赖许可证规则单独评估。 |
| S6 | `s6_alternate_profiles_on_one_thread.py` | **通过。** 用同一个 checkpointer 在一个线程上依次跑 planned → direct → planned（两个档位是两张不同的图），三次都正常完成；`direct` 运行的模型能看到上一次 `planned` 运行的全部消息。 |
| S5 | `s5_first_char_timing_from_logs.py` | **已测，基于 114 的历史日志（10 至 11 月，48 个日常对话请求），不登录、不改服务。** 不带附件（11 个，都勾选了工具）：准备阶段中位数 0.16 秒、p90 1.34 秒；模型首 token 中位数 1.40 秒、p90 2.15 秒；首字符合计中位数 1.64 秒、p90 3.72 秒。带附件（37 个）：准备阶段中位数 9.91 秒、p90 95.70 秒，模型首 token 与不带附件时相同。时间花在模型调用之前的同步附件解析上。**局限**：带附件的样本有 36 个来自 2026-10-26 同一天，量级只说明方向；没有“不勾选任何工具”的样本。 |

## 尚未完成

| 编号 | 内容 | 为什么没做 |
|---|---|---|
| S3-真实模型 | 3 个模型各 5 次：收到插话后是否调用 `write_todos` 改写计划 | 需要可直连的模型接入地址和密钥 |
| S2-行为回归 | 在 langchain 1.5 / deepagents 0.7.39 下跑 `test/linsight/` 全量 | 需要先在分支上升级依赖并重新生成锁文件 |
