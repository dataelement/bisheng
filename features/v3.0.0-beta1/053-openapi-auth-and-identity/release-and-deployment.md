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

### 已运行 F048 环境的模型升级

现有环境不能只替换后端进程。旧 OpenFGA 模型与存量资源只有 `user:*` 技术状态标记，必须使用新版本中的对账脚本完成不可变模型发布、存量标记补齐和 Catalog 切换：

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

脚本先发布/复用新模型，再补齐 `service_account:*` 的目录、动作、授权级别、`permission_enabled` 和权限模式标记，以 higher consistency 验证后原子切换 Catalog。脚本成功后再启动新版本后端。它不修改 `user`、`service_account` 或业务授权记录，也不需要新增 Alembic revision。

上线冒烟以测试服务账号 `e2e-f053-fresh-sa-review` 和知识空间 `4255` 为基准：先确认 editor 可上传，再降为 viewer 验证上传拒绝，最后恢复 editor 并验证撤销后拒绝。代表用户模式必须按被代表用户的权限判定，不能叠加服务账号权限。

## 数据与回滚边界

- 三条迁移只执行 DDL，不回填业务数据。
- 不修改 `user`、`user_tenant` 或 `share_link`；不创建 `open_api_call_log`，调用审计写入现有 `audit_log.metadata`。
- 回滚应用前先关闭服务账号签发和 PAT。`f048-v4` 不改变既有 user/department/group tuple，但旧应用会因期望的模型 checksum 不同而保持权限运行时不可用，因此不能只回滚应用二进制；应优先前滚修复，确需回滚时必须同时准备与旧代码匹配的 Catalog/模型指针恢复方案。
- 数据库 downgrade 必须按上述迁移的逆序执行，并在 MySQL 与 DM8 105 专用环境验证。

## 本仓已验证

- 服务账号技术状态标记修复定向回归：权限/迁移 142 passed、6 skipped（真实 OpenFGA 环境门禁）；开放 API/知识库 103 passed。

- F053 后端核心测试：114 passed。
- 受影响的既有 chat/workstation 回归：47 passed。
- OpenFGA schema/manager 与性能契约：25 + 12 passed。
- platform 定向测试：9 passed；client 定向测试：10 passed。
- backend ruff、platform/client lint、i18n parity、architecture guard 和 `git diff --check` 通过。
- v2 OpenAPI JSON 由实际应用 schema 生成，路由/security/header/schema contract 自动校验通过。
- 默认环境下 E2E 套件安全跳过；只有显式设置 `F053_E2E=1` 才会操作专用部署。

## 发布阻断项

- **商业网关**：源码不在本仓。目标私有仓库为 `dataelement/bisheng-gateway`；依据现有架构文档，待该仓负责人核对的完整候选路径为 `src/main/resources/application.yml`、`src/main/java/com/dataelem/gateway/config/BishengConfig.java`、`src/main/java/com/dataelem/gateway/filter/SelfWebsocketRoutingFilter.java`、`src/main/java/com/dataelem/gateway/filter/PathRateGlobalFilter.java` 和 `src/main/java/com/dataelem/gateway/filter/SensitiveWordsFilter.java`。需使 `/api/v3/**` HTTP 和两个 WebSocket 不进入登录或 API Key 网关。当前工作区没有该仓源码，也没有负责人信息，路径尚不能以源码复核，因此 F07/R03 未完成。
- **真实中间件与数据库**：本地无项目专用 MySQL、Redis、OpenFGA、Milvus/ES/MinIO 和 DM8 105 环境；迁移往返、凭据撤销时效、权限模型发布及检索链路需在 CI/专用环境复核。
- **人工导入与浏览器证据**：Apifox/Postman 导入、无痕 guest HTTP/WS、platform/client Network、既有分享链接和商业版端到端验证仍需按 `e2e-checklist.md` 执行并附截图或日志。

上述阻断项有结果前，不宣告 F07、R01、R03 或 R04 完成。
