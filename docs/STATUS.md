# DSH 企业后台交付状态

- 2026-09-20：模型目录和管理端共用展示名称规则，优先采用管理员配置的 `name`，空白名称使用调用名称 `model_name`。内部模型 ID 继续用于调用、权限和额度。定向回归 48 项通过、2 项 Redis 用例按环境跳过，16 项外部数据库变体排除；Ruff 和架构守卫通过。执行方式与环境边界见 [模型名称修复验证](../features/v3.0.0-beta2/062-dsh-desktop-model-access/model-display-verification.md)。
- 2026-09-17：`codex/dsh-enterprise-beta2` 已归并最新看板、部门额度、导航、个人年度用量和隐藏审计入口，进入提测候选。
- 实现、来源、确定性检查和真实环境验收边界见 [提测交付记录](../features/v3.0.0-beta2/062-dsh-desktop-model-access/enterprise-beta2-delivery.md)。
- 当前组合分支保持原 beta2 基线；真实数据库与登录态端到端验收由提测执行。
