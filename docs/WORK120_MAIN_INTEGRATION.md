# Work 120 main 集成说明

## 来源与配套

后台基于 `feat/bisheng-work-120-main@7c701e86bcdfbafd53a99997f3146097a1497c41`，迁入旧 `feat/bisheng-work-120` 中的 Chat 交互与桌面桥接，以及 `codex/unified-model-access@c555c807bfb3aeb61adc4edffcb56f23adb0a849` 中的积分和权限功能。

桌面配套分支：`dataelement/bisheng-work:codex/v120-unified-credits`，基于 `V1.2.0@a1ce7bf83c1d3f98dda0802f197e906669de167f`，保留该版本知识空间及引用协议，并迁入本地积分、V1.1 原生认证和模型恢复改动。

## 最终行为

管理员统一配置模型可见范围、模型倍率，以及部门、角色、成员的月度积分。Chat 和 Work 使用统一目录和个人积分账本。桌面余额在账号设置显示一位小数，企业模型使用紧凑列表。后台保留新基线的原生授权、登录、退出与审计能力。

## 数据升级

Alembic 链为 `f065_dsh_install_policy_default_off` → `work110_dsh_local_sessions` → `f062_unified_model_access` → `f062_credit_multiplier`。新权限和积分表接在原生会话迁移之后；席位移除沿用基线实现。升级部署前需在目标环境数据库副本上验证历史额度导入，并检查迁移前后个人额度、模型可见范围和使用账本。

## 验证状态

Chat、管理端模型权限及积分、原生认证/迁移、审计定向测试及双前端生产构建与前端工作区类型检查已通过。后台全量 DSH 测试仍包含旧额度断言和环境相关失败，需要继续整理和复验。当前源码可用于集成联调；真实环境登录、Chat/Work 扣分、权限变更、余额刷新及存量数据库升级待验收。

本次保留现有 3006/3007 环境状态。安装包与部署需要从配套新分支生成后再执行验收。
