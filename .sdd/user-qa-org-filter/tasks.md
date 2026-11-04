# USER-QA-ORG 实施记录

设计 1.0 已确认后实施。状态：代码已落地，隔离测试已跑，真实回刷未跑。

| 任务 | 依据 | 结果 |
|---|---|---|
| T1 三列纯函数与合并规则 | AC-UQ-002、AC-UQ-003、AC-UQ-007 | `belonging_organization.py`，参与度合并保留已记下的部门 |
| T2 新提问、登录、名册和新增用户写入 | AC-UQ-002、AC-UQ-008 | 问答复制提问人三级；登录脚本同步三列；新增用户取唯一主部门 |
| T3 数据集维度与分组空键 | AC-UQ-001、AC-UQ-003、AC-UQ-006 | 用户和问答数据集声明三列；内容统计不加 missing |
| T4 历史回刷任务 | AC-UQ-007、AC-UQ-008 | `backfill_belonging_organization_names`，只改三列 |
| T5 隔离测试 | 上述 AC | `test/telemetry/test_belonging_organization.py` 10 条通过 |

验证命令：`src/backend` 下 `.venv/bin/python -m pytest test/telemetry/test_belonging_organization.py` 等，10 条新用例及相邻回归通过。`ruff check` 通过。`scripts/arch-guard.sh` 通过。未连 171，未跑页面。
