# Token Exchange 验证报告

目标：PR2821 → feat/3.1.0-alpha1，已整合7f665b1704的F003平台会话。2026-11-27用户确认第一方静默规则并要求开发完成后部署115，且明确不需要备份。目前本地实现验证完成，115部署尚待SSH认证；没有把本地通过当作115上线。

## 最新：第一方扩展验证

全套同进程合跑 **217 passed, 1 skipped, 913 warnings，10.70s，exit0**，覆盖整个test/oauth2_provider、test/platform_auth，两条真实TCP交换链路、request-scope registry/bootstrap和Alembic single-head。源接缝48项+原平台session10项单独联合58通过；provider新增22项和fault/登记重放回归包含在总数中。

第一方TCP链路：合法HttpOnly式选定Cookie+Origin/CSRF静默换B→JWKS验签/错误aud拒绝→开启require_consent后consent_required→现有authorize/consent明确批准→静默再换成功→HTTP撤销本人同意后B在线401→重新允许免同意后换B→HTTP/auth/logout后B在线401。使用真实Uvicorn/httpx、SQL平台会话引擎；仅自然人/成员事实和Redis为隔离fixture，未执行真实密码登录/生产中间件全栈。共享TCP helper在finally停止线程并关闭socket。

独立审查发现旧待授权页跨同client_id新登记写入consent的问题；修复request/code登记绑定，pending/code/existing-consent三相回归通过。原成员删除测试人工code fixture补充登记字段，原UserInactive拒绝断言保留。

新增schema auto-discovery与MySQL表/索引编译已纳入原双库参数化测试；DM8仍因缺dmSQLAlchemy显式跳过，实库覆盖不计通过。Ruff与arch-guard通过，28119三语文案由生成器输出，route inventory包含新增IDENTITY本人同意撤销端点。完整main/Gateway与115实库验收待部署，需保留F003回滚地板；用户要求不额外备份。

## 历史：原OAuth换证首次验证

## 执行结果

最终同进程合跑：**82 passed, 1 skipped, 208 warnings，10.15s，exit0**。

覆盖：

- 原Provider43项：code/PKCE/refresh/revoke/DSH兼容。
- 新换证与边界：严格iss/aud/类型/身份绑定，scope整体拒绝，当前client和policy限制，固定起始期限计入250秒处理耗时，父session短寿命，失败事务回滚child/link，缺link拒绝，公开客户端拒绝，缺省grant不启用，管理global flag配对，日志值脱敏，重复字段/JSON键/Basic混用/超限。
- 真实TCP集成1项：启动本地Uvicorn，通过httpx执行authorize→consent→A授权码换证→B token exchange→JWKS验签→userinfo→撤销A→B在线401；参考B拒绝其他aud。线程与socket在finally退出。本套SQLite临时库逐例隔离，Redis/身份是fixture，不访问业务数据。
- route registry/bootstrap、Alembic单head；新管理API均声明platform。生成路由元数据更新至1028条。
- 新模型自动发现、MySQL DDL和索引编译通过。DM8 DDL测试显式skip：本机没有dmSQLAlchemy包；不是编译失败修复后假报通过，未执行DM8/MySQL实库。
- Ruff检查及格式通过；arch-guard新增生产文件无输出；三语错误源经生成器写出，两前端生成物check通过，check-i18n无新增漂移。

曾发现并修正：route registry测试因新增两路由未生成而失败，已使用现有export_request_scopes生成；DM编译最初因依赖缺失失败，拆分为参数化可选方言测试，MySQL独立执行，缺依赖DM明确skip。没有修改既有测试来掩盖功能失败。

## 可复现命令

在src/backend，激活兼容虚拟环境，用安全测试配置设置config，并提供bisheng_DATABASE_URL=sqlite://；本机环境需清除继承的HTTP/HTTPS/ALL/NO_PROXY（含小写）避免代理依赖干扰。示例：

	database env: bisheng_DATABASE_URL=sqlite://
	pytest test/oauth2_provider test/e2e/test_e2e_token_exchange_local.py test/admin/test_request_scope_registry.py test/admin/test_request_scope_bootstrap.py test/database/test_alembic_single_head.py -q -p no:cacheprovider

配置示例为docker/bisheng-ft/config.yaml（只提供本地测试所需Redis占位）；测试并不连接该Redis。运行环境本次为已存在的Python3.12环境，未改pyproject或锁文件；正式镜像仍使用项目的Python3.11+约束，未声称已在正式镜像运行。

## AC与证据映射

| AC | 主要自动证据 |
| --- | --- |
| 01/08/14/15 | test_lifecycle_independent_revoke_and_parent_revocation；test_http_authorize_exchange_recipient_and_revocation；test_fixed_start_deadline；test_parent_expiry_and_missing_link |
| 02/03/06/07/10 | test_scope_is_whole_request_denial；test_policy_updates_and_child_online_scope_check；test_client_and_parent_scope_denials；test_default_grants_and_public_source |
| 04/05/12 | test_signed_but_invalid_subject_claims；test_other_credential_types_rejected；test_identity_failure_and_dependency_outage；test_commit_failure_rolls_back |
| 11 | test_policy_admin_http_boundary（依赖已认证身份的global flag被覆盖；不是实际OpenFGA/浏览器登录验收） |
| 13/16 | test_redacted_dependency_logs；test_http_strict_exchange_and_legacy；test_duplicate_json_basic_mixing_and_limits |
| 17 | 原43测试、route registry/bootstrap、single_head、新表发现与MySQL编译 |

## 实际局限

没有全生产main lifespan配合真实MySQL/Redis/OpenFGA/Gateway验收，也没有真实B产品的本地会话建立、普通用户浏览器交互或DM8实库验证。真实HTTP测试覆盖实际F026路由/服务/签名，但使用测试app和被覆盖的身份依赖；不能据此宣称109上线或生产全链路通过。没有新增UI，因此无新增页面验收项。用户现已明确授权115部署，待获得SSH连接后执行真实环境回归；尚未执行不得声明上线。

代码审查与接入说明见code-review.md、README.md。
