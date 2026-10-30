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


## 合并注意事项（2026-10-30）

工具与技能以租户成员普通 Grant 表示默认全员授权。系统资源首次创建时设置默认值；
已有 CURRENT 投影保持管理员当前设置，包括撤销全员授权后的空授权状态。
不能在初始化中检查或自动补齐旧 `user:* visible/system_use_marker`，也不能将缺少
租户全员 Grant 直接认定为损坏，否则会误报初始化失败或恢复管理员已经撤销的权限。
非 CURRENT 投影继续阻塞，交由已有持久操作恢复流程处理。历史公共权限转换使用
显式迁移脚本，不由启动流程补回。

发布线的 `tenant_execution_scope` 与 OpenFGA 启动并发锁继续保留。内置技能本地化
合并到发布线新的 `/api/v1/linsight/skill/center` 数据链路，服务端提供 `builtin_key`，
前端只对企业内置技能做显示翻译，保持资源 ID、原始名称和授权状态不变。


## 本次修复审查与验证（2026-10-30）

审查范围：120 合并冲突处理与系统资源初始化修复。按 sdd-code-review 的边界、权限、
并发、信息泄漏、测试、风格、文档七项检查，未发现本次新增阻塞；完整环境验证仍待执行。

- 后端定向回归：223 passed，5 skipped；另外两个既有失败在合并前 a13758ef3 同样复现
  （匿名 API 测试缺少数据库配置、Skill Catalog 动作数量断言为 3 而实际为 4）。
- 客户端合并相关回归：75 passed；管理端：163 passed，另有三个既有的 Tabs role 断言失败，
  在相同依赖下的 a13758ef3 基线也全部复现。
- 前端 pnpm lint 与 check-i18n 通过；Ruff 与架构守卫通过。
- 类型检查使用本机已安装依赖：platform 21 个、client 23 个错误，规范化路径后错误集合
  与合并前完全一致，涉及旧图标包和缺失依赖。未通过添加抑制或修改业务代码掩盖这些错误。
- 本机 MCP SDK 不支持现有代码的 max_request_body_size 参数，两个涉及完整 main 导入的
  测试文件无法收集；本次未修改对应 SDK 契约。
- 测试使用本地 SQLite 和假的 OpenFGA transport，真实 runtime、owner service 与持久投影
  代码参与执行。未在 166 重新部署，未执行生产迁移；测试结果不替代完整部署验收。
