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
