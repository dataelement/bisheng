# F015 升级与回滚手册

**适用**：从不含 F015 的版本升级到含 F015 的版本。
**原则**：必须停服升级；开放使用前完成冒烟；开放使用后只做前向修复（原因见 [design.md](./design.md) 决策 18）。
**状态**：草稿。停服时长待 MySQL / 达梦演练（tasks T18b）与测试服务器全流程（tasks S9）实测后补入。

以 docker compose 部署为例，服务名取自 `docker/docker-compose.yml`。其他部署方式按同样顺序执行。

## 0. 升级前检查

1. 确认新镜像已拉取；记录当前镜像版本，用于开服前回滚。
2. **额度 Redis 容量**：读取 `redis-cli INFO memory` 的 `used_memory` 与 `maxmemory`，以及 `dsh.quota_memory_budget_bytes`（默认 512 MB）、`dsh.quota_memory_headroom_bytes`（默认 64 MB）。升级后每次调用在 Redis 多占约 0.8 KB、保留 30 天：预计增量 ≈ 日调用量 × 30 × 0.8 KB。若「当前用量 + 增量」接近「预算 − 余量」，先调大预算和 Redis `maxmemory`。
3. 通知用户停服时间。

## 1. 停服

```bash
docker compose stop frontend backend backend_worker     # mysql、redis 保持运行
```

## 2. 备份（开服前回滚的唯一依据）

```bash
docker compose exec mysql mysqldump --single-transaction --routines --databases bisheng > backup/bisheng-升级前.sql
# 达梦：用 dexp 全库导出，参数按现场 DBA 规范
docker compose exec redis redis-cli SAVE
# 复制 Redis 数据目录（dump.rdb 与 AOF 目录）到 backup/
```

## 3. 只迁移、不开服

```bash
docker compose run --rm --no-deps backend alembic upgrade head
```

效果：`create_all` 建 `dsh_credit_setting`；Alembic 给 `dsh_model_call` 加 `pricing`、`cost_micro`、`currency` 三个可空列（不回填旧行）。

## 4. 价格回填

```bash
# 预检：只输出清单（租户、提供方、模型名、匹配到的价格表条目或「默认 0」），不写库
docker compose run --rm --no-deps backend python scripts/backfill_model_pricing.py
# 管理员核对清单后执行
docker compose run --rm --no-deps backend python scripts/backfill_model_pricing.py --apply
```

只给 `model_type == "llm"` 且没有 `pricing` 的模型写入；可重复执行。清单中「默认 0」的收费云模型（如火山方舟接入点、中转站新模型名）需要管理员开服后在后台改价，否则一直免费。

## 5. 门禁

```bash
docker compose run --rm --no-deps backend python scripts/backfill_model_pricing.py --check
```

返回码必须为 0 才继续。检查项：所有大语言模型都有 `pricing`；`dsh_credit_setting` 表与三个新列存在。非 0 时按输出的明细处理后重跑第 4、5 步。

## 6. 冒烟（入口只对管理员开放）

```bash
docker compose up -d
```

按现场网络方式让入口只对管理员可达（防火墙白名单或临时 nginx allow）。管理员在网页发起一次日常对话，确认：用量记录带单价与花费，扣费与手算一致；一个价格为 0 的模型可用。

## 7. 开服

撤掉入口限制，对全员开放。发版说明提示管理员：旧倍率不再生效，积分含义变化（默认 1 积分 = 0.01 元），需重新核对各部门额度。

## 回滚

| 时机 | 做法 | 数据影响 |
|---|---|---|
| 开服前（第 3–6 步任一步失败） | 停 backend、backend_worker、frontend → 用第 2 步备份整库恢复 → 停 redis，用备份的数据目录替换后启动 → 镜像改回升级前版本 → 开服 | 无用户数据损失：停服期间只有冒烟调用写过数据 |
| 开服后 | 不回滚；出补丁镜像，按本手册同样的停服流程升级 | — |

开服后不能换回旧镜像：旧版本的 `UsageEvent` 禁止未知字段，读不了 Redis 中带价格快照的事件（保留 ≥ 30 天）；即使能读，旧公式重算新事件也与月度汇总对不上，恢复会被拒绝。如业务要求开服后也能回滚，需另行开发降级转换脚本（待拍板）。

## 演练记录

| 演练 | 环境 | 数据量 | 结果 |
|---|---|---|---|
| MySQL 迁移 | 本机 Docker MySQL 8 | 100 万 / 1,000 万行 | 待执行（T18b） |
| 达梦迁移 | 同事提供的 Linux + DM8 | 待定 | 待执行（T18b） |
| Redis 容量 | 本机 Docker Redis 7 | 2 万次调用 | 2026-11-12 模拟：每次约 5.3 KB → 精简快照后约 6.1 KB（+15%）；真实流程复测待执行（T18c） |
| 全流程 | 测试服务器 | — | 待执行（S9，需 Callum 同意） |
