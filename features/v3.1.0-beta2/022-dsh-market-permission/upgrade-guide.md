# 上线与回退（F022 企业插件与企业工作台授权）

此变更新增两种 F048 资源类型（`dsh_market_plugin`、`dsh_market_workbench`），授权模型版本为 `f048-v6-app-f118-f022`。**全新安装无需任何操作**；已部署环境（含 109、.116、客户环境）升级到本版本时，必须在同一个维护窗口内完成下列步骤。只更新程序、不执行升级，后端进程在启动阶段就会因 `authorization_model_migration_required` 退出（本机实测，2026-11-16），整站不可用。

运行命令位于 `src/backend`，使用与线上服务相同的 `config` 和依赖环境（镜像部署时见文末）。下文 `<operator-id>` 填一个超级管理员的用户 ID，用于审计记录。

## 维护窗口步骤

1. **停服**：停止全部后端进程——API、Celery（knowledge / workflow / default 等全部队列）、Beat、Linsight worker——并等待 F048 运行时心跳过期（默认约 45 秒）。确认没有进行中的权限投影操作。发布脚本发现仍有心跳或投影操作会拒绝执行。
2. **备份**：一致备份业务数据库和 OpenFGA 存储库（OpenFGA 使用 MySQL 存储时是独立的库），以及部署配置；记录当前 CURRENT Catalog 与模型 ID（第 4 步的预览会打印）。
3. **数据库结构**：用新版本执行 `alembic upgrade head`（本特性没有新的结构变更；同版本其他特性可能有）。
4. **发布预览**：

   ```bash
   PYTHONPATH=./ .venv/bin/python scripts/publish_authorization_model_change.py
   ```

   核对输出中的 `store_id`、`target_model_checksum`、`model_version`（应为 `f048-v6-app-f118-f022`）和 `needs_catalog_cutover: true`。预览不写任何数据。

5. **发布执行**：

   ```bash
   PYTHONPATH=./ .venv/bin/python scripts/publish_authorization_model_change.py \
     --apply \
     --confirm-store-id <预览中的 store_id> \
     --confirm-target-model-checksum <预览中的 target_model_checksum> \
     --operator-id <operator-id>
   ```

   该步骤发布新模型，经 Catalog 草稿发布为两种新类型补齐动作作用域（只为 Catalog 中尚未出现的类型补，其他类型的作用域保持不变），重新推导标准权限级别，并原样保留自定义权限级别（含 F118 生成的「仅可见」级别）。成功时输出 `authorization_model_change_published`。

6. **存量补登记预览**：

   ```bash
   PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_system_owned_resources.py \
     --resource-type dsh_market_plugin --resource-type dsh_market_workbench
   ```

   输出列出全部企业插件、企业工作台（**包括已删除的**，以便日后重新导入恢复时沿用授权）；`missing_count` 是待登记数量。

7. **存量补登记执行**：

   ```bash
   PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_system_owned_resources.py \
     --resource-type dsh_market_plugin --resource-type dsh_market_workbench \
     --apply --confirm-store-id <同上> --operator-id <operator-id>
   ```

   每一项登记为「系统所有 + 全企业可见」（所属租户成员的可撤销授权），与升级前员工看到的内容一致。已登记的项不做任何改动，所以重复执行是安全的，并保留管理员后来的撤销。

8. **校验**：

   ```bash
   PYTHONPATH=./ .venv/bin/python scripts/publish_authorization_model_change.py --verify
   ```

   输出 `"verified": true` 才能启动服务。它按各进程启动时的同一套一致性检查读取 CURRENT Catalog，并核对模型校验值与两种新类型的动作作用域；只读，不写数据。再执行一次第 6 步的预览，`missing_count` 应为 0。

9. **启动**：启动全部新版本进程，核对健康检查。
10. **验收**（用普通员工账号，管理员账号在员工侧总是全部可见）：管理后台 `/dsh` 的企业插件、企业工作台列表出现「权限」按钮，默认全企业可见；员工看到的内容与升级前一致；改为只授权某个部门后，部门外员工刷新后看不到、已安装的在下一次同步后停用并提示「管理员已收回使用权限」；恢复授权后可再次启用。

**不要用** `scripts/upgrade_f048_authorization_model.py`（`docs/architecture/10-permission-rbac.md` §10.1 的旧脚本）完成本次升级：它只补作用域、不重新推导标准权限级别；按代码核对，F118 之后已存储的标准级别与推导结果不一致，各进程启动检查会失败（F022 design 坑 5）。也不要用 `force_write_model`。

## 失败处理

- 第 5 步之前失败：没有写入，修正原因后重跑。
- 第 5 步失败：脚本报告阻断原因并以非零退出；修正后用新的预览值重跑同一命令（按校验值复用已发布的模型，不会重复发布）。
- 第 7 步中断：直接重跑；已登记的项保持不变，未完成的登记按原幂等键续完。
- 第 8 步校验不通过：不要启动服务，按输出的 `problems` 处理，或回退。

## 回退

在维护窗口内：停止全部进程 → 恢复第 2 步的业务库与 OpenFGA 存储库备份和配置 → 部署上一版本镜像 → 启动。只回退程序、不恢复数据库会令模型校验失败（同样整站 503）。上线后如已有新的业务数据，先制定数据保留方案再恢复。OpenFGA 中已发布的新模型无法删除，恢复后它不再被引用，无害；下一次升级会按校验值复用它。

## 镜像部署（docker compose）

在 compose 目录内，用与服务相同的镜像、配置挂载和网络起一个一次性维护进程（不要用正常的 API 入口启动服务来执行这些步骤）：

```bash
docker compose stop backend backend_worker          # 第 1 步：停止全部后端服务（按实际服务名）
docker compose pull backend                        # 获取新版本镜像，暂不启动
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend python scripts/publish_authorization_model_change.py
docker compose run --rm --no-deps backend python scripts/publish_authorization_model_change.py \
  --apply --confirm-store-id <store-id> --confirm-target-model-checksum <checksum> --operator-id <operator-id>
docker compose run --rm --no-deps backend python scripts/reconcile_f048_system_owned_resources.py \
  --resource-type dsh_market_plugin --resource-type dsh_market_workbench
docker compose run --rm --no-deps backend python scripts/reconcile_f048_system_owned_resources.py \
  --resource-type dsh_market_plugin --resource-type dsh_market_workbench \
  --apply --confirm-store-id <store-id> --operator-id <operator-id>
docker compose run --rm --no-deps backend python scripts/publish_authorization_model_change.py --verify
docker compose up -d                               # 第 9 步
```

Drone 自动部署（`release` → 192.168.106.116）与 Helm 初始化都不执行上述步骤，需要部署人员在维护窗口内手动完成。

## 验证记录

**2026-11-16 本机演练**（独立的 MySQL 8 / Redis 7 / OpenFGA v1.15.2 / MinIO 容器；升级前版本为 `feat/3.1.0-beta2` 4315308da，造数：3 名员工、4 个部门、1 个用户组、3 个企业插件（其中 1 个已删除）、2 个企业工作台）：

| 步骤 | 结果 |
|---|---|
| 只部署新程序、不升级 | API 启动即退出（`authorization_model_migration_required`）；随后恢复备份继续演练 |
| 发布预览 | `model_version: f048-v6-app-f118-f022`、`needs_model_publish`/`needs_catalog_cutover: true`；预览前后两库数据行逐行比对无差异 |
| 发布执行 | `authorization_model_change_published`，Catalog 版本 1 → 2 |
| 补登记预览 / 执行 | 5 项（含已删除插件）MISSING → CURRENT；再次预览 `missing_count: 0` |
| `--verify` | `"verified": true`，`problems: []` |
| 启动新版本 | 正常；各员工看到的企业插件、企业工作台与升级前一致 |
| 管理员撤销全员授权后重跑补登记 | 不改动，撤销保留 |
| 回退（恢复两库备份 + 旧版本） | 启动正常，登录及员工视图与升级前一致 |

未在 109 / .116 / 客户环境执行；达梦未验证。
