# F070 积分系统 — 上线检查清单（T028）

**关联**: [design.md §4.5](./design.md) · [tasks.md](./tasks.md)  
**版本**: v2.6.0 · 模块 182  
**最近更新**: 2026-08-07

> 勾选表示「本地联调/当前测试环境已验证」；生产环境上线前须再勾一遍并记录执行人/时间。

---

## 1. 迁移与种子

| 项 | 状态 | 备注 |
|----|------|------|
| Alembic `f078_points_system` upgrade（MySQL） | ✅ | 联调库表可读；见 `test_points_dual_db_smoke.py` |
| Alembic upgrade（DM8） | ⬜ CI | macOS 无 dmPython；依赖 Linux CI |
| 种子规则 G*/R*/M* + `point_copy` 存在 | ✅ | `point_rule` / `point_copy` tenant=1 |
| ORM 使用 `dialect_helpers`（无 MySQL JSON/ON UPDATE） | ✅ | 静态检查通过 |

## 2. 组织与排行

| 项 | 状态 | 备注 |
|----|------|------|
| 唯一公司根已打标；抽查四级 | ⬜ 环境相关 | 共享库默认不 mutate；见 G-M3 + `E2E_POINTS_ALLOW_ORG_MUTATE` |
| 排行快照小时任务可跑 | ✅ | `points_refresh_rank_snapshots` / gm3_trigger refresh |
| 首页 TOP10 三 Tab / 无「我」置底 | ✅ | G-M3 |

## 3. 功能开关与自动发放

| 项 | 状态 | 备注 |
|----|------|------|
| `points.enabled` 默认 false，灰度再开 | ✅ | `PointsConf`；本地联调可 true |
| 打开后：上传计分 / 幂等不双计 | ✅ | G-M2 |
| 日 cap / 超管豁免 / P7=B 受益人豁免 | ✅ | Facade 单测 + G-M2 超管负例 |
| `enabled=false` 后新上传不加分 | ✅ | G-M5 `award_disabled` |
| 外链 share-links **不计分** | ✅ | G-M2 |
| 历史行为不补分（AC-29） | ✅ | 无回填脚本；仅新事件挂钩 |

## 4. 运营台与前台

| 项 | 状态 | 备注 |
|----|------|------|
| 我的积分（摘要/明细/999+/规则弹窗） | ✅ | G-M1 / T021b / G-M4 |
| 管理概览三绝对数 | ✅ | T023 / G-M1 |
| 规则编辑（分值/cap/受益人/启停） | ✅ | G-M4 beneficiary |
| 直接调分（正加负减） | ✅ | G-M1 |
| R* 违规扣减（浏览器路径） | ✅ | Portal 管理端；Client T025 **取消不做**（产品确认） |
| 操作审计列表 | ✅ | G-M4 |

## 5. 对账与同步

| 项 | 状态 | 备注 |
|----|------|------|
| 日对账任务成功且无 mismatch | ✅ | G-M5 `reconcile`；不一致只告警不改流水 |
| sync outbox 关闭时 skipped/pending 不报错 | ✅ | G-M5 `outbox_drain`；默认 `sync_outbox_enabled=false` |

## 6. 发布顺序（design §4.6）

1. BiSheng API + Worker（含迁移）  
2. Platform（组织打标，可先于 Portal）  
3. Portal（用户端 + 运营台）  
4. 打开 `points.enabled`  

BFF：确保 `/api/v1/points/**` 转发（与知识 API 同模式）。

## 7. Gate 记录

| Gate | 结果 | 日期 |
|------|------|------|
| G-M1 | PASS 4/4 | 2026-08-06 |
| G-M2 | PASS 4/4 | 2026-08-06 |
| G-M3 | PASS 4/4（1 skipped mutate） | 2026-08-07 |
| G-M4 | PASS 3/3 | 2026-08-07 |
| G-M5 | PASS 22/1 skipped | 2026-08-07（`npm run test:gm5`） |

## 8. 已知延后

- **T025** Client 文档/问答页 R* 按钮：**取消 / WONTFIX**（2026-08-07 用户确认无此场景）；AC-17 仅走 Portal「违规扣减」。  
- **延迟入账反作弊**（design §7）：本期不做。  
- **协同办公真实联调**：不阻塞上线。
