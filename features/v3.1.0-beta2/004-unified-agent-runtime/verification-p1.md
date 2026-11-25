# F004 P1 等价性验证记录（T039）

**结论**：自动化部分已完成且通过；114 上的界面步骤**没有执行**，AC-34 的 `prep` 实测值**没有取得**。本文件如实区分两者。

## 1. 已执行的验证（本地，2026-11-18，提交 fa58a2f34e）

| 项 | 方法 | 结果 |
|---|---|---|
| 开关关闭时行为不变 | 回归选择集 `test/linsight test/workstation test/open_api test/api/test_route_path_naming.py test/memory test/citation`，与 P1 第一批提交后的结果逐用例对比 | 无新增失败；120 失败、10 错误均为改动前已有（本地无中间件） |
| `direct` 运行：出字、续租、停止、ask_user 挂起与恢复、单次准入、不提前建目录 | `test/workstation/test_direct_run.py`（16 个，脚本化模型 + fakeredis） | 通过 |
| 回答行结构与今天一致 | `test/workstation/test_run_projectors.py::test_direct_answer_row_shape_unchanged` 等 11 个 | 通过 |
| 发送与订阅接口、旧 SSE 帧转译 | `test/workstation/test_unified_run_api.py`（12 个） | 通过 |
| 深度研究在开关开与关时，旧 WebSocket 事件类型序列相同 | `test/linsight/test_planned_run_unified.py::test_legacy_ws_still_receives` | 通过 |
| 开放 API 应答在开关开与关时逐字段相同 | `test/open_api/test_task_mode_contract_unchanged.py`（15 个） | 通过 |
| 附件读取进度事件在 2 秒内出现 | `test/workstation/test_attachment_progress_event.py`（假时钟） | 通过 |
| 指标行 `BS_METRIC domain=agent_run` | `test_direct_run.py::test_metric_line_emitted` | 通过 |

这些测试用脚本化模型和内存替身，没有连接真实的 MySQL、Redis、MinIO 和模型。

## 2. 没有执行的验证

| 项 | 没执行的原因 | 需要谁做 |
|---|---|---|
| 114 上打开测试租户的开关，用未改的前端跑直接回答（带工具）、带附件的直接回答、深度研究（含一次提问、一次停止），逐项对比界面 | 需要在 114 的界面登录。执行这一步的 agent 不能在该地址输入账号密码 | 人工 |
| 用 `s5_first_char_timing_from_logs.py` 取 `prep` 的中位数与 90 分位，与 AC-34 的阈值比较 | 依赖上一项产生的日志 | 人工 |
| 114 部署本分支 | 本分支把 deepagents 升到 0.7.39，114 的虚拟环境不会随 `deploy.sh` 同步；114 当前运行 `feat/3.1-beta2`，部署会影响其他验证 | 人工决定时机 |

## 3. 执行界面步骤前必须知道的限制

以下能力在 P1 的 `direct` 运行里**尚未接入**，对比界面时会表现为与旧链路不一致。它们由 P3 的 T053、T055、T059 接入：

1. 引用角标、长期记忆、读图、技能。
2. 输出侧内容安全替换。
3. 工具的显示名（旧帧里显示工具名，不是“联网搜索”这类中文名）。
4. 未改造的前端在运行中再发消息，只收到结束帧；`direct` 运行遇到提问时看不到问题内容。

因此建议把界面等价性验证放到 P3 完成之后与 T062 一起执行，P1 阶段只对测试租户开开关。

## 4. 人工执行步骤（待执行）

1. 查 114 无进行中的深度研究：`mysql -ubisheng -p -D bisheng -e "select id,status from linsight_session_version where status='in_progress'"`。
2. 同步虚拟环境（`uv sync --frozen`），部署本分支，重启 backend 与 linsight worker。
3. 对测试租户调用 `POST /api/v1/workstation/config/daily`，带 `unified_runtime_enabled: true`。
4. 按上表三种场景各跑一次，记录与开关关闭时的差异。
5. `grep "BS_METRIC domain=agent_run"` 取 `prep_ms`，计算中位数与 90 分位，填入下表。

| 场景 | 样本数 | prep 中位数 | prep 90 分位 | AC-34 阈值 | 是否达标 |
|---|---|---|---|---|---|
| 直接回答（不带附件） | 未测 | 未测 | 未测 | 见 spec AC-34 | 未测 |
