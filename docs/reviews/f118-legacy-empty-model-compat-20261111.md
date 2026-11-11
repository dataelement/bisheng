# Code Review Report

**Feature**: F118 历史空模型及原 F048 来源兼容修复（AC-95–AC-99）  
**Review scope**: 5 个权限生产文件、2 个新增测试文件及既有 F118 合同文档；不代表整个 F118 验收  
**Base branch**: feat/3.1.0-beta1，基线 `1e43b1e49806f6e9e3f3b7567d183b570e58a0ae`  
**Review date**: 2026-11-11

## Summary

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## Evidence

- 原无等级空 CUSTOM 模型只保留既有定义；Catalog 校验仍拒绝空动作却有等级、错误 selected actions、allow_same_level 或伪纯可见元数据的全局空定义。全局有效模型在某目标上动作空集的情况独立保留原等级。
- 共享编译器只保留完整、唯一、ACTIVE 的原可见证明；精确比较租户、资源、owner、model、source/contribution/tuple 指纹、主体、protected class 与 source_version。新主体/目标、缺失、退休、重复、版本或身份漂移被拒绝，不凭形状制造新授权。
- 原首次 F048 writer 使用载荷 JSON 指纹及 migration locator，在线 writer 使用 locator 指纹。F118 逐字段验证已存在的两种协议，保留旧 source_ref/locator/fingerprint。所有其他语义字段必须与 canonicalizer 完全相同；篡改字段仍阻断。
- SQL 名册仍使用原有界游标查询，针对需证明来源按最多 200 owner keys 分批查询精确作用域的 ACTIVE 投影，拒绝不一致而非分页后静默过滤。继承使用最近 CUSTOM 祖先范围且排除祖先 CREATOR；visible 来源摘要保留已证明贡献，具体动作不被添加。
- GrantService 新增、转入、管理/撤销等级策略未修改；普通与系统授权 actor 均不能因空模型兼容取得原本不存在的权限。原有受保护来源及并集/最后贡献移除规则保留。
- 不新增 SQL/FGA 写路径、模型自动发布、DDL 或 API；读路径仍使用既有租户上下文和快照戳，发布/恢复继续由原事务、pin 和投影协议执行。查询为 SQLAlchemy 通用表达式，无新方言语法。
- 新增 38 项测试全部通过；关键迁移/投影选集 86 passed。扩展选集候选 1,246 passed、67 failed、5 errors、10 skipped；基线同选集 1,208 passed、67 failed、5 errors、10 skipped，72 个失败/错误 ID 完全相同，新增失败 0。日志保留，未删改既有失败测试。
- 7 个变更 Python 文件 Ruff check 通过，格式检查与 diff-check 通过，架构 guard 无违规。无业务模块依赖、凭据、错误堆栈出站或对外字段变化。
- design §3 D9 / §7.3.2、spec §11、release-contract §14、QA 八列 TC-KSU-141–145 与 tasks 同步。首次 F048 来源格式及特定资源动作空集的反直觉边界已写入设计。

## Findings

### MEDIUM

- 扩展选集基线存在 67 failed / 5 errors，包含旧 F048 fixture/model drift、静态历史约束及未装配依赖；本修复没有新增失败，但不能宣称整个权限套件全绿。DM8 真实事务未在本机验证；本修复无 DDL 或数据库写入，静态保持双库 SQLAlchemy 合同。

## Live validation boundary

116 实际镜像有两处与发布分支不同的后续修复；部署从镜像原文件只移植本兼容 hunks，5 个原文件及最终补丁哈希逐一验证，没有带入其他 release 变化。只读现场预检已确认 Catalog 198 空模型定义原样、原 Grant 1023/1040 与 Source 2139/2163、0 个可见 tuple 差异，以及 user747/user745 原 HIGHER_CONSISTENCY visible=true。正式全量升级及恢复服务结果单独记录于 environment-116-f118-upgrade-20261111.md。

本增量是内部迁移/来源读取逻辑，没有新增 API 或页面；E2E skill 对纯内部状态的排除适用。现场维护升级、原非管理员用户的实际 FGA 检查和服务恢复 smoke 另作运维验收，不能替代整套 F118 API/UI E2E。

## Overall: PASS_WITH_WARNINGS

无新增 HIGH/MEDIUM 实现缺陷。保留既有测试基线告警及现场升级验收边界；不得以本审查替代整个 F118 完成声明。
