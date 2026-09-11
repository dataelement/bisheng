# 毕昇 A→B 升级与融合：运维执行包

**要动手：只打开 [`复制即跑.md`](./复制即跑.md)，从上到下整段粘贴。** 下面是给复核人看的边界说明，执行时不用看。

## 你要先接受的边界

1. **P2/P3（B 2.2→2.5.0-sg hop）** 是本包可逐步执行的核心。每步有检查、账本、失败即停。
2. **P4 身份接管** 必须先有冻结的用户映射 CSV，禁止按姓名自动合并。脚本只应用已签字的映射。
3. **P5 知识空间融合** 按 [`p5/README.md`](p5/README.md) 执行：export → inventory → dry-run → `APPLY=0` apply → 单空间 `APPLY=1`。默认不落库。禁止拷 A 的向量库 / OpenFGA。
4. 官方 hop 文档里的 `*json_unquote*` 等是飞书转 Markdown 的损坏写法。本包 SQL 已改成合法 MySQL。
5. 本 hop **只针对 MySQL 8**。禁止在 DM8 上跑。
6. 当前摸到的演练机 B 是 `v2.2sgv260402-JiTuan`，不是官方 `v2.2.0`。**第一步必须跑 p2/00-precheck.sh**，把 JiTuan 相对官方 2.2 的表差记进账本；有未知列/缺列要先改 SQL 再继续。
7. 目标 2.5.0-sg 必须写死 **镜像 digest + Git commit + Alembic head**（评审 D02）。测试机路径/镜像写在各 hop 脚本开头。浮动 tag 会被 precheck 拒绝。
8. 容器 `alembic upgrade head || echo WARNING` **不算成功**。本包单独跑 Alembic，对不上 `TARGET_ALEMBIC_HEAD` 就停。

## 谁执行

双人：一人跑命令，一人核对环境、镜像、影响范围和账本输出（评审稿 §13）。

## 一步一步（不要跳）

compose 路径、project 名、`config.yaml` / `entrypoint.sh` 的宿主机位置由 `lib/discover.sh` 从容器标签和挂载表自动发现，不写死路径，换机器无需改脚本。`env.sh` 可选，用于覆盖镜像、容器名和门禁，需手工 `source` 后再跑脚本。

门禁默认全关（`APPLY` / `CONFIRM_LAYOUT` / `DRILL` / `CONFIRM_TYPE2` / `CONFIRM_F006` 均为 0），不 export 就只打印不落库。然后：

| 序号 | 阶段 | 命令 | 完成判据 |
|---:|---|---|---|
| 0 | P0 | 填 `p0/BASELINE.md`，D01–D19 有结论；`env.sh` 的 digest/commit/head 与签字一致 | 评审 §14 关闭或书面豁免 |
| 1 | P1 | `bash p1/run-inventory.sh` | 四份清单在 `logs/p1/` |
| 2 | P2 预检 | `bash p2/00-precheck.sh` | JiTuan schema diff 已阅；目标 digest 已钉 |
| 3 | P2 备份 | `bash p2/01-freeze-and-backup.sh` | 备份校验文件存在；至少一次恢复演练另做 |
| 4 | hop 2.3-beta1 | `bash p2/10-hop-2.3-beta1.sh` | 字段在；`convert_all` 完成 |
| 5 | hop 2.3 | `bash p2/11-hop-2.3-release.sh` | 角色菜单插入；遥测脚本跑完 |
| 6 | hop 2.4-beta1 | `bash p2/20-hop-2.4-beta1.sh` | `message_session.group_ids` 回填完 |
| 7 | hop 2.4 | `bash p2/21-hop-2.4.sh` | 知识空间列存在；再跑 `22` |
| 8 | type=2 | `bash p2/22-hop-2.4-type2.sh` | 与 D07 一致；空库不删 |
| 9 | hop 2.5.0-sg | `bash p2/30-hop-2.5.sh` | `alembic current` = `TARGET_ALEMBIC_HEAD` |
| 10 | F006+工作台 | `bash p2/31-f006-workstation.sh` | dry-run → execute → verify；failed_tuple 待处理=0 |
| 11 | 回归 | `bash p2/40-verify.sh` + 业务 UAT | 评审 §10.1 |
| 12 | P3 | 用**同一包、同一 digest** 在生产 B 重做 3–11 | 不要改脚本现场发挥 |
| 13 | P4 | `bash p4/00-export-a-users.sh` → propose-map → 签字 CSV → `APPLY=0` 再 `APPLY=1 bash p4/apply-takeover.sh` | 员工编码唯一；双行同一 B id；**仍关闭 SG 同步** |
| 14 | P5 | 见 `p5/README.md` 与 `复制即跑.md` §13 | 每批隐藏空间；verify 后再发布 |
| 15 | P6 | 见 `p6/cutover-runbook.md` | 单写；Go/No-Go |
| 16 | P7 | 见 `p7/observe.md` | A 只读 2–4 周 |

中间版本 **不必对外提供 API**。需要的是对应版本的**工具容器**（尤其 2.3 的 `convert_all`）。

可跳过（官方仅换镜像、无 SQL）：2.3-beta2/3/4、2.4-beta1-fix。不可跳过带 SQL/脚本的 hop。

## 失败策略

任一步非 0 退出：**停下**。禁止接着起 API。回滚见 `p2/90-rollback.md`。

## 账本

所有 `*.sh` 往 `logs/ledger.tsv` 追加一行。不要改历史行。
