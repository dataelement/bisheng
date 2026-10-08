# DSH 企业后台上游交付（2026-09-20）

## 交付范围与基线

本次交付覆盖 DSH 企业后台及配套页面、接口、迁移和修复。目标为 `dataelement/bisheng:feat/3.0.0-beta2-pre`，核验基线为 `dff62d2519f69bc425cb11bbe8c3b50fc215889c`。

候选分支为 `codex/dsh-enterprise-beta2-upstream-20260920`，推送到 `SuperstructureJH/bisheng`。原整合分支 `codex/dsh-enterprise-beta2@7374d699a6815cef7451bfa94e88deee9f2fcbb6` 通过常规合并完整保留，上游新增的客户端版本元数据合同一并保留。

## 功能核对

| 功能 | 本次核对 |
| --- | --- |
| 企业身份、授权席位、接入设置 | 已包含原整合实现 |
| 部门/个人模型授权和月额度 | 已包含原整合实现；追加授权树请求复用与加载稳定性修复 |
| 年度、时间范围和最近七天小时用量看板 | 已包含原整合实现 |
| 工作台个人年度用量、下载地址配置 | 已包含原整合实现 |
| 图片模型能力与三语文案 | 已包含原整合实现 |
| 企业插件导入、发布、删除、下载和鉴权 | 已包含原整合实现 |
| 审计采集、历史查询和入口隐藏 | 已包含原整合实现 |
| 模型目录与管理端名称 | 追加管理员配置名称优先规则，并同步目录、候选模型、共享模型测试 |

两项后续修复来源为 `d0b8264de` 和 `58fa0f5f8`，分别通过 `f4ba04d08` 和 `928ed9f4e` 纳入。来源提交涉及的 8 个源码与测试文件逐文件一致；本次额外更新两处仍使用模型调用名称的旧断言，保留模型 ID、租户与共享模型授权断言。

完整性审计扫描 35 个注册工作树、84 个本地分支，所有候选均完成归类。技能中心、3007 页面、知识空间、附件展示与灵思实验按独立功能保留在来源工作树。DSH 工作树中剩余的预览、测试环境、发布证据保留在本地；三语 DSH 导航文案已包含在候选分支。

## 迁移与环境

数据库沿用 `f062_profile_version -> f064_enterprise_market` 的单线迁移。角色策略存量转换使用 `src/backend/scripts/dsh_migrate_role_policies.py` 先输出计划，核对后按环境执行。已有 `f063_dsh_market_merge` 的历史组合环境应先评审迁移图衔接。具体步骤见 [原整合交付记录](enterprise-beta2-delivery.md)。

本次交付为源码 PR。MySQL/DM8 真库、组合分支登录态 UI、Desktop 企业登录及真实模型调用记为 `NOT_RUN`，由集成验收继续执行。

## 本次验证

- 管理端：32 个测试文件，262 项通过；工作台：3 个测试文件，17 项通过。
- DSH 后端：433 项通过，39 项按环境条件跳过，69 项外部数据库变体排除；企业插件市场：40 项通过；Alembic 单一 head：1 项通过。合计 753 项通过。
- 后端按 `uv.lock` 在独立 Python 3.11 环境执行；Redis 使用本机隔离实例，启用 AOF 和 noeviction。数据库用例使用测试 fixture 的隔离库。
- 双前端生产构建、改动文件 ESLint/Ruff、架构守卫、i18n 与 diff 检查通过。工作台严格类型检查 1263 个文件通过。
- 管理端严格类型检查保留两项上游基线错误：`src/test/f048DashboardPermissions.test.tsx:91`、`src/test/routeFilterPurity.test.ts:16`。两份文件与上游基线逐字一致；本次 DSH 文件通过相关测试和定向 lint。
- 真实数据库、登录态 UI 和 Desktop 调用验收边界见上节。

本地复现 DSH 后端命令（在 `src/backend`，使用独立测试配置和 Redis）：

```bash
python -m pytest --confcutdir=test/dsh test/dsh -q --ignore=test/dsh/test_migration_mysql.py -k 'not external'
python -m pytest --confcutdir=test/dsh_market test/dsh_market -q
python -m pytest --confcutdir=test/database test/database/test_alembic_single_head.py -q
```
