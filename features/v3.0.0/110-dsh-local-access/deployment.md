# DSH 无 Gateway 发布与回退

本文件描述从 main 基线升级的发布流程。109 曾直接从另一版本线的审计分支升级，其历史迁移兼容处理已撤回；旧联调记录仅保留当时的行为证据。当前基线修正与环境恢复过程见 [main 基线恢复记录](./main-baseline-109-recovery-20261020.md)。

## 新部署

使用标准 BiSheng API、worker/Beat 及现有数据库、Redis、模型和审计存储。无需 Gateway 镜像、数据库、License 或共享 HMAC。沿用配置管理机制和稳定的平台 JWT 主密钥。

```yaml
dsh:
  enabled: true
  platform_public_url: https://bisheng.example
```

### 统一公开地址

13001 测试环境的现场证据、配置核对及部署验收清单见 [公开地址修复部署验收](./public-origin-13001-validation.md)。

部署者在 `docker/bisheng/config/config.yaml` 的 `dsh.platform_public_url` 配置一次用户实际访问的地址。桌面客户端连接该地址后，登录授权、嵌入 Chat 和 Work 工具共用这套入口；MCP 的 Host 与 Origin 允许值由该配置派生。地址包含协议和对外端口，例如 `https://work.example.com`、`http://192.0.2.15:18081`、`https://work.example.com:18443`。路径由客户端和服务端协议各自拼接。

服务端加载配置时统一域名大小写、默认端口、国际化域名和 IPv6 表示。修改地址后重新启动 API 进程，并让客户端连接新的公开地址。工具的身份、租户和资源权限继续使用当前登录账号。

仓库两套 Nginx API 入口均通过 `proxy_set_header Host $http_host` 保留公开地址和端口。额外部署的负载均衡或 TLS 代理也应原样传递 Host；以下通用转发规则适用于不同部署地址：

```nginx
location / {
    proxy_pass http://bisheng_ingress;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

`bisheng_ingress` 是该代理可访问的毕昇内部 upstream。最外层代理写入公开协议，内层毕昇入口沿用它。工具地址校验以实际 Host 和已配置的公开地址为准；`X-Forwarded-Host` 用于原有链接生成流程。

部署验收依次覆盖：通过公开地址完成桌面登录、打开 Chat、MCP `initialize` / `tools/list`、原生 Work 工具菜单和一次受权工具调用。若工具初始化返回 421，核对 API 实际加载的公开地址、各层代理转发的 Host 及运行版本；保留服务端原始错误用于定位具体拒绝层。

开发回归包含真实 MCP SDK 和可选的本机 Nginx 测试：在后端目录运行 `NGINX_BIN=/path/to/nginx python -m pytest --noconftest -o asyncio_mode=auto test/dsh/test_public_origin.py test/dsh/test_public_origin_nginx.py test/dsh/test_work_capabilities.py`。Nginx 测试从两套生产模板读取 map 和请求头转发指令，验证单层 HTTP、双层 HTTPS 及错误 Host/Origin 拒绝；完整生产路由和真实账号操作在部署环境验收。

部署开关开放管理模块后，还需在 DSH 设置中启用业务访问并配置模型及人员/部门额度。原 Gateway URL 和 introspection_timeout 配置作为弃用字段兼容旧配置，但不会产生网络调用。保留既有额度 Redis 拓扑、账期时区和审计密钥配置；它们属于计量和安全能力。

反向代理将 `/api/v1/dsh/*` 和兼容 `/api/dsh/*` 指向 Python API，并将 `/desktop-login` 指向平台 SPA。删除旧路由到 Java 的转发、认证拦截和验席中间层。若部署环境启用了 BISHENG_PRO/Java SSO 入口，按标准原生登录部署关闭对应商业登录代理；其他 Java 商业功能不能视为已迁入。

## 数据库基线

本分支以 main `4218ba7c138a90764a304681c3d8a5875b2c9c1a` 为数据库基线，原有 83 个迁移文件保持字节不变。
升级链只有 `f065_dsh_install_policy_default_off → work110_dsh_local_sessions`。
新审计表和原生会话表共 15 张，按项目既有流程通过模型发现和 `create_missing_model_tables` 一次创建完整字段、约束和索引；不重放原审计分支的逐列增量 DDL。
唯一新增 Alembic 变更只操作已有 `dsh_model_call` 的 `seat_id`、`grant_version` 可空性及版本检查约束。

其他版本线的 `f062_dsh_audit_tree`、已撤回的 `work110_merge_legacy_audit` 均不属于本分支的可直接升级起点。
测试环境如已混入这些版本，应先完整归档旧库，在新测试库上运行准确 main 源码建立基线并记录实际 schema/head，再升级；不手工修改 `alembic_version`，不向目标分支恢复外来历史。
本分支的 `downgrade()` 不删除审计事实或收紧已有调用列，不能用它把已有新数据的数据库伪装成 main 基线。

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

优先使用保留本地认证和可空事件的新架构修复版本。Gateway 仅作通用反向代理时可以保持现有版本；只有切回由旧 Gateway 负责 DSH 认证的链路，才会遇到 Python 会话不被旧链路识别的问题。若连同后端/worker 一起回退，旧读取器还可能拒绝无 seat_id 的新调用；必须先完成结算并验证数据兼容，再切换流量和要求用户重新登录。DDL downgrade 不删除新历史数据、不收紧可空列；运营回退应保留所有真实消耗和审计证据。
