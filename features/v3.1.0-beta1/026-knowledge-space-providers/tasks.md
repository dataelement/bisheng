# F026 开发任务：知识空间多后端与 WeKnora

依据：[已确认规格](./spec.md)、[已确认设计](./design.md)、[版本契约](../release-contract.md)。2026-11-24。QA参考用例不作为任务输入，以下测试直接追踪规格。

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户已确认37条AC |
| design.md | ✅ 已评审 | 用户已确认设计 |
| tasks.md | ✅ 已拆解 | 依赖和测试覆盖已校验 |
| 实现 | Wave 4 全部任务已本地验结（T033–T048）；Wave 5 七项前端任务本地契约均已验；Wave 6 已执行本地回归并接入严格门禁，真实环境证据不足，T056 不放行 | 54/56；T005 双库验收仍未关闭，真实联调未验 |

测试先于同一切片实现；同波内仍按明确依赖执行。路径为现有入口或拟增文件；上游相对路径指可发布的 WeKnora 源仓，必须登记负责人、扩展提交与构建，不以修改 dist 快照代替发布。先在目标版本确认路径与契约；涉及新增远端持久结构须在该源仓同步补相应数据库迁移和恢复测试。新增错误先复用已登记码；确需新码先核对版本契约。平台/客户端分别通过既有API层，不用store发HTTP。每个实现任务须通过对应先行测试；涉及其他Owner时维持原写入权。

## Wave 1

- [x] **T001 实例、绑定及操作事实**（基础设施）
  - 文件：`src/backend/bisheng/knowledge/domain/models/provider_control.py`
  - 定义实例/单生效绑定、操作、映射及额度预留结构；正文、凭据明文不得入表。
  - 依赖: 无；覆盖 AC: AC-09, AC-16, AC-31
- [x] **T002 双库增量迁移**（基础设施）
  - 文件：`src/backend/bisheng/core/database/alembic/versions/v3_1_0_f026_provider_control.py`
  - 以执行时真实head为父版本；索引覆盖租户幂等、代次和到期租约。空数据可降级；已有外部绑定或未决账本时禁止破坏性降级，关闭新受理并保留证据。
  - 依赖: T001；覆盖 AC: AC-01, AC-08, AC-09

## Wave 2

- [x] **T003 后端解析与原生兼容：先写失败断言**（测试）— 已收集并运行7例，全部因 T004 的 `provider_resolver` 模块尚不存在而预期失败；Ruff通过。此项完成不表示解析行为已通过。
  - 文件：`src/backend/test/knowledge/test_f026_resolver.py`
  - 对照原生空间与缺失外部绑定，后者拒绝；第三Provider不支持Wiki时无副作用。
  - 依赖: T002；覆盖 AC: AC-01, AC-32
- [x] **T004 后端解析与原生兼容**（Domain）— 请求级目标与显式工厂注册表已落地；T003 的7例转绿，连同Wave 1两例共9例通过。生产入口的事实加载与装配仍由后续切片接入。
  - 文件：`src/backend/bisheng/knowledge/application/provider_resolver.py`、`src/backend/bisheng/knowledge/infrastructure/providers/registry.py`
  - 由本地空间绑定解析实例、代次和范围；原生执行不再绕回路由。
  - 依赖: T003, T002；覆盖 AC: AC-01, AC-32
- [ ] **T005 控制账本与条件更新：先写失败断言**（测试）— 先行红灯已复现；T006 实施后 SQLite 两例转绿。MySQL/DM8 四项因未配置专用测试库跳过，双库实跑前不标为已验证。
  - 文件：`src/backend/test/knowledge/test_f026_ledger.py`
  - 同键不同参数拒绝，迟到回写不覆盖新租约；MySQL和DM8各跑一轮。
  - 依赖: T002；覆盖 AC: AC-08, AC-15, AC-31, AC-37
- [x] **T006 控制账本与条件更新**（Domain）— accept/claim/apply仓储已实现，SQLite契约通过；本轮累计11通过、4个实库参数项跳过，未接入生产Worker。
  - 文件：`src/backend/bisheng/knowledge/domain/repositories/provider_operation_repository.py`
  - accept/claim/apply核对请求摘要、租约、epoch、代次，未知结果仅按原目标查回。
  - 依赖: T005, T002；覆盖 AC: AC-08, AC-15, AC-31, AC-37
- [x] **T007 模型用途验证、回读与强锁：先写失败断言**（测试）
  - 文件：`WeKnora源仓/internal/application/service/model_guard_test.go`
  - 空库和非空库均拒绝同ID模型身份变化；A/B/C继承、探测失败及历史产物不变。
  - 依赖: T002；覆盖 AC: AC-04, AC-05, AC-06, AC-07
- [x] **T008 模型用途验证、回读与强锁**（上游）
  - 文件：`WeKnora源仓/internal/application/service/knowledgebase.go`、`WeKnora源仓/internal/application/service/model.go`
  - 覆盖空库、初始化及目录修改；摘要继承和显式覆盖分开；验证模型/VLM用途与版本。
  - 依赖: T007, T002；覆盖 AC: AC-04, AC-05, AC-06, AC-07
- [x] **T009 文件收据与有效版本：先写失败断言**（测试）
  - 文件：`WeKnora源仓/internal/application/service/receipt_test.go`
  - 相同字节不同请求不认领；重放同键仅一个文件；旧版退出召回。
  - 依赖: T002；覆盖 AC: AC-10, AC-11, AC-14
- [x] **T010 文件收据与有效版本**（上游）
  - 文件：`WeKnora源仓/internal/application/service/knowledge_ingest_receipt.go`、`WeKnora源仓/internal/application/service/knowledge_version_scope.go`
  - 持久接收/查回按版本幂等；归档版本退出有效来源。
  - 依赖: T009, T002；覆盖 AC: AC-10, AC-11, AC-14
- [x] **T011 Wiki变更及应用证明：先写失败断言**（测试）
  - 文件：`WeKnora源仓/internal/application/service/wiki_revision_test.go`
  - 注入部分收尾失败，文档完成不能解锁阅读；重建后保留其他来源。
  - 依赖: T002；覆盖 AC: AC-14, AC-17, AC-19
- [x] **T012 Wiki变更及应用证明**（上游）
  - 文件：`WeKnora源仓/internal/application/service/wiki_ingest.go`、`WeKnora源仓/internal/application/service/knowledge_delete.go`
  - 把完整收尾登记与应用修订绑定；删除只撤回目标来源，补登记可重复。
  - 依赖: T011, T002；覆盖 AC: AC-14, AC-17, AC-19
- [x] **T013 空库唯一初始化与回填：先写失败断言**（测试）
  - 文件：`WeKnora源仓/internal/application/service/tag_init_test.go`
  - 两批并发、中断半建词、成功无匹配、全失败四场景；20/3上限且不重建向量。
  - 依赖: T002；覆盖 AC: AC-20, AC-21, AC-22
- [x] **T014 空库唯一初始化与回填**（上游）
  - 文件：`WeKnora源仓/internal/application/service/knowledge_auto_tag.go`、`WeKnora源仓/internal/application/service/tag_initialization.go`
  - 冻结候选草案/样本；原子发布修订和待回填范围，重跑不重算成功项。
  - 依赖: T013, T002；覆盖 AC: AC-20, AC-21, AC-22
- [x] **T015 标签人工来源与安全删除：先写失败断言**（测试）
  - 文件：`WeKnora源仓/internal/application/service/tag_rel_test.go`
  - 并发回填与手工追加保留双方；过期清空失败；有引用标签删除不派内容删除任务。
  - 依赖: T002；覆盖 AC: AC-22, AC-24
- [x] **T016 标签人工来源与安全删除**（上游）
  - 文件：`WeKnora源仓/internal/application/service/tag.go`、`WeKnora源仓/internal/application/service/document_tag_revision.go`
  - 实现增量追加/条件替换/显式清空，删除标签不删文件；保留独立来源。
  - 依赖: T015, T002；覆盖 AC: AC-22, AC-24

### Wave 2 上游工作区与验证记录

源仓：本地 [WeKnora 扩展开发仓](../../../upstream-dev/WeKnora)，分支 `feat/f026-cnnc`，基线 v0.9.0 `f17ee8a`。仅集成文档库使用 `bisheng-v1`。未推送或发布；dist快照保持干净。毕昇T005本地2通过，专用 MySQL、DM8 未配置，4项跳过，保持未验结。

**2026-11-24 比较结果（Go 1.26.0）：**干净基线、扩展分支对相同 service/handler/router 三包分别执行 `go test -count=1 -json`。两侧失败集合按包+测试名完全相同：service 52、handler 1（含子测试），router通过。扩展分支三个包增加21个通过的顶层测试，未增加失败；不是全套通过。扩展分支 repository、container 两包也通过（repository有30个跳过项）。模型/收据/Wiki/初始化/历史补标/人工关联的专项用例已执行，修正Wiki恢复测试夹具后通过。SQLite从000000到000057共58份升级及最后6份逆序降级通过，模型强锁专项3项通过。PG新增135–140迁移尚未实库验证。

**交付限制：**未实测生产模型、PG/Redis和跨系统E2E；Lite内存队列不提供崩溃后持久执行保证。模型证明固定在具体内容子任务受理点，非上传时点。公开凭据不携带数据；上传收据需稳定已验证主体。后续发布须登记最终扩展提交和构建，不得以测试包通过或本地分支存在代替发布。以上 `[x]` 指任务的本地源码和专项验证，不代表生产放行。

**T005 专用双库放行命令（从 `src/backend` 执行）：**CI 通过秘密变量注入已迁移、可回滚的专用 `F026_TEST_MYSQL_URL`（mysql异步驱动）及 `F026_TEST_DM8_URL`（dm异步驱动），运行 `F026_REQUIRE_REAL_DBS=1 .venv/bin/python -m pytest -q -rs test/knowledge/test_f026_ledger.py`。要求6项全部通过且无跳过；严格模式缺连接直接失败，并校验DSN方言，不能把两个SQLite连接当双库。不要使用生产库、默认管理账号或把DSN写入日志。

## Wave 3

- [x] **T017 到期扫描与单步执行：先写失败断言**（测试）— 已运行4个Worker契约用例，均因T018模块未创建而预期失败；不代表真实Broker/数据库故障恢复已经验收。
  - 文件：`src/backend/test/knowledge/test_f026_dispatch.py`
  - 投递失败、租约过期双worker、查回成功补授权、结果未知耗尽转人工。
  - 依赖: T006, T004；覆盖 AC: AC-02, AC-08, AC-15, AC-31, AC-35, AC-37
- [x] **T018 到期扫描与单步执行**（Worker）
  - 文件：`src/backend/bisheng/worker/knowledge/provider_operations.py`、`src/backend/bisheng/worker/knowledge/provider_dispatch.py`
  - Celery headers携带tenant_id，和冻结记录核对后恢复ContextVar；锁外HTTP，只补未完成步骤，按实例限流。
  - 依赖: T017, T006, T004；覆盖 AC: AC-02, AC-08, AC-15, AC-31, AC-35, AC-37
- [x] **T019 个人/部门绑定与模型设置：先写失败断言**（测试）
  - 文件：`src/backend/test/knowledge/test_f026_provision.py`
  - 两部门第二项丢ACK重试；跨租户旧表单拒绝；成员只读、模型修订冲突。
  - 依赖: T008, T006, T004；覆盖 AC: AC-02, AC-03, AC-04, AC-05, AC-06, AC-08, AC-35
- [x] **T020 个人/部门绑定与模型设置**（Domain）
  - 文件：`src/backend/bisheng/knowledge/application/provider_provisioning.py`、`src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py`
  - 按部门冻结预设、请求键和UUID，权限投影成功后ready；配置预检和单未决写。
  - 依赖: T019, T008, T006, T004；覆盖 AC: AC-02, AC-03, AC-04, AC-05, AC-06, AC-08, AC-35
- [x] **T021 受控上传与额度预留：先写失败断言**（测试）
  - 文件：`src/backend/test/knowledge/test_f026_upload.py`
  - 并发超额、零重叠覆盖、断流、重复内容不泄露；查本地存储与原生队列无新内容。
  - 依赖: T010, T006, T004；覆盖 AC: AC-09, AC-10, AC-11, AC-16
- [x] **T022 受控上传与额度预留**（Domain）
  - 文件：`src/backend/bisheng/knowledge/application/space_upload.py`、`src/backend/bisheng/knowledge/application/provider_upload_quota.py`
  - 注册授权版本后流转发，按字节预留/核验/释放；远端未接收才要求客户端重传。
  - 依赖: T021, T010, T006, T004；覆盖 AC: AC-09, AC-10, AC-11, AC-16
- [x] **T023 目录、授权文件与受控流：先写失败断言**（测试）
  - 文件：`src/backend/test/knowledge/test_f026_read.py`
  - 稀疏可见分页，根卡片/详情/搜索计数区分；领取前撤权拒绝。
  - 依赖: T004, T010；覆盖 AC: AC-12, AC-13, AC-18, AC-36
- [x] **T024 目录、授权文件与受控流**（Domain）
  - 文件：`src/backend/bisheng/knowledge/application/provider_reads.py`、`src/backend/bisheng/api/services/f048_permission_runtime.py`
  - 按本地资源事实判权后分页、生成受控句柄，GET/Range重验；流终止关闭上游。
  - 依赖: T023, T004, T010；覆盖 AC: AC-12, AC-13, AC-18, AC-36
- [x] **T025 模板、引用与分页编辑：先写失败断言**（测试）
  - 文件：`src/backend/test/knowledge/test_f026_tag.py`
  - 半份词表不分类、翻页保留第501项、重复导入及旧引用失败。
  - 依赖: T014, T016, T006；覆盖 AC: AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
- [x] **T026 模板、引用与分页编辑**（Domain）
  - 文件：`src/backend/bisheng/knowledge/application/provider_tags.py`、`src/backend/bisheng/knowledge/application/knowledge_batch.py`
  - 公共模板逐部门导入，冻结词表修订；标签引用按代次校验，区分append/replace/clear。
  - 依赖: T025, T014, T016, T006；覆盖 AC: AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
- [x] **T027 授权Wiki及写屏障：先写失败断言**（测试）
  - 文件：`src/backend/test/knowledge/test_f026_wiki.py`
  - 三角色验证同图不同附件权限；旧slug、未映射、清理未证实不放行。
  - 依赖: T012, T004, T006；覆盖 AC: AC-14, AC-17, AC-18, AC-19, AC-35
- [x] **T028 授权Wiki及写屏障**（Domain）
  - 文件：`src/backend/bisheng/knowledge/application/provider_wiki.py`、`src/backend/bisheng/knowledge/application/knowledge_deletion.py`
  - 图谱与正文按空间visible，原文另验；以对应修订解除屏障。
  - 依赖: T027, T012, T004, T006；覆盖 AC: AC-14, AC-17, AC-18, AC-19, AC-35
- [x] **T029 双路召回与metadata：先写失败断言**（测试）
  - 文件：`src/backend/test/knowledge/test_f026_search.py`
  - 检查实际文档候选：改标、空、故障、无权、跨实例旧标签不做全库检索。
  - 依赖: T004, T010, T016；覆盖 AC: AC-25, AC-26, AC-27, AC-32, AC-33
- [x] **T030 双路召回与metadata**（Domain）
  - 文件：`src/backend/bisheng/knowledge/domain/services/retrieval_engine.py`、`src/backend/bisheng/knowledge/application/provider_retrieval.py`
  - 授权集合、版本、标签与可等价metadata求交，空候选直接结束；异构分数按排名融合。
  - 依赖: T029, T004, T010, T016；覆盖 AC: AC-25, AC-26, AC-27, AC-32, AC-33
- [x] **T031 有效代次、删除和迁移：先写失败断言**（测试）
  - 文件：`src/backend/test/knowledge/test_f026_migration.py`
  - 迁移期不重复计费、恢复点错位保持隔离、迟到旧任务不能操作新库。
  - 依赖: T010, T012, T006, T008；覆盖 AC: AC-07, AC-14, AC-16, AC-30, AC-31, AC-37
- [x] **T032 有效代次、删除和迁移**（Domain）
  - 文件：`src/backend/bisheng/knowledge/application/provider_transfer.py`、`src/backend/bisheng/knowledge/application/knowledge_version_mutation.py`
  - 重摄入新库并核对来源后CAS切主；保留旧代次墓碑/未决任务；移动、复制缺能力只读预检即拒绝。
  - 依赖: T031, T010, T012, T006, T008；覆盖 AC: AC-07, AC-14, AC-16, AC-30, AC-31, AC-37

### Wave 3 本地验收记录

T018–T032均完成应用/领域层切片及对应先行契约验证。综合运行 F026、原生上传、部门管理、批处理、删除、权限装配、检索排名/外观及迁移单head回归：226 passed，4 skipped（均为T005专用MySQL/DM8）；不将各子套件结果相加。Alembic仍只有 f026_provider_control 头。模板导入控制记录已纳入租户模型发现和降级保护。

贯通点：发送前持久认领，旧租约只查回；已接收的外部文件不参与检索，只有成功处理证明、有效授权投影和本地版本匹配后才CAS激活。Wiki只读查询不解除写屏障；删除完成须核对冻结操作的修订证明。迁移切主前比对新旧库、逐版本映射、字节与摘要；未支持的移动/复制不落原生副作用。

边界：本地SQLite、可控远端端口及HTTP MockTransport验证不是生产联调。无执行器时Worker不消费，不注入通用权限或远端成功结果。Wiki读取、检索、标签、上传、建库与迁移仍需要后续真实端口/凭据装配；Wave 4负责API/调用方接线；真实Broker、多Worker、WeKnora、OpenFGA、MySQL/DM8并发、性能和跨系统恢复另验。未提交、推送或部署。

## Wave 4

- [x] **T033 空间和文件入口分派：先写失败断言**（测试）— 串行复核：新增受管策略断言先因创建请求缺少 `model_policy` 而失败；修正后 v1 专测 7 项通过（含无效模型、Native 预览、未知 Provider 及受控句柄）。不作为 T034 的生产联调证明。
  - 文件：`src/backend/test/knowledge/test_f026_v1.py`
  - 客户端旧URL、模型无效、未知后端直接请求与仅预览账号均独立验收。
  - 依赖: T024, T022, T020, T018；覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-09, AC-12, AC-13, AC-32, AC-34, AC-36
- [x] **T034 空间和文件入口分派**（API）— 本地契约已验。创建与部门批建按后端分派、受管策略回读；仅预览者只获受控解析文本节选，不发原件下载URL。库设置受理冻结远端版本，远端事务比较版本并保存操作ID、补丁摘要、新版本；本地只凭匹配收据和已读回的字段完成操作。Python 组合回归55通过；Go类型、仓储CAS、服务幂等/管理员校验定向通过。SQLite迁移058已验证；PG141及真实部署的HTTP链未验，settings_write仍标未验证，不视作生产放行。
  - 文件：`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`、`src/backend/bisheng/knowledge/api/endpoints/knowledge.py`
  - 分别接创建/设置/能力/文件/受控预览及旧分享读取，原生返回形态不变。
  - 依赖: T033, T024, T022, T020, T018；覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-09, AC-12, AC-13, AC-32, AC-34, AC-36
- [x] **T035 开放写入和快照导入：先写失败断言**（测试）— 串行实跑5项预期失败：外部file、file_url、chunks、chunks_string的4个请求都在分派前尝试保存/抓取；快照修订契约尚缺。Native同步语义复用已有test_legacy_space_chunks及开放面回归。红灯不代表实现完成。
  - 文件：`src/backend/test/knowledge/test_f026_v2.py`
  - 旧Native可用，外部不兼容请求无本地持久写、无任务；网页变化不混版本。
  - 依赖: T022, T004；覆盖 AC: AC-09, AC-29, AC-34
- [x] **T036 开放写入和快照导入**（API）— 外部v2文件/URL、同步分块和预制文本在抓取/持久化前按真实空间绑定拒绝；网页双产物未具备可查收据，继续保持外部入口关闭。完整快照修订能区分HTML及最终URL，不修改Native元数据。开放写入与Native网页材料/入库回归59项通过，不代表WeKnora远端快照导入已经开放。
  - 文件：`src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`、`src/backend/bisheng/knowledge/application/web_link_upload.py`
  - 在拉取URL或写原文前分派；同步/预制块不保真则拒绝；页面预览与检索同一快照。
  - 依赖: T035, T022, T004；覆盖 AC: AC-09, AC-29, AC-34
- [x] **T037 频道投递分派：先写失败断言**（测试）— 手工/自动两入口的红灯先复现（非原生目标仍在 MinIO 落对象后才失败）；修复后 13 项通过。
  - 文件：`src/backend/test/knowledge/test_f026_channel.py`
  - 两入口产生正确快照，远端失败不留毕昇侧入库副本。
  - 依赖: T022；覆盖 AC: AC-09, AC-29
- [x] **T038 频道投递分派**（Domain）— 在 MinIO 写入与 add_file 之前解析真实后端；远端就绪/准备中/带代次的原生/未决写四类都拒绝，事实不可读时 fail closed；Native 快照、预览与重复名语义回归通过。
  - 文件：`src/backend/bisheng/channel/domain/services/channel_service.py`
  - 手工与自动投递共享按目标授权、完整产物、稳定收据的内容交付。
  - 依赖: T037, T022；覆盖 AC: AC-09, AC-29
- [x] **T039 日常与任务作用域：先写失败断言**（测试）— 15 项先失败；补齐后日常工具 3 场景通过（不可解析的条件只跳过该空间、零匹配空间不发查询、用户固定标签不被模型放宽）。
  - 文件：`src/backend/test/knowledge/test_f026_daily.py`
  - 新任务、重启、重新生成、跨空间筛选失败均不搜索其他文件。
  - 依赖: T030；覆盖 AC: AC-26, AC-27, AC-31
- [x] **T040 日常与任务作用域**（Domain）— 会话转任务携带固定标签，任务工具按冻结范围/标签重验身份且模型不能放宽；重新生成沿用原轮次范围，缺失即拒绝。任务会话新增 `knowledge_space_tag_filters` 列（迁移 f026_linsight_scope），提交映射、Worker 装配同源。
  - 文件：`src/backend/bisheng/workstation/domain/services/chat_service.py`、`src/backend/bisheng/tool/domain/langchain/linsight_knowledge.py`
  - 持久交接用户空间/标签选择，子Agent与恢复复核；重新生成沿用原轮选择，模型工具不能放宽。
  - 依赖: T039, T030；覆盖 AC: AC-26, AC-27, AC-31
- [x] **T041 任务输入与选择快照：先写失败断言**（测试）— 14 项通过；范围做 JSON 安全序列化（字符串键）并在选择边界还原为整数。
  - 文件：`src/backend/test/knowledge/test_f026_scope_schema.py`
  - 往返序列化保留固定标签；失效原选择不推断为全空间。
  - 依赖: T030；覆盖 AC: AC-26, AC-27
- [x] **T042 任务输入与选择快照**（Domain）— 未声明、显式空、固定三类状态可区分；旧任务缺列保持“未记录”，不推断为空或全空间。
  - 文件：`src/backend/bisheng/linsight/domain/schemas/linsight_schema.py`、`src/backend/bisheng/workstation/domain/schemas/chat.py`
  - 为会话转任务与历史轮次增加可区别未选择/历史未记录的范围；兼容老任务。
  - 依赖: T041, T030；覆盖 AC: AC-26, AC-27
- [x] **T043 工作流/助手与受控工具：先写失败断言**（测试）— 5 项通过：上游成功+data:null 视为零命中、代次未就绪/修订越界不发出召回、工作流身份与撤权、真实运行时按授权文档清单约束。
  - 文件：`src/backend/test/knowledge/test_f026_workflow.py`
  - 同输入两身份命中差异、撤权失效、开放工具限制与截断。
  - 依赖: T030；覆盖 AC: AC-26, AC-32, AC-33
- [x] **T044 工作流/助手与受控工具**（Domain）— 保留运行用户/作者共享与 access_scope、白名单和既有返回结构；无外部装配时显式外部选择在 Native 前拒绝。为此修复两处回归：Native 多库恢复历史全局排序快路径；facade 测试假引擎接受请求级 provider 运行时。
  - 文件：`src/backend/bisheng/knowledge/domain/services/space_flow_retrieval.py`、`src/backend/bisheng/knowledge/domain/services/retrieval_facade_service.py`
  - 共用授权检索但保留运行用户或作者共享、入参范围和既有返回结构；开放读取不使用全局管理员。
  - 依赖: T043, T030；覆盖 AC: AC-26, AC-32, AC-33
- [x] **T045 空间内问答及历史引用：先写失败断言**（测试）— 12 项通过：精确文件范围、Provider 检索不回本地索引、历史版本只解析原版本、匿名拒绝。
  - 文件：`src/backend/test/knowledge/test_f026_citation.py`
  - 单文件/目录问答不扩张；历史旧版不可用不跳新正文，匿名拒绝。
  - 依赖: T024, T030, T028；覆盖 AC: AC-13, AC-18, AC-28, AC-34
- [x] **T046 空间内问答及历史引用**（Domain）— 单文件/目录/整空间保持各自范围；引用只回本地受控地址并绑定版本/代次/epoch；shared 片段可读但原文另判权；清理历史不删知识文件。citation 相关回归 317 项通过。
  - 文件：`src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`、`src/backend/bisheng/citation/domain/services/citation_resolve_service.py`
  - 转换本地物理file_id、版本及locator；原始文件和Wiki分别判权，清空历史不删文件。
  - 依赖: T045, T024, T030, T028；覆盖 AC: AC-13, AC-18, AC-28, AC-34
- [x] **T047 批操作和Wiki读取入口：先写失败断言**（测试）— 先复现外部批处理读取环境 MySQL 失败与 Wiki 代次未校验；“空 slug 拒绝”断言改为 fail-closed（404 或 422 均可）。
  - 文件：`src/backend/test/knowledge/test_f026_govern.py`
  - 夹入无权/处理中项、过期计划、重复确认均不扩大操作。
  - 依赖: T028, T026, T032；覆盖 AC: AC-17, AC-18, AC-19, AC-24, AC-30, AC-35
- [x] **T048 批操作和Wiki读取入口**（API）— Wiki graph/search/page/status 已挂载并按空间判权、代次就绪与 source-revision 屏障；批处理 inspect/precheck/confirm 冻结计划、重验修订、幂等认回，未注册真实写端口即拒绝、不回落 Native。批处理会话工厂作为可注入 seam，测试使用一次性 SQLite。govern+wiki+native batch 60 项通过。
  - 文件：`src/backend/bisheng/knowledge/api/endpoints/batch.py`、`src/backend/bisheng/knowledge/api/endpoints/provider_wiki.py`
  - 暴露授权Wiki读取与生成状态；批量重试、追加、删除等先预检，确认重验修订，未支持先拒绝。
  - 依赖: T047, T028, T026, T032；覆盖 AC: AC-17, AC-18, AC-19, AC-24, AC-30, AC-35

### Wave 4 最终验证记录（2026-11-24）

合并运行：`test/knowledge/test_f026_*.py` + Alembic 单 head + `test/citation` = **496 passed, 4 skipped**（跳过项仍是 T005 的 MySQL/DM8 专用库）。另跑检索/批处理邻近回归（facade、facade equality、multi ranking、space_flow、kn_batch、channel upload composition）= **104 passed**。

过程中修复的真实问题：受管建库漏传/漏验 `model_policy`；普通成员读设置被要求 edit；任务交接丢固定标签；Native 多库全局排序被跨源融合改写；任务工具 Provider 路径在引注注释失败时丢弃内容；外部批处理读取环境 MySQL；标签写入与迁移冻结竞态；切库沿用旧库 Wiki 水位；上传重发 epoch 与处理证明对不上。

测试口径修正（不改业务期望）：持久化范围用 JSON 字符串键、选择边界还原整数；“空 slug 拒绝”接受 404 或 422；范围单测不触碰共享引注/关系存储。

仍未验证：真实 WeKnora/OpenFGA/Broker、PostgreSQL 迁移、跨系统 E2E 与性能；Wave5 前端与 T056 发布门槛未开始。

## Wave 5

- [x] **T049 部门批建及状态**（Platform）— 实际管理页可预览并确认，Native 保存独立；当前租户/操作者按原请求键重开查询，在当前浏览器会话保留逐项准入失败信息，未证实的项不算成功。平台 6 项通过，服务端 HTTP/控制账本等 44 项通过；非真实跨系统 E2E。
  - 文件：`src/frontend/platform/src/controllers/API/departmentKnowledgeSpace.ts`
  - 管理端选两个部门提交；重开后逐项显示授权/失败，不把局部成功算整批成功。
  - 依赖: T034；覆盖 AC: AC-02, AC-03, AC-08, AC-35
- [x] **T050 创建及设置表单**（Client）— 页面及请求边界 18 项通过；服务端描述更新及 v1 路由回归 12 项通过。Native 仅改描述不改发布状态或标签。外部回显已验证的模型用途、版本和预设；无确认的设置写能力保持只读，未接真实模型/Worker 联调。外部个人创建的服务端配额与 Native 等价性须单独验证，不以页面校验替代。
  - 文件：`src/frontend/client/src/pages/knowledge/SpaceSettings/useKnowledgeSpaceSettingsForm.ts`
  - 客户端创建/设置页显示模型用途和预设摘要；不合法模型不可提交，普通成员只读；保存描述不更改标签。
  - 依赖: T034；覆盖 AC: AC-03, AC-04, AC-05, AC-06
- [x] **T051 文件上传与能力门禁**（Client，本地契约）— 上传及预览组件 17 项通过；upload_file 不等于 edit，逐项 key/收据，unknown/not_found 只查询、不重传。当前页可恢复，刷新后不保留待发文件。外部部署尚无可证明的签名用户上传端口和双预算组合，upload=unverified、预览编辑禁用；两份真实远端文件上传不计为已验。
  - 文件：`src/frontend/client/src/pages/knowledge/hooks/useFileUpload.ts`
  - 用upload_file而无edit账号上传两份，展示成功/失败可恢复；不支持预览编辑不可选。
  - 依赖: T034；覆盖 AC: AC-09, AC-10, AC-11, AC-36
- [x] **T052 Wiki图谱与详情**（Client，本地契约）— 可见成员从空间详情进入图谱，图谱/搜索/详情均固定 status 中的代次；无权来源仅展示占位，切换空间、身份、租户或代次后丢弃迟到响应。Wiki 客户端 22 项、后端 Wiki/治理 39 项通过；未进行真实远端浏览器联调。
  - 文件：`src/frontend/client/src/pages/knowledge/SpaceDetail/ProviderWikiPage.tsx`
  - 空间右上角进入图谱，搜索/点击打开三种页面；只读成员看到受限来源占位，生成中与失败展示不同。
  - 依赖: T048；覆盖 AC: AC-17, AC-18, AC-19
- [x] **T053 标签编辑与筛选**（Client，本地契约）— 550 词末页跨页保留、原修订条件清空、冲突拒绝；外部列表 tag_filter 未支持时不回退 Native。客户端 16 项、后端标签/迁移 31 项通过；独立上游 manual-tags-v1 仓储、处理器、路由三个 Go 包定向验证通过。旧上游不能写，未部署或实服联测。
  - 文件：`src/frontend/client/src/pages/knowledge/SpaceDetail/EditTagsModal.tsx`
  - 在550项中选择末页词翻页保存，清空前触发并发写，必须提示冲突；不显示全库用量。
  - 依赖: T048；覆盖 AC: AC-23, AC-24, AC-25
- [x] **T054 按原轮次重新生成**（Client，本地契约）— 原问题绑定会话、用户和租户；默认不发送当前选择，原范围不可用返回 12048，只有显式确认才用当前资料重新提问；两条路径保留旧轮次。客户端定向 18 项、既有聊天回归 48 项通过；实际 ASGI/SQLite 12 项覆盖持久化、历史回读、SSE/转任务，未接真实模型或浏览器 E2E。
  - 文件：`src/frontend/client/src/hooks/useAiChat.ts`
  - 更换选择器后重新生成保留原选择；历史范围缺失需确认，新提问才用新范围。
  - 依赖: T040；覆盖 AC: AC-27, AC-28
- [x] **T055 恢复诊断和能力状态**（Platform，本地契约）— 仅当前管理租户且有空间编辑权限的管理员可按页读持久账本；显示冻结目标摘要、阶段、尝试次数和白名单错误类别，未证实的状态不能人工放行。平台诊断 14 项、后端 ASGI/SQLite 6 项通过，包括重开账本与越权拒绝。未做真实部署重启演练。
  - 文件：`src/frontend/platform/src/pages/KnowledgePage/components/SpaceTaskRecordsDialog.tsx`
  - 重启后查看原操作，显示本地/远端目标与脱敏阶段，不展示正文，无法证实禁止手工放行。
  - 依赖: T018；覆盖 AC: AC-15, AC-31, AC-32, AC-35

### Wave 5 验证边界

客户端 F026 七个测试文件同批串行运行 91/91，管理端部门批建与诊断四个测试文件同批 20/20。后端 F026 定向组合含 Alembic 单 head 一次实跑 280 通过、4 跳过；诊断最后一次独立实跑 6/6。这些选择有重叠，不合计为独立用例数。未做真实 WeKnora/OpenFGA 多账号浏览器 E2E 或生产故障演练；外部上传及未经证明的写能力仍关闭，不以本地契约代替 T005/T056。

## Wave 6

- [ ] **T056 发布门槛与双库/真后端验证**（集成测试，环境未验）— 见[本轮验证记录](./verification.md)和[实服清单](./e2e-checklist.md)。已实跑本地 312 通过；6 个真实数据库参数项及证据包测试跳过。严格门禁缺证据会失败；不因本地通过而勾选。
  - 文件：`src/backend/test/knowledge/test_f026_release_contract.py`、`features/v3.1.0-beta1/026-knowledge-space-providers/verification.md`
  - CI对真实双库执行并发和恢复；用测试租户跑两个真实Provider并点引用，注入丢ACK、半登记及撤权。记录上游扩展提交、构建、证据和未验项；未获目标环境证据不能标生产通过。
  - 依赖: T004, T006, T008, T010, T012, T014, T016, T018, T020, T022, T024, T026, T028, T030, T032, T034, T036, T038, T040, T042, T044, T046, T048, T049, T050, T051, T052, T053, T054, T055；覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37

## 实际偏差记录

暂无。推翻已确认范围、数据权威或关键设计时先停止并重新确认；纯实现细节更新设计并在此记指针。
