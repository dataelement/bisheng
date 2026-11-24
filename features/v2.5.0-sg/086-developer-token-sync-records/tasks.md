# 086 实施任务

| 项 | 值 |
|---|---|
| 需求 | requirements.md v0.2.0 |
| 设计 | design.md v0.3.0（已确认可编码） |
| 状态 | 开发完成，待独立验收 |

| ID | 目标 | 依据 | 依赖 | 边界 | 验证 |
|---|---|---|---|---|---|
| T1 | 迁移：`error_message`→LargeText；加 `(developer_token_id, id)` 类索引 | D1 | — | 仅 `filelib_scheduled_sync_run_log` | 迁移可 upgrade；双库注释 |
| T2 | 统一 `finalize` helper：truncate 16KB、脱敏、best-effort 写 | INV-3/4 | T1 | open_endpoints 或 developer_token 小模块 | pytest TC-DTSR-05/06/10 |
| T3 | file/sync、检化验 sync 收尾写入；retrieve 不写 | REQ-004 AC-04 | T2 | 仅同步路径 | TC-DTSR-07/08 |
| T4 | 汽车板继续写同表；保证 token_id；管理 list 按 token | REQ-004/005 | T2 | 复用旧写入 | TC-DTSR-09 |
| T5 | `GET .../developer-tokens/{id}/sync-records` | REQ-001/002 | T1 | 权限同 Token 详情 | TC-DTSR-01/02/03 |
| T6 | Platform：同步记录弹窗+详情复制；删汽车板最近执行 | REQ-001/003/005 | T5 | platform only | 源码/vitest；UI 待验收 |
| T7 | 研发测试 + ruff + arch-guard | AC-01～06 | T2–T6 | 无浏览器 E2E | pytest 相关文件 |

独立验收：UI 点选、真实同步失败一条 — 提测后由测试岗位执行。
