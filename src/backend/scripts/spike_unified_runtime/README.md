# 统一 agent 内核技术验证（F004 前置）

这些脚本为 `features/v3.1.0-beta2/004-unified-agent-runtime/design.md` 提供实测依据。脚本不进生产路径，不读写任何业务数据。

## 运行环境

| 环境 | 用途 | 版本 |
|---|---|---|
| 升级前的后端 `.venv`（提交 d8b911e6fe 及更早） | 0.6.12 基线 | deepagents 0.6.12 / langchain 1.3.11 / langgraph 1.2.10 |
| 升级后的后端 `.venv`，或独立 venv | 0.7 目标 | deepagents 0.7.39 / langchain 1.5.0 / langchain-core 1.8.1 / langgraph 1.2.22 |

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
| S3b | `s3b_diff_todos_alignment.py` | **发现一个既有缺陷。** 改写一条、末尾追加、删除中间一条，`_diff_todos` 都能保持 task id 对齐。**在中间插入一条时错位**：插入项按位置占用了下一条的 id，后面未改动的条目全部换 id。原因是“精确匹配”和“按位置匹配”在同一趟循环里交替执行。允许用户改计划之前必须改成两趟（先对全部条目做精确匹配，再对剩余条目按位置匹配）。 **已修（T007）**：改成两趟后四种改法都是 `aligned: true`，由 `test/linsight/test_stream_event_mapper.py::TestPlanEditAlignment` 守护。 |
| S4 | `s4_async_subagent_transport.py` | **不部署 Agent Server 不可用。** `AsyncSubAgent` 省略 `url` 时，`langgraph_sdk.get_client()` 去 `import langgraph_api.server`。该包未安装时客户端退化为空 ASGI app，`threads.create()` 抛 `TypeError: 'NoneType' object is not callable`。`langgraph-api` 的许可证是 Elastic-2.0，不是开源许可证，引入前需要按 `src/backend/AGENTS.md` 的依赖许可证规则单独评估。 |
| S6 | `s6_alternate_profiles_on_one_thread.py` | **通过。** 用同一个 checkpointer 在一个线程上依次跑 planned → direct → planned（两个档位是两张不同的图），三次都正常完成；`direct` 运行的模型能看到上一次 `planned` 运行的全部消息。 |
| S5 | `s5_first_char_timing_from_logs.py` | **已测，基于 114 的历史日志（10 至 11 月，48 个日常对话请求），不登录、不改服务。** 不带附件（11 个，都勾选了工具）：准备阶段中位数 0.16 秒、p90 1.34 秒；模型首 token 中位数 1.40 秒、p90 2.15 秒；首字符合计中位数 1.64 秒、p90 3.72 秒。带附件（37 个）：准备阶段中位数 9.91 秒、p90 95.70 秒，模型首 token 与不带附件时相同。时间花在模型调用之前的同步附件解析上。**局限**：带附件的样本有 36 个来自 2026-10-26 同一天，量级只说明方向；没有“不勾选任何工具”的样本。 |
| S3c | `s3c_steer_real_model.py` | **通过，覆盖面有限（2026-11-18，114，deepagents 0.6.12）。** 计划写出后立即注入“把第 3 步改成做一份 PPT，不用校对了。”，看模型是否调用 `write_todos` 改写第 3 条。结果见下表。 |
| S2-回归 | `pytest test/linsight test/workstation test/open_api` | **通过（2026-11-18，T004/T005）。** 升级前 3322 通过 / 117 失败 / 10 错误；升级并适配后 3325 通过 / 117 失败 / 10 错误，逐用例对比无新增失败（通过数多 3 个 = 新增 7 个测试 − 删除 4 个旧测试）。基线文件是 `features/v3.1.0-beta2/004-unified-agent-runtime/baseline-before-upgrade.txt`。适配了四处行为变化（`delete` 工具、基础提示词、摘要失败与卸载签名、超窗恢复），见 design §5 坑 13 至坑 16。本地没有中间件，依赖数据库的用例升级前后都失败。 |

### S3c 明细

| 模型 | 成功次数 | 说明 |
|---|---|---|
| deepseek-v4.1-flash（工作台模型 id 9） | 5 / 5 | 每次都在读到插话后的下一次模型调用里改写第 3 条，前两条文字不变 |
| qwen3.8-max（工作台模型 id 16） | 5 / 5 | 其中 1 次第一版计划的三条文字全是空字符串，第二版才有文字；task id 按位置对齐，仍然正确 |

成功的判定：之后的某次 `write_todos` 里第 3 条含“PPT”，并且生产代码的 `_diff_todos` 让三条的 task id 都留在原行。

限制：

- 114 的工作台只配了 2 个模型，没有第 3 个模型的数据。
- 插话都发生在计划刚写出、还没开始执行的时候。执行到一半的插话没有测。
- 脚本用的系统提示词写明“用户要求调整计划时调用 `write_todos`，只改用户要求改的条目”。现行深度研究提示词写的是“只翻转 status，不改写已有文案”，所以这组数字不代表现行提示词下的表现。
- 脚本按 `linsight/worker.py` 的启动方式注册进程内运行时，否则 `LLMService` 拒绝解析模型。脚本只读配置、只调用模型，不写数据库、对象存储和 Redis。

运行方法（在能连上数据库和模型的后端机器上）：

```bash
.venv/bin/python scripts/spike_unified_runtime/s3c_steer_real_model.py --list
```

```bash
.venv/bin/python scripts/spike_unified_runtime/s3c_steer_real_model.py --models 9,16 --runs 5
```

## 尚未完成

| 编号 | 内容 | 为什么没做 |
|---|---|---|
| S3c-补测 | 第 3 个模型；执行到一半的插话；改完深度研究提示词后的重测 | 114 只有 2 个模型；提示词在 P2 才改 |
