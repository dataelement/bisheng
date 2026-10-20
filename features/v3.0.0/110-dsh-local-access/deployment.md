# DSH 无 Gateway 发布与回退

本文件是操作说明，本次未连接生产环境或执行数据迁移。

## 新部署

使用标准 BiSheng API、worker/Beat 及现有数据库、Redis、模型和审计存储。无需 Gateway 镜像、数据库、License 或共享 HMAC。沿用配置管理机制和稳定的平台 JWT 主密钥。

```yaml
dsh:
  enabled: true
  platform_public_url: https://bisheng.example
```

部署开关开放管理模块后，还需在 DSH 设置中启用业务访问并配置模型及人员/部门额度。原 Gateway URL 和 introspection_timeout 配置作为弃用字段兼容旧配置，但不会产生网络调用。保留既有额度 Redis 拓扑、账期时区和审计密钥配置；它们属于计量和安全能力。

反向代理将 `/api/v1/dsh/*` 和兼容 `/api/dsh/*` 指向 Python API，并将 `/desktop-login` 指向平台 SPA。删除旧路由到 Java 的转发、认证拦截和验席中间层。若部署环境启用了 BISHENG_PRO/Java SSO 入口，按标准原生登录部署关闭对应商业登录代理；其他 Java 商业功能不能视为已迁入。

## 已有部署切换

1. 备份数据库和配置，记录未结算请求、Redis 积压、UNKNOWN、租户额度及审计记录数量。不能用历史备份覆盖上线后的真实用量。
2. 检查是否存在启用 ROLE 策略。组织变更暂停期间，使用本分支运维脚本先 dry-run、逐人核对，再执行迁移；脚本通过显式离线读取器读取历史 ROLE 来源，并保留已配置个人额度（含低额度和零）。没有个人配置的成员按迁移前有效额度形成个人配置，随后停用 ROLE。迁移不会自动给未来成员分配个人额度，后续通过部门配置管理。

   ```bash
   cd src/backend
   python scripts/dsh_migrate_role_policies.py --tenant 2 --actor 1 --model 7
   # 核对输出后，在已批准维护窗口追加 --apply；本次未执行。
   ```

   该脚本必须在已初始化本地运行依赖的维护实例执行；旧 API/worker 停止对外服务，额度和审计存储保持。保留版本检查及现有额度恢复流程，迁移失败不得继续切换。
3. 排空模型请求并完成用量投影，暂停旧 API、worker 和 Beat；不要在旧 Gateway worker 与新 Python 会话之间滚动混跑。
4. 按项目标准启动流程执行 `alembic upgrade head`。新 session/refresh 整表通过模型发现和 create_all 建立；`work110_dsh_local_sessions` 将历史调用席位列改可空并兼容无商业版本。DDL 无业务数据改写。先在同版本 MySQL/DM 预演并核对唯一迁移 head。
5. 将认证路径转发到 Python，启动同一版本 API、worker 和 Beat，删除部署配置中手工配置的 `dsh.scan_profiles` 等退休任务。保留 usage、operation policy recovery、model audit 和 audit tree 任务。
6. 升级客户端为 `codex/dsh-without-gateway` 构建，基线 `origin/V1.1.0`。旧版本客户端可经 `/api/dsh` 别名重新登录；旧 Gateway access/refresh Token 不导入本地表。
7. 在 Gateway 完全停止、无 Gateway Secret 的环境，按 validation.md 的原生桌面清单验收后恢复流量。

## 回退

优先使用保留本地认证和可空事件的新架构修复版本。直接恢复旧 Gateway 版本会令新 Python 会话失效，且旧 worker 可能拒绝无 seat_id 事件；必须先完成结算并验证旧读取器兼容，再单独切路由和要求用户重新登录。DDL downgrade 不删除新历史数据、不收紧可空列；运营回退应保留所有真实消耗和审计证据。
