# F053 设计与上线说明

## 1. 模型与一次鉴权

只改变 `department.subtree_member` 的定义及其类型约束：

```fga
type department
  relations
    define member: [user]
    define subtree_member: [user]
```

此片段只列出相关关系；现有 parent、child、admin 和全部资源定义保留。旧定义为 `member or subtree_member from child`。新模型版本为 `f048-v3-contextual-departments`，checksum 为 `75be8b347d67499beea780a85ad5869b6d37798b24b1b5ed22a79cdab138e957`。

例：用户 1 在部门 3，路径为 1 → 2 → 3，资源 A 已持有 `department:1#subtree_member` 授权。毕昇发送：

```json
{
  "authorization_model_id": "<new-model-id>",
  "tuple_key": {"user": "user:1", "relation": "visible", "object": "knowledge_space:A"},
  "contextual_tuples": {"tuple_keys": [
    {"user": "user:1", "relation": "subtree_member", "object": "department:1"},
    {"user": "user:1", "relation": "subtree_member", "object": "department:2"},
    {"user": "user:1", "relation": "subtree_member", "object": "department:3"}
  ]}
}
```

临时事实不是资源授权；没有有效资源来源或资源门禁关闭，OpenFGA 仍拒绝。无需改写既有 `department:X#subtree_member` Grant/visible 来源。`member` 继续由既有组织投影永久维护，语义为直属成员。

## 2. 分层与读取范围

- 组织域 `DepartmentPermissionContextRepository` 查询当前用户的 UserDepartment，再按 parent_id 分层批量读取祖先。只查已知 ID，不遍历整棵树，不依赖可能过期的 path 字段。查询为 SQLModel 通用表达式，未引入 MySQL/DM8 专有语法。
- `DepartmentPermissionContextProvider` 验证 active/CURRENT、完整性和无环，返回只含 user_id 与部门 ID 集合的 `ActorDepartmentContext`。
- 权限应用层 `DepartmentContextPort` 接收业务事实，统一转换为临时 tuple。权限代码不导入组织 ORM/DAO/Service。API/worker 组合根负责注入，Celery 与 Linsight 沿用共享 worker 装配。
- core 的 FGAClient 只支持通用 contextual tuples 提供器。部门语义保留在毕昇的模型和应用装配中，OpenFGA 服务不变。

用户、部门 ID 是现有 FGA 的全局身份键。读取显式绕过自动租户过滤，但严格限定当前用户及其已知祖先，以保留既有跨租户组织挂载路径和多部门成员关系；不能仅截取登录租户内的祖先。资源租户范围、Grant 主体合法性和共享门禁仍走既有业务校验与 FGA 模型。本改动不新增跨租户 Grant。

## 3. 成本、复用及错误语义

设当前用户所属部门及全部祖先的去重数量为 A，最长链为 D：读取至多 D+1 次有界 SQL，每轮按 ID 批量查询，输入大小 O(A)，与整个部门子树人数/部门数无关。多层部门仍有 SQL 往返成本，深度不会完全变成零成本。

一次权限应用操作以 ContextVar 保存已完成的用户事实，嵌套动作检查及 BatchCheck 的 50 项分块共享；操作结束清空。不同用户分开，后续操作重新读取。并发首次读取可能重复查询，未引入后台任务或全局缓存。输入是操作期间的一次读取结果，不承诺并发组织变更下的跨系统线性一致性。

上限为 100 个去重部门，组织读取总预算 5 秒。超过上限、源故障、投影非 CURRENT、归档、祖先缺失或循环均报错，不截断、不发送半成品上下文；原有兼容调用若采用 fail-closed 捕获则返回拒绝。用户确实无部门时允许空上下文。不会回退至 SQL 资源授权或忽略上下文继续放行。

基于完整授权模型的关系依赖图，仅为可能引用 subtree_member 的具体 `user:<正整数>` 请求加载组织事实。系统身份、tenant.member、department.member/admin 等无关关系保持原路径。依赖 subtree_member 的旧 PermissionService Check/ListObjects 禁用原持久结果缓存，避免部门变更后继续命中旧权限。

生产装配要求提供器存在；新旧模型 checksum 不匹配时原 readiness 门禁拒绝启动。`for_model()` 是迁移工具用的独立原始客户端，不携带运行时提供器，不能直接作为业务鉴权客户端。现有客户端没有 ListUsers；本方案不把全体有效用户枚举伪装成具体用户鉴权。

## 4. 模型发布与回滚

代码交付不等于模型上线。本次不执行任何线上发布。

1. 使用既有流程安排维护窗口，停止 API、Celery、Linsight 的权限读写入口，等待运行时 heartbeat 过期并确认无进行中的组织/权限投影。
2. 在新版本 `src/backend/` 下使用部署环境的 `config` 运行 `PYTHONPATH=. python scripts/publish_authorization_model_change.py`。默认 dry-run，核对 Store、CURRENT 和目标 checksum。脚本分页扫描 Store，若存在 object 为 department 且 relation 为 subtree_member 的永久记录则阻断；资源上引用 `department:X#subtree_member` 的记录合法。不要自动删除阻断数据，应先核实历史来源。
3. 使用 dry-run 输出的 Store ID 和目标 checksum，执行既有 `--apply --confirm-store-id <id> --confirm-target-model-checksum <checksum> --operator-id <id>`。沿用既有发布窗口、不可变模型发布和 Catalog CURRENT 切换协议，无业务表结构迁移或资源 Grant 重写。
4. 启动同版本的 API 与所有 worker，核对 readiness 的 model ID/checksum；验证直属/含下级授权、成员移除、部门迁移、文件编辑和完整列表。禁止新旧 runtime 混跑。
5. 如需回滚，重新进入维护窗口，通过既有受控发布流程将 Catalog/授权模型及所有 runtime 一起恢复旧版；仅切回应用镜像会触发 checksum 不匹配。parent/child/member 的原有投影在新版本继续维护，不能在此次上线顺便删掉。

模型本身不能强制“只允许临时 tuple”：运行时写入保护拒绝永久 subtree_member，发布检查防止历史脏数据激活。拥有直接 OpenFGA 写权限的运维工具仍需遵守此契约。

## 5. 决策依据与已知限制

使用官方 [Contextual Tuples](https://openfga.dev/docs/modeling/contextual-tuples) 能力，将组织归属作为请求事实交给 OpenFGA。未采用引擎部门特例，避免改变通用引擎语义；未维护永久传递闭包，避免深层成员和组织迁移导致大量写放大。

MySQL/DM8 实机成本、全量 API E2E、启用各类服务端缓存后的代表性并发负载需在发布验证中完成。本地测试覆盖 SQLite 查询、原版 OpenFGA HTTP 和完整模型决策，不作为生产延迟 SLA。业务资源继承本身的深度限制仍存在；本改动只移除部门子树展开。
