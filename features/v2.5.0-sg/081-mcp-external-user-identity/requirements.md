# F081：需求与验收追溯

- Feature ID: `081-mcp-external-user-identity`
- Status: `IMPLEMENTED_LOCAL`
- Mode: `spec-then-implement`
- Created: `2026-10-22`
- 权威契约：[spec.md](spec.md)；设计：[design.md](design.md)；确认来源：[spec-discovery.md](spec-discovery.md)。

## 1. 确认记录

用户已确认使用必填 `external_id`，可信业务后端验证登录用户后传入；允许跨 Token 所属租户，采用目标用户唯一有效当前租户，单租户使用默认租户；发现范围已于 2026-10-22 确认进入完整规格设计。

用户已确认完整规格并授权任务拆解和实施；不修改配置、依赖、真实权限数据或 Token，不提交/推送/部署。确认过的“Token 不决定业务权限”不等于删除 Token 的绑定/归属有效性检查。

## 2. 需求映射

| Requirement | 需求 | Acceptance | Design | 验证组 |
|---|---|---|---|---|
| REQ-001 | 每次 HTTP 请求保留现有 Token、绑定有效性、IP、路由、限流校验；不把 Token 用户权限用于业务 | AC-02、AC-04 | D-01、D-04 | V-PROTOCOL、V-AUTHORITY |
| REQ-002 | 十工具必填 external_id，schema 与运行时一致，缺参不回退；握手/列工具无此要求 | AC-01 | D-01 | V-PROTOCOL |
| REQ-003 | external_id 为严格字符串，归一化前后空白后精确匹配唯一有效用户，保留前导零，无跨字段回退 | AC-03 | D-02 | V-IDENTITY |
| REQ-004 | 多租户仅取唯一当前有效关系和有效租户；单租户默认租户；允许与 Token 租户不同 | AC-05、AC-06 | D-02、D-03 | V-IDENTITY |
| REQ-005 | 使用目标用户真实角色与正常权限入口；不复制 Token 角色，不取两用户权限交集 | AC-04、AC-07 | D-03、D-04 | V-AUTHORITY |
| REQ-006 | 业务前关闭身份读取豁免，按目标身份建会话；并发、异常、超时和取消后完整恢复 | AC-08 | D-03、D-05 | V-ISOLATION |
| REQ-007 | 九工具 runtime 和原 search_knowledge 共用身份语义；external_id 只在适配层消费 | AC-01、AC-07 | D-01、D-04 | V-PROTOCOL、V-FLOW |
| REQ-008 | 写入的操作者、归属、授权、配额和任务租户走目标用户的原业务流程 | AC-07 | D-04 | V-FLOW |
| REQ-009 | 日志可区分接入 Token 与实际用户/租户；拒绝错误不泄漏候选或凭证 | AC-09 | D-05 | V-ISOLATION |
| REQ-010 | 保留 REST、原工具业务参数/响应、folder_id 兼容、预览下载、空白名单及 CORS | AC-10 | D-01、D-04、D-06 | V-REGRESSION |
| REQ-011 | 身份解析只读、每调用重新解析且有界；不注册/同步身份、不修正租户，不产生隐式数据写入 | AC-03、AC-06、AC-08 | D-02、D-05 | V-IDENTITY、V-ISOLATION |
| REQ-012 | 仅可信后端提供账号，文档说明代理能力、旧客户端升级及回退数据边界 | AC-10 | D-06 | V-DOC |

## 3. 验证组与覆盖原则

| Group | 主要层级 | 目标与计划落点 |
|---|---|---|
| V-PROTOCOL | V2，真实 SDK/HTTP | 扩展 `test/mcp_server/test_mcp_tools.py`、`test_mcp_server.py`；检查十 schema 必填、参数/HTTP 鉴权先后、旧检索与九工具注册；复用主应用 TCP 流程 |
| V-IDENTITY | V2，身份服务及真实仓储 | 新增 `test/mcp_server/test_mcp_user_context_service.py`、`test/tenant/test_tenant_membership_repository.py`；账号候选、大小写/前导零、失效/多当前关系、租户状态、单租户及无写副作用 |
| V-AUTHORITY | V2，目标领域边界 | 对 Token A / 用户 B 的允许与拒绝作双向对照；真实 factory/知识服务按 B 装配，不以 A 的管理员身份借权，也不因 A 无权限拒绝 B |
| V-FLOW | V3，受控端到端 | 扩展九工具真实 SDK/SQLite 流程并补原检索；读取、预览、创建、上传回查与投递身份；外部 FGA/存储/队列可控，不宣称真实基础设施验收 |
| V-ISOLATION | V3，SDK 并发/取消 | 继承污染上下文、两个目标账号/租户、拒绝、超时、断连取消、审计脱敏及 session 释放 |
| V-REGRESSION | V2/V3，相关回归 | MCP、开发者 Token、既有 Filelib 用户代理/检索/来源、目录/上传权限；只扩展受影响范围，保留并对照基线已有失败 |
| V-DOC | V0 | 规格/说明追溯、示例与链接、变更范围检查；实现后补 Ruff/架构检查 |

等价输入以参数化或共享契约覆盖。所有工具的 schema/身份透传使用一组 SDK 用例，领域权限和写入归属选独立业务风险，不为十工具复制同义全栈测试。

## 4. 验证边界

规格静态检查已通过；实施后的行为状态以 verification.md 的实际证据为准。真实 MySQL/DM8、FGA、Redis、MinIO、ES/Milvus、Worker、可信后端及部署代理按条件分别标 `MANUAL_REQUIRED`；无可观察证据不得标 PASS。macOS 不提供 DM8 驱动，不因此取消兼容要求。

实施阶段使用本特性 `verification.md` 记录代码状态、命令、结果与缺口，不能把 F070/F078 的旧通过记录当作新增身份契约通过。
