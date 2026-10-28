# F113 定向验证与提测记录

日期：2026-10-28。分支 `codex/113-service-account-tenant-consistency`，开发基线 `3d0406bc6615a4c04dcc3e846879d8e7524df47f`；用户要求先提交推送本功能开发分支；该提交不代表已发布或验收完成。规格38条AC及修订设计已获用户分别确认。

## 1. 当前结论

代码与定向用例/L1已完成，任务51/53。**未完成真实部署E2E、UI人工验收和最终L2合入门；不能作为已交付声明。** 没有更改116三个存量应用、账号24或审批414/415；本轮仅按授权提交推送开发分支，不对测试环境进行部署或数据写入。本轮未运行全量测试。

## 2. 已执行的定向验证

命令在worktree的`src/backend`运行，解释器为主checkout既有`.venv/bin/python`，`PYTHONPATH=.`；前端在`src/frontend/platform`运行Vitest。以下是分批结果，不相加为去重总数。

| 分组 | 实际执行与结果 | 证据边界 |
|---|---|---|
| 实时账号绑定 | `test/open_api/test_service_account_tenancy.py` 9 passed | SQLite真实User/UserTenant/SA；缓存热命中、迁出再迁回、改owner、0/多条关系、依赖故障、其他主体 |
| 原凭据兼容 | `test/open_api/test_credential_validator.py` 4 passed | 原fixture补真实人员/成员关系；无全局资格放行桩 |
| MCP新工具调用 | `test/open_api/test_mcp_tenant_revalidation.py` 2 passed | 真handler＋真实成员查询；本地SDK构造器桩，非真实传输 |
| WS新消息 | `test/open_api/test_websocket_tenant_revalidation.py` 5 passed；原WS认证3 passed的独立记录 | 回调与v2实际生产者；在途任务/共享连接身份不变；非网络WS E2E |
| 人工应用边界 | `test/app_runtime/test_app_tenant_access.py` 10 passed | 生命周期、meta、data、log策略允许/拒绝；已认证principal优先 |
| 发布/源码独立读取 | `test/app_publish/test_review_tenant_access.py` 10 passed | publish-status及4种源码读取在存储前拒绝；5种角色原权限配对 |
| 冻结发布来源 | `test/app_publish/test_release_tenancy.py`原17 passed；后续`-k 'repository or accept or preapproval or worker or preview or human_metadata'`与批准启动合跑9 passed、19 deselected | 真实有界SQL、不同阶段前置、new preview/describe区别；有部分外部端口桩 |
| 批准与人工启动 | `test/app_publish/test_approved_start_tenancy.py`原4 passed；新增持久失败/清理故障单例1 passed | 内部来源无模拟owner登录；真实SQL失败记录保留current/pending，清理故障不覆盖租户错误 |
| 配置确认重建 | `test/app_runtime/test_secret_rebuild.py`新F113迁出拒绝＋既有正常/确认重放2 passed | 真实User/UserTenant/AppDeployment；SQLite单连接共享测试UoW；生产事务实现不变 |
| 管理范围 | `test/open_api/test_service_account_management_scope.py`原11 passed；inventory/candidate/API选例3 passed、11 deselected；scope HTTP新增单例1 passed | 严格预期头、Root=1、普通admin、disabled/Redis故障；ASGI真实dependency与SQLite，不是真实部署 |
| 旧MCP工具合同 | `test/open_mcp/test_server.py -k 'call_tool or list_tools'` 5 passed | 只测工具合同；为构造器/凭据端口使用显式fixture，不替代资格或传输证明 |
| Platform范围/请求 | `serviceAccountScope.test.tsx` 9 passed | 10类写请求固定scope、迟到/取消、候选分页、切换失败、无默认Root、普通admin、StrictMode |
| 确认框 | `useConfirm.test.tsx` 2 passed | 原失败重试＋所属scope取消关闭；无新视觉样式 |

只对修复点重跑：scope HTTP用例将非超管断言修正为既有26022；SQLite重建fixture解决单连接嵌套BEGIN后仅重跑两例；MCP旧scope拒绝合同发现26003替代原字符串，已保留原PERMISSION_DENIED并仅重跑5个handler合同。不是全量回归。

## 3. 静态检查与限制

- 修改Python文件Ruff check/format通过；无新表/列/Alembic迁移。DM8仅静态：有界SQLModel查询及SQLAlchemy相关子查询/COUNT，未做DM8真实执行。
- arch-guard对本功能69个代码文件逐文件与HEAD基线比较，无新增消息。common/chat两文件各两条旧RULE-1及service_account endpoint一条旧RULE-5保持，不能称仓库绝对全绿。
- 修改前端文件定向ESLint通过；错误码源生成`build.mjs --check`、`scripts/check-i18n.mjs`通过。
- `pnpm --dir src/frontend/platform typecheck`受共享UI缺少图标导出、chat的`@bisheng/ui`解析及其他文件既有/依赖环境错误阻塞；报错清单不指向本次修改文件。没有更改依赖或抑制文件来掩盖；不记typecheck通过。直接tsc同样存在全项目错误，只用来定位，不作为门禁通过。
- formatter现有配置在本机触发CommonJS require ESM/top-level-await错误；仅本次新增文件及API模块用无插件临时配置排版，未改仓库formatter或依赖。
- E2E脚本 `test/e2e/test_e2e_service_account_tenant_consistency.py --collect-only`：1 test collected；**未执行真实HTTP测试，也不将默认skip记通过**。
- 本轮未执行Docker/K8s、全量backend/frontend测试、DM8、arm64、离线安装或授权验证。

## 4. AC追溯及待执行项

| AC | 当前定向证据 | 真实/人工验收 |
|---|---|---|
| AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-32 | 实时绑定、凭据、MCP/WS用例 | 临时owner迁出/迁回，同一key热缓存、实际MCP下一工具和WS下一消息待验 |
| AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16 | 冻结来源、流水线/预览钩子、批准启动、持久失败、配置重建 | 真Celery/审批outbox/manager串联拒绝与清理待验 |
| AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27 | 管理scope API、SQL候选、10类写inventory、Platform9例 | opt-in脚本验证临时SA+真实key；页面三角色/双标签页/窄屏待验 |
| AC-28、AC-29、AC-30、AC-31 | 没有维护脚本/迁移；没有远端写入；定向变更范围核对 | 部署前后存量只读快照一致性待验 |
| AC-33、AC-34、AC-35、AC-36、AC-37、AC-38 | 人工应用策略、独立源码/状态读取、source批准启动与配置重建 | 临时app的新旧租户会话、原超管例外、后台旧版本恢复待验 |

## 5. 提测前置与边界

- 专用多租户环境部署本次backend/worker/platform；不需要更改runtime-manager镜像或数据库schema。用户此次选择先提交推送，因此暂不更新平台服务；真实部署验收保留待办。
- 管理页和后端同步更新。旧多租户超管脚本先 `PUT /api/v1/service-accounts/management-scope {"tenant_id": <正整数>}`，再带 `X-Service-Account-Tenant`（表单打开时固定值）；Root显式1，不用null。
- 自动烟测通过`F113_E2E=1`显式开启；E2E_API_BASE、RAM-only E2E_ADMIN_TOKEN、F113_E2E_TENANT_A/B、F113_E2E_OWNER_A/B由安全环境注入。两owner须为独立e2e-f113用户，名称可被候选接口搜索；可选F113_E2E_RUN_ID仅小写字母数字。
- 脚本仅创建/删除该tenant、该owner及精确e2e-f113前缀的临时账号；先清残留、最后清理并恢复超管原共享scope。临时key仅内存，测试目标repr不含token/headers；不迁移人员、不改既有应用。
- 人员迁移、在途发布和实际连接验收按设计§7.2与`e2e-checklist.md`专用临时对象执行。现有116三个应用/账号24/审批414/415不是测试目标。
- 发布前仍需消除/确认typecheck环境阻塞，完成真实E2E及最终L2；本次用户已授权提交推送开发分支；合入发版线及部署仍按后续指令执行。

## 6. 本次提交推送口径

用户已明确“先开发完成提交推送远端”。交付分支为`codex/113-service-account-tenant-consistency`；不合入`feat/3.0.0`或`release`，不创建tag，不触发镜像发行。当前代码实现及L1已完成，T047真实验收、T048最终合入门保持未完成。复用本轮已完成的功能定向测试，不重跑全量；提交前只核对差异、Ruff/修改文件lint/i18n及记录完整性。

推送前已fetch；核对`origin/feat/3.0.0@1e1c2b9ae0950c4bab8c05765825dbf5a50ccd68`与开发基线，账号/应用/发布核心代码及C5登记无分支间修改冲突。开发分支尚未包含发版线上15个后续提交，合入前仍须按实际最新基线集成核对。远端最终SHA由提交后独立`ls-remote`核验，不在提交正文中循环写入自身摘要。
