# Design 增量 · 任务模式步骤持久化两处修复（F035 follow-up）

> 版本：v2.6.0 · 状态：实现中 · Owner：GuoQing Zhang · 关联：[design.md](./design.md) §3.2/§3.3.1/§3.4
> 本文是 F035 上线后的两处缺陷修复设计，承接 design.md 的事件流/持久化模型，不改前端协议。

---

## 背景

任务执行期事件有两条落点（见 design §3.4）：

| 落点 | 介质 | 刷新后是否可见 |
|---|---|---|
| 消息流 `push_message` | 仅 Redis List（TTL=3600s，LPOP 即弹出） | 否（瞬态） |
| 任务实体 `add_execution_task_step` | Redis + **MySQL 双写**（`LinsightExecuteTask.history`） | 是 |

刷新走 [`get_execute_task_detail`](../../../src/backend/bisheng/linsight/domain/services/workbench_impl.py) → `get_by_session_version_id` → 各任务行 `history`。**未进某条任务行 history 的事件刷新即丢**。由此引出两个缺陷。

---

## 问题一：流式 thinking 被逐 token 落库

**根因**：`messages` 流逐 token 吐 delta，`StreamEventMapper._build_thinking_step` 每个 delta 产一个独立 `ExecStep`（仅共享 `call_id`）；`_handle_exec_step → add_execution_task_step` 对每个 ExecStep **append + 整段 history 回写 MySQL**。N 个 token → history N 条 + N 次全量回写（O(N²)）。

**修复（管理器层按 call_id upsert）**：在 `add_execution_task_step` 内，对带 `call_id` 的步骤做「就地更新」而非 append：

- `step_type == "thinking"`：把新 delta 的 `output` **拼接**到同 `call_id` 既有条目（累积成完整思考），其余字段覆盖。
- 其余（tool start→end、knowledge、subagent）：end 帧**覆盖** start 帧（同 `call_id`，end 帧自带 params + output，是 start 的超集）。
- 无 `call_id`（`NeedUserInput` 的 `call_user_input` 步骤）：仍 append，`set_user_input` 读 `history[-1]` 不受影响。

落库后每个 `call_id` 在 history 中**只留一条最终聚合记录**。实时推流 `push_message` 不变（仍逐 token，前端流式体验不变；前端按 `call_id` merge）。刷新重建：thinking 1 条全文、tool 1 条 end 帧 —— 与旧版「前端 merge 后」渲染等价，**前端零改**。

> 注：thinking 段的 `call_id` 是「每连续段一个」（任一非 thinking chunk 关闭段、下段换新 id，见 mapper `normalize`），故中断后续写的 thinking 用新 id、不会误并到中断前的旧段。

## 问题二：规划期/收尾期/直答的工具步骤不落库

**根因**：mapper 给步骤定 `task_id = current_in_progress_task_id or svid`。无 in_progress todo 时（规划期、收尾期、直答无 todo）步骤 `task_id = svid`。但 DB 无 `id=svid` 的 `LinsightExecuteTask` 行，`add_execution_task_step`/`update_execution_task_status` 命中 orphan 分支直接跳过 → 只进瞬态消息流 → 刷新消失。design §3.3.1 规则4 的「session 级伪任务」从未在 DB 落地。

**修复（建 session 级伪任务行，纯后端）**：

1. **创建**：任务启动时（`_managed_execution` / `_managed_resume` 两个上下文管理器内，覆盖 run/resume/continue 全部入口）幂等插入一条
   ```
   LinsightExecuteTask(id=svid, session_version_id=svid, parent_task_id=None,
                       task_type=SINGLE, status=IN_PROGRESS,
                       task_data={"name": "执行准备", "is_session_global": True}, history=[])
   ```
   `id == svid` 与 mapper 的 orphan `task_id` 对齐，故 `get_execution_task(svid)` 命中、步骤落到它的 history。幂等：已存在则跳过（并发/resume/continue 重入安全）。tenant_id 由既有 SQLAlchemy 事件自动注入（worker 已 restore tenant context）。
2. **完成**：成功/直答完成时把伪任务置 `SUCCESS`（best-effort）；失败/终止由既有 `_set_tasks_failed` 置 `TERMINATED`。
3. **展示**（`get_execute_task_detail`）：① 伪任务 `history` 为空时**剔除**（不渲染空「执行准备」节点）；② 非空时排在根任务**最前**（规划先于子任务）。前端协议不变，伪任务即一个普通根任务节点。

**附带收益**：规划期触发的 HITL（interrupt 路由到 svid）现在 `call_user_input` 步骤能落到伪任务 history，`set_user_input(svid)` 可正确定位 —— 旧版该步骤完全不持久化、续答会失败。

---

## 影响面与不变量

- 前端协议、消息流（push_message）、`MessageEventType` 10 类 **零改动**。
- `get_all_files_from_session` 只用 `execution_tasks[0].session_version_id` + 磁盘 `file_details`，伪任务进列表无副作用。
- `_save_task_info` 的 todo 合并按 8 字符 hash id，与 svid 伪任务 id 不冲突。
- 多租户：伪任务 `tenant_id` 走自动注入，禁手写 WHERE（C3/C4）。

---

## 问题三：HITL 等待用户输入期间刷新后无 loading（且答完无动效）

**现象**：任务模式 `ask_user` 等待输入期间刷新页面 → 输入框看不到、一直加载；答完后也没有 loading 动效。

**根因（两层）**：

1. **前端动效只覆盖两种状态**：`PlanningRow`（仅「running 且还没 todo」）+ `TaskStepRow` 内的任务 spinner（仅「已开始执行的任务」）。todo 已生成但下一个任务还没开始流式、或收尾期，两者都不满足 → 出现「无动效空窗」。叠加 session 级伪任务在 reload 时混进 `tasks` 数组污染 `tasks.length` 判断。
2. **后端从不推送 `user_input_completed`**：`/workbench/user-input` 答完只 `set_user_input` + 重新入队，**没有 `push_message(USER_INPUT_COMPLETED)`**（design §3.3 行5 / §4.5 要求推）。前端 `user_input_completed` 处理器（标记 clarify 完成 + fall-through 刷新状态）永不触发；完成态只靠 `sendInput` 本地乐观更新，刷新即丢。且 session 级 clarify 还跳过了 `set_user_input` → 完成态从不落库 → 刷新后 clarify 卡重现。

**修复**：

- **前端**（`ExecutionFlow.tsx` / `PlanningRow.tsx`）：用 `realTasks = tasks.filter(t => t.id !== versionId)` 剔除伪任务后再判 `planning`；新增 `executing = running && !pendingInput && realTasks.length>0 && !realTasks.some(isTaskRunning)`，在任务行之后渲染一条 `PlanningRow label="正在执行任务"` 呼吸行，桥接「todo 生成→首个任务启动」「任务之间」「收尾期」的空窗。任务正在流式时（`isTaskRunning`）抑制，避免与任务行 spinner 双转。新增 i18n `com_linsight_executing`（zh/en/ja）。
- **后端**（`endpoints/linsight.py`）：伪任务行已存在（问题二），故**统一走 `set_user_input`**（不再 session 级特判），答完 `push_message(USER_INPUT_COMPLETED, data=task.model_dump())`；legacy 无行会话回退为「只入队、不落库」。这样答完前端正规收卡 + 刷新后显示已答状态。

测试：`test/linsight/test_hitl_worker.py` 新增 `test_user_input_pushes_user_input_completed`（断言推 USER_INPUT_COMPLETED）+ 幂等用例补断言不重复推。

---

## 测试

`test/linsight/test_step_persistence.py`（新增）：
- thinking 多 delta（同 call_id）→ history 单条、output 拼接。
- tool start+end（同 call_id）→ history 单条、status=end、含 params+output。
- `NeedUserInput`（无 call_id）→ append，不被 upsert 吞并。
- `_ensure_session_pseudo_task`：首次创建（id/marker 正确）、二次幂等不重复建。
- `get_execute_task_detail`：空 history 伪任务被剔除；非空伪任务排最前。
