# F035 灵思任务模式 · Wave-0 共享 fixtures / stub（Track 0 / Lead 交付）

这些产物把跨 Track 契约**冻结成可编程的 stub/mock**，让每条 Track 对着它编程，
无需等生产方完工（解耦并行）。契约真相在
[`features/v2.6.0/035-linsight-task-mode/依赖与契约约定.md`](../../../../../features/v2.6.0/035-linsight-task-mode/依赖与契约约定.md)。

| 文件 | 契约 | 生产方 → 消费方 | 用途 |
|------|------|----------------|------|
| `fake_workspace_backend.py` | **C2** WorkspaceBackend | C → A/B/H | 内存版工作区后端；A/B 跑装配与 E2B 摄入，集成期换真 `workspace_backend.py` |
| `ws_events/event_samples.json` | **C1** WS 事件协议 | A → H | 10 类 `MessageEventType` 各一条权威样例（schema 真相） |
| `ws_events/step_types.json` | **C1** | A → H | `task_execute_step.step_type` 变体（tool/thinking/subagent+namespace/ui_card） |
| `skill_api_mock.json` | **C3** Skill API | D → A/I | `/skill` 端点 mock 响应 + frontmatter spec + 激活契约 + 错误码 |

## 约定

- **C1 是「同一份真相」**：A 写 `StreamEventMapper` 时对这些 JSON 断言输出，H 渲染时对同一 JSON 编程。
  二者都不互相等。A 在 TA 阶段会用真实 `astream` 录制扩充本目录。
- **`MessageEventType` 枚举冻结**（10 类，见 `state_message_manager.py`），新内核所有信号映射进这 10 类，**不新增类型**。
- **`task_id` 稳定性**：首次 `write_todos` 按 `md5(svid + ':' + content)[:8]` 生成；无 in_progress todo 时 `task_id == svid`（session 级伪任务）。
- **契约变更**：改动 C1/C2/C3 字段须走 `依赖与契约约定.md §6` 流程，并**同步更新本目录 fixtures/stub**。

## 用法示例

```python
from test.linsight.fixtures.fake_workspace_backend import FakeWorkspaceBackend

be = FakeWorkspaceBackend(svid="1f3c9a20-...")
be.write("output/report.md", "# 报告\n正文")
assert be.read("output/report.md", offset=0, limit=1) == "# 报告"
assert be.ls("output/")[0].path == "output/report.md"
```

```python
import json, pathlib
samples = json.loads((pathlib.Path(__file__).parent / "ws_events/event_samples.json").read_text())["samples"]
```
