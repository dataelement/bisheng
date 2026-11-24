# 预置工具编辑实现

权限规则沿用 [constitution C4](../../../docs/constitution.md)：业务模块验证目标后调用统一动作运行时。

`ToolServices.require_preset_tool_edit` 加载工具类别，校验预置类别、当前租户和删除状态，再调用 `require_business_action(resource_type="tool", resource_id=id, action="edit")`。普通配置保存和搜索配置四个接口共用此入口。适配器允许预置工具解析 `edit`，由运行时决定授权；`SYSTEM_TOOL_ACTIONS` 保持 `visible`，不向所有人投影编辑权限。删除仍由业务规则拒绝。

前端 `builtinConfigPolicy` 检查工具有效动作中的 `edit`，`TabTools` 的编辑入口使用该结果。沿用权限懒加载和列表脱敏配置投影，无新增角色推断。索引中的中文名称为历史数据库匹配标识，不是显示文案，本次不改动。

不新增端点、字段、权限模型或迁移。普通工具配置和搜索配置的参数、密钥掩码、版本控制继续使用原实现。

2026-11-24：将预置工具编辑从管理员身份限制改为具体工具的编辑动作授权。
