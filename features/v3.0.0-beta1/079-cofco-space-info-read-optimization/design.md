# Design：中粮空间详情读取优化

**关联**：[spec.md](spec.md) · [tasks.md](tasks.md) · [e2e-checklist.md](e2e-checklist.md)。

**基线**：`feat/cofco-1028-3.0.0-beta1` / `a0bf4205f0070b83f4780ceafc25fd0e99b62401`。

**更新**：2026-10-30，按用户已确认方案实现。

## 1. 目标与约束

减少 `/info` 已确认存在的重复权限计算，并使详情与广场的可见优先规则一致。遵循 [constitution.md](../../../docs/constitution.md) C1–C7 和本版本契约；保留中粮下载开关、重建任务租户守卫和 F048 统一授权边界。

## 2. 范围

业务逻辑仅调整知识模块；不改变权限执行面、资源事实解析、数据库 SQL 或索引。`my-permissions` 和前端按钮逻辑保持现状。

## 3. 关键决策

1. **复用入口结果，保留最小 actions 提示。** 入口 `_require_space_info_permission` 已取得 `has_content_permission`；直接生成 `["visible"]` 或 `[]`。完整动作仍由 `my-permissions` 提供。否决直接删除 actions，因为分享入口 `canOpenSharedSpace` 仍读取它；否决再次计算完整列表，因为其余六类动作没有该入口消费者。若发现独立调用方依赖完整动作，调用方需改用权限摘要接口，不能把提示列表重新描述为完整权限。
2. **展示状态以真实可见优先。** `_resolve_effective_subscription_status` 在 `has_visible=True` 时统一返回 subscribed；无可见性时保留原申请状态。该 helper 仅供 info 和广场使用。历史申请及成员记录不写回。后续若要改变实际审批流转，应另做业务变更，不能用展示修复代替。
3. **保留超管的两个口径。** 普通用户可复用入口的可见结论；超管 `_has_joined_visibility` 仍经统一可见性接口确认真实授权来源。可访问但未加入的超管返回 `actions=["visible"]`、`subscription_status=not_subscribed`，分享入口不能仅依赖订阅状态。
4. **分段记录，先不增加数据库负载。** 复用 F042 `emit_metric`，按原顺序执行统计和展示读取。用局部计时上下文在成功/异常时记录实际阶段耗时；异常继续传播。只有实测指向统计查询时，才重新评估并行或缓存。

## 4. 系统现状

### 4.1 数据流

```mermaid
flowchart LR
  A[读取空间与 visible 校验] --> B[统计与订阅角色]
  B --> C[下载开关与最小访问提示]
  C --> D[部门标签与条件任务]
  D --> E[终态指标与响应]
```

`KnowledgeSpaceService.get_space_info` 保留既有串行读取，仅移除 `_get_effective_actions("knowledge_space", id)`。角色兜底需要的 `manage_permission` 单动作校验仍执行。

### 4.2 对外字段与指标

| 字段 | 当前约定 |
|---|---|
| `/info.actions` | 数组类型保留；仅为入口提示，值为 `["visible"]` 或 `[]`。字段语义收窄，其他调用方不得据此控制编辑、删除等按钮。 |
| `subscription_status/is_followed/is_pending` | 真实可见优先；无可见时保留现有申请状态。超管真实加入判定单独保留。 |
| `user_role` | 创建者/有效成员角色保留；无成员记录但可访问者仍检查 manage_permission 区分 admin/member。 |
| `download_action_enabled` | 保留中粮现有 Catalog 开关逻辑；仅预览路径不额外读取 Catalog。 |
| `BS_METRIC domain=knowledge_space_info` | 每次 Service 调用一次 success/error 终态；受现有 `metric_log.enabled` 总开关控制。 |

阶段字段均以毫秒计：`prepare_elapsed_ms`（原有 worker 导入及响应对象准备）、`auth_elapsed_ms`、`member_count_elapsed_ms`、`file_count_elapsed_ms`、`creator_elapsed_ms`、`subscription_role_elapsed_ms`、`download_catalog_elapsed_ms`、`department_elapsed_ms`、`auto_tag_elapsed_ms`、`rebuild_elapsed_ms`。

附带 `space_id`、`has_content_permission`（若已取得）、actor 解析次数/缓存命中/耗时、`total_elapsed_ms`；失败额外带 `failed_stage` 和 `error_type`。阶段未执行为 0；异常发生阶段也记录已耗时间。actor 耗时包含在相应业务阶段内，不应重复相加。total 是 Service 内耗时，不包含 FastAPI 依赖准备、HTTP 序列化或网关耗时，阶段和 total 的差额为本地编排开销。trace 沿用既有日志上下文。

### 4.3 关键模块

| 文件 | 职责 |
|---|---|
| `knowledge/domain/services/knowledge_space_service.py` | 最小访问提示、可见优先、阶段诊断。 |
| `knowledge/domain/schemas/knowledge_space_schema.py` | 更新详情 actions 的接口说明；列表 schema 说明不变。 |
| `test/knowledge/test_knowledge_space_info_optimization.py` | 真实 Service/入口/角色逻辑和 ASGI 成功响应；DAO/授权 I/O 替身。 |
| `test/e2e/test_e2e_cofco_space_info.py` | 显式启用的真实环境只读接口验证。 |

## 5. 已知坑

| 事实 | 错误处理的影响 | 处理位置 |
|---|---|---|
| 普通成员/部门授权用户也通过分享链接进入 | 删除 actions 会误导至申请页面 | 最小访问提示 + 现有 `canOpenSharedSpace` |
| 超管访问权限不代表真实加入 | 只按 subscription_status 跳转会阻挡超管；按身份订阅会把全部空间标为已加入 | `_has_joined_visibility` |
| 历史审批状态与后来获得的授权可同时存在 | 可见用户仍显示审批中/拒绝 | 详情/广场共用状态 helper |
| `/info` 对非 PUBLISHED 空间原本可能投递重建任务 | 对任意生产空间做所谓“只读复测”仍可能触发既有副作用 | 真实环境仅使用预置且已发布的测试空间 |

## 6. 契约与依赖

Outgoing：`GET /api/v1/knowledge/space/{id}/info` 的 actions 提示及订阅字段；知识广场共用订阅状态；F042 新指标域。Incoming：F048 `check_business_action`/真实可见性/Catalog，既有成员、统计、部门和标签读取，客户端分享 guard 与按钮 my-permissions。外部客户端若消费 `/info.actions` 的其他动作，升级时必须迁移到权限摘要接口。

## 7. 验证与后续

按 [e2e-checklist.md](e2e-checklist.md) 区分离线、真实 API 与浏览器验证。确定收益是消除本方法末尾七类动作展开，不承诺固定毫秒或整体页面加载改善。部署后以同用户、同空间、相同并发比较首开、连续请求和 P95；数据库统计/索引维护与 `/children` 优化独立处理。

## 修订历史

| 日期 | 变更与依据 |
|---|---|
| 2026-10-30 | 用户评审并授权三项方案后，实现最小 actions、可见优先和分段终态指标，补充回归与部署后验收入口。 |
