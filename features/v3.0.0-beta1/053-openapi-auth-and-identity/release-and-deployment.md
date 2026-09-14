# F053 发布与部署检查表

## 发布顺序

1. 发布包含 `service_account` 主体和服务账号技术状态标记的向后兼容 OpenFGA 模型，并运行 schema contract；模型未就绪前保持服务账号签发入口关闭。
2. 依次执行 Alembic revision：
   - `v3_0_0b1_f053_api_credential_tables`
   - `v3_0_0b1_f053_delegate_scope_and_session_subject`
   - `v3_0_0b1_f053_pat_tenant_setting`
3. 部署后端，先验证 v3 精确七个 HTTP 与两个 WebSocket 路由，再验证 v2 密钥面和五个日常模式端点。
4. 切换 client guest 请求和 platform 发布示例至 v3。
5. 更新并验证商业网关的 v3 HTTP/WS 代理后，才完成调用方切换验收。
6. PAT 默认保持部署级和租户级关闭；确认租户策略与管理员 TTL 后再按租户启用。

### 已运行 F048 环境的模型升级与存量标记补齐

此步骤由运维在发布维护窗口显式执行；容器启动、`alembic upgrade head` 和 `docker/deploy.sh update` 不会自动运行权限数据修复。旧资源可能只有 `user:*` 技术状态标记，不能以“模型已是最新版”或“后端重启成功”作为存量数据完整的依据。

已完成 F048 迁移、业务 Grant 不需重建的环境，执行模型发布脚本。它在切换 Catalog 或返回 `already_current` 之前都会补齐并校验服务账号资源标记：

```bash
cd src/backend
export config=<与线上 API/Worker 完全相同的配置文件>
export PYTHONPATH=./
.venv/bin/python scripts/publish_authorization_model_change.py
```

审核输出的 `store_id`、`target_model_checksum` 和 `service_account_marker_tuple_count`。资源标记数量是按 CURRENT 资源模式计算的应有数量，不是实际缺失数量。停止入口流量及 API、Celery、Linsight 进程，等待运行时心跳过期后，使用同配置的独立维护进程/容器执行：

```bash
.venv/bin/python scripts/publish_authorization_model_change.py \
  --apply \
  --confirm-store-id <dry-run 输出的 store_id> \
  --confirm-target-model-checksum <dry-run 输出的 target_model_checksum> \
  --operator-id <执行发布的管理员用户 ID>
```

脚本按每个 CURRENT 资源的已有模式补齐 `service_account:*` 的 `permission_enabled` 和 `custom_mode`/`inherit_mode`，覆盖空间及所有层级的目录、文件，保留自定义权限边界和现有父子关系，不给后代复制服务账号 Grant。写入与 higher-consistency 校验全部成功后才返回成功，并输出 `service_account_marker_tuples_verified`；模型已是最新版时也不会跳过。失败时保持维护状态并按错误修复后重跑，不能继续启服。

如果还需要重建 Grant 的直接可见投影，则使用完整对账脚本；该路径也会补齐相同的服务账号资源标记：

```bash
cd src/backend
export config=<与线上 API/Worker 完全相同的配置文件>
export PYTHONPATH=./
.venv/bin/python scripts/reconcile_f048_visible_projection.py
```

审核 dry-run 输出的 `store_id`、目标模型 checksum、资源标记数量和待更新投影。然后停止入口流量及 API、Celery、Linsight 进程，等待运行时心跳过期，在维护窗口执行：

```bash
.venv/bin/python scripts/reconcile_f048_visible_projection.py \
  --apply \
  --confirm-store-id <dry-run 输出的 store_id> \
  --operator-id <执行发布的管理员用户 ID> \
  --allow-model-upgrade
```

模型不变时可省略 `--allow-model-upgrade`，但不能省略 apply 的数据补齐步骤。脚本先发布/复用模型，再对账直接可见投影和服务账号资源标记，以 higher consistency 验证后按需切换 Catalog。脚本成功后再启动新版本后端。它不修改 `user`、`service_account` 或业务授权记录，也不需要新增 Alembic revision。

从旧 RBAC 首次迁入 F048 的环境仍使用 `migrate_f048_permission_data.py`：首次迁移协调器已在每层资源同时写入 `user:*` 与 `service_account:*` 的模式和启用标记。已经完成首次迁移的环境不要通过重新迁移来补缺。

上线冒烟以测试服务账号 `e2e-f053-fresh-sa-review` 和知识空间 `4255` 为基准：先确认 editor 可上传，再降为 viewer 验证上传拒绝，最后恢复 editor 并验证撤销后拒绝。代表用户模式必须按被代表用户的权限判定，不能叠加服务账号权限。

## 数据与回滚边界

- 三条迁移只执行 DDL，不回填业务数据。
- 不修改 `user`、`user_tenant` 或 `share_link`；不创建 `open_api_call_log`，调用审计写入现有 `audit_log.metadata`。
- 回滚应用前先关闭服务账号签发和 PAT。`f048-v4` 不改变既有 user/department/group tuple，但旧应用会因期望的模型 checksum 不同而保持权限运行时不可用，因此不能只回滚应用二进制；应优先前滚修复，确需回滚时必须同时准备与旧代码匹配的 Catalog/模型指针恢复方案。
- 数据库 downgrade 必须按上述迁移的逆序执行，并在 MySQL 与 DM8 105 专用环境验证。

## 本仓已验证

- `test/open_api/`：110 passed，覆盖 QA 鉴权无副作用、multipart `user_id` 拒绝、v2 HTTP 状态映射、SSE 终态、PAT 迁租户、服务账号授权聚合和知识空间列表 DTO。
- F048 技术标记、Catalog、模式、投影、迁移与对账脚本定向回归：133 passed、6 skipped；跳过项需要真实 OpenFGA。
- platform 服务账号/API wrapper/系统页签定向测试：10 passed。
- 受影响 Python 文件 ruff、全前端 lint、i18n parity、architecture guard 和 `git diff --check` 通过。
- 2026-09-09 在 `192.168.106.116:7861` 执行 F053 API E2E 11/11：无密钥/JWT 回落拒绝、独立 SA 主体、身份头冲突、日常配置、PAT、v3 allowlist、资源授权候选、multipart `user_id`、知识空间 DTO 与 QA 防越权均通过。QA 样本拒绝前后内容哈希一致，测试服务账号清理后残留为 0。
- 同日将该环境 OpenFGA Store `01KQ3ZRQ9VY0FJJ46V8NW98M7M` 从旧模型切换到 `f048-v4` 模型 `01M21ZT2425HJTQ6MX6W18JGYM`，Catalog release 195；补齐 20,764 条 SA 技术标记，41,187 条期望 tuple 经 higher consistency 验证。二次 dry-run 无 source upsert/retire，API/Celery 心跳均绑定新模型与 Catalog。
- 执行 `pnpm install --frozen-lockfile` 同步工作区依赖后，全前端 `pnpm typecheck` 通过：platform 385 个 strict 文件、client 1290 个 strict 文件及 file-viewers 均通过。同步修正 dashboard 测试夹具的懒加载权限 hook 契约和 route filter 测试的字符串类型收窄；相关 10 项测试通过。

## 发布阻断项

- **商业网关**：源码不在本仓。目标私有仓库为 `dataelement/bisheng-gateway`；依据现有架构文档，待该仓负责人核对的完整候选路径为 `src/main/resources/application.yml`、`src/main/java/com/dataelem/gateway/config/BishengConfig.java`、`src/main/java/com/dataelem/gateway/filter/SelfWebsocketRoutingFilter.java`、`src/main/java/com/dataelem/gateway/filter/PathRateGlobalFilter.java` 和 `src/main/java/com/dataelem/gateway/filter/SensitiveWordsFilter.java`。需使 `/api/v3/**` HTTP 和两个 WebSocket 不进入登录或 API Key 网关。当前工作区没有该仓源码，也没有负责人信息，路径尚不能以源码复核，因此 F07/R03 未完成。
- **剩余中间件与数据库**：MySQL、Redis、OpenFGA 模型发布及 API 权限链路已在 192.168.106.116 验证；Milvus/ES/MinIO 的成功写入/检索链路和 DM8 105 migration 往返仍需在对应专用环境复核。
- **商业入口许可证**：`192.168.106.116:3001` 的公开 v3 请求当前返回业务码 11001（软件授权已过期）；直连同机后端 `:7861` 的 v3 与 OpenAPI schema 验证通过。浏览器 guest 与对外入口验收前须续期许可证，并通过实际商业入口复测 HTTP/WS。
- **人工导入与浏览器证据**：Apifox/Postman 导入、无痕 guest HTTP/WS、platform/client Network、既有分享链接和商业版端到端验证仍需按 `e2e-checklist.md` 执行并附截图或日志。

上述阻断项有结果前，不宣告 F07、R01、R03 或 R04 完成。
