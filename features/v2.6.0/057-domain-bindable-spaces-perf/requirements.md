# 需求 Requirements

**Feature ID**: `057-domain-bindable-spaces-perf`  
**Status**: Confirmed  
**Mode**: Performance / API optimization  
**Created**: 2026-07-16

## 背景

业务域绑定只需要管理员在全租户范围内选择有效的公共、部门空间，不需要按管理员个人的空间成员关系过滤。复用通用空间聚合接口会引入无关的权限范围与元数据计算，导致编辑弹窗加载变慢。

## Requirements

### REQ-001 管理员专用接口

BiSheng 必须提供 `GET /api/v1/knowledge/shougang-portal/spaces/domain-bindable`。接口仅允许 `login_user.is_admin()` 为真的用户访问；非管理员必须被拒绝。

- AC-REQ-001-01：管理员调用返回 200 与候选空间列表。验证：API 单测。
- AC-REQ-001-02：非管理员调用返回现有未授权响应。验证：API 单测。

### REQ-002 候选空间范围与性能边界

接口仅返回当前租户内 `space_level` 为 `public` 或 `department` 且 `is_released=true` 的知识空间；响应包含门户现有候选项所需的 ID、名称、描述、空间等级和业务域编码。查询不得按调用者执行成员关系、OpenFGA 可见范围、文件数统计或部门展示元数据计算。

- AC-REQ-002-01：个人、团队空间不返回。验证：服务单测。
- AC-REQ-002-02：`is_released=false` 的公共/部门空间不返回。验证：服务单测。
- AC-REQ-002-03：返回项保留 `business_domain_codes` 和正确 `space_level`。验证：服务单测。
- AC-REQ-002-04：查询不调用通用可见空间聚合路径。验证：服务单测。

### REQ-003 门户 BFF 上游切换

门户 `/api/v1/admin/config/space-options` 必须继续接受门户管理员访问，并改为调用新专用接口；上游失败时维持现有的空候选列表降级响应。不得回退调用慢的通用 `/api/v1/knowledge/space/grouped`。

- AC-REQ-003-01：门户接口调用新上游路径并把返回项转换为既有 `SpaceOption` 响应。验证：门户 API 单测。
- AC-REQ-003-02：新上游失败时返回 200 与空 `options`，且不调用通用空间接口。验证：门户 API 单测。

## Clarifications

- “当前有效空间”已确认定义为 `is_released=true` 的公共或部门空间。
- BiSheng 侧权限采用现有 `login_user.is_admin()`；门户侧继续采用现有门户管理员会话校验。
- 前端缓存与并发请求去重不在本次范围内。
