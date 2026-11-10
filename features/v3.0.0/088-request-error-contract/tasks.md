# F088 开发任务与执行记录

## 状态

| 项目 | 状态 | 依据 |
|---|---|---|
| spec | ✅ 已确认 | 用户确认 |
| design | ✅ 修订获授权 | 用户“补齐这两点后开始开发吧”；两项独立审查修订见 design |
| 基线 | ✅ bc6ca25ba | 两端 React Query 4.44.0，保留已升级实现 |
| 实施 | ✅ 功能代码已落地 | 受影响链回归与限定范围独立复核通过；不等同整体验收 |
| 最终验收 | ⚠️ 未完成 | 基线门禁仍失败、真实后端E2E未执行，见verification-report.md |

## 任务

- [x] T001 共同错误模型与二进制解析通道。覆盖 AC: AC-02、AC-03、AC-04、AC-09、AC-10、AC-19。文件：packages/api-client（模型、解析、测试、配置），两端依赖与质量门禁。先验证正常 body 与显式解码 envelope 能同时保留原始 cause/response/二进制引用，再实现。验证包测试、TS 与 lint。
- [x] T002 platform 入口与强耦合兼容。依赖 T001。覆盖 AC: AC-01、AC-03、AC-06、AC-07、AC-08、AC-10、AC-14、AC-15、AC-16、AC-17、AC-18。文件：controllers/request.ts、消息/提示适配器、types/global.d.ts、LoginPage/login.tsx、DSH 及下载消费和对应测试。测试密码过期、取消、全局、silent、已提示后仍可捕获完整错误及成功结构。
- [x] T003 platform 业务调用迁移与 v4 衔接。依赖 T002。覆盖 AC: AC-05、AC-07、AC-11、AC-12、AC-13、AC-14、AC-20、AC-21。文件：migration-inventory 中 platform 活跃 API→hook→页面链，尤其 ModelPage/manage、Dashboard、BuildPage、DepartmentPage、SystemPage、KnowledgePage；每批补行为回归，清理失败哨兵和吞错。保留离线/缓存键/isInitialLoading；refetch/保存/发布失败不继续成功动作。
- [x] T004 client 强耦合消费预适配与入口切换。依赖 T001。覆盖 AC: AC-01、AC-03、AC-06、AC-07、AC-08、AC-10、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19。文件：api/request.ts、api/skillCenter.ts、Skills/types.ts、SkillUploadDialog.tsx 等 Skills 活跃消费、api/messageExport.ts、其他下载、全局监听及测试。旧/新错误输入验证11053未导入、11055重名覆盖、401及二进制证据，再切入口。
- [x] T005 client 调用方及查询失败迁移。依赖 T004。覆盖 AC: AC-05、AC-07、AC-11、AC-12、AC-13、AC-14、AC-20、AC-21。文件：migration-inventory 的 client API/React Query 消费链；保留命名恢复，移除重复错误构造/提示，避免新业务错误重试；明确异步事件终点捕获。
- [ ] T006 质量门禁、E2E 与独立终审。依赖 T003、T005。覆盖 AC: AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21。运行受影响测试、lint/typecheck/check-i18n、两端构建、e2e-test、sdd-code-review；固定剩余问题、基线差异与回归证据。

## 执行记录与偏差

- 基线由72cee6ca5快进至bc6ca25ba，响应用户已合入的查询库升级；相关4文件8测试通过。
- 独立设计审查两项问题均已通过设计修订处理。用户授权修订后直接实施，不追加重复确认。
- Ruling: 先预适配消费方再原子切换入口；不交付中途开关或只完成局部透传。若分类遗漏会破坏旧业务，必须以真实消费回归与清单闭环兜住。

- Ruling: 自动审批拒绝整段替换 client 拦截器（涉及删除刷新队列）；采用保留原认证/刷新代码、在响应链末端增量规范化的低风险方案。若遗留分支新增特殊结果，需同步最终失败识别测试；不绕过审批删除旧会话逻辑。

- T001: 共同错误模型10项行为测试由失败转通过；独立tsc与eslint通过；接口已包含解码envelope并保留cause/response引用。
- T002/T004: 平台请求4项、客户端契约与命名恢复5项通过；技能消费18项通过；模型查询3文件9项通过。旧提示包装层继续reject的用例已先复现，尚未切换所有业务调用。
- Ruling: 自动审批拒绝跨104文件535处的通用批量变换，操作未执行；改为逐业务链人工核实与迁移，不能用语法检查冒充行为验证。
- 基线门禁：平台全量首轮172文件888测试通过，4项旧DSH错误载体断言需随本特性更新；3项未改动基线失败待独立对照。lint85项均在未改动文件；typecheck在未改动clientVoiceDraft测试报1项参数错误。

- 基础设施独立复查：二进制全局动作、已加载配置刷新失败恢复、HTTP失败无MIME错误解码已补修；通用迁移脚本确认会跳过ModelConfig删除后的onBack/next且不能正确处理确认框Promise，永久弃用写入功能。后续按业务链迁移。

- Ruling: AppChat detail请求原本skip403Redirect=true就reject所有失败，其resolved失败后重新接已删除应用的分支在基线不可达。按AGENTS“死代码删除而非重连”移除该旧分支，新增UI失败/重试终点；不凭存在源码宣称历史恢复曾正常工作。
- client消费回归：上传配额19403早停与参数透传从失败转通过；分享失效404/网络失败重试/维护流程3项从失败转通过；Skills18项通过。

- platform生产HOC调用清零，兼容导出最终切换为提示后reject；3请求回归文件13项通过。迁移独立实施agent已跑到179文件178通过、903项通过、2个已在初轮复现的未改动基线断言失败；无unhandled。尚待最终质量与独立终审。
- client: 菜单申请2项、审批详情错配/列表失败2项、二进制全局流程/元信息10项、inline rename保留输入/重试5项通过。共享语音新增原错误透传回归由失败转通过，共享包模板12项通过。

## 最终收口（2026-10-22）

- platform与client活跃链的迁移、两轮审查修复、附件双文件计数和模型详情失败恢复已落地；原始设计两点及新增审查问题的处置见各review/report。
- 新增调用只在UI终点消费拒绝；查询/API仍保留失败和原证据。实际包依赖、拦截器接线、旧HOC生产调用清零、命名恢复和消费入口均有源码/行为核实，没有凭feature文档宣布发版。
- 两端保持已升级的React Query4.44.0；错误缓存/重试/离线工厂回归保留。
- T006已执行本地自动化、构建、质量检查和独立限定范围审查；尚未满足整体验收，维持未勾选。完整结果、基线对照与需后续真实环境执行部分见verification-report.md、e2e-report.md、e2e-checklist.md。未推送/合并。

- 最终快照：platform946/948（2旧断言）；client687/707（20旧失败，31suite均在干净HEAD复现，新失败suite0）；共享12/12；双端构建通过。platform strict仅已复现旧错误1项，client1493strict全过，翻译通过。两端抑制仅收缩无增长。SDD整体验收仍NEEDS_FIX，仅待基线门禁与真实页面E2E，非隐瞒为全绿。

- 用户后续明确要求停止Vite、合并推送3.0.0并删除开发分支；已在最新发版线4bb923a43上逐块合并并重新验证，见integration-report.md。该集成授权不改变T006的真实业务E2E/基线门禁状态。
