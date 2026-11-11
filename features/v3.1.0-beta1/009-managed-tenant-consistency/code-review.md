# Code Review Report

术语说明：本文技术符号和英文状态值统一见[术语与缩写说明](terminology.md)；H为用户主属租户，M为当前管理目标租户。业务阅读可直接参阅使用中文全称的[影响范围与测试重点](../../../docs/reviews/managed-tenant-impact-test-focus-20261111.md)。

## 最新集成复核（2026-11-11）

当前结论：**PASS_WITH_WARNINGS（本地代码/发布线集成）**，非上线验收结论。用户在得知待验项后明确要求合并；按该授权合并发布线。原Compatibility HIGH已由实际fetch df927a7f6e、逐段解决13文件冲突、F118兼容回归及单head测试关闭。此前Test Coverage HIGH保留为发布前真实环境待验，不宣称E2E通过；SDD Guide §6将有外部依赖的双DB/中间件/Playwright验收归集中回归，本地不伪造环境。

去重测试353通过/10已在最新基线复现失败；本批87项和F118等兼容53项均为其子集。增量ruff无新增诊断、arch-guard无VIOLATION，locale一致；完整前端TSC的共享依赖/组件诊断和真实行锁/外部系统仍为MEDIUM待验。修复本次人员表单Set<number>推断；后台contextual_operation保留原业务入口装饰，copy证明与实际worker证明共存。

语义冲突处理：工作流SQL/引用先原子提交，PENDING阻止使用，权限确认才READY；F118来源豁免与q/T计量同时保留；挂载使用coverage factory且绑定终止在其同事务；QA仅替换copy函数、保留发布线重建函数；locale按键合并而非覆盖整文件。空merge revision只收敛迁移图，不重写已发布迁移。

详细证据见merge-validation.json，影响与测试重点见docs/reviews/managed-tenant-impact-test-focus-20261111.md。下列为合并前检查快照，不能继续拿“未fetch/未集成”描述当前代码，也不能将本次分支合并当生产部署。

## 合并前检查快照（保留历史）

**Feature**：F009 管理租户最小修复。**日期**：2026-11-11。\
**Review scope**：当前worktree中相对HEAD的tracked diff和新增源码/测试；原七表草稿仅作历史，不套用旧LGTM。\
**Base**：`24c02859e2582ed319281bb52285c99930daf81c`；目标发布线`feat/3.1.0-beta1`（合入前需重新核对目标HEAD）。\
**Changed backend Python**：91个路径，含58个bisheng生产路径，其余测试/脚本；涵盖实际生产者和消费者。四列、零新表；薄application/Repository是领域边界，不是新恢复中心。无新依赖或HTTP恢复端点。\
**结论**：业务实现与本地回归完成，未发现尚未处理的新增代码HIGH缺陷；真实集成/前端验收未完成，**整体NEEDS_FIX（验收门禁未满足）**。这不是可以合并/上线的PASS。

## Summary

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 1 | 0 | 0 | NEEDS_FIX，发布线基线未集成 |
| Permission & Auth | 0 | 0 | 0 | PASS，实际FGA需集成验 |
| Concurrency Safety | 0 | 1 | 0 | PASS_WITH_NOTES，双DB锁待验 |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 1 | 0 | 0 | NEEDS_FIX，端到端未验收 |
| Code Style | 0 | 1 | 0 | PASS_WITH_NOTES，完整前端类型检查待补 |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## 已修复的复核发现

- 工作台联合应用查询和simple读漏了父READY过滤：已补Flow分支及count/simple，真实SQLite联合查询覆盖PENDING隐藏、非workflow保留；创建成功/权限失败/审计失败分别保持正确READY状态。
- 作用域扩大、新成员支持及H回迁可能激活历史无效绑定：定义/成员支持变化前先终止旧无效绑定；H实际激活前删除所有历史H普通绑定，独立AdminRole保留；缩放、遗留无效scope、迁出回迁均回归。
- 禁用挂载旧resolver会回Root：同步前核对业务B，失败不能先激活Root/删除绑定；已测aactivate未调用及原绑定保留。
- SSO父路径变化未传播后代、只看主属漏兼属：同SQL更新后代path，枚举旧/新subtree主属+兼属，按最终事实终止；真实二级后代/兼属scope丧失回归。
- copy过的库再次作为源被误判半成品：负向门禁排除有当前copy_target_id的源；普通未发布草稿沿原语义。
- 创建账本操作已完成但owner镜像未完成：固定原op、mode和CREATOR校验后finalize，SQL回归验证非FINALIZED拒绝、重复finalize安全、不把PENDING_DELETE assignee变ACTIVE。

## 检查依据

1. **边界**：role字段缺省与显式空/null区分；普通角色空集合合法，缺定义/主部门H不一致明确24006；Quota0/-1、有限上传MIN、真实0与统计未知区分；copy指针只由服务端写。没有必填UUID兼容破坏。
2. **权限**：真实H不被M覆盖；角色定义/菜单精确O、绑定H、部门B/S区分；外国兼属混合政策在姓名/组写前拒绝。平台/部门/租户身份独立。工具/flow/copy未就绪在super/public/批量前负向拒绝；原F048仍唯一资源动作授权，无新业务tuple写入。
3. **事务/并发**：工具父子及flow/v0原单SQL事务、同T；角色scope和失效绑定同UoW；绑定采用定义→用户及当前锁内重验。copy锁源目标、UNPUBLISHED→COPYING CAS唯一领取、条件发布释放；不把COPYING重复消息当执行许可。异常commit只查原target，不盲删/重建。未知外部写不自动接管。原quota微超合同保留。
4. **信息**：新增错误固定业务文案，ID均来自已授权目标或原请求；不向响应返回原异常。配置为隔离空文件，测试假密码没有生产值；只读盘点需要显式T/可选UID，FGA未验保持NOT_RUN。
5. **测试**：86个本批测试通过，相关202通过/10个基线已失败；真实SQL覆盖主要不变量，权限/外部库仅窄替身。HTTP3 skipped、浏览器未做，不能证明跨进程/双DB/外部副作用完整性；E2E报告对40条逐项标未验/延期。
6. **风格**：新ORM放所属Repository，经application读取跨域事实；无globalfilter/whitelist改动，无新业务恢复表。Ruff相对HEAD0新增诊断，按路径arch-guard0 VIOLATION；保留既有WARNING与遗留lint，不声称全库通过。locale源与生成产物一致。
7. **文档**：spec保留原40条；scope明确28纳入/11部分/1延期；design补实际接口/数据流/反直觉边界/延期与升级说明；tasks实际目标路径与配套回归已核对，T047/T048未打勾。

## HIGH

- **[Compatibility / 发布线基线]** 当前HEAD相对本地缓存发布线`d69b219394`落后2156提交，38个改动路径与其后续变更重叠；发布线已增加work130迁移合并revision。没有fetch或同步，不能宣称对当前发布线兼容或迁移仍单head。合入前同步、核对实际冲突和head、重跑全套检查；明细见release-baseline-check.json。

- **[Test Coverage / 合入门禁]** T047及e2e-report：真实MySQL/DM8、FGA、Redis、Celery broker、对象/向量库与浏览器未验收，3条HTTP用例仅skip，其他本批结果尚无完整HTTP自动覆盖。需在隔离部署补足/执行QA矩阵，复核锁竞争、broker未知与权限失效、最终GET状态及前端交互后重审。当前不能宣称39项本批AC端到端通过。

## MEDIUM

- **[Concurrency]** 新行锁/CAS和同步组织UoW只在SQLite执行了业务/事务回归；SQLite不能证明MySQL/DM8锁序、并发冲突回滚或大部门耗时。集中验收需用两种DB的并发授予/scope变更/copy重复投递和实际规模样本验证。已保持明确失败与受控重试，没有引入新异步恢复体系。
- **[Frontend validation]** 全量Platform TSC当前未通过，缺共享workspace/react等类型依赖并有共享组件诊断；两改动文件transpile仅证明语法。需在标准完整依赖环境跑类型/构建及浏览器。未为了本修复升级依赖或清理无关组件。

## Overall: NEEDS_FIX

剩余为发布线同步、集中集成/前端验收及最终门禁复核；不要求用户再确认已采用的业务方案。没有提交、推送、合并或部署。代码在当前worktree可审阅，操作步骤见upgrade-guide.md。
