# DSH 企业后台交付状态

- 2026-09-20：上游 PR 候选基于 `feat/3.0.0-beta2-pre@dff62d251`，完整保留企业后台整合，并纳入授权树加载稳定性与模型展示名称修复。753 项相关测试、双前端构建及定向检查通过；管理端全量类型检查有两项上游既有错误，真库与登录态验收为 `NOT_RUN`。完整范围、来源和迁移说明见 [上游交付记录](../features/v3.0.0-beta2/062-dsh-desktop-model-access/upstream-pr-delivery.md)。

- 2026-09-20：模型目录和管理端共用展示名称规则，优先采用管理员配置的 `name`，空白名称使用调用名称 `model_name`。内部模型 ID 继续用于调用、权限和额度。定向回归 48 项通过、2 项 Redis 用例按环境跳过，16 项外部数据库变体排除；Ruff 和架构守卫通过。执行方式与环境边界见 [模型名称修复验证](../features/v3.0.0-beta2/062-dsh-desktop-model-access/model-display-verification.md)。
- 2026-09-17：`codex/dsh-enterprise-beta2` 已归并最新看板、部门额度、导航、个人年度用量和隐藏审计入口，进入提测候选。
- 实现、来源、确定性检查和真实环境验收边界见 [提测交付记录](../features/v3.0.0-beta2/062-dsh-desktop-model-access/enterprise-beta2-delivery.md)。
- 当前组合分支基于最新已核验的 beta2-pre 基线；真实数据库与登录态端到端验收由提测执行。
