# DSH 操作审计历史实现

## 范围与基线

2026-09-17：用户确认审计设计继续完善，当前 DSH Desktop 导航隐藏操作审计；可见页签与 URL 解析共用 DSH_SECTIONS，旧 tab=operations 显示首个可用页签。审计组件、后台接口、采集与历史数据保留，待设计确认后恢复 visible。

开发基线为 3006 发布 `25247250b`；发布前合并同期 `0dbadec79` 的部门统计简化。现有页面仅有组件内存中的操作引用；真实记录已持久化到 `dsh_admin_operation` 和 `dsh_subject_policy_audit`。

## 决策

- 复用两张表，按创建时间、来源、来源主键倒序归并；每个来源每页最多读 limit+1 条。采用游标分页，避免全量读取和分页深处的大量 JSON 加载。未来需要跨领域审计再评估统一投影表。
- 新增 F062 内部 GET `/api/v1/dsh/admin/audit-records`，参数 cursor、limit（默认20，最大100）、action、status、tenant_id。返回 PageInfiniteCursorData（data/page_size/has_more/next_cursor）。游标绑定租户、筛选和页大小。
- Endpoint → DshManagementService（原 authorize_admin）→ runtime read adapter → DshAuditRepository → SQL。profile_scope + strict_tenant_filter 限定审计及名称读取；UserTenant 是租户自动过滤排除表，名称关联显式限制该成员关系的租户。
- 当前名称仅用于可读标签，原始主体 ID 始终保留；部门/角色/模型不可见或已删除时回退 ID。名称读取批量进行。历史创建时间按现有数据库时间约定输出，展示北京时间。
- 响应只公开授权开关、额度、状态、版本、Token 等业务快照白名单；payload、result_payload、会话凭证、连接配置和原始错误文本保持服务端。失败/处理中操作的 requested_values 与已提交 after_values 分开展示。
- 页面复用现有 bs-ui Table、DshChoice、DshPager，工具条右对齐。历史表替代当前空白区；未完成的本页席位操作继续显示现有 OperationStatus，保留有界轮询和同 ID 重试。

## 已知边界

- 部门/角色表只有已提交的变更，因此这些记录映射成功；管理操作保留真实状态。
- 创建时间由 SQL CURRENT_TIMESTAMP 生成，按数据库与 Backend 共同部署的 TZ（默认 Asia/Shanghai）解释，再输出带时区时间。3006 实测数据库 SYSTEM/CST，比 UTC 快 8 小时；按模型调用的 UTC 规则直接解释会多加 8 小时。原始时间保持。
- 原始数据中没有保存的事件、本轮也没有新增采集的事件保持缺失，不伪造全量审计覆盖。
- 自动租户过滤仅保证 ORM 直接查询；分别查询两表，避免 UNION 子查询绕过过滤。
- 模型名称沿用 DSH 目录的 model_name 优先规则，空值回退 name；name 在现有数据中可能为 model 5 等内部显示名。

## 模块与字段契约

- `domain/schemas/audit.py`：只读 AuditRecord/AuditPage；created_at 为带 UTC 时区时间，actor/target/model 名称可空，主体 ID 保留。before_values/after_values/requested_values 为标量快照。
- `domain/repositories/audit.py`：来源归并、游标校验、租户内名称解析、字段白名单；没有写入调用。
- `domain/services/admin.py` 与 `admin_runtime.py`：沿用管理员验证与租户上下文，通过线程适配器执行同步只读仓库。
- `api/endpoints/admin.py`：新增查询路由；依赖原租户管理员鉴权，limit 1–100，cursor 最大1024字符，action/status 为有限枚举。
- `controllers/API/dshAudit.ts` 与 `types/dshAudit.ts`：沿用统一请求包装，校验分页及每条记录结构。
- `AuditHistory.tsx`：查询、取消过期响应、筛选、翻页、北京时间格式化、详情；原 OperationStatus 保留未完成席位操作的状态与重试。

## Incoming / Outgoing

- Incoming：现有管理操作及部门/角色授权写入器继续负责持久化；本次没有修改这些写入器。
- Outgoing：仅管理后台调用新增历史查询路由；Desktop、Gateway、商业 License 和统计埋点契约保持。数据库使用现有 ORM/租户过滤与方言适配，没有新增迁移或生产依赖。

## 验证

隔离数据库覆盖两来源、同秒分页、筛选、跨租户、缺失对象、快照白名单；API 覆盖参数与管理员权限；前端覆盖初次读取、重挂载、筛选重置、分页、详情、错误与空状态。使用仓库 e2e-test 和 code-review 检查；真实环境只读验收查询和刷新，不制造授权变更。

## 修订历史

- 2026-09-16：补全已持久化操作历史查询与页面；读取线上数据库确认时区约定。
- 2026-09-17：暂时隐藏 DSH 审计页签，保留实现与数据，旧链接按可见页签回退。
