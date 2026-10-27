# 接入方案与当前证据

状态：采用所属租户成员的可撤销 Grant，沿用 F048 持久投影。

## 已确认的根因

1. 平台 HeaderMenu 使用 build.tools，三个语言包仍显示工具。
2. BuildPage/tools 主动排除内置工具的 manage_permission 查询与按钮。
3. F048ToolPermissionAdapter 将内置工具操作限制为 visible/use；管理页 visible 列表直接包含内置工具。
4. OwnerService 的系统资源创建直接写入 user:* 的 visible/system_use_marker。添加普通用户 Grant 后，撤销该 Grant 仍保留系统全员权限。
5. 技能目前仅接入所有者权限投影。资源注册表、Catalog 操作范围缺少完整 linsight_skill 资源接入；UserSkillsService.records 仅检查启用状态、个人归属与个人开关。
6. 技能 runtime catalog、bundle、云任务 provisioning 和 availability middleware 共享 UserSkillsService，适合作为统一使用授权入口；开放 API 的 check_skills 另外检查租户内启用列表，需要同步核对执行身份。

## 实施方向

- 沿用 PermissionDialog 与资源授权接口，补齐内置工具的授权管理能力和技能资源适配器。
- 将技能纳入统一 Catalog 和授权模型发布契约，覆盖 API 与 worker 的资源注册。
- 对已有系统全员权限进行有持久操作记录的迁移；迁移保留原有全员可用范围。
- 全员可用由 tenant:<id>#member 普通 Grant 表示，限定 use/download 模型。每次进程启动保留管理员已修改的授权状态。
- 列表与执行通过同一个业务权限入口检查 use；管理操作单独检查 manage_permission。
- 数据迁移作为显式运维步骤执行，记录模型/Catalog 发布、旧元组处理、资源版本和幂等恢复结果。

## 验证计划

- 普通用户授权前、授权后、撤销后分别验证列表、选择、直接请求和执行。
- 验证部门/用户组授权、跨租户拒绝、个人技能归属、全局启用开关和个人开关。
- 验证后台直接调用授权接口的权限校验、投影失败恢复和重复迁移。
- 前端验证授权弹窗、按钮决策和授权保存后的重新加载。
- 运行相关后端测试、前端测试、类型与构建检查，并记录基线差异。
- 真实账号与部署环境验收独立记录。
