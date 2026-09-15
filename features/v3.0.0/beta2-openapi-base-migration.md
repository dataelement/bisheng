# 应用工场改接 beta2 开放 API 底座：合并与迁移方案

> **性质**：横切 F049 / F053 / F054 / F055 / F056 的技术迁移方案，不是新 Feature，不改需求口径。需求真相仍是 PRD-1 v2.1 与伴生《开放 API 鉴权与身份传递 PRD》v2.8。
> **背景**：`3.0-vibe` 上 8 月首发的 F049（开放 API 鉴权基线）与发版线 `feat/3.0.0-beta2` 上 highway 9 月交付的 F053（`features/v3.0.0-beta1/053-openapi-auth-and-identity/`）是同一需求的两套实现，28 个 `open_api` 文件 add/add 冲突。2026-09-09 审计结论：beta2 是 vibe 代码的重构版且多做完了 43 端点接入 / 委托 / PAT 全套 / 逐调用审计 / 技能包分发；vibe 独有的只有 `open_api_subject` 工厂、权限位注册表分组文案、两个错误码，合计不到 200 行。
> **结论**：**open_api 整体取 beta2，vibe F049 归档为参考；应用工场（app_runtime / app_publish / dev_toolkit / runtime-manager / app-proxy / CLI）整条线改接 beta2 底座。**
> **分支**：`feat/3.0-vibe/openapi-beta2-base`（自 `3.0-vibe` 969897df5 分叉），完成后合回 `3.0-vibe`。发版线规则不变：vibe 只从 beta2 合下来、不做首发。

---

## 1. 决策

| # | 决策 | 依据 |
|---|---|---|
| M1 | `open_api/**`、`test/open_api/**`、platform 服务账号 / 个人令牌管理 UI、`common/errcode/open_api.py`、`core/config/open_platform.py` 全部取 beta2 版本；vibe 侧对应文件作废 | 2026-09-09 审计（memory `project_openapi_two_implementations_audit`）；发版线规则（`feedback_branch_beta1_first`） |
| M2 | 合并顺序：先 `origin/feat/3.0.0-beta2`（da2be5697），再 `origin/feat/3.0.0-beta1` tip（59b27d1c1） | beta1 tip 多 7 笔（f6bf9f51f 修 D17 管理员 PAT 短路 + D19 换租户随人迁移，另 5 笔 SA / PAT UI 改进），beta2 周期性合 beta1，提前合入只是把必然发生的事前移 |
| M3 | 用 merge 不用 rebase | vibe 独有 116 笔含大量文档提交，逐笔 rebase 解同一批冲突 116 次 |
| M4 | 服务账号数据模型采 beta2 独立 `service_account` 表；vibe 的 `user.user_type` 整条移除（模型列、`UserDao` 过滤、登录守卫、`/user/list` 排除、`grant_subject_service` 排除、`f048_permission_subject` 主体排除、`entry_authz_service` 的 human 分类） | 两套主体模型并存 = F048 主体判定出现双真相；beta2 的 `PermissionActor` 已能表达 `service_account:{id}`（K15），`user_type` 没有任何剩余消费者 |
| M5 | `user.user_type` 用**新增** drop 列迁移移除，保留 `f049_user_user_type` revision 文件不删 | 114 的 `alembic_version` 链路经过该 revision，删文件会让 alembic 定位不到历史 |
| M6 | alembic 新增 merge revision `merge_beta2_openapi_heads`，down = (`vibe_drop_user_user_type`, `f056_user_string_lengths`)——vibe 链是 `merge_update_time_default_heads` → M5 的 drop 列迁移 → 本 merge | 合并后必双头（vibe 链 vs beta2 F053 链） |
| M7 | `app:manage` 从 beta2 的 `issuable=False` 改为**随 `open_platform.enabled` 可签发**；`model:invoke` / `identity:read` 保持不可签发（F051 / F052 顺延）；三扩展位与 `delegate` 互斥硬阻断（**INV-31**，beta2 未做；签发期 `26050`/400、调用期 `26051`/403、签发表单同批加硬阻断）；PAT 永不可获三扩展位（已有 `knowledge:read` 白名单） | PRD-1 GOV-07：CLI 通道由密钥 `app:manage` 位把关；伴生 PRD §4.2.4 互斥；beta2 之所以没做互斥是因三位当时都不可签发，点亮即成漏洞（审计三、次要缺陷第 3 条） |
| M8 | `/api/v2/apps/*`（F055 deploy 管线）改接 beta2 固定管线：端点打 `open_api_scope("app:manage")` marker，鉴权走 `verify_open_api_access`（K14 单一管线，不再自建 `open_api_subject`）；主体读 `get_current_open_api_principal()`；删除 vibe 的 `LoginUser.open_api_principal` 字段 | K14「任一 v2 端点漏标记均 fail-closed；端点体不得另行解析身份」 |
| M9 | 归属人规则不变：deploy 的应用 owner = `principal.resource_owner_user_id`，为空即拒（服务账号必填归属人，伴生 PRD §4.5 定义 6） | 2026-08-17 跨 Feature 裁定 |
| M10 | 托管应用运行期凭据主体 `hosted_app`（F055 T055）**本轮不做**；届时新增迁移放宽 `ck_api_credential_subject_kind` 并注册解析器；vibe 的 `SUBJECT_KIND_HOSTED_APP` / `SUBJECT_KIND_SHARE_LINK` 随 vibe 模型作废 | MVP-核心顺延项；不改 highway 的迁移文件 |
| M11 | 密钥泄漏扫描新增 `bs_pat` 规则（`PERSONAL_TOKEN_PREFIX`），正负样本各一 | 伴生 PRD §4.2.6「两个前缀都要注册」；beta 线没有扫描器，此项只能在应用工场侧做 |
| M12 | 错误码：`common/errcode/open_api.py` 取 beta2；vibe 独有 26012 / 26028 若合并后仍有消费者，按 beta2 段内空号补回；26029 语义按 beta2（不能当归属人）；前端 `api_errors` SSOT 冲突块取 beta2、vibe 独有 16xxx / 26xxx 文案保留、六份产物一律重跑 `build.mjs` | `project_beta1_to_vibe_sync_playbook`：`git checkout --theirs` 会丢 65 条文案 |
| M13 | OpenFGA 模型取并集（beta2 `service_account` 主体类型 + vibe `app` 资源类型），`MODEL_VERSION` 升 `f048-v5`；**2026-09-15 二次同步后改为 `f048-v6`** | 两侧都把各自的形状叫 `f048-v3`，并集是第三个形状；版本串只为可读，不能一名二物。**v6 的由来**：本分支 9-10 把「beta1 v4 + `app`」命名为 v5，同期 beta2 也把「v4 + contextual 部门成员（`subtree_member` 改 `_this()`、按请求注入）」命名为 v5，二次合并后又是第三个形状。**不能用 `f048-v4`**：beta1 tip f6bf9f51f 已把 D17 / D19 修订后的形状命名为 `f048-v4` 并于 2026-09-09 在 116 发布（`features/v3.0.0-beta1/053-openapi-auth-and-identity/release-and-deployment.md`），并集只能顺延为 v5 |
| M14 | platform 管理面：服务账号 / 个人令牌 tab 取 beta2 的 `open_api.management_ui_enabled` 门控（原默认关；**beta2 `75455c572` 起 `management_ui_enabled` / `pat_enabled` 默认开**，另增 `public_base_url`）；`/api/v1/env` 四个开关并存：`open_platform_enabled`（三扩展位 + 接入信息区）、`app_runtime_enabled`（工场运行时层）、`personal_token_enabled`、`open_api_management_enabled` | 各自 gate 不同面，互不合并；应用工场演示剧本步 1 依赖管理面可见；默认已开，存量 `config.yaml` 仍建议显式写 `management_ui_enabled: true` |
| M15 | 114 **不能原地升级**：两侧 `service_account` / `api_credential` 同名不同构，beta2 迁移的 `table_exists` 守卫会跳过建表、启动即崩。部署前须停服 → 备份 → DROP 两张 vibe 结构表**与 vibe 的服务账号 `user` 行** → `alembic upgrade head` → 发布 FGA 模型 **v6**（原写 v5，见 M13）→ 重建服务账号与密钥。步骤见 §4 | 审计四；2026-09-09 拍板暂不部署；2026-09-15 用户确认执行（服务账号按原样全部重建） |
| M17 | **整体取 beta2 时丢掉了 vibe 的一道租户防线，必须补回**：vibe 的 `ServiceAccountService.get_row` 带 `tenant_id` 参数并显式比较（其 docstring 逐字点名这条攻击），beta2 没有——子租户管理员因此可读取、改名、停用根租户服务账号并对它签发 / 吊销密钥。已在 `fix/3.0.0-beta2/service-account-tenant-boundary` 修好并 cherry-pick 回本分支 | 相对合并基线是回归（vibe 有、beta2 无），两名反驳者各自用运行期探针复现；伴生 PRD §4.2.5 / AC-5 |
| M16 | 验证口径：后端分区测试零回归（基线 = 纯 beta2 同范围，在独立 worktree 跑）、ruff、arch-guard、alembic 单头、platform lint + typecheck、client typecheck、`check-i18n`、`docker/verify-app-runtime-compose.sh`、v2 OpenAPI 契约 JSON 重生成（`/api/v2/apps/*` 加入后 beta2 的契约测试必须跟着更新） | `project_beta1_to_vibe_sync_playbook`：差集里的新增失败必须回源分支跑相同组合复核 |

---

## 2. 冲突解法表（`git merge-tree` 预演：add/add 28 · content 24 · modify/delete 2）

| 组 | 文件 | 解法 |
|---|---|---|
| A · open_api add/add | `open_api/**`（20）、`test/open_api/{conftest,test_credential_service,test_credential_validator,test_service_account_service}.py`、`common/errcode/open_api.py`、`core/config/open_platform.py`、platform `controllers/API/serviceAccount.ts`、`SystemPage/components/ServiceAccount/{ApiKeysTab,CreateServiceAccountDialog,KeyIssueDialog}.tsx` | 取 beta2 整文件（`git checkout origin/feat/3.0.0-beta2 -- <path>`） |
| B · vibe 独有被取代 | `test/open_api/{test_open_api_auth_api,test_service_account_api,test_service_account_keys_api,test_wave1_infra}.py`；platform `ServiceAccount/{KeyRevealDialog,OverviewTab,ServiceAccountDetail,ServiceAccountList,ServiceAccountPanel}.tsx`、`types/api/serviceAccount.ts`、`test/serviceAccountTenantCopy.test.tsx`、`public/locales/*/serviceAccount.json`（三语）+ `i18n.js` 的 `serviceAccount` ns；`test/user/test_service_account_login_guard.py`、`test/permission/test_service_account_subject_exclusion.py` | 删除（不进合并结果）；若 beta2 缺 vibe 独有的租户口径文案守卫，另起测试 |
| C · 后端 content | `core/database/tenant_filter.py` | 并集：beta2 `_EXCLUDED_TABLES` + `bisheng.open_api.domain.models` 包级注册，加 vibe 的 app / app_version / app_instance / app_publish / resource_tier 注册 |
| | `api/router.py` | 并集：beta2 的 open_api 路由 + `router_public`，加 vibe 的 app_runtime / app_publish / dev_toolkit 路由；vibe 注释里的 `open_api_subject` 口径改为 marker |
| | `main.py` | 并集：beta2 `OpenApiAuditMiddleware` / `install_open_api_schema` / public 异常处理 / v2 请求体拒绝，加 vibe `_register_app_publish_composition` + app_runtime 异常处理 |
| | `api/v1/endpoints.py` | 四个 env 键并存（M14） |
| | `approval/domain/services/approver_resolver.py` | 两函数并存：vibe `resolve_tenant_admin_user_ids` + beta2 `resolve_resource_permission_role_users` |
| | `common/middleware/admin_scope.py` | 取 beta2（已含 `/api/v1/service-accounts` 与 `/api/v1/personal-tokens`） |
| | `core/config/settings.py` | 并集：beta2 beat 清理 + vibe `app_runtime: AppRuntimeConf` |
| | `core/openfga/authorization_model_f048.py` | 并集 + `f048-v5`（M13） |
| | `tenant/domain/services/f048_permission_subject.py` | 取 beta2（`service_account` 作为独立主体类型），去掉 vibe 的 `USER_TYPE_SERVICE` 排除 |
| | `user/domain/models/user.py`、`user/domain/services/user.py` | 取 beta2 侧结构，vibe 的 `user_type` 相关全部不带（M4） |
| | `test/permission/test_f048_schema_contract.py` | 并集断言（既有 `service_account` 主体、又有 `app` 类型） |
| D · 前端 content | client `@types/chat.ts` | 两个可选字段并存 |
| | client `pages/apps/components/AgentNavigation.tsx`、`hooks/useAppCenter.ts`、`components/AgentCard.tsx` | 并集：beta2 的分页 / 加载错误回调 + vibe 的 `searchActive` 与托管应用 `/apps/{slug}` 新开页 |
| | client `components/NotificationsDialog.tsx`、`components/approval/ApprovalCenterDialog.tsx`（beta2 删除、vibe 修改） | 取 beta2 删除；vibe 改动按 beta2 新落点搬：早分派 → `approval/ApprovalDetailPanels.tsx`；`DETAIL_INTERNAL_KEYS` / `DetailHeader` → `approval/approvalPresentation.tsx`；驳回必填 → `approval/ApprovalPane.tsx`；场景文案键映射 + `isApprovalMessageType` → `messageApproval/notificationContent.ts`。vibe 独有的 `approval/ApprovalDetailPrimitives.tsx` 已删、其 `DetailHeader` 下沉到 `approvalPresentation.tsx`；审批中心外壳由弹窗改为设置页 `pages/settings/SettingsPage.tsx` |
| | platform `contexts/locationContext.tsx` | 四开关并存（M14） |
| | platform `pages/SystemPage/index.tsx` | 取 beta2 结构（`ServiceAccount` + `PersonalToken` + `openApiManagementEnabled` 门控） |
| | platform `i18n.js` | 取 beta2（语言归一化），ns 列表去掉 `serviceAccount` |
| | platform `controllers/API/permission.ts` | 并集：`service_account` 主体类型 + `app` 资源类型 |
| | `eslint-suppressions.json`（client / platform） | 并集后以 lint 实跑为准，禁止手编 |
| E · i18n | `packages/locales/src/api_errors/{en,ja,zh-Hans}.json` | 冲突块取 beta2，其余保留；`node scripts/build.mjs` 重建六份产物；`check-i18n` 验收 |
| | platform `public/locales/*/{bs,api_errors}.json`、client `locales/*/translation.json` | 并集；`bs.json` 中 vibe 的 `serviceAccount` 相关键若已被 beta2 的键覆盖则删 |

---

## 3. 应用工场适配清单（合并后）

| 位置 | 改动 |
|---|---|
| `app_publish/api/endpoints/deploy.py` | 删 `app_manage_subject` 与 `is_known_scope` 导入校验；端点加 `@open_api_scope("app:manage")`（或在 `v2_router` 挂 `Depends(verify_open_api_access)` + 逐端点 marker，与 beta2 `open_endpoints` 写法一致）；`_principal()` 读 beta2 `OpenApiPrincipal`（`resource_owner_user_id` / `actor_id` / `scopes`） |
| `app_publish/domain/services/secret_scanner.py` | `KEY_PREFIX` → `SERVICE_ACCOUNT_KEY_PREFIX`；新增 `bs_pat` 规则（M11） |
| `user/domain/services/auth.py` | 删 `LoginUser.open_api_principal` |
| `app_runtime/domain/services/entry_authz_service.py` | 去 `user_type` 分类，会话主体恒为自然人 |
| `open_api/domain/scopes.py` | `app:manage` 的 `issuable` 改为运行时判定（M7）；补回 vibe 的分组 / 高危提示元数据仅当 beta2 前端签发弹窗需要 |
| `open_api/domain/services/credential_service.py` | `validate_scopes`：三扩展位 × `delegate` 互斥（M7） |
| `test/app_publish/conftest.py`、`test_deploy_api.py`、`test/app_runtime/conftest.py`、`test/dev_toolkit/conftest.py`、`test_secret_rules.py` | 主体桩改 beta2 `OpenApiPrincipal` 形状；`test_delegate_scope_is_not_issuable_this_release` 改为「`app:manage` 与 `delegate` 互斥」断言 |
| `permission/domain/services/catalog_policy.py` + `authorization_model_f048.py` | 双清单同步（M13） |
| platform `BuildPage/hostedApp/**` | 若引用 `appConfig.openPlatformEnabled` 保持；服务账号相关引用改 beta2 API |
| `features/v3.0.0-beta1/053-openapi-auth-and-identity/openapi-v2-key-auth-api.json` | 用 `generate_openapi_contract.py` 重生成（含 `/api/v2/apps/*`） |

---

## 4. 114 重建 runbook（2026-09-15 按 114 实查订正）

起点：114 在 `969897df5`、alembic 在 `merge_update_time_default_heads`、OpenFGA ACTIVE 为 `f048-v3`（从未发布过 v4 / v5）。`/opt/bisheng-ops/deploy.sh` 只从 GitHub 拉 `origin/$BRANCH`（默认 `3.0-vibe`），所以合并结果必须先推送。

1. **前置**：`free -m`（available > 2G，否则重启 worker 会让整机 OOM）；灵思没有 `IN_PROGRESS` 任务；导出服务账号快照（账号的名称 / 描述 / 归属人 / 租户，密钥的名称 / scopes / 到期时间，不含 hash），供第 9 步按原样重建。
2. **停服与备份**：停 8 个服务（api、celery-workflow / default / knowledge、beat、linsight-worker、runtime-manager、app-proxy；minio 与托管应用容器不停）；`mysqldump` 备份 **`bisheng` 与 `openfga` 两个库**。
3. **清 vibe 结构**（顺序由外键决定）：`DROP TABLE api_credential, service_account;` → `DELETE FROM user_tenant WHERE user_id IN (<服务账号 id>);` → ``DELETE FROM `user` WHERE user_type = 'service';``。必须在 upgrade 之前——drop 列迁移一跑，这些行就再也认不出来，会变成普通自然人。`app_deployment.submitted_by_user_id` / `auditlog.operator_id` 里的历史引用保留（无外键）。
4. **手工发代码**（不直接跑 deploy.sh：它先重启再冒烟，此时模型还没发布；且它的 alembic 那行在迁移失败时也打印 `(already at head)`）：`git fetch origin 3.0-vibe && git reset --hard FETCH_HEAD`；`uv.lock` 有依赖变化则 `uv sync --frozen`；`LC_ALL=C .venv/bin/alembic upgrade head` 并**人工看完整输出**，确认到达 `merge_app_factory_beta2_heads`。
5. **写 `config.yaml`**（先发代码再写键）：加 `open_api:` 块并显式写 `management_ui_enabled: true`；保留 `open_platform.enabled: true` 与 `app_runtime`；删掉 `app_runtime` 里已退役的五个容量键（只告警不拒启，但会误导排障）。
6. **发布 OpenFGA `f048-v6`**（服务全停、等 45s 心跳过期）：
   - 两个 dry-run 的目标 checksum 必须一致：`scripts/upgrade_f048_authorization_model.sh plan` 与 `PYTHONPATH=. python scripts/publish_authorization_model_change.py`（后者同时扫描持久 `department:*#subtree_member`，必须为空）；不一致或扫描有命中就停下。
   - `upgrade_f048_authorization_model.sh apply` → `verify`（发布模型、切 release、回填 `app` 的 action scope；verify 只核 SQL 侧，不依赖部门上下文）。
   - `publish_authorization_model_change.py --apply --confirm-store-id <id> --confirm-target-model-checksum <sum> --operator-id <id>`，补 `service_account:*` 资源标记（预期 already_current 或完成补齐）。
   - ⚠️ 不是 `--allow-model-upgrade`（那是 `reconcile_f048_visible_projection.py` 的参数）。v4 与两个 v5 各缺一块：缺 `app` 则托管应用 ReBAC 全部失效，缺 contextual 部门成员则注入的临时 tuple 被拒、依赖部门的判定全部 19002。
7. **前端**：`pnpm install --frozen-lockfile` → `bash /opt/bisheng-ops/rebuild-web-13000.sh`（client 与 platform 都建，先建 `build.new` 再原子 mv）→ 重启手工起的 vite dev（4102 / 4103，pgrep pattern 写进脚本文件）。
8. **起服务**：`bash /opt/bisheng-ops/deploy.sh`——fetch 与 alembic 都是 no-op，重启 8 个服务（**已包含 runtime-manager 与 app-proxy**）并跑 smoke；smoke 跑早了就等 API active 后单独重跑。
9. **恢复服务账号与密钥（持有人无感）**：两套实现的密钥存法完全一致（`sha256(明文)`、`bs-sak-` 前缀、43 位密钥体），所以**不要重签**。先在管理面按快照建出 11 个账号（名称 / 描述 / 归属人），再在一个事务里：把 `service_account.id` / `create_time` / `update_time` 改回旧值（id = 旧 `user_id`，新表无外键引用）→ 把备份里的 `api_credential` 行原样插回（原 id、哈希、`last4`、名称、scopes、`last_used_at`、`create_time`，列名显式列出）。存量 scopes 只在签发 / 编辑时校验，保留 `model:invoke` / `identity:read` 不影响调用。脚本见 114 备份目录 `restore_original_sa_114.py`。
10. **验收**：`/api/v1/env` 三个开关为 true、`runtime-status` 正常、在线容器仍 healthy；**非管理员**经部门授权打开托管应用（验 v6 部门成员语义），无权限者被拒；CLI `login → deploy → client 审批 → 非管理员访问新版本 → logs`。

**回滚**：停服 → `upgrade_f048_authorization_model.sh rollback` → 用两份 dump 恢复两个库 → 代码回 `969897df5` 并恢复原 `config.yaml` → 恢复前端 `build` 备份 → 重启。

---

## 5. 顺延与不做

- `hosted_app` 运行期凭据主体（F055 T055）、`model:invoke` / `identity:read` 可签发（F051 / F052）。
- beta2 与 PRD 的 4 处产品裁定项（D4 独立表、头名 `X-On-Behalf-Of`、日常模式砍功能 + `/chat/list`、v3 匿名面）**按 beta2 现状接受**，裁定权在产品，清单拟落 `features/v3.0.0-beta1/053-openapi-auth-and-identity/prd-deviation-review.md`（2026-09-10 核实：该文件在 beta2 与 vibe 两侧都尚未写，随 §7 回流 beta2 时补）。
- vibe F049 tasks.md 的 43 条未完成任务不再逐条推进：T034–T046（端点接入 / 缺陷修复 / 配置移除）已由 beta2 实现；T047–T056（share-token）beta2 明确不采纳；T057–T071（资源归属人 / 主体侧授权 / 对账豁免 / 管理接口矩阵）已由 beta2 `ResourceGrantsTab` + `owner_repository` 承接；T072–T075 随 beta2 F053 发布验收。

---

## 7. 待回流 beta2（合并期发现的上游悬空引用，本分支不越界改）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| 1 | `AGENTS.md:60` | 引用 `packages/ui/docs/基础-阴影与圆角规范.mdx`，实际文件名是 `基础-圆角与阴影规范.mdx`（词序颠倒） | 回流 beta2 改文件名引用 |
| 2 | `docs/constitution.md` C7 | 引用 `.claude/rules/platform-frontend.md` / `.claude/rules/client-frontend.md`，仓库无 `.claude/rules/` 目录（前端约定实际在 `src/frontend/platform/AGENTS.md` / `src/frontend/client/AGENTS.md`） | 回流 beta2 改指向两份 AGENTS.md |
| 3 | `.claude/skills/approval-module/SKILL.md`（beta2 侧文件） | 前端表引用 `messageApproval/MessageApprovalDialog.tsx`（已被 `pages/settings/SettingsPage.tsx` 取代）；§8 注仍写 `isApprovalMessageType`（`NotificationsDialog.tsx:152-156`），真身在 `messageApproval/notificationContent.ts` | 回流 beta2 同步落点（`.cursor` 副本本分支已按现状同步） |
| 4 | `features/v3.0.0-beta1/053-openapi-auth-and-identity/prd-deviation-review.md` | §5 所引的 4 处产品裁定清单文件尚不存在 | 回流 beta2 时补写 |
| 5 | `test/user/test_user_tenant_sync_service.py` | beta1 f6bf9f51f（D19 换租户随人迁移）让 `user_tenant_sync_service` 在换租户路径调用 `PersonalTokenService`，但同一提交没有给该测试补 patch——纯 beta1 / beta2 环境跑该文件即受此自带缺陷影响；本分支已在测试里 patch `PersonalTokenService` | 回流 beta2 同步补 patch |
| 6 | `src/backend/bisheng/open_api/domain/repositories/service_account_repository.py` + `domain/services/service_account_service.py` | **子租户管理员可管理根租户服务账号并对其签发 / 吊销密钥**（vibe 有显式租户比较、beta2 没有）。已修在 `fix/3.0.0-beta2/service-account-tenant-boundary`（`954982ba3`，8 例回归测试，回滚实现后前 7 例全红），并 cherry-pick 回本分支 | 请 highway 采纳该分支 |
| 7 | `src/backend/bisheng/open_api/domain/scopes.py` | 本分支给权限位登记补回了 vibe 侧原有的展示元数据（`group` / `label_key` / `desc_key` / `hint_keys`）与 `requires_open_platform`——签发弹窗的分组、文案、互斥判据都依赖它。beta2 侧没有，下次合并必冲突 | 建议整体回流发版线 |
| 8 | `src/backend/test/tenant/test_tenant_users_query_source.py` | 它用 `extend_existing` 声明了一个也叫 `user` 的测试表并把 `user_name` 放宽到 255，于是 `test/tenant` 与 `test/user` **同进程跑必红**（`test_user_string_lengths` 读到 255）。判回归时要按目录分进程，或先修表名 | 回流发版线改表名 |
| 9 | `src/backend/bisheng/open_api/domain/services/credential_validator.py` | `resolve_service_account` 跑在租户上下文装好之前，且没有 `bypass_tenant_filter()`（`CredentialRepository.get_by_hash` 有）。多租户部署下这条路径可能抛 `NoTenantContextError` 被包成 503；单租户看不出来 | 请 highway 裁定是否补显式 bypass |
| 10 | `src/backend/bisheng/open_api/domain/services/credential_validator.py` | 伴生 PRD 附录 C 把「服务账号已停用」单列一码（`26027`，与 PAT 持有人失效的 `26043` 同理），beta2 运行期把它折进了 `26002`「凭据无效」——调用方分不清「密钥错了」和「账号被停用」，下一步指引方向不同。CLI 已按服务端事实把两种成因并进 26002 的文案 | 产品口径偏差，建议登记进 `prd-deviation-review.md` 一并转给 highway |


---

## 6. 进度日志

| 日期 | 进度 |
|---|---|
| 2026-09-10 | 方案定稿；worktree `bisheng-prd1` + 分支建立；开始合并 |
| 2026-09-10 | 合并完成：`d2dadca8f`（beta2 da2be5697，54 处冲突按 §2 解）+ `e590ac60a`（beta1 tip 59b27d1c1，含 D17 / D19 修复 `f6bf9f51f`）；§3 适配（deploy 管线 marker 化 / `secret_scanner` / `user_type` 移除 + alembic 单头 / M7 互斥 / 前端收口 / FGA `f048-v4`）分组并行进行中；文档回写：release-contract（表 1 主体类型 + INV-28 D19 + 260 段 owner）/ README / mvp-114-path / F049 三件归档标注 / F053–F056 过时引用 / 架构文档 14 配置键 / constitution `Last revised` / `.cursor` approval-module skill 落点 |
| 2026-09-10 | 适配批一检查点 `865b1b9e2`（deploy 管线 marker 化 / `secret_scanner` 双前缀 / `user_type` 移除 + alembic 单头 / M7 互斥 26050 / 前端收口 / FGA 并集）；FGA 版本由 `f048-v4` 改判 **`f048-v5`**（beta1 已占 v4，M13 已订正）。修复批并行：测试桩改 beta2 `OpenApiPrincipal` 形状、`test_user_tenant_sync_service` patch `PersonalTokenService`（§7-5）、F054 T071 / F055 T044a · T045–T048 / F056 T016 按代码证据勾选、C5 与伴生 PRD 附录 C 登记 26050、`config.yaml` 注释补 `open_api` 三键（`management_ui_enabled` / `pat_enabled` / `pat_admin_ttl_days`） |
| 2026-09-10 | 补 INV-31 运行期兜底：新登记 `26051`（通道入口拒持 `delegate` 的密钥，403，排在权限位校验与委托解析之前），CLI 把 `26016` / `26051` 一并映射为「委托专用、另签一把」并落 exit 5——原先 `login` 得 exit 19、`deploy` 被 26003 引向管理员而管理员被 26050 挡住 |
| 2026-09-10 | 补 CLI 通道租户口径：`publish_pipeline_service._assert_owned` 与 `app_query_service._require_log_access`（仅 owner-only 入口）在比 owner 之外加应用租户 vs 凭据租户比对，不等按原有「不存在 / 非归属」同形答（16205 / 16101，不新增错误码）——`/api/v2` 的 `visible_tenant_ids` 含根租户、D19 令牌随人换租户不失效，两者叠加让归属人换过租户后仍能 `bisheng logs` 读到根租户应用；F054 design D-日志 / T055、F055 design 流程图与端点表已同步 |
| 2026-09-10 | 前端补 INV-31 表单互斥：签发/编辑弹窗（`KeyIssueDialog`，两态同一组件）按权限位目录的 `group === local_dev_toolkit` 派生扩展位集合，勾了 `delegate` 即置灰三扩展位、反之置灰委托并各给一句原因，存量双勾的旧密钥两侧都可点但禁用保存——26050 兜底保留 |
| 2026-09-10 | CLI 侧改按 beta2 实际契约取值：`whoami` 读 `actor_kind` / `actor_id` / `actor_name` / `resource_owner.user_id`（F049 的 `subject_kind` / `service_account{id,name}` / 归属人姓名皆已不存在，归属人如实只印 ID、无归属人时直说不能 deploy）、凭据快照同名收口；`26002` 文案补「服务账号被停用」（beta2 运行期不再抛 `26027`）、`26004` 改按「委托被拒」措辞、补登记 PAT 的 `26040` / `26043`、掩码兼收 `bs-pat-`；`selfcheck.py` 的 `owner["name"]` 两版都取不到已修；新增 `tests/test_platform_contract.py` 用 `ast` 读服务端 `WhoamiResponse` / 错误码类与测试桩对账（不 import 后端，CLI 只有 2 个运行期依赖）——原先 254 用例全绿却在断言一个不存在的服务端 |
| 2026-09-10 | **五视角对抗评审**（鉴权链 / 合并丢改动 / CLI 与部署链 / 契约文档 / 测试质量），每条发现两名反驳者独立复现。确认并已修：租户防线丢失（M17，`cc156df1a` cherry-pick 自发版线分支）· INV-31 运行期兜底（`26051`）· CLI 契约漂移与测试桩造假 · CLI 通道租户口径三处 · 签发表单互斥 · 一批文档矛盾。**证伪**：密钥扫描 `\b` 收尾漏检——`secrets.token_urlsafe(32)` 第 43 位只承载 4 bit，末位字符结构性地只可能是 `048AEIMQUYcgkosw` 之一，`-` 不可达，命中概率为 0 |
| 2026-09-10 | **验证口径与结论**：基线取两侧（纯 `3.0-vibe` 与纯 `origin/feat/3.0.0-beta2` 各建 worktree 跑同一批目录）。后端分区失败**全部在某一侧基线上同样失败 = 零回归**，另有 21 条基线失败在本分支转绿；`import bisheng.main` 通过、alembic 单头、compose 契约守卫全过、v2 OpenAPI 契约重生成后无漂移、`check-i18n` 无新增漂移；platform / client typecheck 与 lint 全绿，前端测试失败逐条在两侧基线复现（platform 10 条来自 vibe、client 7 套件 = vibe 4 + beta2 3）。**新发现并修掉一处只在组合下暴露的顺序污染**：`test/app_publish` 不复位租户 ContextVar，先跑它再跑 `test/open_api` 会让「执行上下文已拆干净」的断言失败——按目录分进程的 CI 看不到，判回归至少要跑一次同进程组合（⚠️ 但 `test/tenant` 与 `test/user` 是例外，同进程必红，原因见 §7-8） |
| 2026-09-15 | **二次同步发版线**：合入 `origin/feat/3.0.0-beta2` 03106e053（98 提交：F066 PAT 数据范围 / contextual 部门成员 / v2 错误码与状态对齐 / 单点登录 / 商业授权 / v3 匿名面；beta1 tip 已全含），merge `8496897b0`，23 个冲突文件按 §2 规则解（locale JSON 用三方键级合并，无叶子冲突，六份产物重跑 `build.mjs`）。**适配**：FGA 升 `f048-v6`（M13）+ 性能契约 checksum 重算；alembic 再次双头 → `merge_app_factory_beta2_heads`；托管应用入口补单点登录校验（复用 `_validate_current_session_token`，被踢会话答 `login / session_superseded`）；`test/app_publish` 隔离夹具补 `knowledge_data_scope_memo`。**核实无需改**：INV-31 运行期拒绝随 beta2 的 `open_api_access_context` 重构原样保留；`open_platform.py` / `endpoints.py` 自动合并无重复；upgrade 脚本 verify 只核 SQL 侧、reconcile 核验的是直接 tuple，都不依赖部门上下文。§4 runbook 按 114 实查订正 |
| 2026-09-15 | **验证与合回**：后端同范围（open_api / permission / approval / api / database / workstation）与纯 beta2 基线做差集，新增失败 2 条，均在 09-10 的 vibe 基线里已失败（seed 用例单跑通过=顺序污染；f040 用例连真 MySQL）→ 零回归；应用工场四目录同进程组合后 `test_deploy_api` 10 条随 beta2 真实 HTTP 状态契约改为断言 400（CLI 先读信封，不受影响）；CLI 268 / app-proxy 154 / runtime-manager 102 通过，compose 守卫全过；platform vitest 相关 7 文件 34 例通过；lint 93 条 / typecheck 3 条（`ApiRequestExamples` 大小写）/ check-i18n 27001 缺文案均为 beta2 自带。merge `639da9cfb` 快进 `3.0-vibe` 并推送，分支与 worktree 已删除 |
| 2026-09-15 | **114 按 §4 重建完成**：备份（`bisheng` + `openfga` 两库、服务账号快照、config、前端 build）在 `/root/backups/pre-beta2-base-20260915/`；DROP 两表 + 删 11 个服务账号的 `user` / `user_tenant` 行；alembic 12 步到 `merge_app_factory_beta2_heads`；FGA `f048-v6` 发布（model `01M2HN5NAWMRVSFYDW510RMAS0`，app 六动作生效，896 条 `service_account:*` 标记核验）；deploy.sh 冒烟全过（含非管理员）；前端两份静态 build 重建、vite 重启；**11 个服务账号与 9 把密钥按原 id / 原哈希恢复，持有人无需任何动作**（最初重签了一批新密钥，发现存法兼容后删除未分发的新密钥、改回原数据）。无感验证：以同样方式直插的临时密钥 whoami 正确解析为 90023 / 归属人 90012；新版与合并前版本 CLI 的 `login` / `logs` / `deploy` 均走通（旧 CLI 重新 `login` 时账号名显示「(未命名)」，因旧 whoami 字段已换；已登录者不受影响）；管理面 11 个账号 id、归属人、密钥掩码 / scopes / 最近使用时间与迁移前一致。审计里留有 09-15 12:30 重建时的 20 条创建记录（指向已改号的临时 id），未删。**验收**：CLI `login → deploy`（临时应用 `e2e-beta2-0915`，received→build→probe→审批单 8s）→ 审批通过 5s 上线 → 同租户非管理员经「研发部 + 含子部门」授权进入 200、子树外 403（v6 contextual 部门成员生效）→ `bisheng logs` 正常 → 下线并删除。**顺带发现（非本次引入）**：① form-survey 被 08-18 的 `execute_failed` 审批实例挡住迭代发布（16251，`_DUPLICATE_ACTIVE_STATUSES` 含 `execute_failed`，需在审批中心异常处理收尾）；② 托管应用删除先 `_transition` 到 DELETED 再 `_project_delete`，后者因 `_target` 拒绝 deleted 状态抛 19003——状态与容器已删，但 FGA tuple 未清、`app.delete` 审计与生命周期钩子未执行（F054 首版 `244886ebd` 起即如此）；③ 跨租户访客进入托管应用答 404 属 AC-29 设计 |
