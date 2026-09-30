# 设计 Design

**Feature ID**: `057-domain-bindable-spaces-perf`  
**Status**: Confirmed  
**Mode**: Performance / API optimization  
**Created**: 2026-07-16

## Goals

- 让业务域编辑候选空间查询不再执行用户空间权限范围计算。
- 保持门户现有 `SpaceOption` 对前端的响应契约和失败降级行为。
- 将“只有管理员可全量查询”的安全约束落实在 BiSheng 和门户两端。

## Non-goals

- 不修改通用 `/api/v1/knowledge/space/grouped`。
- 不改动空间成员权限、OpenFGA 模型、数据库结构或前端缓存行为。
- 不统计候选空间文件数；门户已有字段保留默认值兼容响应。

## 调用链

```text
门户管理员
  -> GET /api/v1/admin/config/space-options（门户 require_admin_session）
  -> GET /api/v1/knowledge/shougang-portal/spaces/domain-bindable（BiSheng is_admin）
  -> scope(level=public|department) + knowledge(type=SPACE,is_released=true)
  -> SpaceOption[]
```

## 接口设计

### BiSheng

`GET /api/v1/knowledge/shougang-portal/spaces/domain-bindable`

- Endpoint 使用 `KnowledgeSpaceService`，在服务方法的入口检查 `self.login_user.is_admin()`；失败抛出既有 `UnAuthorizedError`。
- Service 并发获取公共、部门 scope ID，去重后使用现有 `KnowledgeDao.async_get_spaces_by_ids` 批量读取。
- 在 Service 中过滤 `KnowledgeTypeEnum.SPACE`（DAO 已保证）和 `is_released=true`，根据 scope 映射 `space_level`，构造轻量响应项；不调用 `_list_accessible_spaces`、`_format_accessible_spaces` 或文件数统计。
- 响应项包含 `id`、`name`、`description`、`space_level`、`business_domain_codes`；`file_num` 固定为 `0`，用于兼容门户现有映射字段但不产生统计查询。

### 门户 BFF

- 将 `admin_config.py` 的候选空间加载方法改调新上游路径。
- 保持 `require_admin_session`、`DOMAIN_BINDABLE_SPACE_LEVELS` 的最终防御性筛选、`build_space_options()` 映射和上游异常时空列表响应。
- 不保留对 `/api/v1/knowledge/space/grouped` 的回退，避免性能问题重新出现。

## File Structure Plan

| 文件 | 职责 |
|---|---|
| `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py` | 定义专用候选空间响应 DTO。 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 实现管理员校验与轻量空间查询。 |
| `src/backend/bisheng/knowledge/api/endpoints/shougang_portal.py` | 暴露专用 GET 接口。 |
| `src/backend/test/knowledge/test_shougang_portal_business_domain_codes.py` | 覆盖接口与服务边界。 |
| `backend/app/api/routes/admin_config.py` | 切换门户 BFF 上游路径。 |
| `backend/tests/test_admin_config_api.py` | 覆盖新路径与失败降级。 |

## 错误与回滚

- 非管理员：BiSheng 使用既有未授权错误；门户非管理员仍由原依赖返回 403。
- 上游故障：门户返回既有空列表成功响应，避免阻塞配置页面；不回退通用接口。
- 回滚：门户恢复原上游路径、BiSheng 保留新增只读接口即可；无数据变更。

## Traceability

| Requirement | Design elements | Tests |
|---|---|---|
| REQ-001 | 服务入口管理员校验、专用 GET endpoint | 非管理员与管理员 API 测试 |
| REQ-002 | scope ID 批量查询、`is_released` 过滤、轻量 DTO | 空间等级/发布状态/无通用路径测试 |
| REQ-003 | BFF 常量路径切换、空列表降级 | 门户 API 上游路径与故障测试 |
