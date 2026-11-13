# 进度

每完成一个 Wave 追加一节，记录 Wave 验收命令与三条固定命令的关键输出行。

运行约定：后端测试用 `uv run --no-sync python -m pytest`（清代理变量），见 decisions-self.md T001。

## Wave 0（T001–T009）
- 三个子代理完成 V1–V8；`pytest test/memory/spike -q`：27 passed。
- 基线：干净 worktree 上按目录名 crc32 分 8 片，14380 个用例，1242 个既有失败或报错。架构检查基线 51 行（23 行 VIOLATION）。
- V7 推翻深度研究"轮"的前提的一部分 → P-01，按保守做法 C 继续。

## Wave 1（T010–T014）
- `pytest test/database/test_alembic_single_head.py -q`：1 passed；`alembic heads`：`f132_long_term_memory (head)`。
- `pnpm check-i18n`：OK — no new i18n drift。
- 〔架构检查〕ARCH 0；〔分层检查〕LAYER 0。

## Wave 2–6（T015–T040）
- `pytest test/memory test/workstation/test_memory_config.py -q`：逐 Wave 全部通过、无 skipped（Wave 6 末 202 passed）。
- 第一次〔基线比对〕（按位置分片）报 50 个新增失败，根因三个：①记忆测试在合跑时撞上别的套件注册的全局租户过滤（测试接缝加 bypass）；②`test/dsh/test_telemetry.py` 钉死 `ApplicationTypeEnum` 成员、`test/fixtures/table_definitions.py` 手写 `assistant` DDL（P-02，已按 A 处理）；③按位置分片使新目录挪动其他目录的执行顺序（改为 crc32 分片并重做基线）。
- 〔架构检查〕ARCH 0；〔分层检查〕LAYER 0（Wave 7 末再测一次）。

## Wave 7（T041–T048）
- `pytest test/memory -q`：237 passed，无 skipped。
- 〔架构检查〕ARCH 0；〔分层检查〕LAYER 0。
- 〔基线比对〕：merged 14627 cases, 1241 failed/errored；`NEW FAILURES: 0`。
- 按用户 2026-11-13 的建议，Wave 8–13 改为 6 个独立 worktree 并行（Workflow），最后统一合并验证。并行前先把 `dispatch_client` 的 `memory_register` 参数做好（提交 076893d0b2），避免 Wave 9、10 同改 `manager.py`。

## Wave 8–13（T049–T086，6 个并行 worktree）
- 6 个分支全部完成、无未做任务；各自的 Wave 验收：W8 270 passed、W9 275 passed、W10 300 passed、W11 278 passed（均无 skipped）；W12 vitest 5 files / 35 tests passed；W13 jest 6 suites / 38 tests passed。
- 合并顺序 8→13，唯一冲突在 `chat_service._task_mode_stream_completion`（日常入口任务模式的登记），合并为"Wave 11 的钩子 + Wave 8 的登录态回调门控"。
- 合并后：后端全部记忆测试一起跑 412 passed；platform vitest 35 passed；client jest 38 passed；`pnpm lint` 0、`pnpm typecheck` 0（worktree 的 node_modules 改为逐项软链、`@bisheng/*` 指向本 worktree 的 packages 后）、`pnpm check-i18n` OK。
- 第一次合并后〔基线比对〕NEW FAILURES 10：均为 Wave 8 测试在合跑时受 `test/linsight` 遗留的租户 ContextVar 影响，测试夹具固定租户后修复。
- 〔架构检查〕ARCH 0；〔分层检查〕LAYER 0。

## Wave 14–16
- T087 运行器、T088 用例 40 条（加上 T090、T092 各 2 条共 44 条）：`pytest ../../tools/memory_eval/tests` 6 passed。
- T090–T093（P1）：`pytest test/memory ../../tools/memory_eval/tests -q`：232 passed。
- T095 文档回写完成。T089、T094、T096 留给人工。
- 最终〔基线比对〕（合并、T090–T093、夹具修复之后）：merged 14797 cases, 1241 failed/errored；`NEW FAILURES: 0`。
- 用户批准 P-02 后的〔基线比对〕：merged 14797 cases, 1242 failed/errored -> /tmp/f132-current.xml NEW FAILURES: 1 
- 重跑〔基线比对〕：merged 14797 cases, 1241 failed/errored；`NEW FAILURES: 0`（正常结束）。
