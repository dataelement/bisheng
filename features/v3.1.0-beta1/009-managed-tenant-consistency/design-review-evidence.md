# F009 最小修复设计复审依据

2026-11-10。原七表稿被用户要求调整；当前设计为候选最小修复。本轮只读源码核对和文档修订，未实施、执行测试、提交或部署。

## 当前结论

- 原完整稿的LGTM/PROCEED不沿用；原文件、评审结论均保留为历史快照。
- 针对原稿的最小化独立复审为[REVISE](minimal-change-architecture-review.md)，指出多层操作编排过重。
- 针对最小候选的[第二轮](minimal-change-architecture-review-v2.md)提出复制唯一执行领取、DSH round合同和未知提交区分；当前均已补齐，[最终复核](minimal-change-architecture-review-v3.md)为PROCEED，无未关闭技术发现。
- SDD整体一致性仍有一个已知high：原40条AC完整规格与最小交付不等价。[范围调整](scope-revision.md)逐条披露28条纳入、11条部分、1条延期，已于2026-11-10获用户明确确认；范围检查high关闭。

## 24项检查

依据[sdd-review](../../../.claude/skills/sdd-review/SKILL.md)的[design清单](../../../.claude/skills/sdd-review/references/design-checklist.md)。PASS为文档检查，不是业务测试。

| 项 | 结果 | 依据 |
| --- | --- | --- |
| 1 目标简明 | PASS | §1六项租户缺陷、三项质量优先 |
| 2 非目标 | PASS | §1/§8完整恢复与全局重构不捆绑 |
| 3 特有约束 | PASS | §2 H/M/B/S/O/T、直接策略、普通额度合同 |
| 4 Constitution | PASS | 引用C1–C8；owner端口、严格T、原F048、跨DB DDL与无本地权威状态 |
| 5 关键决策 | PASS | D1–D5 |
| 6 备选/选定/原因 | PASS | 同步事务、父记录状态、现有DSH读、复制关联的更小备选 |
| 7 重考虑触发 | PASS | 每条D含范围或实测规模触发 |
| 8 证据 | PASS | 当前真实工具两commit、flow/v0原单事务、DSH按次读取+动态限额、copy原源状态先提交 |
| 9 主数据流 | PASS | §4.1及六项改动表 |
| 10 字段/格式 | PASS | E输出、四列str/int/null及状态转换、原API必填保持 |
| 11 模块职责 | PASS | §4.1/§4.2/§6逐域owner及不接管范围 |
| 12 现状与设计区分 | PASS | 字段/入口均标拟新增，未声称已实现 |
| 13 反直觉事实 | PASS | §5八条 |
| 14 坑的影响 | PASS | §5影响列 |
| 15 处理位置 | PASS | §5具体Service/DAO/应用接口 |
| 16 Outgoing | PASS | §6原HTTP字段、有效角色函数、权限窄包装及状态 |
| 17 Incoming | PASS | §6权威H/B、原F048/DSH、SQL/Celery/外部存储 |
| 18 依赖风险 | PASS | 断链拒绝、未知提交/消息不盲恢复，旧worker需核对 |
| 19 验证层 | PASS | §7 ORM/故障/双DB/实际消费面，未声称已跑 |
| 20 手工复核 | PASS | §7隔离观察命令与测试部署步骤；URL/账号待提供，不编造真实验收 |
| 21 短板 | PASS | §8，逐项幂等/自动恢复/强收敛明确延期 |
| 22 历史 | PASS | 当前稿及旧快照、三轮独立意见保留 |
| 23 spec一致性 | PASS | 用户已确认scope-revision，28条纳入/11条部分/1条延期作为本批边界 |
| 24 实际偏差 | N/A | 未实施、未创建tasks，不补造实际偏差 |

## 进一步源码事实（避免过度解释）

- `tool/domain/services/tool.py::add_tools`写H；`GptsToolsDao.insert_tool_type`父子两次commit，可以用原SQL事务收敛。
- `workflow.create_flow`写H；`FlowDao.create_flow`主/初始版本已同事务，修显式继承租户即可解决该错位，不能以此声称必须新操作表。
- `dsh/domain/services/model.py::complete`与`chat_credits.py::start`每次读取政策，并传monthly_token_limit给QuotaRedis；Lua动态路径使用传入值。已准入round内unmetered保留跳过月比较的合同，不能泛化为所有调用重验额度，也不能据此证明旧快照瞬时失效。
- `file_copy_celery`已有acks_late，关联校验必须再配唯一领取CAS；崩溃不自动重领是零明细账本方案的明确可用性代价。
- ResourcePermissionMode/projection账本只用于权限，不提供文件进度或SQL业务操作的一般恢复。四列方案未把七表JSON搬到旧字段。

## 文档/代码验证边界

已检查候选40条范围ID连续唯一、Markdown本地链接存在、候选错误码占用和git diff --check。业务代码/正式测试/迁移文件无新改动。本轮未重跑原诊断，也未连接真实DB/Redis/FGA/Celery/向量库/浏览器；同步事务规模及完整消费门禁须后续实现验证。

2026-11-10：用户回复“采用最小修复范围，继续开发”，范围high已关闭，design-review更新LGTM。
