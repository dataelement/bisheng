# F016 验证记录

## 本地自动化（bisheng `feat/3.1.0-beta1-016-credit-pricing`）

| 日期 | 范围 | 结果 |
|---|---|---|
| 2026-11-12 | A 组：test/dsh test/llm test/database test/workstation test/channel test/common（不连真实库） | 与基线（3254ab555：3,358 通过 / 73 失败 / 60 报错）逐条对比，新增失败 0 |
| 2026-11-12 | B 组：test/dsh 中使用真实库的文件（Docker MySQL 8.0.46 + Redis 7） | 与基线（99 通过 / 52 失败）逐条对比，新增失败 0；新增的价格快照投影、对账恢复用例在真实 MySQL 上通过 |
| 2026-11-12 | 知识空间、看图、溯源相关 36 个测试文件（改动前后两个工作树） | 前后均为 384 通过 / 5 失败，无差异 |

## 迁移与容量演练

| 演练 | 环境 | 结果 |
|---|---|---|
| MySQL 迁移 | 本机 Docker MySQL 8.0.46，`dsh_model_call` 100 万行 | 加 3 列 0.40 秒；重复执行 0.01 秒；价格快照 JSON 往返一致 |
| 达梦迁移 | — | 不单独演练，交发版前统一回归（2026-11-12 确认） |
| Redis 容量 | 本机 Docker Redis 7，真实准入 / 结算 / 投影确认 | 每次调用 5,203 B → 5,792 B（+11%） |

## 真实环境

待部署后按 runbook 与 test-cases.md 执行（tasks T32）。
