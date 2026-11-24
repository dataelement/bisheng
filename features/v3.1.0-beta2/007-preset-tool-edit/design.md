# 预置工具编辑实现

权限规则沿用 [constitution C4](../../../docs/constitution.md)：业务模块验证目标后调用统一动作运行时。

`ToolServices.require_preset_tool_edit` 加载工具类别，校验预置类别、当前租户和删除状态，再调用 `require_business_action(resource_type="tool", resource_id=id, action="edit")`。普通配置保存和搜索配置四个接口共用此入口。适配器允许预置工具解析 `edit`，由运行时决定授权；`SYSTEM_TOOL_ACTIONS` 保持 `visible`，不向所有人投影编辑权限。删除仍由业务规则拒绝。

前端 `builtinConfigPolicy` 检查工具有效动作中的 `edit`，`TabTools` 的编辑入口使用该结果。沿用权限懒加载和列表脱敏配置投影，无新增角色推断。索引中的中文名称为历史数据库匹配标识，不是显示文案，本次不改动。

不新增端点、字段、权限模型或迁移。普通工具配置和搜索配置的参数、密钥掩码、版本控制继续使用原实现。

2026-11-24：将预置工具编辑从管理员身份限制改为具体工具的编辑动作授权。

2026-11-24：按用户补充要求，移除 `PermissionListTab` 合成的系统预置只读行及其专用搜索、空态判断。继续过滤历史 `user:None` 所有者记录，保留真实用户授权管理和全员可用开关；后端系统预置来源不变。

2026-11-24：补齐空用户过滤：按用户身份占位值识别，不再限定 `owner` 模型；与后端现有新增授权时拒绝 none/null/undefined 用户 ID 的规则保持一致。

所有者保护对照：工作流/助手适配器从业务 `user_id` 生成 `owner_user_id`，工具适配器复用同一流程；`F048OwnerProjectionService._protected_owner` 将其编译成 `CREATOR + protected=True` 来源。Grant mutation 根据来源的 `protected` 标记拒绝 MOVE/REMOVE，界面按该标记锁定该授权记录。普通直接授予的 owner 模型不是受保护来源，不按模型名一概锁定。系统预置工具无有效业务用户时走 system-owned 来源，不能把空值转成真实所有者授权。

本轮修复仅补齐历史空用户边界：列表过滤不依赖模型，服务端 MOVE 复用新增授权已有的空用户识别规则并返回现有 25016 错误；不改受保护标记、实际授权投影或真实用户授权关系，也不在本轮清理历史数据库记录。
