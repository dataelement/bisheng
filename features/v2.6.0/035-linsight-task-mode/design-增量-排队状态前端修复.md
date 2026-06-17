# Design 增量 · 任务模式排队状态前端修复（F035 follow-up）

> 版本：v2.6.0 · 状态：实现中 · Owner：GuoQing Zhang · 关联：[design.md](./design.md) §3.4、worker.py 队列机制、[track-h-ui-spec.md](./track-h-ui-spec.md)
> 本文是 F035 Track J 统一入口上线后的纯前端缺陷修复，不改后端、不改 WebSocket/消息流协议。

---

## 背景

任务模式发起链路（F035 Track J 统一到日常会话入口）：

```
POST /workstation/chat/completions (task_mode:true)  →  只创建 session_version + 回 linsight_task_handoff，不入队
   → 前端 createLinsight 播种 store
   → POST /linsight/workbench/start-execute            →  queue.put(svid) 真正入 Redis 队列
   → 连接 task-message-stream WebSocket
```

后端队列是无界 Redis LIST，**并发上限在 worker 端**（`worker_num × max_concurrency` 信号量），槽位占满时新任务在队列里 FIFO 等待、不拒绝。用户侧唯一的「排队」可见信号是 `GET /workbench/queue-status` 返回的 `index`（前面有几个新任务，被 worker 取走即从 LIST 移除 → index=0）。

## 问题：日常会话任务模式从不查询排队状态

| 链路 | 渲染组件 | QueueCard | 排队轮询 | 现状 |
|---|---|---|---|---|
| 旧 `/linsight` 独立页 | ExecutionFlow | ✅ | ✅ 挂在 Sop/index 的内联 `useQueueStatus` | 能显示（但有缺陷） |
| **F035 日常 `/c` 会话** | **TaskTurnPanel** | ❌ 未引入 | ❌ 完全没接 | **排队态不可见** |

**根因**：`queueCount` 在 `useAiChat` 播种为 0 后再无更新；TaskTurnPanel 既不渲染 QueueCard 也不轮询。旧 `useQueueStatus` 另有三缺陷：① 只在 `versionId` 变化时触发一次（同版本内提交不重查）；② 首帧 `index=0` 即永久停轮询（与「入队未完成/已被取走」竞态）；③ 60s 间隔过粗。结果：start-execute 入队后前端直接连 WS 干等，排队期完全无提示。

---

## 修复（纯前端，共享一份健壮轮询）

### 1. 新增共享 hook `useLinsightQueuePolling(versionId, enabled)`

[`hooks/useLinsightQueuePolling.ts`](../../../src/frontend/client/src/hooks/useLinsightQueuePolling.ts)，取代 Sop/index 内联 `useQueueStatus`：

- `enabled` 进依赖 → start-execute 置 `Running` 后能被重新拉起，不再只认 versionId 变化（修缺陷①）。
- 停轮询条件改为 `index===0`（worker 取走）或 `enabled` 转 false，**首帧 0 不再永久停**（修缺陷②）。
- 间隔 60s → 5s（修缺陷③）。
- 轮询失败 best-effort 下一 tick 重试，徽标非关键路径，绝不卡死视图。
- 只更新 `queueCount`，不再像旧逻辑顺带强写 `status=Running`（status 交给 start-execute 的 `.then` 与 WS，职责单一）。

### 2. 两条链路统一接入

- **[TaskTurnPanel.tsx](../../../src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.tsx)（核心修复）**：引入 `QueueCard` + hook + WS 的 `stop`；`enabled = running && noProgressYet`（`noProgressYet = 无 tasks 且无 sessionSteps`）；渲染排队卡，取消排队复用 `stop`。
- **[ExecutionFlow.tsx](../../../src/frontend/client/src/components/Linsight/Execution/ExecutionFlow.tsx)（旧页收敛）**：改用同一 hook，自包含轮询。
- **[Sop/index.tsx](../../../src/frontend/client/src/components/Sop/index.tsx)**：删除内联 `useQueueStatus` 及注入链路。

### 3. `queueing` 加 `noProgressYet` 守卫（防残留）

两处 `queueing = running && noProgressYet && queueCount>0`。原因：worker 取走后 WS 先吐出 `task_generate` 使 `tasks` 非空、`enabled` 翻 false 停轮询，此时**最后一次轮询的 `queueCount` 可能残留 >0**；不加 `noProgressYet` 会让排队卡与真实任务行并存。加守卫后步骤/任务一出现排队卡即消失，与「worker 已开跑」语义一致。

---

## 影响面与不变量

- **后端零改动**：`/workbench/queue-status` 端点、`queue.index` 语义（只数新任务、resume 不计）、worker 队列机制全部复用。
- WebSocket / 消息流 / `MessageEventType` 10 类协议零改动。
- 取消排队复用既有 `stop`（terminate-execute → `queue.remove` + 置终态 + worker 非终态守卫丢弃残留队列项）。
- 多轮 continue 也走 `queue.put`，TaskTurnPanel 按 versionId 独立挂 hook，自然覆盖。
- 轮询与 WS 交接点清晰：排队期 WS 静默；worker 开跑后首个执行事件使 `noProgressYet` 转 false → 轮询停 + 排队卡消失。

## 验证

- i18n 三语（en/zh-Hans/ja）`com_linsight_queue_{waiting,position,cancel}` 键齐全。
- 改动 4 文件 `tsc --noEmit` 零错误（仓库其余既有 TS 报错与本次无关）。
- 手动回归：worker `--max_concurrency 1` 连发两任务 → 第二个显示「排队中（第 1 位）」、5s 刷新、首个完成后转执行；测「取消排队」删队列项不复活；单任务直跑不误显示排队卡。
