# F053 发布与部署检查表

## 发布顺序

1. 发布包含 `service_account` 主体的向后兼容 OpenFGA 模型，并运行 schema contract；模型未就绪前保持服务账号签发入口关闭。
2. 依次执行 Alembic revision：
   - `v3_0_0b1_f053_api_credential_tables`
   - `v3_0_0b1_f053_delegate_scope_and_session_subject`
   - `v3_0_0b1_f053_pat_tenant_setting`
3. 部署后端，先验证 v3 精确七个 HTTP 与两个 WebSocket 路由，再验证 v2 密钥面和五个日常模式端点。
4. 切换 client guest 请求和 platform 发布示例至 v3。
5. 更新并验证商业网关的 v3 HTTP/WS 代理后，才完成调用方切换验收。
6. PAT 默认保持部署级和租户级关闭；确认租户策略与管理员 TTL 后再按租户启用。

## 数据与回滚边界

- 三条迁移只执行 DDL，不回填业务数据。
- 不修改 `user`、`user_tenant` 或 `share_link`；不创建 `open_api_call_log`，调用审计写入现有 `audit_log.metadata`。
- 回滚应用前先关闭服务账号签发和 PAT；保留 OpenFGA 新主体类型不会改变既有 user/department/group tuple。
- 数据库 downgrade 必须按上述迁移的逆序执行，并在 MySQL 与 DM8 105 专用环境验证。

## 本仓已验证

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
