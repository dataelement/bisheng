# 知识库与知识空间统一：功能工作区

**迁移日期**：2026-11-04\
**功能分支**：`codex/3.1.0-beta1/118-knowledge-space-unification`\
**工作区**：`/Users/zhangguoqing/works/bisheng/.worktrees/118-knowledge-space-unification`\
**建分支时历史基线**：`d99eb7e430929323a9bf19e2242df9f54d63d908`，在本功能分支合并主工作区本地 `61971a13d8129a12a4522e31ff23d6dbd595bac2` 和最新远端 `origin/feat/3.1.0-beta1` 的 `22d46549f9a1f09fb7b63f3f7235c882b1576646`，两边提交均保留。

## 文档入口

- [Spec：94 条验收标准](./spec.md)
- [技术设计：迁移、策略统一、业务绑定维护和强制删除](./design.md)
- [实施任务：接口、依赖、文件 Owner 与验证](./tasks.md)
- [剩余129项：需求分组、逐项编号和依赖](./pending-tasks.md)
- [剩余任务范围复核：AC依据、授权边界与外移记录](./scope-review.md)
- [独立待办：分享链接签发授权（已移出F118）](../../../docs/backlog/share-link-issuance-authorization.md)
- [多 agent 并行开发：边界、耦合与合流协议](./parallel-development.md)
- [QA 参考：140 条八列用例](./test-cases.md)
- [任务拆分复审记录：原213项LGTM](./tasks-review.md)
- [W0/W1集成与任务级评审](./implementation-review.md)
- [W2业务写入口集成与复查记录](./wave2-implementation-review.md)
- [W3运行准入、共享来源读取及集成复查](./wave3-implementation-review.md)
- [W4剩余业务来源接口合同](./business-sources-contract.md)
- [W4剩余来源接线与集成复查](./wave4-implementation-review.md)
- [W5使用准入消费面冻结合同](./wave5-consumers-contract.md)
- [W5多agent交付、复查及验证](./wave5-implementation-review.md)
- [运行与共享来源接口合同V1](./execution-read-contract.md)
- [运行与共享读取实际入口接线](./execution-entrypoints.md)
- [冻结接口合同：REF V1.1、W2 Runtime/batch与P1/J1/A1](./contracts.md)
- [升级说明：停服、引用回填、恢复与核对](./upgrade-guide.md)
- [HTML 技术评审：13 张流程图](../../../docs/architecture/review/2026-11-03-bisheng-knowledge-unification-technical-review.html)
- [版本契约：保留其他特性登记并加入 F118 增量](../release-contract.md)

## 评审状态

| 文档 / 阶段 | 状态 | 记录 |
| --- | --- | --- |
| spec.md | ✅ 已评审、用户已确认 | 2026-11-05 确认完整 94 条 AC，作为设计评审的需求基线 |
| design.md | ✅ 已评审、用户已确认 | 四项口径独立复查闭合；2026-11-05 用户授权进入任务拆分 |
| test-cases.md | 已生成，待执行 | 140 条，94 AC 全覆盖；QA 参考，不是任务或 Harness 输入 |
| tasks.md / parallel-development.md | ✅ 已拆分、复审 LGTM | 原213项复审通过；W4四类来源和消费者已合流，历史604编号：465已完成/历史交付、137当前待办、2外移；验证见W4记录；完整特性仍在开发 |

## W5当前交付进度（2026-11-06）

原157队列完成20项，7个既有需求接缝叶子闭合，当前137待办。功能源码34fcbd7fe通过100路径2852测试及15子测试，前端目标6例全绿、全lint通过；平台typecheck22条及扩展回归旧失败均对照基线、新增0。详细证据与限制见W5记录，不代表完整特性/迁移验收。

## 范围复核时点说明（2026-11-06）

分享签发 T404/T405 已移出本特性及其验收前置，尚未实施；原历史记录中的要求由本轮决定替代。其余157项逐条复核，发布/分享等其他动作不因 use 下线放宽，QA/协议/任务/运维只做本次范围。详见范围复核。历史 W3/W4 数字和测试证据保持当时含义，不当作当前任务分母。

## 迁移边界

本次迁入已有规格、设计、升级说明和 HTML，保留已确认的 Q-01–Q-05、业务同事务维护绑定、旧数据回填及强删后保留失效关系的规则。原文中的 `feat/3.0.0` / `25e50eceeeb71989257e5ff38e35f5e011e59bae` 是历史源码调研证据，并非新功能工作区的当前代码基线。

完整spec与设计已确认，已开始核心代码实施；完整业务接线审查、正式迁移脚本及全特性验收尚未完成。F118 编号保持现有文档约定。主工作区其他配置、登录流程及验证文档不迁移。

## 2026-11-04 Spec 评审修订

本轮已按用户四项反馈同步 Spec、design、HTML、升级说明和版本契约：文件动作统一判定、旧任务过期、具体业务引用保留/解除，以及逐项修复失效引用。design §6.4.1 补充 577d8bd14 基线的定向源码证据；不是全仓行为审查，功能与回填脚本仍未实现。此为该轮评审时记录，后续已checkpoint。

## 本轮补充确认

已新增 AC-93（存量失效保留标记、对账完整可升级）与 AC-94（文件/文件夹精确直接引用保护），合计 94 条。design §6.11–§6.12 和 HTML 第 13 图细化实现边界；升级说明同步。此前四项评审修订保持，主工作区未改动，文档后续已checkpoint，当前代码状态见实施记录。

## 2026-11-05 技术设计评审后修订

不扩展文件 edit，保留现有用例动作映射；纯可见授权按 design §7.3.2 保留原 model_key、Source 和管理等级，并支持原入口撤销；文件删除复用空间 F048 投影在先、SQL finalize 在后的顺序；Worker 在途异步写入与用户后续修改的竞态暂不处理。spec、design、升级说明、HTML 和版本契约已对齐，仍为 94 条 AC、13 张图；该次决策阶段仅修订文档，当前实施状态见下文。

## 2026-11-05 开始实施

T001基线已对齐至远端 `9eef0016de`，合并提交 `a1b1a2387`。T002 [接口合同V1](./contracts.md) 已冻结；按源码核对追加T214–T227，冻结当时计划227项。已从同一冻结提交创建独立lane worktree，并行开发权限、引用和处理核心；主agent统一结构迁移、注册、合流和测试。未推送或部署。

W0/W1历史交付为86/273项、组合424项通过，见[历史记录](./implementation-review.md)。本次W2的实际固定提交、完成卡与组合验证见[W2集成复查](./wave2-implementation-review.md)。完整特性、数据库真实回归、E2E及停服迁移尚未完成。


## W2业务入口接线

从9cbb0141de创建WF/AS/TARGET三个独立lane；INT先交Runtime、legacy Reader与生产composition，实际Owner和业务写入按依赖接线，其他agent固定快照复查，主agent集成验证。工作流保存版本及助手当前配置在同一事务维护引用，支持既定原槽修复；新增知识统一按真实type及原actor校验visible，整根删除核完整版本/集合/raw明细。模型共享明确撤销允许原槽保留或移除，新增及执行拒绝，不新增权限动作或持久状态。

W2结束时166/342项完成（本波新增80项）；主agent在411d4f461473组合验证821项通过（35个pytest路径），架构检查56文件无违规，Ruff 56文件通过。未推送、部署或执行迁移。这些在W2结束时未完成的WF运行、AS共用Agent/Info和来源读取scope已由下节W3接线；其他来源写端及全特性验收仍待推进。升级仍要求停服及一致备份后正式盘点并冻结基线；Reader/结构就绪不代表回填或Coverage就绪。


## W3运行准入与共享来源读取

先冻结可信原身份、来源只读scope、目标当前读与最终root重验合同，再由WF/AS/REF并行开发。普通/public WS、v2、单节点预览、共用Agent、Info和JWT评测已按依赖接线，API/worker装配实际Reader；common在执行副作用前调用端点绑定Port，不自行导入领域服务。

W3结束时248/421项完成，本波新增82项。主agent在0c2587dbe5ec组合验证1199 passed、6 subtests passed（46个pytest路径），Ruff/格式70文件通过，架构新增违规0，既有告警见[W3集成记录](./wave3-implementation-review.md)。全部记录保留94AC/140QA及13张原图；分享签发授权T404/T405、其余来源与页面、正式回填/Coverage和真实环境验收仍待实施。无push、部署或数据迁移。


## W4剩余业务来源接线

APP真实保存版本、频道完整当前配置、Knowledge自身模型和五类默认配置已接实际维护与严格读取。模型默认覆盖与多空间同事务更新，commit后派发7字段业务命令；RAG/worker从当前业务配置取模型。APP维持原0/3检索能力，历史QA/删除目标保ID与失效状态。查询不再暗中产生退休重建消息；旧无stage/期望任务明确失败待升级受控处置。

先冻结[业务来源合同](./business-sources-contract.md)，再按APP/CH/LLM/KN及最后WORKER独占交接并行；主agent固定提交复查、正常合流和组合验证。设计、升级说明与HTML已同步，原94AC、140QA及13张SVG保持。主组合2390项及6子测试通过（81路径），438/597任务完成。确切受测源码、静态结果及其余范围见[W4集成记录](./wave4-implementation-review.md)。未推送、迁移或部署，主工作区保持原状。

## W6持续实施（2026-11-07）

W6持续实施；历史794编号：663已完成/历史交付、129当前待办、2外移；原137队列已完成28项、剩109项，另20张既有需求接缝卡待办。见[当前清单](./pending-tasks.md)及[W6记录](./wave6-implementation-review.md)，完整特性未验收。本轮真实原凭据、整版本精确JOIN、bounded列表、模型Owner影响核心、MIG同run/checkpoint及mock辅助已合；模型强删公开协调/SourceReader、全来源正式回填/Coverage等仍待推进。详情见[W6记录](./wave6-implementation-review.md)与[冻结合同](./wave6-completion-contract.md)。

109:3005由用户撤回后保持不动；109新独立项目已启动标准旧版本API/worker和真实中间件，真实注册/登录并准备隔离租户和mock模型，尚未执行F118迁移。用户选mock模型/ETL并免除本轮DM8实测；不免C2静态，也不以此代替MySQL事务、索引、投影和升级恢复演练。
