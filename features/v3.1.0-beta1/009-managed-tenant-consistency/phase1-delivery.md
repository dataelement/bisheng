# 管理租户第一阶段交付与测试重点

日期：2026-11-13（Asia/Taipei）。状态：**第一阶段本地开发及定向回归完成，专用环境端到端验收待执行；未合并、未推送、未部署。**

分支：`codex/3.1.0-beta1/tenant-context-phase1`。隔离工作树：`/Users/zhangguoqing/works/bisheng/.worktrees/tenant-context-phase1`。开发基线为当时最新远端发布线 `origin/feat/3.1.0-beta1` / `fe4ae2cdd17d42c95dfe9d03e0b7070b57ac97b0`。主工作树既有未提交修改未纳入。

## 1. 实际修改与影响范围

| 业务链 | 修改后的行为 | 主要文件/配对验证 |
| --- | --- | --- |
| 访客链接设置 | 已登录读取及设置使用经验证的管理目标；写入校验页面目标。匿名访问保留独立凭据和权限 | `common/middleware/admin_scope.py`、`controllers/managementScope.ts`；`test_f114_scope_middleware`、`managementScope.test` |
| 管理导航/模型展示 | 全局导航只取工作台图标，不触发模型、工具、知识运行策略；跨主属超管展示目标的合法模型配置，不构造个人角色/额度 | `workstation`配置端点/服务、`dsh/model_catalog.py`、`llm/api/router.py`、`locationContext.tsx`及API；导航HTTP、模型展示/引用拒绝测试 |
| 创建者/运行人检索 | 根据真实用户主属构建身份，保留工作流资源执行目标；权限开关决定选用的身份，已有动作检查保持 | `space_flow_retrieval.py`；真实有效角色解析、上下文及拒绝回归 |
| 角色创建/维护 | 默认本租户角色取已验证目标；显式共享需平台资格，新定义在Root；菜单随定义所有者。页面展示类型及已授权可见定义的所有者 | `role` schema/service/API、Roles/视图/API类型及三语词条；真实SQLite、服务及表单回归 |
| 上传预览 | 暂存、启动预览、修改/删除块四类写入口检查页面目标；资源/上传人/修订检查不变，通用临时上传不新增目标要求 | 前后端既有目标校验清单；六种写入组合的缺失/错误/匹配测试及原上传预览测试 |
| 当前平台资格 | 触及的敏感写入、访客设置、完整工作台/模型展示及工作流连接重验权威资格；拒绝旧正缓存或未知事实带来的放行 | `http_middleware.py`、`admin_scope.py`、`auth.py`；缓存失效、独立合法旧管理员来源、未知拒绝测试 |
| 辅助404 | 辅助资源GET的业务404展示结构化错误，保留当前页面；原403及整页切租户刷新保持 | `request.ts`；请求兼容矩阵及错误测试 |
| 工作流连接 | 认证连接固定已验证资源目标，核验流程归属、类型、就绪和原use动作；断开/异常恢复上下文。已验证桌面设备会话用凭据目标 | `workflow.py`、`workflow/application/browser_scope.py`、`auth.py`；连接目标固定/恢复、错目标拒绝、设备凭据隔离测试 |

既有Worker消息上下文及流程持久目标的恢复格式未改变，不额外读取浏览器后续选择。未改客户端应用、Java网关、工作流Worker调度或依赖清单。

## 2. 历史数据和接口兼容

- **本次不新增表/列，不执行迁移、回填或线上数据修改。**旧批次已有字段和迁移保持。本次没有历史绑定修正、部门划租承接、重新授予默认角色或额度重算。
- 旧角色类型、定义所有者、菜单所有者、用户绑定及人员主属不搬迁。针对非Root持有的既有共享定义，真实数据库回归验证编辑后所有者/菜单仍留原处。创建者仍是真实用户，不伪装为目标租户成员。
- 角色创建新增可选 `role_type`，省略时为 `tenant`；旧调用方如果依赖超管隐式创建共享角色，需要显式传 `global`。编辑不支持类型/所有者转换。该行为变化已登记版本合同。
- 角色列表/详情/创建/编辑新增定义 `tenant_id` 展示字段，仅对本来获准可见的角色返回，不开放跨租户人员目录或新的绑定权限。
- 工作台原完整GET保持；新增可选 `purpose=navigation` 时仅返回 `assistantIcon`。没有用导航数据替代运行配置校验或修复失效引用。
- 触及写入口需要现有 `X-Management-Tenant` 请求头：缺少返回400/19703，过期目标返回409/19704。请求头不是权限凭证，普通人员仍用合法自身租户及已有权限。
- Redis仍保存整数租户选择；用户主属、普通角色、菜单、个人配额及合法独立凭据规则不被管理切换重写。

**前后端须配套发布。**新前端搭配旧后端可能忽略角色类型/导航用途，旧前端搭配新后端可能缺少新覆盖写入口的目标头；不要通过兼容回退去掉服务端拒绝。发布前盘点直接调用角色创建接口的脚本。

## 3. 本地验证

| 检查 | 实际结果 | 证据/限制 |
| --- | --- | --- |
| 后端定向业务测试 | 157通过、3个已确认基线失败用例排除 | `/private/tmp/tenant-phase1-targeted-final.log`；详细范围和排除项见下文 |
| 工作台及模型既有配置兼容 | 35通过 | `/private/tmp/tenant-phase1-config-final.log` |
| 前端请求、表单、菜单和配额回归 | 42通过，6个测试文件 | `/private/tmp/tenant-phase1-final-frontend.log` |
| Python Ruff格式/规则 | 通过 | 修改和新增Python文件；未扩大格式化到全仓 |
| 架构守卫 | 无VIOLATION；workflow端点已有模型导入警告 | `/private/tmp/tenant-phase1-arch-guard-final.log` |
| 前端全量TypeScript | **未通过；无新增去重诊断** | 基线627条/452种，本分支628条/452种；同一未改Select源文件经工作树依赖两路径报告，按真实路径和去行号比较；`/private/tmp/tenant-phase1-typecheck-comparison.json` |
| 专用环境API端到端 | **9跳过，PARTIAL（部分验证）** | 缺专用测试身份/数据，未发出现场业务请求；`/private/tmp/tenant-phase1-e2e-final.log` |
| 真实浏览器、MySQL/DM8、外部服务/网关 | 未执行 | 不以服务测试或SQLite结果替代 |

后端定向运行范围：`test/admin/{test_f114_scope_middleware,test_current_super_qualification}.py`、`test/role/{test_role_service,test_managed_tenant_role,test_effective_roles}.py`、`test/workflow/{test_browser_scope,test_managed_tenant_creation,test_temp_kb_identity}.py`、`test/knowledge/test_space_flow_retrieval.py`、`test/workstation/test_navigation_config.py`、`test/permission/test_auth_jwt_token_version.py`、`test/public_endpoints/test_guest_link.py`、`test/knowledge_unification/test_upload_preview.py`、`test/dsh/test_model_display_catalog.py`。

另外35项来自 `test/workstation/{test_config_knowledge_permission,test_config_tool_permission,test_daily_config_is_fallback,test_config_resolve_root_bypass}.py`、`test/llm/test_model_catalog.py`。前端运行 `Roles.creation`、`managementScope`、`requestErrors`、`requestCompatibilityMatrix`、`roleQuotaConfig`、`roleMenuSelection`。

后端使用已有Python3.11虚拟环境、隔离空配置 `config=/private/tmp/bisheng-tenant-phase1-config.yaml PYTHONPATH=.`；未读取生产配置。前端复用已安装依赖，不改锁文件；Node25测试使用 `NODE_OPTIONS=--no-experimental-webstorage` 防止原生localStorage覆盖测试环境。日志是本机证据文件，独立结论写于本文，不依赖日志长期保留。

### 已复现的基线失败

下列在未修改的主发布线工作树复现；相关源码在开发基线之间没有差异，不以排除它们声称全套测试通过：

1. 三个定向排除用例：`test_admin_settings_preserve_raw_metadata_and_check_tenant_scope` 缺旧测试的模型引用运行时配置；`test_specified_user_overrides_default`、`test_use_check_rereads_switch_and_raises_26403` 的旧访客执行fixture依赖真实创建/权限运行时与数据库，隔离配置未提供。复现日志为 `tenant-phase1-model-baseline.log`、`tenant-phase1-existing-guards-baseline.log`（均在 `/private/tmp/`）。
2. 扩展Worker检查另有5个旧fixture失败：`test_use_gate_sees_the_restored_identity[execute/continue]`、`test_gate_carries_a_plain_operator_without_privilege`、`test_denied_use_stops_the_run[execute/continue]`；旧admin范围测试亦存在缺少有效租户/成员事实的fixture失败。没有借此修改授权或测试预期。
3. 全局架构测试2项失败：`test_no_new_route_contains_config` 报既有 `/api/v2/workstation/config/knowledge`；`test_no_exc_info_passed_to_loguru` 报未改 `linsight_html_check.py` 的两处旧调用。主树同样2失败/2通过，日志 `/private/tmp/tenant-phase1-architecture-baseline.log`。修改文件的架构守卫无新增违规。

## 4. 测试重点和未交付边界

真实验收按[八列测试用例](test-cases.md)的TC-MTP-001～009及[端到端清单](e2e-checklist.md)执行，状态仍为待执行。重点如下：

1. Root超管切子租户，打开/创建工作流并读取访客链接设置，辅助404不导致整页消失；缺目标/旧目标写入不能修改内容。
2. 失效模型引用不影响导航；完整运行配置继续拒绝。合法跨主属模型展示正确，不能据此获得新个人模型额度或跨主属管理调试能力。
3. 子租户普通获权用户运行超管创建的流程；知识检索权限开/关分别核对真实运行人/创建者。原本禁止的跨租户直接执行、未就绪流程仍拒绝。
4. 本租户默认角色、显式共享角色分别核对定义及菜单归属；编辑旧共享角色不搬所有者。兼属人员普通绑定、菜单和额度应保持既有合同，普通人员不能共享创建。
5. 上传四类写入分别验证目标、真实上传人、空间及版本；通用临时上传保持原行为。核对反向代理不丢弃目标请求/响应头。
6. 撤销所有实际平台身份来源并保留旧正缓存/选择，敏感入口必须拒绝；合法独立管理员来源保留，权威不可核实不能误判为可用。
7. 浏览器连接从A建立、切B后仍固定A，断开恢复；桌面受信设备连接仍固定凭据租户。只使用隔离测试身份和数据，恢复专用管理员选择。

本阶段未完成：全平台端点登记及强制覆盖、个人业务全入口分类/生命周期、网关自有能力目标匹配、历史绑定修正、行政承接及其新增字段、管理调试计费身份、同租户往返切换的旧表单世代标识、跨系统原子撤权。既有 `clear_on_role_revoke` 未被接通所有外部生产者；本批对敏感入口核实权威资格，不将“删选择”或“等缓存过期”作为撤权成功证明。

## 5. 集成及回退

当前只有本地分支和可审查变更；发布前仍需专用环境部署匹配前后端、完成真实验收及常规合入审查。无需执行任何本批迁移/历史修正脚本。若后续回退代码，先停止使用新增前端/API合同并配套回退前后端；本批创建的资源/角色是正常业务记录，不能随代码回退批量删除或变更其租户归属。

审查范围和风险见[第一阶段代码审查](phase1-code-review.md)。本文中的API为应用程序接口、HTTP为网络请求协议、WebSocket为长连接、SQLite为本地测试数据库；端到端是通过实际部署的完整调用链验证，不等于本地模拟测试。
