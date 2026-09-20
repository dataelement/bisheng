# DSH 模型展示名称修复状态

- 2026-09-20：基于 `dataelement/bisheng:feat/3.0.0-beta2-pre@dff62d2519f69bc425cb11bbe8c3b50fc215889c` 完成模型展示名称修复。
- 模型目录和管理端共用展示名称规则，优先采用管理员配置的 `name`，空白名称使用调用名称 `model_name`。内部模型 ID 继续用于调用、权限和额度。
- 定向回归 42 项通过、2 项 Redis 用例按环境跳过、12 项外部数据库变体排除；Ruff 和架构守卫通过。执行方式与验收边界见 [模型名称修复验证](../features/v3.0.0-beta2/062-dsh-desktop-model-access/model-display-verification.md)。
