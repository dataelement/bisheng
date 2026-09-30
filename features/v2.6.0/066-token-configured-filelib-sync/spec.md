# F066：Token 配置化统一文件同步接口

## 状态

- Status: `folder-target automated implementation complete; T021 manual verification pending`
- Date: `2026-07-22`
- Detailed requirements: [requirements.md](./requirements.md)
- Detailed design: [design.md](./design.md)
- Release contract: [../release-contract.md](../release-contract.md)
- Tasks: [tasks.md](./tasks.md)
- Verification: [verification.md](./verification.md)（目录目标 T022-T029 已完成；T021 尚未执行）

## 目标

把现有 11 个请求、响应和上传流程相同的 Filelib 固定规则接口合并为：

```http
POST /api/v2/filelib/file/sync
```

文件分类、业务域与目标知识空间不再由 URL 编号选择，而由本次认证的开发者 Token 上唯一、完整的 `file_sync_rule` 决定。分类始终固定；业务域和目标空间分别支持固定或动态。固定目标可选择公共/部门知识空间根目录或目录，并按 Token 绑定用户权限过滤；动态目标继续解析到空间根目录。只要存在动态维度，就由 Token 统一指定使用 `params.department_id` 或 `params.responsible_person_id` 的主部门解析。

## Release Contract

- Owner extension：F066 拥有 `DeveloperToken.file_sync_rule` 的结构、校验和写入行为，不取得 DeveloperToken 其他字段、门户配置、部门、知识空间或知识文件的所有权。
- Dependencies：F044 Developer Token、F047 Filelib Sync、F060 DepartmentSpaceTargetResolver、Knowledge 只读目录契约与 `PermissionService`。
- Error modules：管理配置错误追加在 198xx；同步运行时复用 19901～19905并追加 19906。
- INV-7：配置不授予权限；目标选项、保存、换绑和运行时均按 Token 绑定用户对最终根/目录节点的 `upload_file` 过滤与复核。
- INV-8：动态域只读取当前租户 `domains[].department_ids`，不复制映射。
- INV-9：缺失、失效、歧义、跨租户、目录错配和权限丢失全部失败关闭，目录目标不得 fallback 到根目录。

## 核心契约

1. 每个 Token 最多一份 `file_sync_rule`；`NULL` 表示未开通，其他 Token API 不受影响，统一同步返回 403/19906。
2. 配置不存在草稿：启用时必须一次满足分类、fixed/dynamic 模式、固定值和动态来源真值表。
3. 分类只保存一级与二级稳定编码且永远固定；请求不能覆盖。
4. 业务域和目标空间独立 fixed/dynamic；任一动态时共用 `department_id` 或 `responsible_person_id`，指定 ID 必须显式传入。
5. `department_id` 直接选择部门；`responsible_person_id` 选择该用户当前租户唯一主部门；缺失时不使用调用人或另一个 ID 回退。
6. 动态域按当前租户门户聚合配置精确匹配部门；动态空间复用 F060 确定性 resolver；零候选 404，多候选 409。
7. 固定分类、固定域、固定空间和可空固定目录在保存时校验；所有最终资源、目录所属空间、域-空间绑定和权限在每次同步时再次校验。
8. 固定目标树只分公共/部门空间；以 Token 绑定用户的 `upload_file` 为权限主体。深层授权只展示必要不可选祖先并隐藏无关兄弟；空间名称搜索、目录游标懒加载、根/目录单选。
9. 路由白名单拒绝 19812 先于业务配置；固定根、固定目录和动态根均按 Token 绑定用户复核最终节点权限，配置和管理员身份不授权。
10. 根目录调用 `add_file(parent_id=None)`，固定目录调用 `add_file(parent_id=folder_id)`；动态目标始终根目录。multipart、`params`、外部响应、跳过审批、重复冲突、固定编码、失败清理和异步解析保持既有语义。
11. 11 个旧 `/file/sync/{code}` URL 立即移除，无重定向；已有 Token 配置和 route whitelist 均不自动迁移。
12. 管理页列表/编辑使用服务端批量解析的结构化当前路径摘要；目录重命名/同空间移动继续有效，删除/错配显示稳定 ID 和失效状态，不保存路径快照或产生 N+1。
13. 本次只在既有 `JsonType` JSON 中增加可空 `folder_id`，缺失/`null` 兼容为空间根目录，不新增 migration/backfill；旧严格 schema 应用回退前需清理/转换目录规则或 forward fix。

## 配置摘要

```json
{
  "category": {
    "code": "POLICY",
    "subcategory_code": "MGMT_POLICY"
  },
  "business_domain": {
    "mode": "fixed",
    "code": "SAFETY"
  },
  "target_space": {
    "mode": "fixed",
    "knowledge_id": 118,
    "folder_id": 4096
  },
  "dynamic_source": null
}
```

| 业务域 | 目标空间 | 目标目录 | 动态来源 |
|---|---|---|---|
| fixed | fixed | 可空；空为根目录 | 不允许 |
| fixed | dynamic | 必须为空；动态根目录 | 必填，供目标空间使用 |
| dynamic | fixed | 可空；空为根目录 | 必填，供业务域使用 |
| dynamic | dynamic | 必须为空；动态根目录 | 必填，两者共用 |

## API 摘要

### 第三方同步

- `POST /api/v2/filelib/file/sync`
- Header：`X-Developer-Token`
- multipart：`file` + `params`
- 成功：既有 `external_file_id`、`file_id`、`file_encoding`、`knowledge_id`、`knowledge_name`、`status`
- 目录上传不新增 `folder_id`、目录名称或路径字段。

### 管理端

- 扩展 `POST/PUT/GET /api/v1/admin/developer-tokens...` 的 `file_sync_rule`。
- 扩展 `GET /api/v1/admin/developer-tokens/config/file-sync-options?tenant_id=...&user_id=...`，返回分类/域和按绑定用户过滤的公共/部门空间分组游标。
- 新增 `GET /api/v1/admin/developer-tokens/config/file-sync-target-children?...`，按展开节点游标返回目录、可选状态和必要导航祖先，不返回文件。
- Token list/detail 返回结构化 `file_sync_target_display` 当前路径/根/失效状态；options、保存和运行时都不授予权限。

## 错误摘要

- `19812`：路由白名单拒绝，优先于业务配置处理。
- `19813`：管理员提交的 Token 文件同步规则无效。
- `19814`：目标树空间/目录游标无效，不静默回到首页。
- `19901`：动态来源 ID 缺失或 `params` 无效。
- `19902`：运行时 Token 绑定用户无最终根目录/目录上传权限。
- `19903`：分类、域、空间、目录、人员、部门或绑定不存在/失效/错配，目录不回退根目录。
- `19904`：动态解析歧义或重复文件冲突。
- `19905`：multipart 无效。
- `19906`：Token 未配置文件同步业务。

## 交付边界

- Backend：在既有 JSON 中增加可空目录、按绑定用户过滤的目标树/保存复核、批量路径摘要、固定目录运行时解析与 `add_file(parent_id)`。
- Platform：独立目标树与懒加载 hook、公共/部门分组、根/目录单选、导航祖先和当前路径摘要，补齐全部 locale 文案。
- Docs：在统一接口文档中明确固定目录、动态根目录、权限主体、响应不变、无新 migration 和应用回退策略。
- Release：管理员手工配置 Token 和路由白名单；调用方在同一发布窗口切换 URL。
- 当前阶段只交付规格与任务计划，不交付上述生产实现。

## 非目标

- 多规则 Token、配置草稿/版本/审批、分类动态化、请求覆盖固定值。
- 团队/个人空间、文件节点、目录创建/移动/重命名、全局目录搜索、多目标和动态目录。
- 旧 URL 兼容层、配置或 whitelist 自动迁移、`external_file_id` 幂等。
- 新业务域映射事实源、自动修改知识空间/业务域绑定、配置即授权。
- 修复数据库写入与 Celery 入队非原子问题。
- 未经后续确认的代码、数据库或配置数据变更。

## Review Gate

- [x] Spec Discovery 结论已写入稳定 REQ/AC。
- [x] Release Contract 已登记 Owner extension、依赖、不变量和错误模块。
- [x] 9 个 Requirements、53 条 AC 与 Design/Tasks/Verification 已建立完整追踪。
- [x] 兼容性、迁移、上线、回退和验证策略已明确。
- [x] 初版需求与设计已于 2026-07-22 获用户确认；目录目标澄清结论已写入规格。
- [ ] 目录目标修订的 requirements/design/tasks 待用户最终评审确认；确认前不进入 T022 生产实现。
