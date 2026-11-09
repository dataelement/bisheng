# Tasks：知识空间统一与全平台 use 退役

**版本**：v3.1.0-beta1 / F118 · **拆分日期**：2026-11-05

**依据**：[spec.md](./spec.md)（94 条 AC） · [design.md](./design.md) · [并行边界与合同](./parallel-development.md) · [版本契约](../release-contract.md)

## 状态

| 阶段 | 状态 | 记录 |
| --- | --- | --- |
| spec.md | ✅ 已评审、用户已确认 | 2026-11-05，94 条 AC |
| design.md | ✅ 已评审、用户已确认 | 四项口径独立复查通过；本轮用户授权继续任务拆分 |
| test-cases.md | 已生成，待 QA 执行 | 八列参考用例；不作为 tasks/Harness/实施门禁输入 |
| tasks.md | 原213项拆分复审LGTM；追加卡已登记 | 依赖/Owner/覆盖与L1见[集成评审](./implementation-review.md)，原拆分见[记录](./tasks-review.md) |
| 实现 | 依赖推进中 | W6持续实施；历史980编号：875已完成/历史交付、103当前待办、2外移；原137队列已完成38项、剩99项，另4张既有需求接缝卡待办。见[当前清单](./pending-tasks.md)及[W6记录](./wave6-implementation-review.md)，完整特性未验收 |

## 当前范围与已移出编号（2026-11-06）

本轮验证口径以用户2026-11-07决定为准：免DM8实库，继续遵守C2的Model/Repository/DDL可移植规范；MySQL真实事务、中间件和迁移演练照常。下方既有卡及历史记录中的“双库实测”按此口径执行，不改变数据库兼容要求。

本次按已确认 spec 逐项核对原159个待办；T404/T405 已按用户决定移出，其余157项保留并收紧可能扩权的措辞，详见 [范围复核](./scope-review.md)。use→visible、旧知识兼容、模型引用核验分别追溯，不把三类任务混称为使用准入。其他动作及原业务条件继续独立校验；可见不等于可发布或可分享。

| 历史编号 | 当前归属 | F118 状态 |
| --- | --- | --- |
| T404 | [SL-AUTH-01 签发授权复现与测试](../../../docs/backlog/share-link-issuance-authorization.md) | 已外移，未实施，不计完成或剩余、不计 AC 覆盖 |
| T405 | [SL-AUTH-02 签发授权实现](../../../docs/backlog/share-link-issuance-authorization.md) | 已外移，未实施，不作为本次依赖或验收前置 |

范围复核时历史597编号 = 438已完成/历史交付（含后续退役）+157待办+2外移。W5交付后历史604编号 = 465已完成/历史交付+137当前待办+2外移；当前带复选框的范围内任务602项。原编号不重排；历史 W3/W4 数字保留其当时含义，由本节替代其中签发加固的旧前置要求。

## 领取与执行规则

每卡最多 2 个写入文件，目标约 30 分钟；已有文件增量过大先拆卡。文件显示“拟新增”表示实现计划，未声称已有行为。任务直接追溯 spec AC，不依赖 QA 用例表；已有统一权限/兼容/引用入口满足需求时只验证与复用，不为完成卡强行新增改写或重复框架；设计论证见 design，接口论证见 parallel-development。基础定义排在业务之前；后端配对测试先红后绿，最终集成测试按真实环境执行。

初始任务按拓扑排列；源码核对追加任务保留原编号，因此依赖图而非编号大小决定顺序。`依赖`满足即可启动，但同文件由唯一 Owner 串行；生成时已加入同文件的前一写入任务作为依赖。建议保持 INT 协调 + 3 开发槽，按并行文档 W0–W6 调度。所有实施任务先完成 T001 基线对齐与 T002 合同 V1；尚未批准变更公共接口时不得各自猜测字段。

测试文件均位于 `src/backend/test/knowledge_unification/`，新模块整表由 SQLModel 发现；既有表结构由 MIG 唯一编排 Alembic，数据转换仅停服脚本。Worker 卡统一遵守 Celery headers 中 tenant_id → ContextVar；相关配置/索引过期检查保留，不实施已排除的在途 I/O 竞态围栏。

每次交付提交任务 ID、base SHA、只写路径、配对测试的实际命令/结果、接口版本及未运行项。未经用户授权不推送、合并 PR、部署；不得 repo-wide Git 写操作。实际发现入口变化须先补叶子任务并更新覆盖/Owner，不能将清单未闭合标成完成。

## 任务清单

- [x] **T001 · 开发基线、文件 Owner 与入口清单**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/parallel-development.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/contracts.md`（拟新增）\
  **逻辑 / 测试上下文**：实施前按路径保留脏文档；核对/合入实际最新发版线，记录 SHA，再创建同一基线子工作区。contracts.md 登记全平台 use 消费者、旧知识调用面、MCP/SDK 实际路径及唯一 Owner；任何额外叶子文件先拆卡。禁止覆盖未提交内容。\
  **依赖**：无\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T002 · 冻结 R1/R2/R3/J1/A1/P1 合同 V1**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/contracts.md`（拟新增）\
  **逻辑 / 测试上下文**：按 parallel-development §3 冻结函数签名、错误/分页、确认摘要、幂等键、锁序、管理员具体租户、纯可见快照和任务状态；核对实际 OpenAPI 后登记路径，不使用 config 路径段。历史 envelope 保持，文件 edit 不扩展。\
  **依赖**：T001\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T003 · 来源/目标与替换 DTO**
  **类型 / Owner**：基础设施 / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/contracts.py`（拟新增）\
  **逻辑 / 测试上下文**：定义 SourceKey/ReferenceTarget/VerifiedTargetContext、稳定 slot、revision、extractor_version、来源集合摘要和已登记失效证据；仅模型/空间/直接文件，外部 Session 不 commit。\
  **依赖**：T002\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T004 · 引用明细与零引用集合 SQLModel**
  **类型 / Owner**：基础设施 / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/models/business_resource_reference.py`（拟新增）；`src/backend/bisheng/resource_reference/domain/models/business_reference_set.py`（拟新增）\
  **逻辑 / 测试上下文**：落实 design §6.2 唯一键、来源/目标/target_space_id 索引、真实目标租户与未知旧目标、基线证据；使用双库 helpers，不用专有 upsert。新整表自动发现；回退新表前备份/确认无已启用业务写入，不丢现有表。\
  **依赖**：T003\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T005 · 目标删除标记 SQLModel**
  **类型 / Owner**：基础设施 / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/models/resource_reference_tombstone.py`（拟新增）\
  **逻辑 / 测试上下文**：定义目标 deleting/deleted、操作/操作者/时间与幂等信息，不复制业务配置/凭据。存量失效不伪造 tombstone；新增整表同上回退限制。\
  **依赖**：T004\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T006 · 纯可见快照字段和兼容序列化**
  **类型 / Owner**：基础设施 / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/schemas/f048.py`；`src/backend/bisheng/permission/domain/services/grant_source_service.py`\
  **逻辑 / 测试上下文**：定义 visibility_only_resource_types/visibility_level，保留原 model_key、Source、范围和管理等级；旧字段兼容读取，checksum 规范化规则落 P1；快照字段在GrantModelSnapshot定义处扩展，不修改原Grant/Source表；持久元数据由T214加入PermissionModel，T009编排DDL。\
  **依赖**：T002\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T007 · 分类型默认与任务公开 DTO**
  **类型 / Owner**：基础设施 / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/processing_settings.py`（拟新增）；`src/backend/bisheng/knowledge/domain/schemas/processing_job.py`（拟新增）\
  **逻辑 / 测试上下文**：定义普通文档/表格独立草稿与保存版本、相关模型/索引修订、accepted 与 job/item 枚举、失败明细及裁剪字段；网页/音视频专用参数不混入。\
  **依赖**：T002\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T008 · 任务/子项 SQLModel**
  **类型 / Owner**：基础设施 / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_processing_job.py`（拟新增）；`src/backend/bisheng/knowledge/domain/models/knowledge_processing_item.py`（拟新增）\
  **逻辑 / 测试上下文**：记录空间/文件/逻辑文档/版本映射、实际处理快照、generation/lease、幂等键和检查点；模型只从业务读，不加任务模型引用。双库索引、无本机文件状态；新表未启用前可删除，启用后回退用一致备份。\
  **依赖**：T007\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T009 · 既有表字段与 Alembic 唯一编排**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge.py`；`src/backend/bisheng/core/database/alembic/versions/f118_knowledge_unification.py`（拟新增）\
  **逻辑 / 测试上下文**：按冻结 schema 增加 durable migration origin/分类型默认及相关配置版本；只迁既有结构，不跑数据转换。revision 文件名/父链由 MIG 实施时核对唯一值；测试 upgrade/downgrade(MySQL/DM8)，降级不得静默丢已生效配置。\
  **依赖**：T008, T005, T006, T214, T219\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T010 · 迁移账本 SQLModel**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_unification_run.py`（拟新增）\
  **逻辑 / 测试上下文**：定义 run/原基线/plan hash/阶段/租户来源覆盖持久结构，双库 helpers，不写本机共享状态。新表启用前可撤，转换后回退完整一致备份。\
  **依赖**：T009\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T011 · 新模块租户注册**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/core/database/tenant_filter.py`；`src/backend/test/fixtures/table_definitions.py`\
  **逻辑 / 测试上下文**：登记 resource_reference 及 knowledge job/item/run/operation_plan 新表的自动租户注入；共享模型跨租户反查通过可信专用 Repository，普通调用不得传任意 tenant 绕过；不改变 SQLModel 自动发现方式。\
  **依赖**：T010\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T012 · 错误码与测试基础**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/common/errcode/knowledge.py`；`src/backend/test/knowledge_unification/conftest.py`（拟新增）\
  **逻辑 / 测试上下文**：核对现有知识错误码子段，新增覆盖未就绪/引用变化/失效/任务过期等已冻结错误；准备两个租户、超管/租管/普通/独立子项授权、事务故障注入 fixture。其他模块错误如需增加，另拆注册卡交 INT。\
  **依赖**：T011\
  **验证 / 完成条件**：仅定义合同/结构，不交付业务行为；对照调用方编译/序列化或双库 DDL 验证，记录实际结果。

- [x] **T013 · 来源集合与目标反查 Repository：先写测试**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_repo.py`（拟新增）\
  **逻辑 / 测试上下文**：同来源重复保存无重复、空集有记录、不同版本独立；普通租户不串数据；共享目标能查两租户，异常不当空集。\
  **依赖**：T012, T004, T005\
  **覆盖 AC**: AC-72, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T014 · 来源集合与目标反查 Repository**
  **类型 / Owner**：后端 Domain / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`（拟新增）\
  **逻辑 / 测试上下文**：实现按 SourceKey 加载/差分/替换及目标/空间范围反查，零引用集合持久；普通按租户，受信共享模型反查汇总全部实际来源租户。只收外部 Session、不 commit。\
  **依赖**：T013\
  **配对测试**：T013\
  **验证 / 完成条件**：运行配对测试 T013；验证本卡预期，相关范围检查通过。

- [x] **T015 · 同 Session 原子替换与来源 CAS：先写测试**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_replace.py`（拟新增）\
  **逻辑 / 测试上下文**：事务中绑定失败配置不提交；两保存 CAS 冲突；保存/普通删并发无漏引用；部分修复保留另一失效槽，新建复制导入拒绝已删目标。\
  **依赖**：T014, T003\
  **覆盖 AC**: AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T016 · 同 Session 原子替换与来源 CAS**
  **类型 / Owner**：后端 Domain / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/bindings.py`；`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：实现 R2 replace_source_bindings；来源根修订门闩、候选目标锁后当前读重验，集合变化回滚重算；配置、明细、集合只由业务统一 commit。新非法目标拒绝，原未改动已登记失效允许保留。\
  **依赖**：T015\
  **配对测试**：T015\
  **验证 / 完成条件**：运行配对测试 T015；验证本卡预期，相关范围检查通过。

- [x] **T017 · 目标失效判定与覆盖就绪：先写测试**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_state.py`（拟新增）\
  **逻辑 / 测试上下文**：未完成来源/零引用集合缺失都阻断；登记存量失效不算缺口；迁移自身漏行不得降格存量失效；状态不可泄露其他租户细节。\
  **依赖**：T016\
  **覆盖 AC**: AC-89, AC-90, AC-91, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T018 · 目标失效判定与覆盖就绪**
  **类型 / Owner**：后端 Domain / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/target_state.py`（拟新增）；`src/backend/bisheng/resource_reference/domain/repositories/coverage_repository.py`（拟新增）\
  **逻辑 / 测试上下文**：统一 live/deleting/deleted、强删与基线已登记存量失效；按租户/来源类型 coverage_ready 查询，未登记异常 fail closed；提供 initialize_empty_tenant_coverage(session, tenant_id, writer_contract_version)，仅可信新租户/全新安装空数据证据且全部写端已启用可初始化，既有租户不得以缺账本冒充空租户。无独立改绑定 HTTP 接口。\
  **依赖**：T017\
  **配对测试**：T017\
  **验证 / 完成条件**：运行配对测试 T017；验证本卡预期，相关范围检查通过。

- [x] **T019 · 移除活动 use 与合法纯可见模型：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_policy.py`（拟新增）\
  **逻辑 / 测试上下文**：use-only 与跨资源全局 download 模型分别退化；原可见集合等价，rename 不变，非法空模型拒绝；历史快照 use 原文保留。\
  **依赖**：T006, T012\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-82\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T020 · 移除活动 use 与合法纯可见模型**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/model_policy.py`；`src/backend/bisheng/permission/domain/services/catalog_policy.py`\
  **逻辑 / 测试上下文**：从标准/自定义/预设/系统活动动作删 use；原资源类型退化纯可见时保留 model_key/等级/主体/Source，不补 edit/download，不创建 visible 具体动作；未标记任意空模型仍拒绝。\
  **依赖**：T019\
  **配对测试**：T019\
  **验证 / 完成条件**：运行配对测试 T019；验证本卡预期，相关范围检查通过。

- [x] **T021 · 纯可见授权可授予、列表与撤销：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_grant.py`（拟新增）\
  **逻辑 / 测试上下文**：有管理权限可经原入口找到并撤销 use-only 迁移授权；重复来源撤销一个仍可见；低等级操作者不得越权/撤受保护来源。\
  **依赖**：T020, T216\
  **覆盖 AC**: AC-78, AC-81, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T022 · 纯可见授权可授予、列表与撤销**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/grant_service.py`；`src/backend/bisheng/permission/application/catalog_api.py`\
  **逻辑 / 测试上下文**：grantable/manage-existing 识别合法纯可见快照与原管理等级；保留受保护来源限制，撤销仅当前 Source，其他来源并集保留；返回可管理可撤销能力。\
  **依赖**：T021\
  **配对测试**：T021\
  **验证 / 完成条件**：运行配对测试 T021；验证本卡预期，相关范围检查通过。

- [x] **T023 · 可见性编译与 F048 模型发布：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_projection.py`（拟新增）\
  **逻辑 / 测试上下文**：目录独立子项授权仍隔离；可见不等于下载/rename/edit；全员/系统/普通 Source 投影可逆、非 use 检查差异为零。\
  **依赖**：T022, T218\
  **覆盖 AC**: AC-30, AC-31, AC-59, AC-79, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T024 · 可见性编译与 F048 模型发布**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/visibility_projection_service.py`；`src/backend/bisheng/core/openfga/authorization_model_f048.py`\
  **逻辑 / 测试上下文**：编译纯可见快照、租户全员/系统可见来源，更新 F048 模型；只变原使用准入，保留子项、tenant、scope 与其他动作。版本/Catalog/checksum 按 P1 发布。\
  **依赖**：T023\
  **配对测试**：T023\
  **验证 / 完成条件**：运行配对测试 T023；验证本卡预期，相关范围检查通过。

- [x] **T025 · 运行协议与旧 use 表达兼容：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_runtime.py`（拟新增）\
  **逻辑 / 测试上下文**：旧协议表达可按 visible 调用，当前保存 use 不形成独立来源；失效凭证/跨租户/子项无权仍拒绝。\
  **依赖**：T024\
  **覆盖 AC**: AC-35, AC-78, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T026 · 运行协议与旧 use 表达兼容**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/business_authorization.py`；`src/backend/bisheng/permission/domain/services/permission_action_service.py`\
  **逻辑 / 测试上下文**：统一当前 use/use_kb 受支持适配为 visible，活动动作接口不保存返回 use；保留主体、凭证 scope、tenant 和业务状态；历史审计不重写。\
  **依赖**：T025\
  **配对测试**：T025\
  **验证 / 完成条件**：运行配对测试 T025；验证本卡预期，相关范围检查通过。

- [x] **T027 · 投影运行时快照与 checksum：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_runtime_snapshot.py`（拟新增）\
  **逻辑 / 测试上下文**：纯可见序列化往返checksum一致、Catalog发布/撤销可恢复，空动作合法模型不丢Source；非法空模型仍拒绝。\
  **依赖**：T026, T218\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T028 · 投影运行时快照与 checksum**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/projection_service.py`；`src/backend/bisheng/permission/application/runtime.py`\
  **逻辑 / 测试上下文**：F048 snapshot编译/持久校验和、target资源解析、Catalog变更impact支持合法纯可见标记/等级和Grant Source；仍复用原prepare/project/finalize及撤销路径，不为use另建规则。\
  **依赖**：T027\
  **配对测试**：T027\
  **验证 / 完成条件**：运行配对测试 T027；验证本卡预期，相关范围检查通过。

- [x] **T029 · 应用声明名称到真实目标合同：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_resolve.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：同名歧义拒绝，唯一名称解析与运行一致；历史 manifest 不修改；无法解析旧目标不得猜 ID 标为存量失效；冻结后名称重新指向另一ID时运行/预览失败，不调用未绑定目标。\
  **依赖**：T016, T026, T258, T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T030 · 应用声明名称到真实目标合同**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/reference_extractor.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：复用运行 name/id 解析，CapabilityModelRef name 与 knowledge name/id 均解析真实稳定 ID；歧义失败，冻结版本绑定依真实 ID，保留 manifest 原文；输出 B2；该版本解析真实ID随引用集合冻结，运行/预览必须逐槽匹配已登记ID，名字后续改名/重名不得漂移，解析不一致明确失败。\
  **依赖**：T029\
  **配对测试**：T029\
  **验证 / 完成条件**：运行配对测试 T029；验证本卡预期，相关范围检查通过。

- [x] **T031 · 工作流按版本提取器：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_extract.py`（拟新增）\
  **逻辑 / 测试上下文**：同一目标多槽独立；草稿/离线/非当前保留；删槽移除对应关系，聊天/评测/任务不计。\
  **依赖**：T016, T258\
  **覆盖 AC**: AC-71, AC-87, AC-88\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T032 · 工作流按版本提取器**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/workflow/domain/services/reference_extractor.py`（拟新增）\
  **逻辑 / 测试上下文**：由 Owner 解析实际节点/模型/空间/直接文件槽位，稳定 node/slot_key，不扫数组下标；所有未删除版本含草稿/非当前，不计 Flow.data 镜像。\
  **依赖**：T031\
  **配对测试**：T031\
  **验证 / 完成条件**：运行配对测试 T031；验证本卡预期，相关范围检查通过。

- [x] **T033 · 工作流 Repository 外部事务：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_transaction.py`（拟新增）\
  **逻辑 / 测试上下文**：create/update/delete 参与外部事务，失败回滚；旧 DAO 调用兼容。多版本新增与删除共根 revision 门闩。\
  **依赖**：T032\
  **覆盖 AC**: AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T034 · 工作流 Repository 外部事务**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/workflow/domain/repositories/workflow_version_repository.py`（拟新增）\
  **逻辑 / 测试上下文**：新增领域Repository接受外部原生AsyncSession，flush不commit；旧两DAO保持不变。root锁与版本真实ID由Repository提供，业务与R2最终同事务。\
  **依赖**：T033\
  **配对测试**：T033\
  **验证 / 完成条件**：运行配对测试 T033；验证本卡预期，相关范围检查通过。

- [x] **T035 · 工作流新增版本与保存：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_save.py`（拟新增）\
  **逻辑 / 测试上下文**：新增和保存不同版本独立绑定；绑定失败版本不提交；暂不能运行草稿也保留。\
  **依赖**：T034, T018, T287, T299\
  **覆盖 AC**: AC-71, AC-87, AC-88\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T036 · 工作流新增版本与保存**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：仅接create_new_version/update_version_info：提取对应版本完整集合，业务+R2同事务、revision门闩；所有草稿/非当前版本保护，Flow.data镜像不重复。\
  **依赖**：T035, T280, T291, T299\
  **配对测试**：T035\
  **验证 / 完成条件**：运行配对测试 T035；验证本卡预期，相关范围检查通过。

- [x] **T037 · 工作流当前版本与发布校验：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_current.py`（拟新增）\
  **逻辑 / 测试上下文**：切current不解除旧版本；失效版本发布失败；完整运行另T041/T042，先修一个槽保存保另一个；恢复旧current不猜模型。\
  **依赖**：T036\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-88, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T038 · 工作流当前版本与发布校验**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/flow.py`；`src/backend/bisheng/api/services/workflow.py`\
  **逻辑 / 测试上下文**：change_current_version/发布回滚沿既有操作，不清非当前绑定；发布校验剩余失效，完整运行另T041/T042，原可编辑来源允许逐项保存修复。\
  **依赖**：T037, T036\
  **配对测试**：T037\
  **验证 / 完成条件**：运行配对测试 T037；验证本卡预期，相关范围检查通过。

- [x] **T039 · 工作流删除/复制/导入绑定接线：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_bindings.py`（拟新增）\
  **逻辑 / 测试上下文**：删除一版本其他保持，删整flow全释放；复制导入非法目标零落盘，绑定故障全回滚。\
  **依赖**：T038\
  **覆盖 AC**: AC-68, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T040 · 工作流删除/复制/导入绑定接线**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：delete_version仅解除被删版本，整工作流删除解除全部；复制/导入调用同提取事务并拒绝新增已删目标，原不同版本互不误清。\
  **依赖**：T039, T038, T280, T291\
  **配对测试**：T039\
  **验证 / 完成条件**：运行配对测试 T039；验证本卡预期，相关范围检查通过。

- [x] **T041 · 工作流执行可见准入：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_entry.py`（拟新增）\
  **逻辑 / 测试上下文**：保存/preview/node facade对真实版本/完整graph与目标、原身份授权；saved召回保持原过滤，temporary须edit+实际知识visible，不造source。\
  **依赖**：T354, T344, T345\
  **覆盖 AC**: AC-37, AC-68, AC-79, AC-82, AC-83, AC-91\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T042 · 工作流执行可见准入**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/workflow/application/execution_admission.py`；`src/backend/bisheng/workflow/application/execution_port.py`\
  **逻辑 / 测试上下文**：集中saved/preview/node三个用例及bound Port，旧API/WS/open接线另T356/T358/T360，scope/原身份/渠道执行条件保持。\
  **依赖**：T041, T351, T381\
  **配对测试**：T041\
  **验证 / 完成条件**：运行配对测试 T041；验证本卡预期，相关范围检查通过。

- [x] **T043 · 助手引用提取及事务 DAO：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_extract.py`（拟新增）\
  **逻辑 / 测试上下文**：创建/替换模型、知识添加/解除形成真实 ID；DAO 故障回滚，不误把 model_name 当显示名。\
  **依赖**：T016, T258\
  **覆盖 AC**: AC-71, AC-87, AC-88\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T044 · 助手引用提取及事务 DAO**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/assistant/domain/services/reference_extractor.py`（拟新增）；`src/backend/bisheng/assistant/domain/repositories/assistant_repository.py`（拟新增）\
  **逻辑 / 测试上下文**：解析实际 model_name 标识及 AssistantLink.knowledge_id，稳定槽；新领域Repository统一root/三类links外部Session，无内部提前commit，旧DAO保持不变。\
  **依赖**：T043\
  **配对测试**：T043\
  **验证 / 完成条件**：运行配对测试 T043；验证本卡预期，相关范围检查通过。

- [x] **T045 · 助手创建修改删除与发布接线：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_bindings.py`（拟新增）\
  **逻辑 / 测试上下文**：创建不漏绑定，删除不残留；离线保持；双失效槽只修一个可保存仍不能发布（共用运行入口另T283）；已有知识权限/scopes 不扩大。\
  **依赖**：T044, T018, T026, T280\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T046 · 助手创建修改删除与发布接线**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/api/services/assistant.py`\
  **逻辑 / 测试上下文**：create/update/delete及同文件prompt/flow/tool/description/status实际写端同事务维护当前来源；复制导入拒绝新增已删目标；下线保留关系，发布失效报错；共用执行入口另T283，修改允许部分修复；原 use 准入改 visible。\
  **依赖**：T045, T280, T291\
  **配对测试**：T045\
  **验证 / 完成条件**：运行配对测试 T045；验证本卡预期，相关范围检查通过。

- [x] **T047 · 不可变应用版本插入同事务：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_snapshot.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：绑定错误版本行不落盘；历史管理预览版本保护；新版本只修新配置，旧绑定继续存在。\
  **依赖**：T439, T443, T512, T018, T258\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T048 · 不可变应用版本插入同事务**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/version_service.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：_insert_version 建立 app/version 引用集合并同事务提交；新版本/复制/导入应用新配置拒绝非法目标；历史保存版本均计引用，不按 terminal/current 过滤，不改写 AppVersion 内容。\
  **依赖**：T047\
  **配对测试**：T047\
  **验证 / 完成条件**：运行配对测试 T047；验证本卡预期，相关范围检查通过。

- [x] **T049 · 应用删除解除与历史预览失效：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_lifecycle.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：停止不解除，真正删除才解除；旧历史引用失效可见，预览失败不fallback，不因评测结果拦删除。\
  **依赖**：T048, T441\
  **覆盖 AC**: AC-71, AC-75, AC-88, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T050 · 应用删除解除与历史预览失效**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_runtime/domain/services/app_state_service.py`；`src/backend/bisheng/app_publish/domain/services/preview_instance_service.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：沿现有应用删除生命周期解除被真正删除来源；停止应用不解除。预览/重新启用保留不可变历史并检测失效；不新增历史编辑/退役。\
  **依赖**：T049, T540\
  **配对测试**：T049\
  **验证 / 完成条件**：运行配对测试 T049；验证本卡预期，相关范围检查通过。

- [x] **T051 · 应用能力执行可见准入：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_entry.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：仅可见主体可调用但超 capability/scope 拒绝；旧 manifest 不要求重新发布。\
  **依赖**：T050, T445, T026\
  **覆盖 AC**: AC-35, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T052 · 应用能力执行可见准入**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：应用入口原 use 改 visible，能力执行仍保持 OBO/SAK/PAT、声明范围、子项权限；历史旧知识类型运行兼容。\
  **依赖**：T051\
  **配对测试**：T051\
  **验证 / 完成条件**：运行配对测试 T051；验证本卡预期，相关范围检查通过。

- [x] **T053 · 频道配置来源维护：先写测试**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_bindings.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：暂停依然有引用；删除同步目标/解散才解除；原调用自动清目标不得破坏失效槽，部分修复可保存。\
  **依赖**：T018, T026, T258, T453, T518\
  **覆盖 AC**: AC-71, AC-87, AC-88, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T054 · 频道配置来源维护**
  **类型 / Owner**：后端 Domain / CH\
  **写入文件**：`src/backend/bisheng/channel/domain/services/channel_service.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：_save/_load_knowledge_sync/dismiss_channel 同事务绑定，使用稳定频道配置来源键不依赖重建 sync 行 ID；关闭保留，解除/解散移除；强删不自动清配置。\
  **依赖**：T053\
  **配对测试**：T053\
  **验证 / 完成条件**：运行配对测试 T053；验证本卡预期，相关范围检查通过。

- [x] **T055 · 租户/Root 默认槽位绑定：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_defaults.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：五类业务默认全部覆盖；共享模型跨租户有真实原始来源，替换只改本槽；绑定失败不保存默认。\
  **依赖**：T018, T258, T467\
  **覆盖 AC**: AC-71, AC-74, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T056 · 租户/Root 默认槽位绑定**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default.py`；`src/backend/bisheng/llm/domain/services/llm.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：覆盖 knowledge/assistant/workflow/evaluation/workbench 默认保存，原始 Root 槽位及租户 override 同事务；继承消费者不复制绑定，不把评测任务当来源。暂不接删除服务逻辑。\
  **依赖**：T055\
  **配对测试**：T055\
  **验证 / 完成条件**：运行配对测试 T055；验证本卡预期，相关范围检查通过。

- [x] **T057 · 恢复默认继承入口：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_inherit.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：恢复继承不删 Root/其他租户默认；默认与绑定故障同回滚。\
  **依赖**：T056\
  **覆盖 AC**: AC-71, AC-87, AC-88\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T058 · 恢复默认继承入口**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default.py`；`src/backend/bisheng/llm/api/router.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：恢复继承经 LLM 应用服务只解除该租户 override，恢复有效默认解析；Endpoint 不查 ORM/不单独写引用，事务由服务持有。\
  **依赖**：T057\
  **配对测试**：T057\
  **验证 / 完成条件**：运行配对测试 T057；验证本卡预期，相关范围检查通过。

- [x] **T059 · 默认配置 Repository 与优先级：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_settings_repo.py`（拟新增）\
  **逻辑 / 测试上下文**：文档与表格范围校验，overlap>size/headerstart>end 拒绝；旧空间无默认按系统回退；实际处理快照不被改默认覆盖。\
  **依赖**：T007, T009, T012\
  **覆盖 AC**: AC-38, AC-39, AC-40, AC-42, AC-43, AC-44\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T060 · 默认配置 Repository 与优先级**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/processing_settings_repository.py`（拟新增）；`src/backend/bisheng/knowledge/domain/services/processing_settings_service.py`（拟新增）\
  **逻辑 / 测试上下文**：普通文档和表格分别保存 schema/version；batch/file 显式 > space > system，专用网页/音视频既有规则优先；不将上传临时值反存空间；改默认不重处理历史。\
  **依赖**：T059\
  **配对测试**：T059\
  **验证 / 完成条件**：运行配对测试 T059；验证本卡预期，相关范围检查通过。

- [x] **T061 · 任务与子项存储：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_repo.py`（拟新增）\
  **逻辑 / 测试上下文**：重复提交同任务不重建文件/版本，部分失败只领取失败项；相关配置变更新步骤拒绝，恢复旧模型也需新重建。\
  **依赖**：T008, T060, T245, T246\
  **覆盖 AC**: AC-49, AC-50, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T062 · 任务与子项存储**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`（拟新增）\
  **逻辑 / 测试上下文**：按幂等键创建/查询/领取/失败项恢复及 checkpoints，相关业务/索引 revision 决定 obsolete，name/description 不影响；区分 partial/failed/completed，进度源于真实 items。\
  **依赖**：T061\
  **配对测试**：T061\
  **验证 / 完成条件**：运行配对测试 T061；验证本卡预期，相关范围检查通过。

- [x] **T063 · 任务接收与恢复应用用例：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_service.py`（拟新增）\
  **逻辑 / 测试上下文**：提交不报完成；故障可恢复且不重复；无合法配置/已删模型明确失败，不回退历史参数。\
  **范围限制**：仅知识处理任务，复用现有 Celery/Beat；不建设全平台任务系统或 worker 在途 I/O 一致性机制。\
  **依赖**：T062, T026, T243, T244, T609, T611, T613, T621, T625\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T064 · 任务接收与恢复应用用例**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/processing_job_service.py`（拟新增）\
  **逻辑 / 测试上下文**：accepted 后通过既有投递模式可恢复派发，不创建任务模型引用；任务详情按最新文件可见性裁剪，隐藏内容只数状态；模型从所属当前业务读，校验相关 revision/generation。\
  **范围限制**：仅知识处理任务，复用现有 Celery/Beat；不建设全平台任务系统或 worker 在途 I/O 一致性机制。\
  **依赖**：T063\
  **配对测试**：T063\
  **验证 / 完成条件**：运行配对测试 T063；验证本卡预期，相关范围检查通过。

- [x] **T065 · 重建全量分页保留源分段：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_rebuild_page.py`（拟新增）；`src/backend/test/knowledge_unification/test_kn_worker_model_source.py`\
  **逻辑 / 测试上下文**：10001+ Chunk 数量及内容一致，失败源仍在；另一空间不阻塞；tenant headers 缺失拒绝，重试只失败项且配置过期拒绝。\
  **依赖**：T064\
  **覆盖 AC**: AC-48, AC-49, AC-52, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T066 · 重建全量分页保留源分段**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/rebuild_knowledge_worker.py`\
  **逻辑 / 测试上下文**：复用现有 Chunk/metadata，分页超过 10000；失败保留 ES 重试源、只切成功文件检索，不重切分/丢人工修改。tenant_id 从 Celery headers 注入 ContextVar，使用业务模型配置。\
  **依赖**：T065, T658\
  **配对测试**：T065\
  **验证 / 完成条件**：运行配对测试 T065；验证本卡预期，相关范围检查通过。

- [x] **T067 · 文件处理实际快照与恢复：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_worker.py`（拟新增）\
  **逻辑 / 测试上下文**：指定版本重处理只改其内容；异常结果真实，重投不重复版本；陈旧任务新步骤拒绝，无配置不能用历史模型。\
  **依赖**：T066, T070\
  **覆盖 AC**: AC-10, AC-43, AC-44, AC-45, AC-49, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T068 · 文件处理实际快照与恢复**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/file_worker.py`；`src/backend/bisheng/knowledge/rag/knowledge_file_pipeline.py`\
  **逻辑 / 测试上下文**：接入 J1 分类型实际配置/文件版本快照与任务项结果；领取及可控步骤重验相关模型/索引，SQL finalize 核 generation/lease；不加外部在途 I/O 围栏。tenant_id headers→ContextVar，不存 bearer。\
  **依赖**：T067\
  **配对测试**：T067\
  **验证 / 完成条件**：运行配对测试 T067；验证本卡预期，相关范围检查通过。

- [x] **T069 · 旧 FileProcessBase 与专用规则适配：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_process_adapter.py`（拟新增）\
  **逻辑 / 测试上下文**：旧文档/表格/网页/音视频请求回归，优先级与类型参数不串用。\
  **依赖**：T060, T605\
  **覆盖 AC**: AC-39, AC-40, AC-43, AC-44, AC-66\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T070 · 旧 FileProcessBase 与专用规则适配**
  **类型 / Owner**：后端 API / PROC\
  **写入文件**：`src/backend/bisheng/api/v1/schemas.py`；`src/backend/bisheng/knowledge/application/file_processing_adapter.py`\
  **逻辑 / 测试上下文**：保持旧上传请求与 FileProcessBase 字段兼容，将实际显式值传 J1 解析，不新增不支持参数；不把单次配置污染默认，提交语义不报 completed。\
  **依赖**：T069\
  **配对测试**：T069\
  **验证 / 完成条件**：运行配对测试 T069；验证本卡预期，相关范围检查通过。

- [x] **T071 · 元数据结构任务：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_job.py`（拟新增）\
  **逻辑 / 测试上下文**：新增空值、取消零改动；rename/drop 错误不报成功，指定 version 值更新结果正确且不可见详情裁剪。\
  **依赖**：T064\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T072 · 元数据结构任务**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/metadata_processing_service.py`（拟新增）\
  **逻辑 / 测试上下文**：新增字段历史为空，rename/drop 冻结前后 schema 与范围且二次确认，SQL/索引实际结果计 item，不用 accepted 冒充完成；仍原容器 edit，失败可恢复。\
  **依赖**：T071, T740, T742, T748\
  **配对测试**：T071\
  **验证 / 完成条件**：运行配对测试 T071；验证本卡预期，相关范围检查通过。

- [ ] **T073 · 移动索引迁移步骤幂等：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_worker.py`（拟新增）\
  **逻辑 / 测试上下文**：重投不重复 Chunk/版本；跨对象引用路径可用、源空间删除不破坏目标；失败项恢复和过期拒绝。\
  **依赖**：T064\
  **覆盖 AC**: AC-19, AC-20, AC-23, AC-24, AC-49, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T074 · 移动索引迁移步骤幂等**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/move_worker.py`\
  **逻辑 / 测试上下文**：接收 KN 已确认归属/整版本计划，按 item/checkpoint 目标幂等写及源清理；旧空间残留检索不返回，失败保留资源与已确认归属。tenant_id headers→ContextVar。\
  **依赖**：T073\
  **配对测试**：T073\
  **验证 / 完成条件**：运行配对测试 T073；验证本卡预期，相关范围检查通过。

- [ ] **T075 · 投递恢复与任务派发：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_worker_dispatch.py`（拟新增）\
  **逻辑 / 测试上下文**：停派发保留队列、恢复校验后启动；重复调度只领一次，tenant不串任务，已删业务不得执行。\
  **依赖**：T070, T072, T074\
  **覆盖 AC**: AC-49, AC-54, AC-85, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T076 · 投递恢复与任务派发**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/scheduler.py`\
  **逻辑 / 测试上下文**：复用现有 Celery/Beat 机制投递/恢复 job/items，带 tenant_id headers、actor 标识和幂等键，不传 bearer、不把排队参数作为模型绑定；无合法业务配置则失败。\
  **依赖**：T075\
  **配对测试**：T075\
  **验证 / 完成条件**：运行配对测试 T075；验证本卡预期，相关范围检查通过。

- [x] **T077 · 资源访问生命周期与动作映射：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_auth.py`（拟新增）\
  **逻辑 / 测试上下文**：继承/自定义同有效动作；only rename 能重命名而不能容器 edit；重建可下载目录，写入和检索暂停；未发布可合法处理。\
  **依赖**：T026, T605\
  **覆盖 AC**: AC-08, AC-30, AC-31, AC-32, AC-33, AC-51, AC-60\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T078 · 资源访问生命周期与动作映射**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_permission_service.py`\
  **逻辑 / 测试上下文**：将处理态与可访问生命周期分离；重建仍目录/预览/下载，写入冲突单独控制；有效权限统一解析继承/自定义，rename 原动作，Chunk/metadata原容器 edit，原文件 retry 原rename，不加文件 edit/额外可见 gate。\
  **依赖**：T077\
  **配对测试**：T077\
  **验证 / 完成条件**：运行配对测试 T077；验证本卡预期，相关范围检查通过。

- [x] **T079 · 统一空间创建：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_creation.py`（拟新增）\
  **逻辑 / 测试上下文**：两端默认相同，后台显式配置生效；无权模型及绑定失败不创建残留空间。\
  **依赖**：T078, T018, T060, T258\
  **覆盖 AC**: AC-06, AC-07, AC-14, AC-15, AC-87\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T080 · 统一空间创建**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：前台只简化业务项沿当前默认，后台可信入口可选模型和分类型默认；同R2保存模型槽，审批/安全/格式/配额沿已有用例。\
  **依赖**：T079\
  **配对测试**：T079\
  **验证 / 完成条件**：运行配对测试 T079；验证本卡预期，相关范围检查通过。

- [x] **T081 · 管理员具体租户清单与操作上下文：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_create.py`（拟新增）\
  **逻辑 / 测试上下文**：菜单不等于资源权限；空tenant/汇总拒绝，直接请求普通/admin矩阵；管理业务校验不跳。\
  **依赖**：T080\
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-25, AC-84\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T082 · 管理员具体租户清单与操作上下文**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：admin仅超管/相应租管、一次具体tenant，超管默认所属可切，租管仅所属；普通列表不借admin扩大，owner/dept不准入。copy保创建者限制。\
  **依赖**：T081, T080\
  **配对测试**：T081\
  **验证 / 完成条件**：运行配对测试 T081；验证本卡预期，相关范围检查通过。

- [x] **T083 · 后台文件上传与整版本注册：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload.py`（拟新增）\
  **逻辑 / 测试上下文**：同文件前后端版本路径一致，保留历史；失败不留孤立版本或半链，解析期unsupported/内容安全失败保原失败File及完整版本链；相似文档按现有开关选择保留/新版本。\
  **依赖**：T082, T882, T884\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-11, AC-14, AC-43\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T084 · 后台文件上传与整版本注册**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：后台调用同目录/文件夹/网页/新版本用例，沿既有审批、内容安全、格式/大小/深度/重名/配额与开关；统一 document/version 关系，只有成功主版本检索；effective快照共用原SSOT，初始上传保原scheduler，不套空间edit的J1重处理。\
  **依赖**：T083, T082\
  **配对测试**：T083\
  **验证 / 完成条件**：运行配对测试 T083；验证本卡预期，相关范围检查通过。

- [ ] **T085 · 批量预检确认与逐项结果：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_batch.py`（拟新增）\
  **逻辑 / 测试上下文**：混合无权/处理中/unsupported/引用受阻全部列明；取消零修改，确认仅有效项；新引用变化重新确认。\
  **依赖**：T084\
  **覆盖 AC**: AC-12, AC-13, AC-31, AC-94\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T086 · 批量预检确认与逐项结果**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：删除/下载/标签/retry 逐项权限和状态预检，服务端计划绑定范围/修订，确认才跳过失败项执行；取消零写；最终再次重验。沿原 retry/tags/encoding 动作，不扩文件edit。\
  **依赖**：T085, T084\
  **配对测试**：T085\
  **验证 / 完成条件**：运行配对测试 T085；验证本卡预期，相关范围检查通过。

- [ ] **T087 · 移动预检与确认计划：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_move_preflight.py`（拟新增）\
  **逻辑 / 测试上下文**：违规目标拒绝；取消无资源变化；版本/字段/权限影响摘要变更重新确认。\
  **依赖**：T086, T074, T016\
  **覆盖 AC**: AC-17, AC-18, AC-21, AC-22\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T088 · 移动预检与确认计划**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：仅构建服务端不可变plan：源move/目标upload、同租户/自身子目录/深度/重名，整版本范围与metadata同名同类型保留/清除字段明细、标签不带入、继承变更/自定义保留；取消零写。\
  **依赖**：T087, T086\
  **配对测试**：T087\
  **验证 / 完成条件**：运行配对测试 T087；验证本卡预期，相关范围检查通过。

- [ ] **T089 · 移动归属与权限阶段提交：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_move_finalize.py`（拟新增）\
  **逻辑 / 测试上下文**：投影失败归属不先提交；成功后SQL失败同plan恢复；自定义不被父级覆盖，确认变化拒绝。\
  **依赖**：T088\
  **覆盖 AC**: AC-17, AC-18, AC-22, AC-24\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T090 · 移动归属与权限阶段提交**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：按已确认durable plan锁后重验，完成F048父级/继承投影后SQL归属finalize，自定义及各子项模式保留；phase失败原plan恢复，不重复移动。\
  **依赖**：T089, T088\
  **配对测试**：T089\
  **验证 / 完成条件**：运行配对测试 T089；验证本卡预期，相关范围检查通过。

- [ ] **T091 · 整版本对象引用与检索任务接线：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_move.py`（拟新增）\
  **逻辑 / 测试上下文**：全部历史版本/metadata映射一致，源删后图片附件仍可访问；归属绑定不漂移，旧空间残留结果不返回，重试无重复版本。\
  **依赖**：T090\
  **覆盖 AC**: AC-19, AC-20, AC-21, AC-23, AC-24, AC-87, AC-88\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T092 · 整版本对象引用与检索任务接线**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：基于finalize已确认归属计划迁整版本，原始/附件路径不依赖源存活；直接文件target_space_id同事务更新，委托PROC索引迁移。失败保文件版本与归属，重试原job。\
  **依赖**：T091, T090\
  **配对测试**：T091\
  **验证 / 完成条件**：运行配对测试 T091；验证本卡预期，相关范围检查通过。

- [ ] **T093 · QA 创建删除清空的模型槽位：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_qa_bindings.py`；`src/backend/test/knowledge/test_v2_filelib_unified.py`\
  **逻辑 / 测试上下文**：同步/异步创建QA都有零集或真实模型绑定，失败整事务回滚；clear不解除模型、delete才解除；不把QA转换SPACE。\
  **范围限制**：QA 仅复用原创建/清空/删除/模型变更及重建入口维护引用，不合并 QA，不新增空间高级处理框架或页面。\
  **依赖**：T018, T258, T052\
  **覆盖 AC**: AC-55, AC-65, AC-70, AC-71, AC-74, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T094 · QA 创建删除清空的模型槽位**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`（原Service接线已交付，仅根因叶恢复QA条件）\
  **逻辑 / 测试上下文**：QA type1保持独立入口与原业务；create_knowledge/create_knowledge_base/acreate_knowledge_base和delete_knowledge使用R2维护当前模型槽，删除QA解除出向模型绑定，clear保留；模型修改复用原 QA 变更/重建路径，引用随原业务槽位更新。\
  **范围限制**：QA 仅复用原创建/清空/删除/模型变更及重建入口维护引用，不合并 QA，不新增空间高级处理框架或页面。\
  **依赖**：T093\
  **配对测试**：T093\
  **验证 / 完成条件**：运行配对测试 T093；验证本卡预期，相关范围检查通过。

- [ ] **T095 · 整空间独立复制：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_copy.py`（拟新增）\
  **逻辑 / 测试上下文**：管理员非创建者拒绝；源/副本ID索引状态独立；副本owner正确，授权范围提示，损坏副本不影响源。\
  **依赖**：T092, T018\
  **覆盖 AC**: AC-25, AC-26, AC-27, AC-84, AC-87\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T096 · 整空间独立复制**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：仅源创建者，目录/全部版本/标签/metadata/解析配置生成独立资源/索引/任务，copy本身模型槽同事务绑定；按现行规范新owner/普通授权，不照搬受保护创建者。默认不发布、不复制订阅/置顶/聊天。\
  **依赖**：T095, T094\
  **配对测试**：T095\
  **验证 / 完成条件**：运行配对测试 T095；验证本卡预期，相关范围检查通过。

- [ ] **T097 · 统一模型重建与高级处理委托：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_processing_wire.py`（拟新增）\
  **逻辑 / 测试上下文**：SPACE 不走仅 NORMAL/QA 旧分支；重建保人工分段，old model有效引用切换前阻普通删除；目录可读、冲突写拒绝，过期任务不可恢复。\
  **依赖**：T096, T076, T072\
  **覆盖 AC**: AC-33, AC-34, AC-44, AC-45, AC-48, AC-49, AC-51, AC-52, AC-53, AC-54, AC-74, AC-86, AC-87\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T098 · 统一模型重建与高级处理委托**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：旧 update_knowledge 与新空间命令委托 PROC；模型变更先可用/确认，当前及 staged 模型槽同事务绑定；清空保留模型槽，切换完成才释放旧槽。冲突矩阵阻同空间上传/新版本/Chunk/metadata/移入出，不阻其他空间。\
  **依赖**：T097, T092, T096\
  **配对测试**：T097\
  **验证 / 完成条件**：运行配对测试 T097；验证本卡预期，相关范围检查通过。

- [ ] **T099 · Chunk/文件元数据原权限与指定版本：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_chunk.py`（拟新增）\
  **逻辑 / 测试上下文**：有文件 rename无容器edit不能Chunk修改；原容器edit有效无需额外文件edit；历史版本定位正确、原对象不变、索引失败可见。\
  **依赖**：T098\
  **覆盖 AC**: AC-31, AC-33, AC-45, AC-46, AC-47\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T100 · Chunk/文件元数据原权限与指定版本**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_file_service.py`\
  **逻辑 / 测试上下文**：Chunk edit/delete 与 modify_file_user_metadata 仍所属容器 edit；只改指定版本索引内容不改原文件，重切分覆盖人工调整先确认；返回实际索引成功/失败。\
  **依赖**：T099, T098\
  **配对测试**：T099\
  **验证 / 完成条件**：运行配对测试 T099；验证本卡预期，相关范围检查通过。

- [ ] **T101 · 统一检索可见性与成功主版本：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_retrieval.py`（拟新增）\
  **逻辑 / 测试上下文**：仅可见无use可选可检索；独立子项不扩可见面；旧ID同授权，sameidentity/config/question 对账，use预期增量单列。\
  **依赖**：T100, T026\
  **覆盖 AC**: AC-08, AC-30, AC-35, AC-36, AC-37, AC-60, AC-67, AC-79, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T102 · 统一检索可见性与成功主版本**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/retrieval_facade_service.py`\
  **逻辑 / 测试上下文**：空间/library/QA 原 use gate改visible，旧类型映射到真实资源；保原actor、token、capability白名单、tenant及文件过滤；只成功主版本，无旧归属/失败项/重建空间结果。\
  **依赖**：T101\
  **配对测试**：T101\
  **验证 / 完成条件**：运行配对测试 T101；验证本卡预期，相关范围检查通过。

- [ ] **T103 · 知识目标检查与引用展示：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_refs.py`（拟新增）\
  **逻辑 / 测试上下文**：绑定整个空间不阻普通文件删除；无权来源只类型数量；coverage未就绪/查失败一律拒绝，不全库扫描业务JSON。\
  **依赖**：T102, T042, T046, T052, T054, T058, T258\
  **覆盖 AC**: AC-28, AC-29, AC-72, AC-89, AC-90, AC-91, AC-94\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T104 · 知识目标检查与引用展示**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_reference_service.py`（拟新增）\
  **逻辑 / 测试上下文**：知识 Owner 校验空间/真实文件版本与归属；按绑定索引查依赖并经来源应用接口批量补名称入口、按权限裁剪；whole-space/delete/clear覆盖空间及直接内容，文件删除仅实际直接范围。\
  **依赖**：T103\
  **配对测试**：T103\
  **验证 / 完成条件**：运行配对测试 T103；验证本卡预期，相关范围检查通过。

- [ ] **T105 · 文件夹精确 manifest 与持久删除计划：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_delete_plan.py`（拟新增）\
  **逻辑 / 测试上下文**：无关版本不误拦；夹内一项引用整夹零修改；force参数拒绝，最终新引用阻断/重新确认，操作幂等。\
  **依赖**：T104, T086\
  **覆盖 AC**: AC-12, AC-13, AC-28, AC-29, AC-94\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T106 · 文件夹精确 manifest 与持久删除计划**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/knowledge_space_delete_repository.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_direct_delete_service.py`\
  **逻辑 / 测试上下文**：复用空间 durable删除框架冻结实际文件/夹及版本范围、锁后引用复查；整夹任一直接引用则整项拒绝；混合批确认跳过，文件/夹拒绝force。先写计划/围栏，不业务删除。\
  **依赖**：T105\
  **配对测试**：T105\
  **验证 / 完成条件**：运行配对测试 T105；验证本卡预期，相关范围检查通过。

- [ ] **T107 · 文件投影在先、SQL finalize 在后：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_delete_order.py`（拟新增）\
  **逻辑 / 测试上下文**：投影失败业务行仍在且围栏阻新写；FGA成功SQL失败原计划恢复；SQL成功清理失败只重试清理，不误报完全成功。\
  **依赖**：T106\
  **覆盖 AC**: AC-29, AC-94\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T108 · 文件投影在先、SQL finalize 在后**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_direct_delete_service.py`\
  **逻辑 / 测试上下文**：按计划完成所有 F048 projection 后才业务SQL finalize及相关出向绑定清理，随后 MinIO/ES/Milvus purge；投影不放到 purge。断点记录 phase，重试同计划，不重复版本/删除。\
  **依赖**：T107, T106\
  **配对测试**：T107\
  **验证 / 完成条件**：运行配对测试 T107；验证本卡预期，相关范围检查通过。

- [ ] **T109 · 空间普通/强删/清空与 tombstone：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_space_delete.py`（拟新增）\
  **逻辑 / 测试上下文**：取消零改动；强删影响变化重确认、隐藏来源不泄露；空间直接文件随之失效；清空保模型关系、删除才解除；异常覆盖未就绪禁止force。\
  **依赖**：T108\
  **覆盖 AC**: AC-28, AC-29, AC-74, AC-84, AC-87, AC-88, AC-90, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T110 · 空间普通/强删/清空与 tombstone**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：普通删/清空阻空间+内容有效引用；clear无force保空间模型槽；spaceforce二次确认当前影响、保来源原ID/绑定与tombstone，真实删除释放自身出向模型绑定。遵现有FGA→SQL→purge、权限/状态冲突不跳。\
  **依赖**：T109, T098\
  **配对测试**：T109\
  **验证 / 完成条件**：运行配对测试 T109；验证本卡预期，相关范围检查通过。

- [ ] **T111 · 模型目标锁与跨租户影响：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_refs.py`（拟新增）\
  **逻辑 / 测试上下文**：五类模型及共享两租户依赖均计数；仅历史聊天审计不阻；检查失败与未ready不能当无引用，不能泄露名称。\
  **依赖**：T058, T652, T654\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T112 · 模型目标锁与跨租户影响**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/model_reference_service.py`（拟新增）\
  **逻辑 / 测试上下文**：按 R3 查单模型/删除清单/整服务所有模型，受信共享目标跨租户反查；现有管理员/tenant/共享只读保持，按权限展示；锁序与 R2相同，异常fail closed。\
  **依赖**：T111\
  **配对测试**：T111\
  **验证 / 完成条件**：运行配对测试 T111；验证本卡预期，相关范围检查通过。

- [ ] **T113 · 模型删除/清单差集计划：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_delete_plan.py`（拟新增）\
  **逻辑 / 测试上下文**：三入口目标全集正确；未ready/检查异常失败无业务写，受限来源只摘要；plan绑定当前操作者/目标/revision。\
  **依赖**：T112, T110\
  **覆盖 AC**: AC-70, AC-72, AC-73, AC-76, AC-77\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T114 · 模型删除/清单差集计划**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/llm.py`\
  **逻辑 / 测试上下文**：单删/编辑清单/服务整删统一算removed目标全集及影响摘要；服务其它共享/清单字段暂不保存，检查准入/tenant/shared readonly和覆盖，生成R3确认plan。\
  **依赖**：T113, T056\
  **配对测试**：T113\
  **验证 / 完成条件**：运行配对测试 T113；验证本卡预期，相关范围检查通过。

- [ ] **T115 · 模型普通删除原子事务：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_delete_normal.py`（拟新增）\
  **逻辑 / 测试上下文**：整服务任一模型受阻零修改；并发新引用与删除同锁序不漏，历史任务不阻，默认/空间旧模型槽仍生效则阻。\
  **依赖**：T114\
  **覆盖 AC**: AC-70, AC-73, AC-74, AC-76, AC-77\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T116 · 模型普通删除原子事务**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/llm.py`\
  **逻辑 / 测试上下文**：持计划锁后重验引用，普通存在有效关系整次拒绝；无引用才一次提交服务/模型差集，不能先保存共享字段。任务无独立绑定不阻断，幂等重复稳定。\
  **依赖**：T115, T114\
  **配对测试**：T115\
  **验证 / 完成条件**：运行配对测试 T115；验证本卡预期，相关范围检查通过。

- [ ] **T117 · 模型强删确认与 tombstone：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_delete.py`（拟新增）\
  **逻辑 / 测试上下文**：确认影响变化重新确认，检查异常/readonly拒绝force，重复force不误报；下游保失效槽并允许原来源逐项修复。\
  **依赖**：T116\
  **覆盖 AC**: AC-72, AC-73, AC-76, AC-77, AC-90, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T118 · 模型强删确认与 tombstone**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/llm.py`\
  **逻辑 / 测试上下文**：显式force重验目标/操作者/影响plan及最新引用；仅越过已知引用阻断，保持所有其它业务限制，持久tombstone保来源原ID/绑定，不自动清槽或切模型。\
  **依赖**：T117, T116\
  **配对测试**：T117\
  **验证 / 完成条件**：运行配对测试 T117；验证本卡预期，相关范围检查通过。

- [ ] **T119 · 模型影响预检与删除入口：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_api.py`（拟新增）\
  **逻辑 / 测试上下文**：旧调用不携force仍普通；伪plan/他人plan/变化plan拒绝，重复请求结果稳定，scope/shared readonly保留。\
  **依赖**：T118\
  **覆盖 AC**: AC-70, AC-72, AC-73, AC-76, AC-77, AC-90\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T120 · 模型影响预检与删除入口**
  **类型 / Owner**：后端 API / LLM\
  **写入文件**：`src/backend/bisheng/llm/api/router.py`\
  **逻辑 / 测试上下文**：Endpoint 只委托service，默认普通delete，显式force+服务端plan/digest；新旧批量入口同规则，错误不报成功；DTO保留失效及受限摘要。\
  **依赖**：T119, T058\
  **配对测试**：T119\
  **验证 / 完成条件**：运行配对测试 T119；验证本卡预期，相关范围检查通过。

- [ ] **T121 · 空间列表/管理/创建与详情 API：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_api_space.py`（拟新增）\
  **逻辑 / 测试上下文**：路由动态冲突检查；普通参数不能切admin；role/tenant矩阵及直链越权；前后台同ID/内容/授权。\
  **依赖**：T110, T120\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-14, AC-15, AC-32, AC-84\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T122 · 空间列表/管理/创建与详情 API**
  **类型 / Owner**：后端 API / KN\
  **写入文件**：`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`\
  **逻辑 / 测试上下文**：按 A1接普通与admin独立清单、具体租户详情/操作上下文，后台模型/默认配置入口委托已有usecase；管理员copy不豁免，DTO含真实能力/处理态、无权不泄名称。\
  **依赖**：T121\
  **配对测试**：T121\
  **验证 / 完成条件**：运行配对测试 T121；验证本卡预期，相关范围检查通过。

- [ ] **T123 · 处理设置及任务查询/重试 API：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_api_jobs.py`（拟新增）\
  **逻辑 / 测试上下文**：settings参数错误不保存；菜单/凭证/资源组合矩阵；不同身份缓存不复用明细；retry原任务/obsolete状态正确。\
  **依赖**：T122, T064\
  **覆盖 AC**: AC-33, AC-34, AC-35, AC-38, AC-42, AC-45, AC-48, AC-49, AC-50, AC-54\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T124 · 处理设置及任务查询/重试 API**
  **类型 / Owner**：后端 API / KN\
  **写入文件**：`src/backend/bisheng/knowledge/api/endpoints/knowledge_processing.py`（拟新增）\
  **逻辑 / 测试上下文**：按冻结 A1/J1 新增 settings、rebuild/reprocess、jobs/detail/retry端点；网页高级保原菜单资格和容器edit，开放不要求网页菜单；任务详情当前身份裁剪，accepted不报完成。\
  **依赖**：T123\
  **配对测试**：T123\
  **验证 / 完成条件**：运行配对测试 T123；验证本卡预期，相关范围检查通过。

- [ ] **T125 · 旧文档合同兼容适配：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_api_legacy.py`（拟新增）\
  **逻辑 / 测试上下文**：旧消费者请求快照与返回结构对照，新旧ID同实体/授权；删除不能绕过引用/force/状态，QA行为保留。\
  **依赖**：T124\
  **覆盖 AC**: AC-10, AC-55, AC-65, AC-66, AC-67, AC-68, AC-69\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T126 · 旧文档合同兼容适配**
  **类型 / Owner**：后端 API / KN\
  **写入文件**：`src/backend/bisheng/knowledge/api/endpoints/knowledge.py`；`src/backend/bisheng/knowledge/api/endpoints/knowledge_version.py`\
  **逻辑 / 测试上下文**：type0请求实建SPACE，旧列表/详情/创建/上传/复制/删除按旧返回type/envelope/分页，内部同授权删除和任务；QA1保留，type2不复活。新API type3，3.x不提前退出。\
  **依赖**：T125\
  **配对测试**：T125\
  **验证 / 完成条件**：运行配对测试 T125；验证本卡预期，相关范围检查通过。

- [x] **T127 · 工具/Skill 使用准入切换：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_tool.py`（拟新增）；`src/backend/test/tool/test_f048_tool_permissions.py`\
  **逻辑 / 测试上下文**：工具preset/custom及Skill原可见鉴权无use可调用，无可见/无scope仍拒绝，活动动作响应无use；Skill的enabled使用/管理分离由T145/T146独立回归，本组联合验收等待它们。\
  **依赖**：T026\
  **覆盖 AC**: AC-78, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T128 · 工具/Skill 使用准入切换**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/tool/domain/services/f048_tool_permission.py`\
  **逻辑 / 测试上下文**：工具preset/custom原独立use检查改visible；生产Skill接缝在T146，未接线旧f048_skill_permission不改，保tenant/身份/scope/可执行状态，不给额外动作；调用现有统一 PermissionService，历史保存协议只兼容解释。\
  **依赖**：T127\
  **配对测试**：T127\
  **验证 / 完成条件**：运行配对测试 T127；验证本卡预期，相关范围检查通过。

- [ ] **T129 · 工作台/工作流知识节点兼容：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_workstation.py`（拟新增）\
  **逻辑 / 测试上下文**：历史节点无需重新发布；sameactor检索只成功可见主版本；失效不忽略不fallback。\
  **依赖**：T102, T042, T128\
  **覆盖 AC**: AC-35, AC-37, AC-68, AC-79, AC-82, AC-83, AC-91\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T130 · 工作台/工作流知识节点兼容**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/workstation/domain/services/workstation_service.py`；`src/backend/bisheng/workflow/nodes/knowledge_retriever/knowledge_retriever.py`\
  **逻辑 / 测试上下文**：旧knowledge type/ID和原use表达委托统一解析/检索，不重写历史节点；保workbench/tenant凭证与文件可见性，失效明确报错。\
  **依赖**：T129\
  **配对测试**：T129\
  **验证 / 完成条件**：运行配对测试 T129；验证本卡预期，相关范围检查通过。

- [ ] **T131 · 开放 v2 filelib/knowledge API 合同：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_rpc.py`（拟新增）\
  **逻辑 / 测试上下文**：SAK/PAT/OBO有效/缺scope/跨tenant矩阵；旧filelib数据形状、QA独立和错误映射，引用保护两端一致。\
  **依赖**：T126, T130\
  **覆盖 AC**: AC-35, AC-66, AC-67, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T132 · 开放 v2 filelib/knowledge API 合同**
  **类型 / Owner**：后端 API / EDGE\
  **写入文件**：`src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`；`src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py`\
  **逻辑 / 测试上下文**：开放接口保原请求/返回及身份范围，经统一业务服务；不要求后台菜单，不旁路删除保护/文件动作；旧type解释兼容。\
  **依赖**：T131\
  **配对测试**：T131\
  **验证 / 完成条件**：运行配对测试 T131；验证本卡预期，相关范围检查通过。

- [ ] **T133 · SDK/MCP 协议端回归：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_sdk.py`（拟新增）\
  **逻辑 / 测试上下文**：真实协议入口旧ID/type/pagination/schema兼容；凭证白名单、子项权限和失效错误不被适配吞掉；整个3.x不下线。\
  **范围限制**：只核对本次旧知识 type/ID、use 字段、错误与身份范围；复用既有入口，不升级 SDK/MCP 协议或建设通用兼容层。\
  **依赖**：T132\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-69, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T134 · SDK/MCP 协议端回归**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/dev_toolkit/sdk_compat.py`；`src/backend/bisheng/open_mcp/compatibility.py`\
  **逻辑 / 测试上下文**：适配 SDK/MCP 旧 type/ID/固定 use 字段为统一空间/可见性语义，保持原请求响应与错误，旧发布不重写；调用统一业务服务，保身份白名单。T001清单逐入口核对，剩余叶子先拆补充任务，未闭合不能完成。\
  **范围限制**：只核对本次旧知识 type/ID、use 字段、错误与身份范围；复用既有入口，不升级 SDK/MCP 协议或建设通用兼容层。\
  **依赖**：T133\
  **配对测试**：T133\
  **验证 / 完成条件**：运行配对测试 T133；验证本卡预期，相关范围检查通过。

- [x] **T135 · 应用可见资格与能力 DTO：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_visibility.py`（拟新增）；`src/backend/test/app_runtime/test_f114_action_authorization.py`\
  **逻辑 / 测试上下文**：原使用资格可见无 use 可调用；发布仍须原发布动作/owner 等资格、生命周期及来源条件，可见但缺发布/分享资格仍拒绝；Source 变化复查，旧协议只解释不保存。\
  **依赖**：T052, T026\
  **覆盖 AC**: AC-78, AC-79, AC-81, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T136 · 应用可见资格与能力 DTO**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/app_publish_current_visibility_service.py`；`src/backend/bisheng/app_runtime/domain/schemas/app_authorization.py`\
  **逻辑 / 测试上下文**：仅来源及应用原 use 使用判断改 visible，活动能力 DTO 不形成独立 use；应用自身发布动作、owner/管理资格、分享动作、生命周期及 capability 范围保持原逻辑，不能把可见当发布或分享许可；保 Source 一致性。\
  **依赖**：T135, T599\
  **配对测试**：T135\
  **验证 / 完成条件**：运行配对测试 T135；验证本卡预期，相关范围检查通过。

- [x] **T137 · 助手 HTTP 动作默认与选择器：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_http.py`（拟新增）\
  **逻辑 / 测试上下文**：旧query默认/显式use按visible；失效助手失败，隐藏知识不暴露；无菜单机器凭证按原scope。\
  **依赖**：T046, T295\
  **覆盖 AC**: AC-37, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T138 · 助手 HTTP 动作默认与选择器**
  **类型 / Owner**：后端 API / AS\
  **写入文件**：`src/backend/bisheng/api/v1/assistant.py`\
  **逻辑 / 测试上下文**：列表/运行旧默认use解释visible，当前输出action不含use；委托AS统一服务，保scope/tenant/执行状态，不重写历史配置。\
  **依赖**：T137\
  **配对测试**：T137\
  **验证 / 完成条件**：运行配对测试 T137；验证本卡预期，相关范围检查通过。

- [x] **T139 · 应用模型执行逐槽核对冻结ID：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_model_binding.py`（拟新增）\
  **逻辑 / 测试上下文**：W6§45：保已有真实同名ID/server漂移等回归，补实际preview principal→gateway和真实删除Model→零provider两例；原主体/route/SQL来源完整，不改SDK或生产以凑断言。\
  **依赖**：T136, T447\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-91\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T140 · 应用模型执行逐槽核对冻结ID**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/open_api/domain/services/model_range_policy.py`；`src/backend/bisheng/open_api/domain/services/model_gateway_service.py`\
  **逻辑 / 测试上下文**：消费 APP 版本SourceKey及冻结slot目标映射，保原名称协议但最终实际ID必须匹配该版本绑定；改名/同名解析漂移明确失败，不转用新模型。预览/运行共检查，历史manifest原文不改。\
  **依赖**：T139\
  **配对测试**：T139\
  **验证 / 完成条件**：运行配对测试 T139；验证本卡预期，相关范围检查通过。

- [x] **T141 · 聊天准入与管理器：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_chat.py`（拟新增）\
  **逻辑 / 测试上下文**：W6§47实际online HTTP默认/legacy use规范化与两sort分支；Manager原execution.operator、fresh消息准入和visible gate，旧tenant重验保持；不写历史/引用。\
  **依赖**：T026, T136, T383\
  **覆盖 AC**: AC-35, AC-79, AC-82, AC-83, AC-91\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T142 · 聊天准入与管理器**
  **类型 / Owner**：后端 API / EDGE\
  **写入文件**：`src/backend/bisheng/api/v1/chat.py`；`src/backend/bisheng/common/chat/manager.py`\
  **逻辑 / 测试上下文**：原使用准入显式改visible并保持原actor/tenant/凭证、资源业务状态；失效配置明确错误，不能以兼容为由静默fallback。\
  **依赖**：T141\
  **配对测试**：T141\
  **验证 / 完成条件**：运行配对测试 T141；验证本卡预期，相关范围检查通过。

- [x] **T143 · 工具枚举与实际执行：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_tool_call.py`（拟新增）；`src/backend/test/tool/test_tool_executor_permissions.py`\
  **逻辑 / 测试上下文**：列出与执行相同准入；可见无use可执行，disabled和无scope拒绝；剩余use调用方清单闭合。\
  **依赖**：T128\
  **覆盖 AC**: AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T144 · 工具枚举与实际执行**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/tool/domain/services/tool.py`；`src/backend/bisheng/tool/domain/services/executor.py`\
  **逻辑 / 测试上下文**：get_tool_list默认和executor执行统一visible，保preset/owner/tool enabled与既有运行条件，不因仅删use分支丢禁用校验。\
  **依赖**：T143\
  **配对测试**：T143\
  **验证 / 完成条件**：运行配对测试 T143；验证本卡预期，相关范围检查通过。

- [x] **T145 · Skill 枚举与启用校验：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_skill.py`（拟新增）；`src/backend/test/linsight/test_user_skills.py`\
  **逻辑 / 测试上下文**：批量结果不漏仅可见，停用仍不可运行、无scope拒绝，tenant隔离。\
  **依赖**：T144\
  **覆盖 AC**: AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T146 · Skill 枚举与启用校验**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/linsight/domain/services/user_skills.py`；`src/backend/bisheng/linsight/domain/services/skill_permission.py`\
  **逻辑 / 测试上下文**：user_skills批量过滤及skill_permission原use分支转visible，同时独立保enabled等业务校验；不要因动作改名使disabled可执行。\
  **依赖**：T145\
  **配对测试**：T145\
  **验证 / 完成条件**：运行配对测试 T145；验证本卡预期，相关范围检查通过。

- [x] **T147 · DSH 工具能力目录：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_dsh.py`（拟新增）\
  **逻辑 / 测试上下文**：能力枚举/工作执行一致，仅可见可用但缺scope/停用仍拒绝。\
  **依赖**：T146\
  **覆盖 AC**: AC-35, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T148 · DSH 工具能力目录**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/dsh/domain/services/capability_catalog.py`；`src/backend/bisheng/dsh/domain/services/work_capabilities.py`\
  **逻辑 / 测试上下文**：明确tool list准入visible，保原DSH身份上下文、声明范围、内容安全/配额/状态；旧工具绑定不改写。\
  **依赖**：T147\
  **配对测试**：T147\
  **验证 / 完成条件**：运行配对测试 T147；验证本卡预期，相关范围检查通过。

- [x] **T149 · 开放 task mode 领取与提交准入：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_taskmode.py`（拟新增）\
  **逻辑 / 测试上下文**：提交与执行两阶段同可见语义；missing模型配置明确失败，队列参数不复活旧模型；scope/跨tenant拒绝。\
  **依赖**：T148, T745\
  **覆盖 AC**: AC-35, AC-68, AC-79, AC-82, AC-83, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T150 · 开放 task mode 领取与提交准入**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/open_api/domain/services/task_mode_service.py`\
  **逻辑 / 测试上下文**：提交知识来源批量action和任务执行阶段均按visible，仍读业务资源模型/索引配置和旧ID；保凭证、业务状态，任务不绑定模型。\
  **依赖**：T149, T745, T746, T747\
  **配对测试**：T149\
  **验证 / 完成条件**：运行配对测试 T149；验证本卡预期，相关范围检查通过。

- [x] **T151 · 工作台及开放工作流入口：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_apps_rpc.py`（拟新增）\
  **逻辑 / 测试上下文**：实际旧调用default/explicit use都兼容；无scope/业务停止等原限制保持。\
  **依赖**：T150, T042\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T152 · 工作台及开放工作流入口**
  **类型 / Owner**：后端 API / EDGE\
  **写入文件**：`src/backend/bisheng/workstation/api/endpoints/apps.py`；`src/backend/bisheng/open_endpoints/api/endpoints/workflow.py`\
  **逻辑 / 测试上下文**：HTTP委托统一visible使用准入，保原路由及请求/错误格式；历史应用/工作流发布与knowledge类型照常解释，无权内容不返回。\
  **依赖**：T151\
  **配对测试**：T151\
  **验证 / 完成条件**：运行配对测试 T151；验证本卡预期，相关范围检查通过。

- [x] **T153 · 系统应用与租户分享纯可见：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_shared.py`（拟新增）\
  **逻辑 / 测试上下文**：工作流/助手/tool/library系统分享无use，原范围不扩；撤来源不删他源，QA与文档映射正确。\
  **依赖**：T026\
  **覆盖 AC**: AC-78, AC-79, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T154 · 系统应用与租户分享纯可见**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/api/services/f048_application_permission.py`；`src/backend/bisheng/tenant/domain/services/resource_share_service.py`\
  **逻辑 / 测试上下文**：系统应用动作集和tenant share标准集合移除use，保visible、原主体/Source及分享管理资格；合法纯可见仍可撤销，不改租户原共享边界。\
  **依赖**：T153\
  **配对测试**：T153\
  **验证 / 完成条件**：运行配对测试 T153；验证本卡预期，相关范围检查通过。

- [x] **T155 · 频道只读准入集合：先写测试**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_permission.py`（拟新增）\
  **逻辑 / 测试上下文**：普通只读频道可见可用、无编辑能力，tenant和停用状态按原业务执行。\
  **依赖**：T054, T026\
  **覆盖 AC**: AC-78, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T156 · 频道只读准入集合**
  **类型 / Owner**：后端 Domain / CH\
  **写入文件**：`src/backend/bisheng/channel/domain/services/f048_channel_permission.py`\
  **逻辑 / 测试上下文**：READ_ONLY_CHANNEL_ACTIONS只保visible并经统一权限服务；保频道状态/归属及配置权限，不用新独立use动作。\
  **依赖**：T155\
  **配对测试**：T155\
  **验证 / 完成条件**：运行配对测试 T155；验证本卡预期，相关范围检查通过。

- [ ] **T157 · 全平台权限停服子计划与校验：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_migration.py`（拟新增）\
  **逻辑 / 测试上下文**：run/plan/checksum不符拒绝；use-only授权保留可撤销，global download/纯vis拆分正确；非use尤其rename不变，脚本不查停服。\
  **依赖**：T028, T605\
  **覆盖 AC**: AC-31, AC-56, AC-59, AC-63, AC-78, AC-80, AC-81, AC-83, AC-85\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T158 · 全平台权限停服子计划与校验**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/migration/f118_plan.py`（拟新增）；`src/backend/bisheng/permission/migration/f118_verify.py`（拟新增）\
  **逻辑 / 测试上下文**：仅停服后正式盘点原model/Grant/Source/visibility/non-use(含rename)/Catalog/checksum并并入同run/plan/hash；转换纯可见合同与投影，不用维护前快照；按冻结原基线列use预期差异及其他零差异。\
  **依赖**：T157\
  **配对测试**：T157\
  **验证 / 完成条件**：运行配对测试 T157；验证本卡预期，相关范围检查通过。

- [x] **T159 · 停服 run/计划/检查点持久账本：先写测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_ledger.py`（拟新增）\
  **逻辑 / 测试上下文**：重复run同计划幂等；hash变化拒绝，M2前不能M3，转换中断沿原checkpoint，无停服检测参数。\
  **依赖**：T011\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-85, AC-89, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T160 · 停服 run/计划/检查点持久账本**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_run_repository.py`（拟新增）\
  **逻辑 / 测试上下文**：持久run/原基线/plan hash/阶段及租户来源覆盖，不写本机文件共享状态；新表自动发现/tenant登记按MIG已有卡串行补充。resume载同基线，冻结后不能对转换后数据重冻。\
  **依赖**：T159\
  **配对测试**：T159\
  **验证 / 完成条件**：运行配对测试 T159；验证本卡预期，相关范围检查通过。

- [ ] **T161 · 正式盘点、预检与存量失效证据：先写测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_inventory.py`（拟新增）\
  **逻辑 / 测试上下文**：合法旧缺失可登记，旧type误判/名称歧义/creator缺失/跨tenant均失败；permission子计划纳同run，未冻结零转换。\
  **依赖**：T160, T030, T126\
  **覆盖 AC**: AC-55, AC-56, AC-63, AC-64, AC-80, AC-85, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T162 · 正式盘点、预检与存量失效证据**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/unification_inventory_service.py`（拟新增）\
  **逻辑 / 测试上下文**：运维停服备份后全租户正式盘点资源/creator、版本、标签metadata、模型索引、权限、业务引用、任务、配额；转换前冻结。原ID明确且已缺失保留证据；歧义/非法跨租户/其他异常拒绝，不把旧类型误查当缺失。\
  **依赖**：T161\
  **配对测试**：T161\
  **验证 / 完成条件**：运行配对测试 T161；验证本卡预期，相关范围检查通过。

- [ ] **T163 · type/版本/标签转换与来源配额：先写测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_convert.py`（拟新增）\
  **逻辑 / 测试上下文**：重复转换无重复版本标签；前后ID/模型/索引/授权相等，未发布可访问，超额保留存量但限新建。转换失败只原计划修复/一致备份回退。\
  **范围限制**：只转换本次文档库 type=0；type=1 独立保留，type=2 保持退休且不复活，不顺带删除或清理其历史数据。\
  **依赖**：T162\
  **覆盖 AC**: AC-55, AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T164 · type/版本/标签转换与来源配额**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/unification_conversion_service.py`（拟新增）\
  **逻辑 / 测试上下文**：按冻结计划 type0→3、type1保留/type2退休；保ID原对象/模型/索引，不解析重嵌；补首版本/标签去重，durable origin不额外文件用量，存量private迁移不清授权、不默认广场发布。\
  **范围限制**：只转换本次文档库 type=0；type=1 独立保留，type=2 保持退休且不复活，不顺带删除或清理其历史数据。\
  **依赖**：T163\
  **配对测试**：T163\
  **验证 / 完成条件**：运行配对测试 T163；验证本卡预期，相关范围检查通过。

- [x] **T165 · 迁移空间配额显示与创建统一：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_quota.py`（拟新增）\
  **逻辑 / 测试上下文**：W6§44：原sync/async创建计数与QuotaService user显示同一count-only条件；换owner/新Session后origin仍豁免，tenant总量/部门/文件SUM不变。正式T164转换与配额联验保留在T203。\
  **依赖**：T010, T082\
  **覆盖 AC**: AC-14, AC-61, AC-62\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [x] **T166 · 迁移空间配额显示与创建统一**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge.py`；`src/backend/bisheng/role/domain/services/quota_service.py`\
  **逻辑 / 测试上下文**：以durable migration origin持续豁免个人新建空间数量，tenant总量超额保存量限新增；部门/存储原规则保持，校验与展示同计数，不按一次标记跳检查。\
  **依赖**：T165\
  **配对测试**：T165\
  **验证 / 完成条件**：运行配对测试 T165；验证本卡预期，相关范围检查通过。

- [ ] **T167 · 存量来源绑定回填：先写测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_backfill.py`（拟新增）\
  **逻辑 / 测试上下文**：所有来源类型+版本+空集覆盖；中断重跑无重复，known legacy允许但新漂移/歧义/未解释missing失败；不改业务原文、不伪造tombstone。\
  **依赖**：T164, T094, T040, T046, T048, T054, T058, T098, T018\
  **覆盖 AC**: AC-71, AC-87, AC-88, AC-89, AC-91, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T168 · 存量来源绑定回填**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/resource_reference/application/backfill.py`（拟新增）\
  **逻辑 / 测试上下文**：调用各业务同版本提取协议覆盖spec来源表全部已保存版本/默认含Root/paused，零引用集合也写；known forced-invalid/legacy-invalid原关系保留，任务不回填；按source revision摘要和checkpoint幂等。\
  **依赖**：T167\
  **配对测试**：T167\
  **验证 / 完成条件**：运行配对测试 T167；验证本卡预期，相关范围检查通过。

- [ ] **T169 · 覆盖对账与启用保护：先写测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_reconcile.py`（拟新增）\
  **逻辑 / 测试上下文**：漏一来源或零引用集合失败；known legacy仍有原配置标记且受影响执行失败，正常业务继续；错误重跑不能重分类原基线。\
  **依赖**：T168, T166, T104\
  **覆盖 AC**: AC-37, AC-59, AC-64, AC-80, AC-89, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T170 · 覆盖对账与启用保护**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/resource_reference/application/reconcile.py`（拟新增）；`src/backend/bisheng/knowledge/domain/services/unification_verification_service.py`（拟新增）\
  **逻辑 / 测试上下文**：以同停服冻结基线全量核资源/文件/版本/标签metadata/授权配额/来源集合摘要及检索抽样；known legacy清单保留不阻正常业务。全租户覆盖就绪与差异解释完成才登记ready，不未ready启删除保护。\
  **依赖**：T169\
  **配对测试**：T169\
  **验证 / 完成条件**：运行配对测试 T169；验证本卡预期，相关范围检查通过。

- [ ] **T171 · 新租户/空安装覆盖就绪初始化：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_tenant_coverage.py`（拟新增）\
  **逻辑 / 测试上下文**：新租户零业务可正常删除空资源；创建/初始化故障回滚，既有未回填租户仍拒绝删除；初始化不能外部伪造或跨tenant调用。\
  **依赖**：T170, T018\
  **覆盖 AC**: AC-89, AC-90\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T172 · 新租户/空安装覆盖就绪初始化**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/tenant/domain/services/tenant_service.py`；`src/backend/bisheng/resource_reference/application/bootstrap.py`（拟新增）\
  **逻辑 / 测试上下文**：新租户创建用例同事务调用REF初始化协议；空新安装通过同一内部bootstrap能力在全部同步写端可用后初始化，来源为空证据与writer_contract版本持久记录。既有存量tenant没有账本必须回填对账，不能按无行自动ready。初始化错误租户创建整体回滚。\
  **依赖**：T171\
  **配对测试**：T171\
  **验证 / 完成条件**：运行配对测试 T171；验证本卡预期，相关范围检查通过。

- [ ] **T173 · 停服升级入口/报告/恢复命令：先写测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_cli.py`（拟新增）\
  **逻辑 / 测试上下文**：M2→M3→M4先后，dryrun/正式用途清楚；模拟中断resume同run，异常退出不执行恢复；命令实际存在后才更新升级说明。\
  **范围限制**：只交付运维 CLI/报告/检查点恢复命令，不新增在线迁移 HTTP API、后台管理平台或停服控制。\
  **依赖**：T170\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-80, AC-85, AC-89, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T174 · 停服升级入口/报告/恢复命令**
  **类型 / Owner**：运维脚本 / MIG\
  **写入文件**：`src/backend/scripts/unify_knowledge_spaces.py`（拟新增）\
  **逻辑 / 测试上下文**：只调盘点/预检/冻结/convert/backfill/verify及checkpoint resume，输出run/hash/范围/失效清单/差异；不探测端口/进程/Worker/停服标记，不启停/等待服务；失败不自动恢复业务。\
  **范围限制**：只交付运维 CLI/报告/检查点恢复命令，不新增在线迁移 HTTP API、后台管理平台或停服控制。\
  **依赖**：T173\
  **配对测试**：T173\
  **验证 / 完成条件**：运行配对测试 T173；验证本卡预期，相关范围检查通过。

- [x] **T175 · 平台 API 与合同 Mock**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`；`src/frontend/platform/src/controllers/hooks/knowledge.ts`\
  **逻辑 / 测试上下文**：按A1/J1/R3冻结 DTO封装普通/admin、settings、jobs、预检确认；react-query key带身份/租户/范围，Mock与真接口可替换；HTTP只在API层。\
  **依赖**：T002, T007, T003, T006, T605, T606\
  **验证 / 完成条件**：Mock序列化与合同一致；切租户/身份不复用缓存，平台类型检查；关联规格：AC-02, AC-03, AC-04, AC-05, AC-49, AC-50。

- [x] **T176 · 平台入口/三页签与创建**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/index.tsx`；`src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx`\
  **逻辑 / 测试上下文**：按W6§22三tab/scope/ordinary Cursor/admin DB分页与SPACE懒授权、真实创建/基本设置/默认Dialog挂载；QA独立，copy/delete与完整详情/目录/上传后续接线不冒充完成。\
  **依赖**：T722, T721, T719, T698, T707, T728, T729, T730\
  **验证 / 完成条件**：菜单与角色/租户切换、无权直链、QA入口；Zustand不直接HTTP；关联规格：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-16, AC-84。

- [ ] **T177 · 平台目录/上传/版本**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/detail.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`\
  **逻辑 / 测试上下文**：复用空间树/文件夹上传/网页/预览下载rename版本，按相同开关相似文档/标签，按钮来自现有效动作，不新增fileedit。\
  **依赖**：T176, T757\
  **验证 / 完成条件**：多层目录、新版本历史与主版本选择、rename-only行为；两端同数据人工验证；关联规格：AC-09, AC-10, AC-11, AC-14, AC-15, AC-30, AC-31。

- [x] **T178 · 平台分类型策略草稿**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/RuleFile.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/RuleTable.tsx`\
  **逻辑 / 测试上下文**：W6§17两叶新增具名受控默认fields及Draft类型，保旧上传分支；数字清空不补默认、完整字段保留；切类型/保存父边界由T707承接，实际入口T176/T179另验。\
  **依赖**：T705, T698, T696\
  **验证 / 完成条件**：切文档/表格保未保存值、overlap/header范围及错误、取消/失败零保存；关联规格：AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44。

- [ ] **T179 · 平台上传与默认设置接线**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/filesUpload.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/FileUploadSplitStrategy.tsx`\
  **逻辑 / 测试上下文**：打开已保存空间默认，显式上传参数不反存默认；网页/音视频保既有专用规则，不展示不支持选项。\
  **依赖**：T178\
  **验证 / 完成条件**：两文件类型优先级、历史文件无重处理、上传失败无默认变化；关联规格：AC-07, AC-09, AC-10, AC-39, AC-40, AC-43, AC-44。

- [ ] **T180 · 平台批量确认/逐项结果**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/BatchOperationDialog.tsx`（拟新增）；`src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`\
  **逻辑 / 测试上下文**：预检列无权/状态/不支持/直接引用失败，确认后跳过执行、取消零改；最终变化重新确认；普通file/夹永不展示force。\
  **依赖**：T179, T177\
  **验证 / 完成条件**：混合批确认/取消、整夹受阻、文件force参数无入口；结果不把accepted当completed；关联规格：AC-12, AC-13, AC-28, AC-29, AC-94。

- [ ] **T181 · 平台跨空间移动风险**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/MoveDialog.tsx`（拟新增）；`src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`\
  **逻辑 / 测试上下文**：展示目标/全历史版本、metadata字段保留和清除明细、标签、继承与自定义影响，二次确认携plan，任务进度/失败同任务重试。\
  **依赖**：T180\
  **验证 / 完成条件**：取消不请求执行；metadata异类型丢失明细、继承变化提示，失败归属不反复移动；关联规格：AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24。

- [ ] **T182 · 平台高级处理与任务面板**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/ProcessingJobPanel.tsx`（拟新增）；`src/frontend/platform/src/pages/KnowledgePage/detail.tsx`\
  **逻辑 / 测试上下文**：重建/重处理/切分独立确认，模型重建保Chunk；显示真实item进度/失败/obsolete和原任务retry，受限内容只计数；重建原文件可读、冲突写按钮禁用。\
  **依赖**：T181, T176\
  **验证 / 完成条件**：accepted仅接收；部分失败/过期/无权详情、跨租户缓存清理；无新增文件edit；关联规格：AC-33, AC-34, AC-45, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54。

- [ ] **T183 · 平台 Chunk/元数据反馈**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/Paragraphs.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/MetadataManagementDialog.tsx`\
  **逻辑 / 测试上下文**：Chunk指定版本保原文件；新增metadata历史空，rename/drop二次确认，展示实际索引任务结果，容器edit原能力不变。\
  **依赖**：T182\
  **验证 / 完成条件**：取消零改、version定位、失败不报成功及当前能力判断；关联规格：AC-33, AC-45, AC-46, AC-47, AC-49。

- [ ] **T184 · 平台空间/模型引用影响确认**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/ResourceDeleteDialog.tsx`（拟新增）；`src/frontend/platform/src/pages/BuildPage/bench/ModelManagement.tsx`\
  **逻辑 / 测试上下文**：普通阻断依赖/入口、受限摘要；空间/模型force显式二次确认plan，clear无force；模型清单编辑整次阻断不假保存。保留失效配置ID供手动修复。\
  **依赖**：T183\
  **验证 / 完成条件**：单模型/服务/清单移除、受限来源、摘要变化重新确认；copy创建者规则不因admin放宽；关联规格：AC-28, AC-29, AC-70, AC-72, AC-73, AC-76, AC-77, AC-90, AC-91, AC-92。

- [ ] **T185 · 平台选择器失效槽与历史兼容**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpace.tsx`；`src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/ModelSelect.tsx`\
  **逻辑 / 测试上下文**：仅可见即可选空间，QA独立；原配置已删ID显示失效不自动清掉/替换，允许业务部分修复但提示运行发布仍禁止；旧绑定无需重发。\
  **依赖**：T184\
  **验证 / 完成条件**：新建不可选deleted，编辑原多失效只改一项保其余；历史ID原文保留；关联规格：AC-36, AC-37, AC-68, AC-79, AC-91, AC-92, AC-93。

- [ ] **T186 · 平台纯可见授权可撤销**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/permission.ts`；`src/frontend/platform/src/pages/KnowledgePage/components/PermissionModelAdapter.tsx`（拟新增）\
  **逻辑 / 测试上下文**：A1/P1活动action不显示use，合法纯可见模型仍展示来源和撤销入口；委托已有授权组件，未授动作不显示为拥有；不改旧审计快照。\
  **依赖**：T185, T022\
  **验证 / 完成条件**：use-only授权可找到/撤销一个Source，其他来源可见仍在；file rename独立展示；关联规格：AC-30, AC-31, AC-78, AC-81, AC-83。

- [x] **T187 · 客户端 API 与 Mock**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/api/knowledgeProcessing.ts`（拟新增）；`src/frontend/client/src/pages/knowledge/SpaceDetail/knowledgeSpaceTypes.ts`\
  **逻辑 / 测试上下文**：A1/J1/R3前台简化状态/预检/任务DTO，React-query/Recoil保持，身份/租户key隔离；无后台高级配置。\
  **依赖**：T002, T007, T003, T006, T605, T607\
  **验证 / 完成条件**：Mock合同及客户端类型检查；不从platform导入页面/hooks/store；关联规格：AC-02, AC-12, AC-13, AC-49, AC-50。

- [ ] **T188 · 客户端入口/选择/失效来源**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/pages/knowledge/KnowledgeHomePage.tsx`；`src/frontend/client/src/pages/knowledge/KnowledgePageContent.tsx`\
  **逻辑 / 测试上下文**：统一知识空间与独立QA命名；真实ID旧链接/可见性，失效槽显示原选择并指引原业务修复，不自动解除或fallback。\
  **依赖**：T187\
  **验证 / 完成条件**：可见无use可选，无权不泄露名称；有效/失效旧ID、QA、管理员缓存不复用；关联规格：AC-01, AC-02, AC-06, AC-08, AC-36, AC-37, AC-68, AC-79, AC-91, AC-92, AC-93。

- [ ] **T189 · 客户端批量与文件删除**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/pages/knowledge/SpaceDetail/useKnowledgeSelectionActions.ts`；`src/frontend/client/src/pages/knowledge/SpaceDetail/useKnowledgeFileActions.ts`\
  **逻辑 / 测试上下文**：按逐项预检弹确认，取消零执行；直接引用文件/夹受阻，空间绑定不阻普通文件；不新增fileforce/高级editgate。\
  **依赖**：T188\
  **验证 / 完成条件**：混合批/整夹引用/确认后变化、rename独立能力、错误逐项反馈；关联规格：AC-12, AC-13, AC-28, AC-29, AC-31, AC-94。

- [ ] **T190 · 客户端移动简化风险**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/pages/knowledge/SpaceDetail/MoveToDialog.tsx`；`src/frontend/client/src/pages/knowledge/SpaceDetail/KnowledgeSpaceOverlays.tsx`\
  **逻辑 / 测试上下文**：展示目标、整版本、metadata丢失、继承变化/自定义保留，简化确认同plan；失败重试原任务保归属。\
  **依赖**：T189\
  **验证 / 完成条件**：取消零变化，跨租户/自身子目录错误，成功与失败进度不会重复移动；关联规格：AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24。

- [ ] **T191 · 客户端任务/删除影响展示**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx`；`src/frontend/client/src/pages/knowledge/SpaceDetail/ProcessingState.tsx`（拟新增）\
  **逻辑 / 测试上下文**：只显示处理/完成/失败/过期，重建保目录预览下载暂停检索冲突写；空间删除显式force影响确认，clear无force，隐藏来源只数量；不加后台选模型/Chunk设置。\
  **依赖**：T190\
  **验证 / 完成条件**：重建/部分失败/obsolete/同空间冲突/其他空间正常，force摘要变化重确认；关联规格：AC-28, AC-29, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-90, AC-91, AC-94。

- [x] **T192 · 平台通用授权纯可见模型**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/components/bs-comp/permission/PermissionGrantTab.tsx`；`src/frontend/platform/src/components/bs-comp/permission/PermissionListTab.tsx`\
  **逻辑 / 测试上下文**：当前动作不显示use；纯可见模型虽动作数组为空仍展示有效主体、原Source与可撤销能力，等级按服务端；普通非法空模型不允许授予。\
  **依赖**：T631, T632, T022\
  **验证 / 完成条件**：所有资源权限弹窗use-only迁移授权可授予/列出/撤销，其他Source仍生效，file rename不被edit替代；关联规格：AC-78, AC-81, AC-83。

- [x] **T193 · 平台全员与托管应用动作**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/components/bs-comp/permission/AllMembersPermission.tsx`；`src/frontend/platform/src/pages/BuildPage/hostedApp/appActions.ts`\
  **逻辑 / 测试上下文**：全员纯可见和 APP 原使用按钮按服务端 visible 解释，不再独立 use；发布、分享、编辑、删除与管理按钮使用各自服务端动作结果，不能由 visible 推断；保护原管理等级和可撤销性。\
  **依赖**：T192, T136, T633\
  **验证 / 完成条件**：全员Source撤销/其他来源并集，app可见但无编辑动作按钮矩阵；历史审计文字不改写；关联规格：AC-78, AC-79, AC-81, AC-83。

- [x] **T194 · 客户端通用授权展示**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/components/permission/PermissionListTab.tsx`；`src/frontend/client/src/components/permission/UnifiedPermissionControls.tsx`\
  **逻辑 / 测试上下文**：当前模型动作去use，合法纯可见主体及Source继续显示、管理和撤销；保既有管理能力/等级，继承模式统一解析。\
  **依赖**：T628, T629, T022\
  **验证 / 完成条件**：仅use迁移后列表不消失、可撤单来源，其他来源仍有效；view不能edit/download/rename；关联规格：AC-30, AC-31, AC-78, AC-81, AC-83。

- [x] **T195 · 客户端纯可见授予选择**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/components/permission/PermissionGrantTab.tsx`；`src/frontend/client/src/api/permission.ts`\
  **逻辑 / 测试上下文**：空action不等于无效：识别服务端合法纯可见模型与管理能力，支持原授予/撤销协议，不创建新visible动作或use来源。\
  **依赖**：T194\
  **验证 / 完成条件**：合法pure-visible可选、任意空模型拒绝；现行use字段无返回/保存，旧协议兼容测试；关联规格：AC-78, AC-81, AC-83。

- [ ] **T196 · 模块路由与导出装配：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_wire_router.py`（拟新增）\
  **逻辑 / 测试上下文**：用真实FastAPI路由表与OpenAPI断言所有合同端点唯一；普通admin隔离、旧请求稳定、新任务accepted正确。\
  **依赖**：T126, T152, T140, T154, T156, T138, T136, T172, T174, T218, T219, T221, T223, T225, T227, T230, T232, T234, T238, T242, T246, T248, T250, T252, T255, T258, T259, T264, T266, T268, T270, T271, T272, T273\
  **覆盖 AC**: AC-02, AC-04, AC-05, AC-35, AC-49, AC-65, AC-66, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T197 · 模块路由与导出装配**
  **类型 / Owner**：后端 API / INT\
  **写入文件**：`src/backend/bisheng/knowledge/api/router.py`；`src/backend/bisheng/api/router.py`\
  **逻辑 / 测试上下文**：顺序接线冻结候选接口并消除动态路径遮蔽；新模块自动发现、租户登记与job worker路由逐项核对，额外叶子接线先拆补充卡；不在Endpoint直接ORM/跨模块API互导。\
  **依赖**：T196\
  **配对测试**：T196\
  **验证 / 完成条件**：运行配对测试 T196；验证本卡预期，相关范围检查通过。

- [ ] **T198 · 共享三语词条唯一集成**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/packages/locales/src/shared/zh-Hans.json`；`features/v3.1.0-beta1/118-knowledge-space-unification/contracts.md`（拟新增）\
  **逻辑 / 测试上下文**：汇总两端键/三语词条及归属，不手改生成api_errors；本卡只落中文源与合同清单，后续英/日源独立两文件任务。\
  **依赖**：T186, T191, T002\
  **验证 / 完成条件**：JSON可解析，无重复/缺失key，键清单审阅；不是业务实现基础设施前置，属于最终文案集成。

- [ ] **T199 · 英日源词条与现有生成链**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/packages/locales/src/shared/en.json`；`src/frontend/packages/locales/src/shared/ja.json`\
  **逻辑 / 测试上下文**：补齐同一键的英/日译文，执行现有生成/同步链，两端实际消费路径以T001清单为准；若遗留app locale需直接改，先拆两文件补充卡，不把产物当手改源。\
  **依赖**：T198\
  **验证 / 完成条件**：三语key完全一致、现有生成链无残留；两端切语言检查文字和错误文案。

- [ ] **T200 · 平台真实接口验收**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`；`src/frontend/platform/src/pages/KnowledgePage/detail.tsx`\
  **逻辑 / 测试上下文**：撤去已冻结Mock接真实服务，核列表/管理/文件/策略/任务/强删；统一query失效跨端刷新，权限以服务端为准，不留TODO式临时旁路。\
  **依赖**：T197, T193, T199, T175, T182\
  **验证 / 完成条件**：平台lint/类型检查及构建；按合同真实接口验证前后台同数据、重建/失败/管理员/普通矩阵，记录环境和未执行项。

- [ ] **T201 · 客户端真实接口验收**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/api/knowledge.ts`；`src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx`\
  **逻辑 / 测试上下文**：替换Mock并核目录/移动/状态/批量/删除失效展示，跨端刷新同资源，同一用户子项可见范围不扩；无高级界面复制。\
  **依赖**：T197, T195, T199, T187, T191\
  **验证 / 完成条件**：客户端lint/类型检查及构建；真实接口管理员/普通/独立文件授权、处理状态和强删矩阵，记录环境。

- [ ] **T202 · MySQL事务/投影/并发实测与C2规范复核**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_cross_domain_integration.py`（拟新增）\
  **逻辑 / 测试上下文**：按固定锁序覆盖保存vs普通/强删、服务清单原子性、同来源多版本CAS、FGA失败/SQL失败/清理失败分阶段恢复；新MySQL环境真实执行，Model/Repository/DDL保C2静态规范复核。2026-11-06用户明确本轮免除DM8实测，不将免验或静态核对标成真实DM8通过。\
  **依赖**：T200, T201, T174\
  **覆盖 AC**: AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84, AC-85, AC-86, AC-87, AC-88, AC-89, AC-90, AC-91, AC-92, AC-93, AC-94\
  **验证 / 完成条件**：真实MySQL/中间件证据与C2静态核对分别记录；用户免验DM8不作环境阻塞，不以mock或免验声称双库实测通过。失败修复先补独立叶子任务。

- [ ] **T203 · 升级说明与迁移演练**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/upgrade-guide.md`；`src/backend/test/knowledge_unification/test_upgrade_rehearsal.py`（拟新增）\
  **逻辑 / 测试上下文**：脚本实现后补真实命令与参数，演练停服备份→正式全平台权限/资源盘点冻结→转换/回填→同基线核对→运维恢复；合法存量失效保留清单，中断resume和完整备份回退。脚本不探测/控制停服。\
  **依赖**：T202\
  **覆盖 AC**: AC-37, AC-55, AC-56, AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-80, AC-81, AC-85, AC-89, AC-93\
  **验证 / 完成条件**：记录数据规模、耗时、run/plan hash、差异和恢复证据；无真实环境不得标完成。QA参考文档不是演练输入或门禁。

- [ ] **T204 · 权限/管理员真实矩阵：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_access.py`（拟新增）\
  **逻辑 / 测试上下文**：两租户/超管/租管/owner/普通/独立file授权；仅可见可用、rename独立；撤Source保他源；原scope/菜单边界；重建不扩大文件edit。\
  **依赖**：T203\
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-08, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T205 · 两端普通目录/上传/版本：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_files.py`（拟新增）\
  **逻辑 / 测试上下文**：前后台同资源刷新；QA独立；目录、web、新版本/主版本、同开关、审批配额、混合批取消零变更与确认逐项结果。\
  **依赖**：T203\
  **覆盖 AC**: AC-01, AC-02, AC-06, AC-07, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T206 · 移动/复制/内容删除：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_move_copy.py`（拟新增）\
  **逻辑 / 测试上下文**：源move/目标upload与整版本、附件、metadata、权限、失败同任务；copy仅创建者独立索引；直接引用夹整项拦截、无fileforce、FGA失败先保业务。\
  **依赖**：T203\
  **覆盖 AC**: AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-94\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T207 · 默认/高级处理：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_processing.py`（拟新增）\
  **逻辑 / 测试上下文**：两类型草稿切换、取消/错误不保存、三层优先级及专用规则；指定版本Chunk/metadata原容器edit；重建保人工Chunk不重切分。\
  **依赖**：T203\
  **覆盖 AC**: AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T208 · 任务状态/过期/恢复：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_jobs.py`（拟新增）\
  **逻辑 / 测试上下文**：accepted不报完成；重建保目录下载、暂停冲突与检索；部分失败/原任务retry、相关配置替换obsolete，无关name不影响；headers tenant及无配置失败。\
  **依赖**：T203\
  **覆盖 AC**: AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T209 · 引用/强删/手工修复：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_refs.py`（拟新增）\
  **逻辑 / 测试上下文**：业务来源矩阵/零集合、共享两tenant、服务差集整事务；强删确认变化和失效保留/部分修复；存量失效无伪tombstone；不可变历史不强改。\
  **依赖**：T203\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-87, AC-88, AC-89, AC-90, AC-91, AC-92, AC-93, AC-94\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T210 · 旧协议/SDK/MCP：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_compat.py`（拟新增）\
  **逻辑 / 测试上下文**：旧文档API请求返回type0而真实SPACE、QA1独立；历史知识绑定不重发；SDK/MCP真实协议及scope，整个3.x保兼容。\
  **依赖**：T203\
  **覆盖 AC**: AC-35, AC-65, AC-66, AC-67, AC-68, AC-69, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T211 · 升级后全量验收：端到端测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_e2e_upgrade.py`（拟新增）\
  **逻辑 / 测试上下文**：停服备份后同run正式盘点冻结转换核对；保ID模型索引授权、配额豁免、版本标签幂等、legacy清单；排队保留后业务配置校验，异常维持维护。\
  **依赖**：T203\
  **覆盖 AC**: AC-55, AC-56, AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-80, AC-81, AC-85, AC-89, AC-93\
  **验证 / 完成条件**：先写可执行断言，再在真实服务/凭证/数据中运行；两端UI步骤进入报告。每卡仅本组用例，若超约30min继续按场景拆分，不以一个大函数占位。

- [ ] **T212 · E2E 汇总执行与报告**
  **类型 / Owner**：验证汇总 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/e2e-report.md`（拟新增）\
  **逻辑 / 测试上下文**：调用 /e2e-test，以spec AC核对上述8组实际覆盖；记录两端页面手动清单、SDK/MCP和API真实结果、环境、运行命令及未执行项。QA参考用例不作为Harness输入。\
  **依赖**：T204, T205, T206, T207, T208, T209, T210, T211\
  **验证 / 完成条件**：静态/单元/CI/部署/E2E分别报告；若缺环境保持待执行，不把mock和构建替代真实结果。

- [ ] **T213 · 特性代码评审及文档收口**
  **类型 / Owner**：评审收口 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/README.md`\
  **逻辑 / 测试上下文**：执行 /sdd-code-review --base feat/3.1.0-beta1；确认发布契约C1–C8、活动use全调用面、来源覆盖、保护启用就绪。偏差先回写design/任务并复核；仅实际完成任务打勾，不自动merge/push。额外文档回写每次按1–2文件另拆。\
  **依赖**：T212\
  **验证 / 完成条件**：评审无未闭合问题，所有必要验证有证据；否则实现状态保持未完成。

## 本轮范围修订（2026-11-06）

用户确认默认 Embedding 只供空间创建初始化，T480/T481 改为默认来源原子维护与既有空间不受影响回归；T488/T489 原全空间联动已退役，历史完成编号保留，不再作为开发要求。空间显式改模型仍重建。APP 多模型声明每个候选/锁后阶段只重验目录一次，保持私有计划和原权限边界。以上修订不勾选其他未完成卡。后续本轮范围复核已将 T404/T405 外移：历史597编号中438已完成/历史交付、157范围内待办、2外移；分组与逐项依赖见 [pending-tasks.md](./pending-tasks.md)。

## 合同冻结后追加任务（保持既有编号）

新增T214–T221由源码核对发现；排程以DAG为准，编号不代表拓扑次序。T009/T021/T023/T027已补前置。

- [x] **T214 · PermissionModel持久字段与内部派生结构**
  **类型 / Owner**：基础设施 / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/models/catalog.py`；`src/backend/bisheng/permission/domain/services/model_policy.py`\
  **逻辑 / 测试上下文**：按P1新增types(JsonType)/level(int nullable)及内部派生类型默认值；原Grant/Source表不变。canonical/策略行为在T020实现，既有表DDL统一交MIG。\
  **依赖**：T002, T006\
  **验证 / 完成条件**：仅定义结构合同；双库DDL编译/导入检查，结构回退先确认未启用写端，转换后使用一致备份。

- [x] **T215 · GrantSource合法纯可见与目标化快照：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_source_snapshot.py`\
  **逻辑 / 测试上下文**：混合全局download但tool纯可见、合法空actions授予/撤销、inactive原Source清理、原等级和其他Source贡献均保留；未标记空模型仍拒绝。\
  **依赖**：T012, T020, T214\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：先记录可观察红阶段，不修改实现。

- [x] **T216 · GrantSource目标化快照与合法空动作guard**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/grant_source_service.py`\
  **逻辑 / 测试上下文**：实现P1 model_snapshot_for_target和_ensure_target_model，action scopes由可信Catalog计算；空模型例外仅server-owned标记目标，不授额外具体动作。与T006同Owner串行。\
  **依赖**：T215\
  **配对测试**：T215\
  **验证 / 完成条件**：运行配对测试 T215，lint/类型/序列化往返通过。

- [x] **T217 · Catalog持久/当前快照往返：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_control_snapshot.py`\
  **逻辑 / 测试上下文**：SQL模型→loader→canonical checksum→目标化快照往返types/level不丢；旧None归一化，HTTP不能伪造marker，全新安装标准viewer可用。\
  **依赖**：T216, T214, T012\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：先记录可观察红阶段，不修改实现。

- [x] **T218 · Catalog与运行控制层快照接线**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/control_state.py`；`src/backend/bisheng/permission/application/catalog_api.py`\
  **逻辑 / 测试上下文**：_load_models/_replace_children/current_catalog统一保types/level与checksum；新增/编辑HTTP不信任marker，全新安装bootstrap用内置合法viewer元数据，受控迁移保原model_key。\
  **依赖**：T217\
  **配对测试**：T217\
  **验证 / 完成条件**：运行配对测试 T217，lint/类型/序列化往返通过。

- [x] **T219 · 持久确认计划SQLModel**
  **类型 / Owner**：基础设施 / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_operation_plan.py`\
  **逻辑 / 测试上下文**：OperationPrecheck持久opaque计划，tenant/actor/operation/目标及来源修订/规范payloadhash/impact摘要/expire/消耗operation_id。预检不创建job、不改业务资源；不能复用deletejob造成围栏提前生效。无凭据/全文。新整表自动发现，MIG统一租户注册。\
  **依赖**：T002, T007\
  **验证 / 完成条件**：仅定义结构合同；双库DDL编译/导入检查，结构回退先确认未启用写端，转换后使用一致备份。

- [x] **T220 · 高级管理写可信租户防竞态：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_management_scope.py`\
  **逻辑 / 测试上下文**：新后台processing-settings/job提交重试按可信scope对照X-Management-Tenant；普通space文件写不额外强加网页头，v2机器凭证仍按原scope/actor准入。\
  **依赖**：T012\
  **覆盖 AC**: AC-04, AC-05, AC-33, AC-35, AC-84\
  **验证 / 完成条件**：先记录可观察红阶段，不修改实现。

- [x] **T221 · 高级管理写scope接线**
  **类型 / Owner**：后端 API / INT\
  **写入文件**：`src/backend/bisheng/common/middleware/admin_scope.py`\
  **逻辑 / 测试上下文**：只添加冻结高级写端点/使用既有require_expected_management_tenant协议；不信任query tenant、不扩管理角色、不改变普通客户端文件写。Endpoint门禁另由KN消费合同。\
  **依赖**：T220\
  **配对测试**：T220\
  **验证 / 完成条件**：运行配对测试 T220，lint/类型/序列化往返通过。

- [ ] **T222 · 知识旧列表和RAG使用资格适配：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_knowledge_usage_adapters.py`\
  **逻辑 / 测试上下文**：将旧列表/知识RAG batch返回动作过滤统一visible；受支持query action=use仅边界归一化，不让业务继续按use集合判定。保scope、真实类型QA/SPACE与成功主版本。；可见无use可用、无可见/无凭证scope拒绝，旧协议不形成独立授权。\
  **依赖**：T026, T108\
  **覆盖 AC**: AC-35, AC-36, AC-37, AC-66, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：先记录红阶段，不修改实现。

- [ ] **T223 · 知识旧列表和RAG使用资格适配**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/knowledge_rag.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：将旧列表/知识RAG batch返回动作过滤统一visible；受支持query action=use仅边界归一化，不让业务继续按use集合判定。保scope、真实类型QA/SPACE与成功主版本。\
  **依赖**：T222\
  **配对测试**：T222\
  **验证 / 完成条件**：配对测试转绿、相关既有回归及架构检查通过。
- [x] **T224 · 资源Owner系统动作白名单：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_permission_owner_actions.py`\
  **逻辑 / 测试上下文**：Owner管理受保护系统Source的白名单移除use，合法viewer纯可见识别；保protected/原管理等级及移交规则，不顺带赋予可见主体管理能力。；可见无use可用、无可见/无凭证scope拒绝，旧协议不形成独立授权。\
  **依赖**：T216, T218\
  **覆盖 AC**: AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：先记录红阶段，不修改实现。

- [x] **T225 · 资源Owner系统动作白名单**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/owner_service.py`\
  **逻辑 / 测试上下文**：Owner管理受保护系统Source的白名单移除use，合法viewer纯可见识别；保protected/原管理等级及移交规则，不顺带赋予可见主体管理能力。\
  **依赖**：T224, T128, T146\
  **配对测试**：T224\
  **验证 / 完成条件**：配对测试转绿、相关既有回归及架构检查通过。
- [x] **T226 · 工具HTTP旧动作参数适配：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_tool_http_action.py`\
  **逻辑 / 测试上下文**：当前默认visible、保受支持旧use query按visible解释；经原服务鉴权，旧请求/返回结构维持，活动动作不输出use。；可见无use可用、无可见/无凭证scope拒绝，旧协议不形成独立授权。\
  **依赖**：T136, T144\
  **覆盖 AC**: AC-35, AC-66, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：先记录红阶段，不修改实现。

- [x] **T227 · 工具HTTP旧动作参数适配**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/tool/api/tool.py`\
  **逻辑 / 测试上下文**：当前默认visible、保受支持旧use query按visible解释；经原服务鉴权，旧请求/返回结构维持，活动动作不输出use。\
  **依赖**：T226\
  **配对测试**：T226\
  **验证 / 完成条件**：配对测试转绿、相关既有回归及架构检查通过。

## W0/W1源码核对与集成补充任务

以下编号追加，排序以DAG为准；每项由原Owner唯一写入，不改变94条AC。

- [x] **T228 · 跨lane结构与DDL集成验证**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_contract_infrastructure.py`\
  **逻辑 / 测试上下文**：验证全部新表可发现/tenant注册，老表重复upgrade仅加结构、保原type/model/Grant key，降级不静默丢provenance；内部修订/迁移/切换字段不扩旧Base DTO。\
  **依赖**：T009, T010, T011, T012\
  **覆盖 AC**: AC-02, AC-55, AC-57, AC-59, AC-63, AC-65, AC-66, AC-67, AC-80, AC-81, AC-89\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T229 · F118错误HTTP状态：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_error_http_status.py`\
  **逻辑 / 测试上下文**：13种错误实例和包装HTTPException的v2映射503/409/404正确，原权限及旧错误映射不变。\
  **依赖**：T012\
  **覆盖 AC**: AC-35, AC-66, AC-76, AC-89, AC-90\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T230 · F118错误v2状态接线**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/open_api/domain/http_status.py`\
  **逻辑 / 测试上下文**：只对KnowledgeUnificationError使用明确http_status，v1 envelope/原错误逻辑保持；不是把所有任意异常http属性当新状态来源。\
  **依赖**：T229\
  **配对测试**：T229\
  **验证 / 完成条件**：配对测试T229转绿，ruff/架构检查与相关回归通过。

- [x] **T231 · 错误三语源：中文与英文**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/packages/locales/src/api_errors/zh-Hans.json`；`src/frontend/packages/locales/src/api_errors/en.json`\
  **逻辑 / 测试上下文**：补13个新错误键，不覆盖已占用键，不手改生成产物。\
  **依赖**：T012\
  **验证 / 完成条件**：结构/序列化/对应DDL检查及相关集成验证；真实双库结果独立记录，不以SQLite替代。

- [x] **T232 · 错误三语源：日文**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/packages/locales/src/api_errors/ja.json`\
  **逻辑 / 测试上下文**：补同13个日文键，运行现有check-i18n验证三语与backend Code对齐。\
  **依赖**：T231\
  **验证 / 完成条件**：结构/序列化/对应DDL检查及相关集成验证；真实双库结果独立记录，不以SQLite替代。

- [x] **T233 · 合法字符切分兜底：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_schema_compatibility.py`\
  **逻辑 / 测试上下文**：当前ElemCharacterTextSplitter支持空字符串字符fallback。完整和partial规则均允许[空串]或含空串列表，仍拒空列表/错长度/非字符串，不新增算法。\
  **依赖**：T007\
  **覆盖 AC**: AC-39, AC-42, AC-43, AC-66\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T234 · 保留空分隔符合法能力**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/processing_settings.py`\
  **逻辑 / 测试上下文**：仅去除对separator空字符串元素的错误禁令，保类型/列表长度/规则对齐与最终参数校验。\
  **依赖**：T233\
  **配对测试**：T233\
  **验证 / 完成条件**：配对测试T233转绿，ruff/架构检查与相关回归通过。

- [x] **T235 · 全新安装viewer：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_bootstrap.py`\
  **逻辑 / 测试上下文**：全新库内置标准viewer纯可见标记/等级持久，任何已有Catalog(含非CURRENT草稿)不经bootstrap静默改写。\
  **依赖**：T218\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T236 · 新安装标准可见模型初始化**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/catalog_bootstrap.py`\
  **逻辑 / 测试上下文**：_seed_control_plane保存P1元数据；旧安装由停服迁移/显式发布处理，不用bootstrap改CURRENT。\
  **依赖**：T235\
  **配对测试**：T235\
  **验证 / 完成条件**：配对测试T235转绿，ruff/架构检查与相关回归通过。

- [x] **T237 · 资源实际权限DTO：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_resource_dto.py`\
  **逻辑 / 测试上下文**：真实grantable/roster/模式上下文dict返回目标level与visibility_only，不只依赖未使用的DTO默认。\
  **依赖**：T028, T236\
  **覆盖 AC**: AC-78, AC-81, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T238 · 资源API目标化模型输出**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/resource_api.py`\
  **逻辑 / 测试上下文**：直接拼dict的get_grantable_models/list_grant_sources等使用同目标快照、level和flag；模式草稿仅摘要不造列表。\
  **依赖**：T237\
  **配对测试**：T237\
  **验证 / 完成条件**：配对测试T237转绿，ruff/架构检查与相关回归通过。

- [x] **T239 · 当前动作/新安装既有回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_f048_action_catalog_policy.py`；`src/backend/test/permission/test_f048_catalog_bootstrap.py`\
  **逻辑 / 测试上下文**：只将当前活动use断言/fixture换新合同，保原未分级、非法空、继承并集、来源撤销与edit/download限制测试目的；历史审计/迁移快照use原文不改。每卡单独提交。\
  **依赖**：T238\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T240 · 当前inactive来源/可见并集回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_inactive_model_existing_roster.py`；`src/backend/test/permission/test_f048_visibility_projection.py`\
  **逻辑 / 测试上下文**：只将当前活动use断言/fixture换新合同，保原未分级、非法空、继承并集、来源撤销与edit/download限制测试目的；历史审计/迁移快照use原文不改。每卡单独提交。\
  **依赖**：T238\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T241 · 当前FGA模型回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_f048_authorization_model.py`\
  **逻辑 / 测试上下文**：只将当前活动use断言/fixture换新合同，保原未分级、非法空、继承并集、来源撤销与edit/download限制测试目的；历史审计/迁移快照use原文不改。每卡单独提交。\
  **依赖**：T238\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T242 · 当前累积模型/预设回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_f048_model_policy.py`；`src/backend/test/permission/test_catalog_model_presets.py`\
  **逻辑 / 测试上下文**：只将当前活动use断言/fixture换新合同，保原未分级、非法空、继承并集、来源撤销与edit/download限制测试目的；历史审计/迁移快照use原文不改。每卡单独提交。\
  **依赖**：T238\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T243 · 模型切换业务配置结构**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge.py`；`src/backend/bisheng/core/database/alembic/versions/f118_knowledge_unification.py`\
  **逻辑 / 测试上下文**：新增私有nullable JsonType model_transition：生效/目标模型与原/目标索引、阶段/operation_id存业务资源；任务只读取其有效执行槽，不用job.parameters当权威。未发布DDL只加结构，升级不改老配置。\
  **依赖**：T009\
  **验证 / 完成条件**：结构/序列化/对应DDL检查及相关集成验证；真实双库结果独立记录，不以SQLite替代。

- [x] **T244 · 模型切换fixture结构对齐**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/test/fixtures/table_definitions.py`\
  **逻辑 / 测试上下文**：中央SQLite知识表补model_transition，旧记录NULL；T228同时验证新字段仍不在公共Base DTO。\
  **依赖**：T243\
  **验证 / 完成条件**：结构/序列化/对应DDL检查及相关集成验证；真实双库结果独立记录，不以SQLite替代。

- [x] **T245 · 独立重试幂等收据SQLModel**
  **类型 / Owner**：基础设施 / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_processing_retry.py`\
  **逻辑 / 测试上下文**：KnowledgeProcessingRetryReceipt唯一tenant/job/key，保存规范hash/可信请求actor_ref/expected与accepted revision/item_count/time；不把receipt塞入冻结params/snapshot或无限JSON map。原子接收重试与失败项reset同事务。\
  **依赖**：T008\
  **验证 / 完成条件**：结构/序列化/对应DDL检查及相关集成验证；真实双库结果独立记录，不以SQLite替代。

- [x] **T246 · 重试收据租户注册**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/core/database/tenant_filter.py`\
  **逻辑 / 测试上下文**：新独立表自动发现并登记tenant hook；普通查询不跨tenant，worker处理按可信上下文。\
  **依赖**：T245, T011\
  **验证 / 完成条件**：结构/序列化/对应DDL检查及相关集成验证；真实双库结果独立记录，不以SQLite替代。

- [x] **T247 · 创建前目标化授权DTO：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_prospective_dto.py`\
  **逻辑 / 测试上下文**：混合download(L1)+tool纯可见(L3)创建前后上下文同为tool level3/flagTrue，不能只资格检查scoped后仍返回raw全局level。\
  **依赖**：T238\
  **覆盖 AC**: AC-78, AC-81, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T248 · 创建前授权目标快照接线**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/prospective_grant.py`；`src/backend/bisheng/permission/application/runtime.py`\
  **逻辑 / 测试上下文**：prospective port显式传resource_type并返回目标化snapshots，context输出flag，原scope/管理边界保留。\
  **依赖**：T247\
  **配对测试**：T247\
  **验证 / 完成条件**：配对测试T247转绿，ruff/架构检查与相关回归通过。

- [x] **T249 · 受控可见标记动作往返：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_visibility_provenance.py`\
  **逻辑 / 测试上下文**：真实Catalog保原marker与level：先加edit暂非纯可见，再删edit返回tool纯可见；原Source仍可REMOVE，HTTP不能新造marker。\
  **依赖**：T248, T259\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T250 · 保留纯可见provenance**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/model_policy.py`；`src/backend/bisheng/permission/domain/services/grant_source_service.py`\
  **逻辑 / 测试上下文**：受控原types/visibility_level持续保存，只有目标当前适用动作空才启用pure flag/原level；具体动作存在时用非pure规则，不永久删原provenance。\
  **依赖**：T249\
  **配对测试**：T249\
  **验证 / 完成条件**：配对测试T249转绿，ruff/架构检查与相关回归通过。

- [x] **T251 · CURRENT Scope完整性：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_catalog_integrity.py`\
  **逻辑 / 测试上下文**：删全部/部分SQL Scope但保CURRENT/auth/checksum须fail closed，合法窄scope保留，全部effective动作关闭的已验空scope合法，readiness不得接受未验快照。\
  **依赖**：T250\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：记录真实红阶段；不得在测试任务修改实现。

- [x] **T252 · CURRENT canonical完整性校验**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/control_state.py`；`src/backend/bisheng/permission/application/runtime.py`\
  **逻辑 / 测试上下文**：按发布同一canonical规则重算SQL动作/模型/元数据及派生一致性，与存储release checksum核对；缺Scope不可静态扩回。不得强等静态全集；保持已验证空与未验缺数据之别。\
  **依赖**：T251\
  **配对测试**：T251\
  **验证 / 完成条件**：配对测试T251转绿，ruff/架构检查与相关回归通过。

- [x] **T253 · Owner核验收据来源：先写测试**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_verification.py`\
  **逻辑 / 测试上下文**：伪造VerifiedTarget/receipt、dataclasses.replace、跨Verifier、旧事务重放均拒；真实Owner必须被调用；跨租户共享反查只能使用实际Owner核验的拥有租户。\
  **依赖**：T018\
  **覆盖 AC**: AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：记录真实红阶段并独立提交；测试任务不修改实现。

- [x] **T254 · 受信Verifier签发同事务收据**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/target_verification.py`；`src/backend/bisheng/resource_reference/application/contracts.py`\
  **逻辑 / 测试上下文**：由ReferenceTargetVerifier调用注册Owner，按完整目标组/来源/事务验证，并登记原receipt对象；不允许调用方仅声明已核验目标。\
  **依赖**：T253\
  **配对测试**：T253\
  **验证 / 完成条件**：配对回归、ruff、架构检查和diff-check通过；记录实际环境限制。

- [x] **T255 · 绑定与共享反查消费受信收据**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/bindings.py`；`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：Bindings与Repository注入同一个Verifier，拒绝非其本事务发行对象；共享反查不得由调用方自报目标租户或issuer。\
  **依赖**：T254\
  **配对测试**：T253\
  **验证 / 完成条件**：配对回归、ruff、架构检查和diff-check通过；记录实际环境限制。

- [x] **T256 · 引用测试接入真实核验链**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_repo.py`；`src/backend/test/knowledge_unification/test_ref_replace.py`\
  **逻辑 / 测试上下文**：将fixture接入实际Owner调用/Verifier发行，保留原租户、失效、部分修复和原生async断言。\
  **依赖**：T255\
  **覆盖 AC**: AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：配对回归、ruff、架构检查和diff-check通过；记录实际环境限制。

- [x] **T257 · 删除中目标的同步写围栏：先写测试**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_deleting_fence.py`\
  **逻辑 / 测试上下文**：旧/新集合任一DELETING时保持槽、移除槽、effective=False均拒；业务row/引用/root revision整笔回滚；INVALID_DELETED后仍可修复，读取DELETING正常。\
  **依赖**：T256\
  **覆盖 AC**: AC-88, AC-89, AC-90, AC-91, AC-92\
  **验证 / 完成条件**：记录真实红阶段并独立提交；测试任务不修改实现。

- [x] **T258 · 冻结删除计划期间引用写入**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/bindings.py`\
  **逻辑 / 测试上下文**：真实Verifier检查后、source/root写入前，DELETING一律10999/reference_target_deleting。已删除或冻结legacy的原槽部分修复规则不变；不扩worker外部IO竞态范围。\
  **依赖**：T257\
  **配对测试**：T257\
  **验证 / 完成条件**：配对回归、ruff、架构检查和diff-check通过；记录实际环境限制。

- [x] **T259 · 创建前授权Runtime Port签名对齐**
  **类型 / Owner**：基础设施 / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/ports.py`\
  **逻辑 / 测试上下文**：get_prospective_context增加与Runtime一致的可选resource_type关键字，旧零参兼容；具体目标DTO由T248负责，不在Port定义业务行为。\
  **依赖**：T248\
  **验证 / 完成条件**：配对回归、ruff、架构检查和diff-check通过；记录实际环境限制。

- [x] **T260 · 重试收据通用审计字段**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_processing_retry.py`\
  **逻辑 / 测试上下文**：不可变收据保留accepted_at语义，补齐新表约定create_time/update_time；不替代accepted_job_revision排序，也不建立任务模型绑定。\
  **依赖**：T245, T246\
  **验证 / 完成条件**：本地基础结构9项、ruff及arch-guard通过，提交d89532c6f；真实双库待集成环境。

- [x] **T261 · 通用引用阻断中英文提示**
  **类型 / Owner**：前端 / INT\
  **写入文件**：`src/frontend/packages/locales/src/api_errors/en.json`；`src/frontend/packages/locales/src/api_errors/zh-Hans.json`\
  **逻辑 / 测试上下文**：10995被文件/目录/clear共同使用，移除通用强删建议，改为先到相关业务调整引用；强删说明仅由支持force的具体确认UI展示。\
  **依赖**：T231\
  **验证 / 完成条件**：相关定向回归、三语漂移或静态检查通过，单卡独立提交，不降低原有效/无效边界。

- [x] **T262 · 通用引用阻断日语提示**
  **类型 / Owner**：前端 / INT\
  **写入文件**：`src/frontend/packages/locales/src/api_errors/ja.json`\
  **逻辑 / 测试上下文**：同步T261中性提示，三语键/语义一致；未改变错误码或HTTP状态。\
  **依赖**：T261, T232\
  **验证 / 完成条件**：相关定向回归、三语漂移或静态检查通过，单卡独立提交，不降低原有效/无效边界。

- [x] **T263 · CURRENT真实发布hash回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_control_snapshot.py`；`src/backend/test/knowledge_unification/test_perm_bootstrap.py`\
  **逻辑 / 测试上下文**：CURRENT fixture使用真实发布canonical pair hash；既有CURRENT未被bootstrap改写比较真实初始值，不能以假hash绕过新校验，不改历史审计/迁移fixture。\
  **依赖**：T252\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：相关定向回归、三语漂移或静态检查通过，单卡独立提交，不降低原有效/无效边界。

- [x] **T264 · provenance与prospective回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_policy.py`；`src/backend/test/permission/test_prospective_grant_application.py`\
  **逻辑 / 测试上下文**：受控marker新增动作后仍保留provenance；原prospective mock接可选resource_type及只读visibility_only字段，保留原目标scope断言目的。\
  **依赖**：T263, T259\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：相关定向回归、三语漂移或静态检查通过，单卡独立提交，不降低原有效/无效边界。

- [x] **T265 · 等价整数URL管理租户pin：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_management_paths.py`\
  **逻辑 / 测试上下文**：真实ASGI请求覆盖4个新高级写端点，编码+7/空白7仍要求预期租户header，缺header400/不匹配409/匹配200；资源权限由后续Owner校验。\
  **依赖**：T221\
  **覆盖 AC**: AC-04, AC-05, AC-35, AC-66, AC-84\
  **验证 / 完成条件**：记录真实红绿、固定快照复核与相关组合回归；源实现不超过两文件，未执行环境如实列明。

- [x] **T266 · 高级管理路径范围完整匹配**
  **类型 / Owner**：后端 Middleware / INT\
  **写入文件**：`src/backend/bisheng/common/middleware/admin_scope.py`\
  **逻辑 / 测试上下文**：仅两条F118高级路径space段改为非斜杠段，由路由校验int；普通文件写、读取、v2保持原header合同。\
  **依赖**：T265\
  **配对测试**：T265\
  **验证 / 完成条件**：记录真实红绿、固定快照复核与相关组合回归；源实现不超过两文件，未执行环境如实列明。

- [x] **T267 · 旧create原始ORM出站隔离：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_legacy_knowledge_wire.py`\
  **逻辑 / 测试上下文**：实际旧create函数经mock Owner返回Knowledge→Any envelope序列化，六内部字段不得出站；SQLite commit/SELECT属性仍完整保留。\
  **依赖**：T243, T244\
  **覆盖 AC**: AC-65, AC-66, AC-68\
  **验证 / 完成条件**：记录真实红绿、固定快照复核与相关组合回归；源实现不超过两文件，未执行环境如实列明。

- [x] **T268 · Knowledge内部列统一排除wire输出**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge.py`\
  **逻辑 / 测试上下文**：六内部列Field exclude JSON，仍是ORM列/属性，不只靠从Base移字段保护；公开高级DTO由Owner显式构造，副本default后续按专用DTO复制。\
  **依赖**：T267\
  **配对测试**：T267\
  **验证 / 完成条件**：记录真实红绿、固定快照复核与相关组合回归；源实现不超过两文件，未执行环境如实列明。

- [x] **T269 · 正常启动不改已发布CURRENT：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_startup_integrity.py`\
  **逻辑 / 测试上下文**：合法窄scope、合法全disabled空effective scope及fresh bootstrap经过真实initialize不在线补范围、不破canonical校验；禁止以静态范围恢复fallback。\
  **依赖**：T264\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：记录真实红绿、固定快照复核与相关组合回归；源实现不超过两文件，未执行环境如实列明。

- [x] **T270 · 停用启动时在线补CURRENT范围**
  **类型 / Owner**：后端 Application / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/process_runtime.py`；`src/backend/bisheng/permission/application/catalog_bootstrap.py`\
  **逻辑 / 测试上下文**：停止旧ensure_linsight_skill_action_scopes改写已发布CURRENT；范围变更走正式发布/停服迁移，fresh初始化已完整；确认无真实caller后删除死helper。\
  **依赖**：T269\
  **配对测试**：T269\
  **验证 / 完成条件**：记录真实红绿、固定快照复核与相关组合回归；源实现不超过两文件，未执行环境如实列明。

- [x] **T271 · 既有授权roster显式scope回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_inactive_model_existing_roster.py`\
  **逻辑 / 测试上下文**：合法CURRENT mock显式声明edit/manage_permission对knowledge_space范围；不恢复生产静态fallback，不更改原inactive来源可撤销断言。\
  **依赖**：T264\
  **覆盖 AC**: AC-78, AC-79, AC-80, AC-81\
  **验证 / 完成条件**：记录真实红绿、固定快照复核与相关组合回归；源实现不超过两文件，未执行环境如实列明。

- [x] **T272 · 新安装Skill范围与退役helper回归适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_f048_catalog_bootstrap.py`\
  **逻辑 / 测试上下文**：删除仅断言已退役在线补CURRENT helper的旧用例，保留并加强fresh完整Skill scope；T269覆盖真实startup合法窄/空scope不改且ready。\
  **依赖**：T270, T239\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：新旧初始化相关回归和新startup测试通过，不复活在线改CURRENT逻辑；独立提交。

- [x] **T273 · 既有API Runtime注入断言适配**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_f048_api_process_runtime.py`\
  **逻辑 / 测试上下文**：基线3ede归档已复现旧SkillAdapter无_loader导致该例失败，相关Skill/API装配源0diff；仅Skill分支强断言adapter.runtime为facade且非state，其余9类继续逐项校验原loader注入身份，不删或放宽断言。\
  **依赖**：T270, T272\
  **覆盖 AC**: AC-78, AC-83\
  **验证 / 完成条件**：独立提交当前接口fixture适配，重跑与process_runtime改动直接相关API/Worker组合；保留基线归因日志，不改Skill业务源。

- [x] **T274 · 知识目标Owner：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_knowledge_reference_owner.py`\
  **逻辑 / 测试上下文**：实际space/file归属锁、type0/1/3、祖先tombstone、原槽legacy及nativeasync，不造tenant。\
  **依赖**：T258\
  **覆盖 AC**: AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T275 · 知识目标Owner及外部事务Repository**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/reference_target_repository.py`；`src/backend/bisheng/knowledge/application/reference_target_owner.py`\
  **逻辑 / 测试上下文**：候选space→file完整组有序current locks，变化回滚；missing仅原证据可解释；由Verifier调用签发真实receipt。\
  **依赖**：T274, T278\
  **配对测试**：T274\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T276 · 模型目标Owner与合法共享：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_reference_owner.py`\
  **逻辑 / 测试上下文**：model/server一致tenant、真实Root→Child共享与继承默认、缺失证据、不因offline清绑定，原生async。\
  **依赖**：T258\
  **覆盖 AC**: AC-71, AC-73, AC-74, AC-87, AC-89\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T277 · 模型目标Owner与原生共享策略**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`；`src/backend/bisheng/llm/application/reference_target_owner.py`\
  **逻辑 / 测试上下文**：serverIDs→modelIDs完整锁；async共享经permission application与同Session实际继承配置，异常不静默缩窄；sync外租户无可信原生共享证据明确失败，MIG可注入冻结证明。\
  **依赖**：T276, T278\
  **配对测试**：T276\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T278 · 冻结legacy证据应用端口**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/evidence.py`\
  **逻辑 / 测试上下文**：resolve/aresolve接Session+精确SourceKey/TargetKey/run/key，不收HTTP证据，不猜ledger阶段；同target多slot证据键一致。\
  **依赖**：T258\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T279 · 业务绑定事务准备：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_binding_write_runtime.py`\
  **逻辑 / 测试上下文**：targets→真实source root回调→root/source CAS，值快照防identity-map覆盖，旧缺index拒、deleting先拒、外部事务rollback。\
  **依赖**：T258\
  **覆盖 AC**: AC-87, AC-88, AC-89, AC-90, AC-91, AC-92\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T280 · 同事务准备/替换与显式Runtime访问**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/write_runtime.py`；`src/backend/bisheng/resource_reference/application/access.py`\
  **逻辑 / 测试上下文**：Runtime(repo,verifier)；sync/async prepare+apply，真实new_source才初始化。async getter未装配10994，不装测试fallback，不自行commit。\
  **依赖**：T279\
  **配对测试**：T279\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T281 · 来源执行及失效核验回归**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_reference_source_validation.py`\
  **逻辑 / 测试上下文**：T280已有实现首轮即绿；当前业务摘要与ready来源对照，inactive/失效不能运行，无已指定目标时不从历史参数fallback，runtime缺装配失败。\
  **依赖**：T280\
  **覆盖 AC**: AC-37, AC-68, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T282 · 助手明确模型ID默认回退：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_entry.py`\
  **逻辑 / 测试上下文**：Agent模型初始化对明确已指定缺失ID拒绝，合法空配置沿原业务默认；完整source/知识引用运行准入保留T283，不以本卡替代。\
  **依赖**：T046, T281\
  **覆盖 AC**: AC-37, AC-68, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T283 · 助手Agent初始化失效准入**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/api/services/assistant_agent.py`\
  **逻辑 / 测试上下文**：init/run/stream以原login_user与可选外部Session核当前配置引用，使用同快照links，不从invoke_user_id重建person；缓存配置不匹配明确10998。\
  **依赖**：T366\
  **配对测试**：T366\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T284 · 工作流根软删入口：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_root_entry.py`\
  **逻辑 / 测试上下文**：真实DELETE /flows进入业务Service，目标围栏先于FGA投影，F004软删root/versions及全部引用同事务。\
  **依赖**：T040, T309\
  **覆盖 AC**: AC-68, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T285 · 工作流根删除Router委托**
  **类型 / Owner**：后端 API / WF\
  **写入文件**：`src/backend/bisheng/api/services/flow.py`；`src/backend/bisheng/api/v1/flows.py`\
  **逻辑 / 测试上下文**：Endpoint委托T040统一删除Service，不绕过绑定事务/冻结计划，不再独立DAO提前提交。\
  **依赖**：T284, T314, T318\
  **配对测试**：T284\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T286 · 工作流首次v0创建：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_create.py`\
  **逻辑 / 测试上下文**：真实root/v0创建、空来源集合、模型绑定失败全部回滚，传record给权限adapter无未commit重载，投影成功后唯一SQLcommit。\
  **依赖**：T034, T280, T299\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T287 · 工作流首次创建入口接线**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/v1/workflow.py`；`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：Router原创建委托Service，新增真实root/自增v0与R2同事务；仅新leaf允许先flush拿ID，随后真实root状态复核，不先commit业务绕过投影。\
  **依赖**：T286, T291\
  **配对测试**：T286\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T288 · 冻结ledger证据读取：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_legacy_reference_evidence.py`\
  **逻辑 / 测试上下文**：仅原Source/target已登记legacy、同run和证据key、冻结descriptor/hash及阶段可出具proof；错tenant/错key/未冻结拒，nativeasync。\
  **依赖**：T278, T293\
  **覆盖 AC**: AC-89, AC-91, AC-93\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T289 · 原legacy引用冻结账本适配器**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/reference_legacy_evidence_repository.py`；`src/backend/bisheng/knowledge/application/reference_legacy_evidence.py`\
  **逻辑 / 测试上下文**：外部Session核原引用+同tenant migration run与持久baseline/plan descriptors，不猜phase，不在REF导入知识ORM，不读取本机文件。\
  **依赖**：T288\
  **配对测试**：T288\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T290 · 生产Owner装配与双进程注册：先写测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_reference_composition.py`\
  **逻辑 / 测试上下文**：真实Owner/共享/legacy adapter同Verifier，API和worker均安装；未装配fail closed，无生产fake/ permissive默认。\
  **依赖**：T275, T277, T280, T289\
  **覆盖 AC**: AC-87, AC-88, AC-89\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T291 · API生产引用装配**
  **类型 / Owner**：后端 Composition / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/composition.py`；`src/backend/bisheng/main.py`\
  **逻辑 / 测试上下文**：composition root仅导入业务application工厂，显式注入真实Owner和冻结证据Reader；API启动注册，Reference核心不反向读业务ORM。\
  **依赖**：T290\
  **配对测试**：T290\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T292 · Worker生产引用装配**
  **类型 / Owner**：后端 Composition / INT\
  **写入文件**：`src/backend/bisheng/worker/main.py`\
  **逻辑 / 测试上下文**：worker初始化安装同composition，为异步业务写端提供真实runtime；不新增迁移健康gate。\
  **依赖**：T291\
  **配对测试**：T290\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T293 · 迁移冻结阶段与artifact描述合同**
  **类型 / Owner**：基础设施 / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_unification_run.py`\
  **逻辑 / 测试上下文**：追加阶段枚举与冻结baseline/plan descriptor约定（object_key/sha256）；不改既有列或default，不执行数据迁移。\
  **依赖**：T010\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T294 · 助手失效关联原ID出站：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_reference_view.py`\
  **逻辑 / 测试上下文**：实际Info读取不因目标行缺失而丢原关联ID，提供引用状态；不合成假的KnowledgeRead/owner/name，不泄露无权目标详情。\
  **依赖**：T368, T365\
  **覆盖 AC**: AC-68, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T295 · 助手关联状态兼容DTO**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/api/v1/schemas.py`；`src/backend/bisheng/api/services/assistant.py`\
  **逻辑 / 测试上下文**：在原Info协议显式给原knowledge IDs和状态，旧有效知识列表保留，新增knowledge_ids/reference_states的state与is_valid展示字段，缺失引用可见但不伪造资源元数据或公开内部authority字段。\
  **依赖**：T294, T368\
  **配对测试**：T294\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T296 · 助手描述流既有回归适配**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/assistant/test_assistant_description_stream.py`\
  **逻辑 / 测试上下文**：等价调整旧DAO mock到事务helper，不删除描述流业务断言，不以mock代替新R2原子性测试。\
  **依赖**：T046\
  **覆盖 AC**: AC-68, AC-88\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T297 · 助手发布知识模型错误回归适配**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/assistant/test_publish_knowledge_embedding_error.py`\
  **逻辑 / 测试上下文**：既有发布错误断言适配统一事务/引用准入，不放宽10996/现有Embedding错误原目的。\
  **依赖**：T046, T302\
  **覆盖 AC**: AC-37, AC-68, AC-91\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T298 · 工作流名称查重Repository：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_transaction.py`\
  **逻辑 / 测试上下文**：真实tenant/user/WORKFLOW类型及版本名称精确查重，不混sync旧DAO。\
  **依赖**：T034\
  **覆盖 AC**: AC-68, AC-87, AC-88\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T299 · 工作流名称查询Repository**
  **类型 / Owner**：后端 Repository / WF\
  **写入文件**：`src/backend/bisheng/workflow/domain/repositories/workflow_version_repository.py`\
  **逻辑 / 测试上下文**：新增外部Session候选名称查询，旧DAO0diff，调用方再持root锁复核。\
  **依赖**：T298\
  **配对测试**：T298\
  **验证 / 完成条件**：记录实际红绿与独立复核，相关回归/ruff/架构/全提交diff-check通过；不把SQLite证明当真实双库或中间件验收。

- [x] **T300 · 丢失root guard跨版本保护：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_binding_write_runtime.py`；`src/backend/test/knowledge_unification/test_ref_replace.py`\
  **逻辑 / 测试上下文**：存在任意同root来源集合但guard丢失时，不得重建counter；零引用/inactive/兄弟version同样拒绝。\
  **依赖**：T280\
  **覆盖 AC**: AC-87, AC-88, AC-89\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T301 · root guard完整性拒绝静默重置**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/resource_reference/application/write_runtime.py`；`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：Runtime与底层advance均核同root任意来源存在性，缺guard报10994。\
  **依赖**：T300\
  **配对测试**：T300\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T302 · 显式模型ID缺失禁止默认回退**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/api/services/assistant_agent.py`\
  **逻辑 / 测试上下文**：仅真实空选择解析默认；明确指定不存在ID立即失败，不以本卡代替T283的全部执行准入。\
  **依赖**：T282\
  **配对测试**：T282\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T303 · 工作流root锁后当前读：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_save.py`；`src/backend/test/knowledge_unification/test_wf_transaction.py`\
  **逻辑 / 测试上下文**：模拟已有snapshot的旧version/list，持root锁后必须锁定当前读，避免RR旧数据覆盖。\
  **依赖**：T036\
  **覆盖 AC**: AC-87, AC-88, AC-89\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T304 · 工作流版本当前读接线**
  **类型 / Owner**：后端 Repository / WF\
  **写入文件**：`src/backend/bisheng/workflow/domain/repositories/workflow_version_repository.py`；`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：mutation的version及版本manifest显式for_update，锁后重新取真实值；不是仅populate_existing。\
  **依赖**：T303\
  **配对测试**：T303\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T305 · 工作流管理选中租户回归**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_management_scope.py`\
  **逻辑 / 测试上下文**：JWT home与server pin不同，六管理写路径用可信当前tenant，原actor保持。\
  **依赖**：T304, T287\
  **覆盖 AC**: AC-68, AC-79, AC-87, AC-88\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T306 · 工作流可信当前租户写入**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：不从JWT home替代已校验的management tenant；新Source与业务root同一具体tenant。\
  **依赖**：T305\
  **配对测试**：T305\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T307 · 助手管理选中租户和typed默认回归**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_management_scope.py`\
  **逻辑 / 测试上下文**：两层真实tenant、typed default，超管JWT home1选择101，创建/修改/删除及默认模型均按当前tenant且身份不变；首轮即绿，登记为既有正确行为证明。\
  **依赖**：T046\
  **覆盖 AC**: AC-68, AC-79, AC-87, AC-88\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T308 · 助手租户pin路径核对**
  **类型 / Owner**：核对 / AS\
  **写入文件**：`src/backend/bisheng/assistant/domain/repositories/assistant_repository.py`；`src/backend/bisheng/api/services/assistant.py`\
  **逻辑 / 测试上下文**：T307首轮即绿：外部Session repository已使用get_tenant_id，default getter原已取当前租户；本卡仅复核，无伪造修复提交或改actor。\
  **依赖**：T307\
  **配对测试**：T307\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T309 · 整根多来源原子替换：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_batch.py`\
  **逻辑 / 测试上下文**：全target预锁后逐source验原证据，统一root manifest，第二source失败全回滚；不跨source借legacy。\
  **依赖**：T301\
  **覆盖 AC**: AC-68, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T310 · Verifier多来源完整物理预锁合同**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/resource_reference/application/contracts.py`；`src/backend/bisheng/resource_reference/application/target_verification.py`\
  **逻辑 / 测试上下文**：新增内部batch预锁端口/计划；预锁不发资格receipt，按原source/version另验并签原收据，晚出现新parent/server拒绝。\
  **依赖**：T309, T312, T313\
  **配对测试**：T309\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T311 · 实际Owner完整批量预锁：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_knowledge_reference_owner.py`；`src/backend/test/knowledge_unification/test_model_reference_owner.py`\
  **逻辑 / 测试上下文**：全空间→文件、全server→模型含继承默认辅助依赖，依赖集合漂移拒，不用先逐source上锁假冒全局顺序。\
  **依赖**：T309\
  **覆盖 AC**: AC-87, AC-88, AC-89\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T312 · 知识Owner完整批量物理锁**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/knowledge/application/reference_target_owner.py`；`src/backend/bisheng/knowledge/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：同事务预锁完整空间/文件，计划比对拒晚新增依赖，保持各来源证据隔离。\
  **依赖**：T311\
  **配对测试**：T311\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T313 · 模型Owner完整批量物理锁**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/llm/application/reference_target_owner.py`；`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：含共享继承默认实际依赖的server/model锁计划；预锁不含共享资格，资格稍后按来源当前核验。\
  **依赖**：T311\
  **配对测试**：T311\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T314 · 多来源准备与一次事务替换**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/resource_reference/application/batch.py`\
  **逻辑 / 测试上下文**：非空同tenant/type/root请求规范顺序，全目标union物理预锁→逐source实际Owner资格及receipt→真实root manifest回调→guard/source CAS；apply不自行commit。\
  **依赖**：T309, T310, T312, T313, T318\
  **配对测试**：T309\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T315 · 助手新增知识可见性：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_knowledge_selection.py`；`src/backend/test/knowledge_unification/test_as_bindings.py`\
  **逻辑 / 测试上下文**：新增slot/type/id才校验visible：0/1旧容器与3空间分别真实type，原actor窄credential拒绝，旧隐藏/invalid可保持或移除。\
  **依赖**：T046\
  **覆盖 AC**: AC-37, AC-79, AC-83, AC-87, AC-91, AC-92\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T316 · 助手新增知识关联可见性准入**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/assistant/domain/repositories/assistant_repository.py`；`src/backend/bisheng/api/services/assistant.py`\
  **逻辑 / 测试上下文**：持targets+root后，核旧配置digest，new-old集合以同Session真实Knowledge.type选择sole visible gate，不新增模型动作。\
  **依赖**：T315\
  **配对测试**：T315\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T317 · 同root完整来源索引盘点：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_batch.py`；`src/backend/test/knowledge_unification/test_ref_repo.py`\
  **逻辑 / 测试上下文**：包含inactive/零引用所有版本，严格tenant/type/root与规范顺序，FOR UPDATE当前读；root manifest不完整拒。\
  **依赖**：T310\
  **覆盖 AC**: AC-68, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T318 · 同root全部来源集合Repository**
  **类型 / Owner**：后端 Repository / TARGET\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：list/alist_source_sets_for_root，保留所有终态/零引用集合而不是只活跃项，外部Session无commit。\
  **依赖**：T317\
  **配对测试**：T317\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T319 · 停用租户保留模型绑定事实：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_reference_owner.py`\
  **逻辑 / 测试上下文**：migration/native Owner能核已保存停用租户模型归属与FrozenSharing，业务访问门槛不被目标事实层重定义。\
  **依赖**：T313\
  **覆盖 AC**: AC-71, AC-73, AC-89\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T320 · 模型事实层与租户可登录状态分离**
  **类型 / Owner**：后端 Repository / TARGET\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：删除目标事实层active限制，保真实Root/Child父子拓扑与共享证明；外层原业务disabled准入保持。\
  **依赖**：T319\
  **配对测试**：T319\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T321 · 助手重复ONLINE仍验证引用：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_bindings.py`\
  **逻辑 / 测试上下文**：已ONLINE重复请求覆盖missing index、配置漂移、deleted模型、deleting；有效noop不增修订/投影/初始化。\
  **依赖**：T316\
  **覆盖 AC**: AC-37, AC-68, AC-89, AC-91\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T322 · 重复ONLINE完整准入且保持幂等**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/api/services/assistant.py`\
  **逻辑 / 测试上下文**：ONLINE始终targets→root refresh→旧digest→source valid，再判断状态不变；OFFLINE原noop与实际停止语义保持。\
  **依赖**：T321\
  **配对测试**：T321\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T323 · 工作流legacy use列表兼容：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_legacy_action.py`\
  **逻辑 / 测试上下文**：原default use在Catalog退役后不能提前过滤丢资源；实际Facade返回visible拒绝也不得fallback。\
  **依赖**：T038\
  **覆盖 AC**: AC-78, AC-79, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T324 · legacy列表请求统一可见性解释**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/workflow.py`\
  **逻辑 / 测试上下文**：旧字面use经唯一Facade解释visible，Catalog/FGA不恢复use；保留原action map回归。\
  **依赖**：T323\
  **配对测试**：T323\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T325 · F004删除既有回归适配**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/workflow/test_flow_soft_delete.py`\
  **逻辑 / 测试上下文**：Router委托后改为真实Service+引用SQL fixture，保留既有auth、软删、清理和二次删除断言。\
  **依赖**：T285\
  **覆盖 AC**: AC-68, AC-87, AC-88\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T326 · 工作流畸形引用业务错误：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_save.py`\
  **逻辑 / 测试上下文**：非空非法target ID、重复node key返回稳定业务错误，不将SQL/Runtime异常当提取错误吞掉。\
  **依赖**：T036\
  **覆盖 AC**: AC-87, AC-88, AC-91\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T327 · 提取器格式错误的Service边界映射**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：仅TypeError/ValueError转10996 workflow_reference_invalid；不宽泛兜底异常或改自动提取语义。\
  **依赖**：T326\
  **配对测试**：T326\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T328 · 真实运行与共享读取入口交接清单**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/execution-entrypoints.md`\
  **逻辑 / 测试上下文**：登记实际WS、开放invoke、评测、未保存preview enqueue与payload事实；T041/T042/T283/T295不以保存接线假完成，下一波先冻结SourceExecution/SourceOwnerReadScope。\
  **依赖**：T285, T302\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T329 · 工作流新增知识可见性：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_knowledge_selection.py`\
  **逻辑 / 测试上下文**：新增source/新版本/copy所有目标新验visible，原槽同ID隐藏可保留或移除，不借其他version；原actor及credential范围不扩大。\
  **依赖**：T306\
  **覆盖 AC**: AC-37, AC-79, AC-83, AC-87, AC-91, AC-92\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T330 · 工作流新增知识关联可见性准入**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/workflow/domain/repositories/workflow_version_repository.py`；`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：实际Knowledge.type同Session当前读，0/1→knowledge_library、3→knowledge_space，new-old精确集合才额外require visible，模型无新动作。\
  **依赖**：T329\
  **配对测试**：T329\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T331 · 撤销模型共享后原槽修复：先写测试**
  **类型 / Owner**：测试 / TARGET\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_revoked_sharing.py`\
  **逻辑 / 测试上下文**：真实SQL sync/async原slot保留、改绑own、清除/删除来源可行；新槽/copy/version/batch借证据及执行拒绝，共享异常不降级。\
  **依赖**：T320, T314\
  **覆盖 AC**: AC-68, AC-87, AC-88, AC-91, AC-92\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T332 · 内部绑定资格与原槽身份核验**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/resource_reference/application/contracts.py`；`src/backend/bisheng/resource_reference/application/bindings.py`\
  **逻辑 / 测试上下文**：VerifiedReferenceTarget新增派生new_binding_allowed默认True，仅MODEL/VALID可False，R2按精确source/version/slot/target允许保持，不改状态/表/摘要。\
  **依赖**：T331\
  **配对测试**：T331\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T333 · 共享撤销后的Owner和执行门槛**
  **类型 / Owner**：后端 Application / TARGET\
  **写入文件**：`src/backend/bisheng/resource_reference/application/write_runtime.py`；`src/backend/bisheng/llm/application/reference_target_owner.py`\
  **逻辑 / 测试上下文**：仅明确共享deny且有同source/version真实原target可发eligible False；可存原槽或移除，运行发布拒绝，异常不得转deny。\
  **依赖**：T332\
  **配对测试**：T331\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T334 · root无来源集合的原始引用残留：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_root_entry.py`\
  **逻辑 / 测试上下文**：缺set的terminal raw refs、unknown source raw refs、set空摘要却残rows均投影前10994；合法旧已删无set且无rows不被阻断。\
  **依赖**：T285\
  **覆盖 AC**: AC-68, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T335 · 同root原始引用全量读取**
  **类型 / Owner**：后端 Repository / WF\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：临时转交REF Repo唯一Owner，list/alist_source_references_for_root严格tenant/type/id，含terminal，无inner commit、支持锁定当前读。\
  **依赖**：T334\
  **配对测试**：T334\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T336 · 整根删除核完整原始引用集合**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/flow.py`\
  **逻辑 / 测试上下文**：targets/root/guard后核所有raw行对应真实SQLversion+ready/set revision+digest，terminal不得raw；未知数据拒绝且不自动清理。\
  **依赖**：T335\
  **配对测试**：T334\
  **验证 / 完成条件**：独立固定快照复核、主agent集成回归和L1元数据/范围核验；本地SQLite或静态验证不等价真实双库/中间件/E2E。

- [x] **T337 · 工作流自动租户过滤与pin核验：先写测试**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_transaction.py`\
  **逻辑 / 测试上下文**：真实C3 listener验证SELECT自动注入、跨tenant拒绝、bypass失败及当前锁读，不靠手写tenant谓词使fixture变绿。\
  **依赖**：T330\
  **覆盖 AC**: AC-79, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：独立红测后仅T338改实现，原可信pin和外部事务保持；不以SQLite证明真实MySQL/DM8锁。

- [x] **T338 · 工作流Repository统一自动租户过滤**
  **类型 / Owner**：后端 Repository / WF\
  **写入文件**：`src/backend/bisheng/workflow/domain/repositories/workflow_version_repository.py`\
  **逻辑 / 测试上下文**：普通SELECT使用strict_tenant_filter，参数pin与当前tenant/root事实核对；保留原调用签名、不新增session/commit，bulk仍显式可信tenant。\
  **依赖**：T337\
  **配对测试**：T337\
  **验证 / 完成条件**：实现与原七路径回归、ruff/架构检查通过，固定SHA独立复核。

- [x] **T339 · W2接口与技术设计同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/contracts.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/design.md`\
  **逻辑 / 测试上下文**：实际Owner/Runtime/batch、new knowledge visible、retain-only资格及冻结artifact协议同步，94AC不变。\
  **依赖**：T338, T333, T322\
  **验证 / 完成条件**：与实际源码和受测固定SHA一致，元数据/文档链接/HTML13SVG完整性及diff-check通过。

- [x] **T340 · W2依赖与并行任务同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/parallel-development.md`\
  **逻辑 / 测试上下文**：按实际提交叶子登记追加卡、hotspot唯一写入与review记录；完整执行/Info继续待办，不扩大已完成卡。\
  **依赖**：T339\
  **验证 / 完成条件**：与实际源码和受测固定SHA一致，元数据/文档链接/HTML13SVG完整性及diff-check通过。

- [x] **T341 · W2升级边界与文档索引同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/upgrade-guide.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/README.md`\
  **逻辑 / 测试上下文**：保停服后正式盘点/冻结，Reader或DDL不代表已迁移；当前进度与历史W1分开。\
  **依赖**：T340\
  **验证 / 完成条件**：与实际源码和受测固定SHA一致，元数据/文档链接/HTML13SVG完整性及diff-check通过。

- [x] **T342 · W2评审HTML及集成证据**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`docs/architecture/review/2026-11-03-bisheng-knowledge-unification-technical-review.html`；`features/v3.1.0-beta1/118-knowledge-space-unification/wave2-implementation-review.md`\
  **逻辑 / 测试上下文**：保13SVG、锚点与本地链接，记录固定SHA独立复核、主agent组合验证、L1及真实环境未执行项。\
  **依赖**：T341, T328\
  **验证 / 完成条件**：与实际源码和受测固定SHA一致，元数据/文档链接/HTML13SVG完整性及diff-check通过。

- [x] **T343 · W3运行与共享读取合同冻结**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/execution-read-contract.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/contracts.md`\
  **逻辑 / 测试上下文**：实际入口与原身份/权限范围；先targets后root、同事务外部Session、token只inspect、完整graph与临时preview，不恢复Root默认业务共享。\
  **依赖**：T342\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T344 · 只读来源与临时预览DTO合同**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_contracts.py`\
  **逻辑 / 测试上下文**：canonical不可变payload、原SourceKey/完整refs、精确purpose及只读target facts；构造DTO不授予scope。\
  **依赖**：T346\
  **配对测试**：T346\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T345 · 只读Runtime显式访问口**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_access.py`\
  **逻辑 / 测试上下文**：async getter，未装配10994，任意对象不作生产runtime。\
  **依赖**：T348\
  **配对测试**：T348\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T346 · 只读DTO边界红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_contracts.py`\
  **逻辑 / 测试上下文**：canonical UTF8摘要、token不能run、无自报tenant、temp无source、冻结tuple及derived状态。\
  **依赖**：T343\
  **覆盖 AC**: AC-87, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T347 · 原身份与凭证范围指纹适配**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/read_identity.py`\
  **逻辑 / 测试上下文**：原user对象、真实PermissionActor/OpenAPI/public principal/trace及当前tenant，拒bypass，不存原token或降格身份。\
  **依赖**：T350, T349\
  **配对测试**：T350\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T348 · 缺装配只读访问红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_access.py`\
  **逻辑 / 测试上下文**：配置缺失明确10994，无法从任意duck object取得Reader。\
  **依赖**：T343\
  **覆盖 AC**: AC-89\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T349 · 公共发布身份application端口**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/public_endpoints/application/access_context.py`\
  **逻辑 / 测试上下文**：只转出当前可信PublicApiPrincipal，不查业务资源，不新建guest授权。\
  **依赖**：T343\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T350 · 身份切换与凭证收窄红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_identity.py`\
  **逻辑 / 测试上下文**：JWT home与pin分开、SCA/PAT data scope/public资源上下文变化改变指纹，原对象不由ID重建。\
  **依赖**：T344\
  **覆盖 AC**: AC-79, AC-83, AC-87\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T351 · common工作流执行Port**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/common/interfaces/resource_execution.py`\
  **逻辑 / 测试上下文**：仅Protocol声明，实际绑定由端点业务Owner注入，不反向import domain/API；无临时source。\
  **依赖**：T343\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T352 · W3基线与唯一Owner调度登记**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/parallel-development.md`\
  **逻辑 / 测试上下文**：从d528及公共DTO checkpoint建独立WF/AS/REF工作区；root独占identity/common/composition/evaluation，业务Owner独占各自叶子。\
  **依赖**：T343\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T353 · 工作流真实SourceOwner红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_source_owner.py`\
  **逻辑 / 测试上下文**：真实root/version/current/完整graph、原visible/edit、current重验、非current与public限制，精确scope不自报tenant。\
  **依赖**：T344\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T354 · 工作流来源Owner和快照Repository**
  **类型 / Owner**：后端 Application / WF\
  **写入文件**：`src/backend/bisheng/workflow/application/reference_source_owner.py`；`src/backend/bisheng/workflow/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：真实列投影不污染外tenant identity map，source与normalize nodes/edges，targets后root/version锁并重授权。\
  **依赖**：T353\
  **配对测试**：T353\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T355 · 单节点预览准入红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_node_admission.py`\
  **逻辑 / 测试上下文**：临时节点edit、真实KN visible/模型共享、失效零运行，不造source或owner_query。\
  **依赖**：T042\
  **覆盖 AC**: AC-37, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T356 · run_once临时节点接线**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/api/services/workflow.py`\
  **逻辑 / 测试上下文**：NodeFactory执行前调用workflow facade，保原节点输入/线程规则与BaseErrorCode。\
  **依赖**：T355\
  **配对测试**：T355\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T357 · WS绑定执行Port端点红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_ws_admission.py`\
  **逻辑 / 测试上下文**：普通/public真实绑定trusted ID与原身份，public不可preview，optional version是提示非权限。\
  **依赖**：T042, T351\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T358 · 两WS端点注入绑定Port**
  **类型 / Owner**：后端 API / WF\
  **写入文件**：`src/backend/bisheng/api/v1/workflow.py`；`src/backend/bisheng/public_endpoints/api/endpoints/workflow.py`\
  **逻辑 / 测试上下文**：保guest/session/snapshot和原online，按冻结common参数传Port，不从message信tenant/root。\
  **依赖**：T357\
  **配对测试**：T357\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T359 · v2保存图及override红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_published_admission.py`\
  **逻辑 / 测试上下文**：真实saved source准入、原operator对象，深拷贝非ref override可行，ref-changing拒且零队列副作用。\
  **依赖**：T042\
  **覆盖 AC**: AC-37, AC-68, AC-87, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T360 · Published与开放入口准入接线**
  **类型 / Owner**：后端 Domain / WF\
  **写入文件**：`src/backend/bisheng/workflow/domain/services/published_workflow_service.py`；`src/backend/bisheng/open_endpoints/api/endpoints/workflow.py`\
  **逻辑 / 测试上下文**：保原v2 scopes、session及online语义，真实准入图写Redis，operator ID不降格凭证。\
  **依赖**：T359\
  **配对测试**：T359\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T361 · 平台预览携真实版本提示**
  **类型 / Owner**：前端 / WF\
  **写入文件**：`src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatPane.tsx`\
  **逻辑 / 测试上下文**：仅原初始化消息增optional execution_mode/version_id，保原UI行为；根/版本仍由服务端验证。\
  **依赖**：T358\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T362 · 助手SourceOwner与token inspect红测**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_source_owner.py`\
  **逻辑 / 测试上下文**：同Session真实root/links/ACTIVE token及资源绑定；原actor、非授权Root拒、token不能run、锁后重新授权。\
  **依赖**：T344\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-89\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T363 · 助手来源Owner与只读Repository**
  **类型 / Owner**：后端 Application / AS\
  **写入文件**：`src/backend/bisheng/assistant/application/reference_source_owner.py`；`src/backend/bisheng/assistant/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：精确列投影真实snapshot，token重验同一外部Session；不setCurrentTenant、无内层commit。\
  **依赖**：T362\
  **配对测试**：T362\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T364 · 助手准入facade红测**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_execution_admission.py`\
  **逻辑 / 测试上下文**：owned/borrowed事务、原identity，完整refs、配置links快照一致，源缺index/失效拒，运行override分离。\
  **依赖**：T363, T344, T345\
  **覆盖 AC**: AC-37, AC-68, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T365 · 助手执行与inspect facade**
  **类型 / Owner**：后端 Application / AS\
  **写入文件**：`src/backend/bisheng/assistant/application/execution_admission.py`\
  **逻辑 / 测试上下文**：内部SourceReadRuntime只读，外部Session不begin/commit，普通入口自持读事务，未装配failclosed。\
  **依赖**：T364, T381\
  **配对测试**：T364\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T366 · Agent每次执行及原凭证红测**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_runtime_admission.py`\
  **逻辑 / 测试上下文**：init/run/stream及cached source变更拒、原user与SCA/PAT收窄、无userID fallback、不扩大knowledge_auth。\
  **依赖**：T365\
  **覆盖 AC**: AC-37, AC-68, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T367 · 助手发布外部事务准入红测**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_publish_admission.py`\
  **逻辑 / 测试上下文**：before_save传外部Session避免反锁；RPC runtime temperature不污染持久digest；失效零Agent执行/回滚。\
  **依赖**：T283\
  **覆盖 AC**: AC-37, AC-68, AC-88, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T368 · 发布及RPC传原身份和Session**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/api/services/assistant.py`；`src/backend/bisheng/assistant/domain/services/published_assistant_service.py`\
  **逻辑 / 测试上下文**：before_save(session,row)、Agent原user/reference_session；不用布尔skip，自动模型修复工具不误加完整source gate。\
  **依赖**：T367\
  **配对测试**：T367\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T369 · 缓存ChatClient失配可恢复红测**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_chat_admission.py`\
  **逻辑 / 测试上下文**：原login_user传给Agent、每消息原凭证与目标重验、10998清缓存后能重建，保流与会话行为。\
  **依赖**：T283\
  **覆盖 AC**: AC-37, AC-68, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T370 · ChatClient身份传递和缓存失效**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/common/chat/client.py`\
  **逻辑 / 测试上下文**：只通过原有Agent入口传身份，无新增common反向领域import；失配清缓存，不重建普通person。\
  **依赖**：T369\
  **配对测试**：T369\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T371 · 私有只读scope发行与隔离红测**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_scope.py`\
  **逻辑 / 测试上下文**：actual Owner调用、原对象私有登记，换tx/身份/租户/purpose/复制拒、target-plan未发行不能先root重验。\
  **依赖**：T344\
  **覆盖 AC**: AC-79, AC-83, AC-87, AC-89\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T372 · SourceReadVerifier及私有scope**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_verification.py`\
  **逻辑 / 测试上下文**：独立R2外的只读authority；source/transient精准scope及target-plan前置，原身份FP校验。\
  **依赖**：T371\
  **配对测试**：T371\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T373 · scope限定索引只读红测**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_repository.py`\
  **逻辑 / 测试上下文**：真实SQLModel listener、合法跨源精确列投影、零引用/root guard/原raw refs完整，拒forge/bypass/身份切换。\
  **依赖**：T372\
  **覆盖 AC**: AC-87, AC-89\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T374 · Scoped索引Repository**
  **类型 / Owner**：后端 Repository / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/source_read_repository.py`\
  **逻辑 / 测试上下文**：exact tenant/type/id/version short bypass，no_autoflush，无ORM污染/写入；R2旧Repo不扩权限。\
  **依赖**：T373\
  **配对测试**：T373\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T375 · 实际只读TargetOwner红测**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_knowledge_read_owner.py`；`src/backend/test/knowledge_unification/test_model_read_owner.py`\
  **逻辑 / 测试上下文**：source owner tenant事实+请求actor分离，全target有序锁，deleted/deleting/legacy/sharing revoked/nativeasync，不借root默认共享。\
  **依赖**：T372, T374\
  **覆盖 AC**: AC-37, AC-68, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T376 · 知识只读TargetOwner与Repository**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/knowledge/application/source_read_target_owner.py`；`src/backend/bisheng/knowledge/domain/repositories/source_read_target_repository.py`\
  **逻辑 / 测试上下文**：实际space→file current锁、归属/tombstone与原legacy证明；每入口显式identity+同authority验scope。\
  **依赖**：T375, T379\
  **配对测试**：T375\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T377 · 模型只读TargetOwner与Repository**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/llm/application/source_read_target_owner.py`；`src/backend/bisheng/llm/domain/repositories/source_read_target_repository.py`\
  **逻辑 / 测试上下文**：实际server→models含共享默认依赖，按SourceOwnerTenant共享资格；原request actor不拿Root grant，不动现R2。\
  **依赖**：T375, T379\
  **配对测试**：T375\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T378 · Scoped冻结legacy证明红测**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_legacy.py`\
  **逻辑 / 测试上下文**：原source/target/run/key同scope，冻结descriptor及阶段；跨来源/换凭证/失败phase拒，不自造legacy/tombstone。\
  **依赖**：T372, T374\
  **覆盖 AC**: AC-89, AC-91, AC-93\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T379 · 只读legacy账本适配**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/knowledge/application/reference_read_legacy_evidence.py`；`src/backend/bisheng/knowledge/domain/repositories/reference_read_legacy_evidence_repository.py`\
  **逻辑 / 测试上下文**：scope显式identity、同Session精确列投影，复用冻结语义，无Context切换/内Session/commit。\
  **依赖**：T378\
  **配对测试**：T378\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T380 · 完整运行/inspect/preview只读Runtime红测**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_runtime.py`\
  **逻辑 / 测试上下文**：完整target→root→索引重读、revision/digest/extractor/配置变化拒、inspect/execute隔离，preview无source/index。\
  **依赖**：T374, T344\
  **覆盖 AC**: AC-37, AC-68, AC-87, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T381 · SourceReadRuntime协调**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_read.py`\
  **逻辑 / 测试上下文**：真实Owner组读取精确targets，private target-plan后重验root/index，失效执行拒、inspect不可借run，无内部事务写。\
  **依赖**：T380\
  **配对测试**：T380\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T382 · common入队前准入与副作用红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_client_admission.py`\
  **逻辑 / 测试上下文**：Port在check_status/建会话/Redis前、body换root/业务错误不变500，拒绝无副作用，原guest/snapshot不丢。\
  **依赖**：T042, T358\
  **覆盖 AC**: AC-37, AC-68, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T383 · common工作流Client注入接线**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/common/chat/clients/workflow_client.py`；`src/backend/bisheng/common/chat/manager.py`\
  **逻辑 / 测试上下文**：显式转交Port到client，仅common接口，不新增domain/API反向依赖。\
  **依赖**：T382\
  **配对测试**：T382\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T384 · 评测可信身份及来源准入红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_evaluation_reference_admission.py`\
  **逻辑 / 测试上下文**：JWT原identity、owner/tenant调度前核、真实指定version/AS当前source、拒绝在CSV/Redis/模型前，无任务模型绑定。\
  **依赖**：T042, T283\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T385 · 评测入口及执行身份接线**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/evaluation/api/endpoints/evaluation.py`；`src/backend/bisheng/evaluation/domain/services/evaluation_service.py`\
  **逻辑 / 测试上下文**：原login_user进BackgroundTasks，核真实evaluation owner/currenttenant，不凭任意ID冒充creator；各业务facade先于执行。\
  **依赖**：T384\
  **配对测试**：T384\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T386 · 生产只读装配红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_composition.py`\
  **逻辑 / 测试上下文**：实际SourceOwner/TargetOwner/identity/legacy同authority，API与worker既有register都安装，缺装配无fallback。\
  **依赖**：T354, T363, T381, T376, T377, T379, T347\
  **覆盖 AC**: AC-87, AC-89\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T387 · 生产只读Composition**
  **类型 / Owner**：后端 Composition / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/read_composition.py`；`src/backend/bisheng/resource_reference/composition.py`\
  **逻辑 / 测试上下文**：在既有API/worker register同入口装配实际只读链，不加迁移健康gate、不恢复Root业务默认共享。\
  **依赖**：T386\
  **配对测试**：T386\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T388 · W3合同与技术设计落地同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/execution-read-contract.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/design.md`\
  **逻辑 / 测试上下文**：同步真实接口/锁序/边界与未运行环境，94AC不改。\
  **依赖**：T383, T385, T387, T295, T360\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T389 · W3任务进度与并行交付同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/parallel-development.md`\
  **逻辑 / 测试上下文**：逐卡paths/依赖/配对测试与Owner准确，已完成数不代替AC验收。\
  **依赖**：T388\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T390 · W3升级与文档导航同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/upgrade-guide.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/README.md`\
  **逻辑 / 测试上下文**：Reader/执行就绪不替代停服基线冻结/回填/Coverage，记录本地验证限制。\
  **依赖**：T389\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T391 · W3 HTML与集成证据**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`docs/architecture/review/2026-11-03-bisheng-knowledge-unification-technical-review.html`；`features/v3.1.0-beta1/118-knowledge-space-unification/wave3-implementation-review.md`\
  **逻辑 / 测试上下文**：固定SHA复核、组合测试/架构delta及13SVG/锚点完整性，真实环境/E2E/迁移分开。\
  **依赖**：T390\
  **验证 / 完成条件**：实际红绿或接口结构验证、固定提交独立复核及主agent集成；不得用本地SQLite/SQL形状替代双库/真实服务/E2E。

- [x] **T392 · 临时知识类型锁后当前读红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_source_owner.py`\
  **逻辑 / 测试上下文**：实际type0→3交错，候选无锁、final当前锁与library→space原授权，不以RR旧snapshot批准。\
  **依赖**：T354\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T393 · 临时知识授权重验当前类型**
  **类型 / Owner**：后端 Application / WF\
  **写入文件**：`src/backend/bisheng/workflow/application/reference_source_owner.py`；`src/backend/bisheng/workflow/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：候选不提前锁KN，targets后final用for_update/current type，不破坏Model→KN→root顺序。\
  **依赖**：T392\
  **配对测试**：T392\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T394 · 既有run_once线程回归适配**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/workflow/test_run_once_off_event_loop.py`\
  **逻辑 / 测试上下文**：mock新准入Port返回原node/input，保offloop/tenant/工具IO全部断言并核原identity。\
  **依赖**：T356\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T395 · 分享token真实会话绑定红测**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_source_owner.py`\
  **逻辑 / 测试上下文**：真实MessageSession绑定，metadata伪造/错root/type/deleted/issuer/tenant拒，Root源与用户叶租户分开。\
  **依赖**：T363\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T396 · 助手分享查看核真实会话**
  **类型 / Owner**：后端 Application / AS\
  **写入文件**：`src/backend/bisheng/assistant/application/reference_source_owner.py`；`src/backend/bisheng/assistant/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：ACTIVE token精确会话/原C3候选，不因token新增Source业务bypass，不把现有发行ACL说成已修。\
  **依赖**：T395\
  **配对测试**：T395\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T397 · 实际Core临时payload原文集成红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_entry.py`\
  **逻辑 / 测试上下文**：真实SourceOwner/Core/Identity/SQL索引，saved对照绿、preview额外root字段违反canonical原文红。\
  **依赖**：T381, T354\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T398 · 临时快照保持实际准入输入原文**
  **类型 / Owner**：后端 Application / WF\
  **写入文件**：`src/backend/bisheng/workflow/application/reference_source_owner.py`\
  **逻辑 / 测试上下文**：临时payload仅graph/node_input，RootID/ownerTenant在专用事实字段及最终真实授权，不把Root事实硬塞客户端请求。\
  **依赖**：T397\
  **配对测试**：T397\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T399 · 工作流候选后软删错误归类红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_source_owner.py`\
  **逻辑 / 测试上下文**：root/version/临时root在候选后消失应10998，初查仍404，原auth与coverage错误不吞。\
  **依赖**：T398\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T400 · 最终重验丢失按配置变化报错**
  **类型 / Owner**：后端 Application / WF\
  **写入文件**：`src/backend/bisheng/workflow/application/reference_source_owner.py`\
  **逻辑 / 测试上下文**：仅final捕NotFound→10998，候选与其他异常原样失败。\
  **依赖**：T399\
  **配对测试**：T399\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T401 · 助手首次初始化失败缓存红测**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_chat_admission.py`\
  **逻辑 / 测试上下文**：首次10996后手修再发消息，必须重新创建并初始化，不复用未完成Agent。\
  **依赖**：T370\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T402 · Agent成功初始化后才缓存**
  **类型 / Owner**：后端 Domain / AS\
  **写入文件**：`src/backend/bisheng/common/chat/client.py`\
  **逻辑 / 测试上下文**：局部candidate成功后赋cache，保持原identity/调用流程，不加无权限fallback。\
  **依赖**：T401\
  **配对测试**：T401\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T403 · 旧knowledge_auth回归等价适配**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/api/test_assistant_knowledge_auth_gate.py`\
  **逻辑 / 测试上下文**：真实UserPayload+已准入links替退休DAO mock，保ON/OFF原断言，禁止独立DAO重读并核对象is。\
  **依赖**：T283\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T406 · WS非法mode容器形状红测**
  **类型 / Owner**：测试 / WF\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_entry.py`\
  **逻辑 / 测试上下文**：list/dict mode稳定10996且零getter/授权/数据副作用，不能TypeError500。\
  **依赖**：T042\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T407 · 执行mode按类型校验**
  **类型 / Owner**：后端 Application / WF\
  **写入文件**：`src/backend/bisheng/workflow/application/execution_admission.py`\
  **逻辑 / 测试上下文**：str/None显式校验，不hash任意WS claim；正常saved/preview不变。\
  **依赖**：T406\
  **配对测试**：T406\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T408 · 助手既有绑定fixture真实类适配**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_bindings.py`\
  **逻辑 / 测试上下文**：从真实模型类patch原三DAO方法，保全部SQL/业务断言，不为旧module alias重新引无用生产依赖。\
  **依赖**：T295\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T409 · Scope equality/hash子类克隆红测**
  **类型 / Owner**：测试 / REF\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_scope.py`\
  **逻辑 / 测试上下文**：模拟等价hash子类copy命中WeakKey，正常原scope控制继续可读；不是自造Root授权。\
  **依赖**：T372\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T410 · Scope私有发行原对象身份校验**
  **类型 / Owner**：后端 Application / REF\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_verification.py`\
  **逻辑 / 测试上下文**：私有registration weakref() is scope，不能只依赖eq=False或WeakKey membership。\
  **依赖**：T409\
  **配对测试**：T409\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T411 · 旧R2收据及反查scope子类克隆红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_verification.py`；`src/backend/test/knowledge_unification/test_ref_repo.py`\
  **逻辑 / 测试上下文**：实际SQL deleted/legacy新槽正常拒，eq/hash clone篡改VALID不得过；OwnerTargetScope clone同步/async同拒。\
  **依赖**：T410\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T412 · R2私有收据及反查scope原对象核验**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/target_verification.py`；`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：仅复现后加private weakref原对象门槛，不变公开DTO/签名/目标锁序或新W3读取实现。\
  **依赖**：T411\
  **配对测试**：T411\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [x] **T413 · 既有评测进度回归等价适配**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/evaluation/test_evaluation_progress.py`\
  **逻辑 / 测试上下文**：真实原UserPayload和新facade替旧DAO假设，保原CSV/进度/失败处理断言。\
  **依赖**：T385\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T414 · 读取legacy证据Port类型冻结**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_contracts.py`\
  **逻辑 / 测试上下文**：显式aresolve同scope/source/target/run/key/identity协议，无生产IO或授权变化。\
  **依赖**：T379\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T415 · 真实JWT web_session身份红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_evaluation_reference_admission.py`\
  **逻辑 / 测试上下文**：实际get_login_user签发web_session；正常JWT及homeTenant不同管理pin应可用，非web/伪字段和OpenAPI/Public拒。\
  **依赖**：T385\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T416 · 评测准入接受原JWT会话凭据**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/evaluation/domain/services/evaluation_service.py`\
  **逻辑 / 测试上下文**：核web_session原user/homeTenant/tokenVersion一致，管理pin独立；不重建身份或放宽eval owner/tenant。\
  **依赖**：T415\
  **配对测试**：T415\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T417 · 状态查询不可切换连接根红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_wf_client_admission.py`\
  **逻辑 / 测试上下文**：action check_status和直接调用均在会话/Redis前拒body切root，保持原client状态且10996。\
  **依赖**：T383\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T418 · 所有WF消息保持可信连接根**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/common/chat/clients/workflow_client.py`\
  **逻辑 / 测试上下文**：只补endpoint绑定root校验，状态查询不再用未经核对的body选源，不扩大worker在途/旧session治理。\
  **依赖**：T417\
  **配对测试**：T417\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T419 · 存储字段回归补显式租户fixture**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_legacy_knowledge_wire.py`\
  **逻辑 / 测试上下文**：固定旧4d49组合也复现C3缺Context，注入tenant_context(101)并保所有列/Owner/JSON隐去断言，不绕过生产C3。\
  **依赖**：T267\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T420 · W3实际入口盘点更新**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/execution-entrypoints.md`\
  **逻辑 / 测试上下文**：原W2盘点保历史语境，补W3实际入口及仍未完成范围，不把其他来源或真实环境声称完成。\
  **依赖**：T388\
  **验证 / 完成条件**：固定SHA独立复核、实际回归及主集成；本地验证不替代双库/真实服务/E2E。

- [x] **T421 · 既有自动重跑配置回归等价适配**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/common/test_workflow_auto_rerun_config.py`\
  **逻辑 / 测试上下文**：原4d49同文件2fail/12pass；补既有OpenApiConf及原wire code_node_enabled=False，保strict字典及自动重跑/异常failclosed断言，不改生产或隐藏字段。\
  **依赖**：T418\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-91\
  **验证 / 完成条件**：固定基线归因、14项绿、主agent复核单叶diff与最终组合，真实服务/E2E单列。

- [x] **T422 · W4四类来源及跨域接口合同冻结**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/business-sources-contract.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/contracts.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T391\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T423 · W4依赖与唯一叶子登记**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/parallel-development.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T424 · 原生同步scope与当前读红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_native.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T425 · 原生同步scope私有发行及target-plan**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_verification.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T424\
  **配对测试**：T424\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T426 · 原生同步索引及完整来源Runtime**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/source_read_repository.py`；`src/backend/bisheng/resource_reference/application/source_read.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T425\
  **配对测试**：T424\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T427 · 原生同步冻结legacy证据红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_native_legacy.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T426\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T428 · 原生同步来源legacy Reader**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/reference_read_legacy_evidence.py`；`src/backend/bisheng/knowledge/domain/repositories/reference_read_legacy_evidence_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T427\
  **配对测试**：T427\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T429 · 原生同步共享关系transport红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_openfga_native_shared_query.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T430 · pinned FGA原生同步窄关系查询**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/core/openfga/client.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T429\
  **配对测试**：T429\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T431 · READY同步关系应用边界红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_permission_native_relation.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T430\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T432 · 同步窄共享关系唯一应用Port**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/permission/application/relation_api.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T431\
  **配对测试**：T431\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T433 · 默认与多空间混合root原子准备红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_mixed_sources.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T434 · 混合来源变更值合同**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/contracts.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T433\
  **配对测试**：T433\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T435 · 同tenant默认及空间混合root准备**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/target_verification.py`；`src/backend/bisheng/resource_reference/application/write_runtime.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T434\
  **配对测试**：T433\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T436 · 应用版本与凭据事实外部事务红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T437 · 应用真实根版本和凭据Repository**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T436\
  **配对测试**：T436\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T438 · APP同Session解析及完整名称计划红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_resolution.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T030, T437, T477, T520\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T439 · APP模型知识真实ID冻结解析**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_resolution.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T438\
  **配对测试**：T438\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T440 · 应用真实来源及原principal红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_source_owner.py`；`src/backend/test/knowledge_unification/test_app_read_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T439, T514, T516\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T441 · 应用来源Owner与原principal身份适配**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_source_owner.py`；`src/backend/bisheng/app_publish/application/reference_read_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T440\
  **配对测试**：T440\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T442 · APP专属实际authority装配红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_reference_composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T441, T377, T379\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T443 · APP只读显式access和生产装配**
  **类型 / Owner**：实现 / INT-APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_access.py`；`src/backend/bisheng/app_publish/composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T442\
  **配对测试**：T442\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T444 · APP能力总线完整来源准入红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_model_binding.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T443, T048\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T445 · APP能力总线按冻结版本准入**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T444, T544\
  **配对测试**：T444\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T446 · 实际provider实例化前冻结ID红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_gateway_binding.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T445\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T447 · 模型gateway与range最终ID核验**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/open_api/domain/services/model_gateway_service.py`；`src/backend/bisheng/open_api/domain/services/model_range_policy.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T446\
  **配对测试**：T446\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T448 · 托管知识调用透传原principal红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_filelib_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T445\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T449 · 托管知识入口原principal接线**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T448\
  **配对测试**：T448\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T450 · 频道稳定语义槽提取红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T451 · 频道真实配置稳定槽提取器**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/domain/services/reference_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T450\
  **配对测试**：T450\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T452 · 频道外部事务及无tenant子表红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T451\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T453 · 频道根及完整同步配置Repository**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/domain/repositories/reference_binding_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T452\
  **配对测试**：T452\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T454 · 频道真实source锁后重授权红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_source_owner.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T453, T054\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T455 · 频道SourceOwner和列投影**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/application/reference_source_owner.py`；`src/backend/bisheng/channel/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T454\
  **配对测试**：T454\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T456 · 频道自动化真实当前身份红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_automation_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T457 · 频道域恢复真实自动化身份**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/application/automation_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T456\
  **配对测试**：T456\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T458 · 频道完整来源执行前准入红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_execution_admission.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T455, T457\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T459 · 频道自动delivery准入facade**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/application/execution_admission.py`；`src/backend/bisheng/channel/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T458\
  **配对测试**：T458\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T460 · 实际派发旧UUID及拒绝零副作用红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_delivery_admission.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T459\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T461 · 频道delivery及worker实际接线**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/domain/services/information_knowledge_delivery_service.py`；`src/backend/bisheng/worker/information/knowledge_delivery.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T460\
  **配对测试**：T460\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T462 · 频道失效原选择项展示红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_reference_view.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T455\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T463 · 频道完整失效原ID及裁剪状态**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/domain/schemas/channel_manager_schema.py`；`src/backend/bisheng/channel/domain/services/channel_service.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T462, T054\
  **配对测试**：T462\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T464 · 真实五key默认模型槽红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T465 · 五key实际默认槽提取器**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/default_reference_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T464\
  **配对测试**：T464\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T466 · 默认own原始与真实继承SQL红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T465\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T467 · 默认模型外部事务Repository**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/model_default_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T466\
  **配对测试**：T466\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T468 · 默认原ambient及SourceOwner红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_source.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T467\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T469 · 默认模型双模式身份与Owner**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default_read_identity.py`；`src/backend/bisheng/llm/application/model_default_source_owner.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T468\
  **配对测试**：T468\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T470 · 原生同步真实Model目标红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_default_native_target.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T426, T432\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T471 · Model只读Owner原生同步适配**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/source_read_target_owner.py`；`src/backend/bisheng/llm/domain/repositories/source_read_target_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T470\
  **配对测试**：T470\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T472 · 默认全源严格双模式读取红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_read.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T469, T471, T428\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T473 · 默认原始与执行读取facade**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default_read.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T472\
  **配对测试**：T472\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T474 · 混合来源MODEL物理预锁红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_mixed_source_locks.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T435\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T475 · MODEL混合root纯物理预锁**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/reference_target_owner.py`；`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T474\
  **配对测试**：T474\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T476 · APP同Session完整名称计划红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T477 · LLM唯一uncached名称计划Port**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T476\
  **配对测试**：T476\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T478 · 默认实际消费不回退原ID红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_consumers.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T473, T056\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T479 · LLM默认管理与运行消费者接线**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/llm.py`；`src/backend/bisheng/llm/api/router.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T478, T058\
  **配对测试**：T478\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T480 · 工作台默认原子保存与空间独立模型回归**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_workbench_reference_atomicity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T475, T489, T056\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T481 · 工作台默认独立来源维护**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default.py`；`src/backend/bisheng/llm/domain/services/llm.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T480, T479\
  **配对测试**：T480\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T482 · 空间QA实际及阶段模型槽红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T483 · 空间QA模型业务槽提取**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/model_reference_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T482\
  **配对测试**：T482\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T484 · 知识模型外部事务Repository红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T483\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T485 · 知识模型配置原子存储**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T484\
  **配对测试**：T484\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T486 · 知识模型来源唯一写口红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_bindings.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T485, T435\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T487 · 知识模型来源创建变更应用用例**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T486, T538\
  **配对测试**：T486\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T488 · 原全空间默认联动测试退役（用户范围修订）**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_workbench_reference_atomicity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T487, T475\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T489 · 原全空间批量模型计划退役（用户范围修订）**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T488\
  **配对测试**：T488\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T490 · 旧库QA空间创建同事务来源红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_creation.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T487\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T491 · 真实知识创建接入模型来源**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T490, T538\
  **配对测试**：T490\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T492 · 旧embedding更新及清空出向来源红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_mutation.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T491\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T493 · QA旧库embedding及删除来源接线**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`；`src/backend/bisheng/knowledge/api/endpoints/knowledge.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T492\
  **配对测试**：T492\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T494 · 空间模型出向删除及保频道失效红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_space_reference_lifecycle.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T493, T054\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T495 · 空间模型来源及移除自动清频道**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T494\
  **配对测试**：T494\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T496 · 知识完整模型双模式读取红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_source.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T487, T426, T471, T428\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T497 · Knowledge模型SourceOwner与身份**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/reference_source_owner.py`；`src/backend/bisheng/knowledge/application/reference_read_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T496\
  **配对测试**：T496\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T498 · Knowledge模型执行读取facade**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference_read.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T497\
  **配对测试**：T496\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T499 · 实际RAG消费模型原配置准入红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_rag_model_admission.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T498\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T500 · 知识RAG原生模型来源准入**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/knowledge_rag.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T499\
  **配对测试**：T499\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T501 · 模型任务从业务配置及过期拒绝红测**
  **类型 / Owner**：测试 / WORKER\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_worker_model_source.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T498, T493\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T502 · 旧重建worker读取业务模型并finalize**
  **类型 / Owner**：实现 / WORKER\
  **写入文件**：`src/backend/bisheng/worker/knowledge/rebuild_knowledge_worker.py`；`src/backend/bisheng/worker/knowledge/qa.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T501\
  **配对测试**：T501\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T503 · API启动不得在线转换默认JSON红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_default_startup_migration_boundary.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T504 · 取消默认配置在线自动转换**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/main.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T503\
  **配对测试**：T503\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T505 · 四类来源真实生产装配红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_business_sources_composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T455, T498, T443, T473\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T506 · 完整来源API与worker实际装配**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/read_composition.py`；`src/backend/bisheng/resource_reference/composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T505\
  **配对测试**：T505\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T507 · W4真实来源合同和设计同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/business-sources-contract.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/design.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T506, T502, T481, T050, T052, T447, T449, T461, T463, T552, T585, T587, T589, T592, T594, T595, T596, T597\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T508 · W4任务及并行交付同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/parallel-development.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T507\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T509 · W4升级及导航同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/upgrade-guide.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/README.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T508, T504\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T510 · W4 HTML与固定提交验证**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`docs/architecture/review/2026-11-03-bisheng-knowledge-unification-technical-review.html`；`features/v3.1.0-beta1/118-knowledge-space-unification/wave4-implementation-review.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T509\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [x] **T511 · 版本写原冻结凭据上下文红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_runtime_authorization_context.py`\
  **逻辑 / 测试上下文**：保既有真实credential_ref恢复语义，原yield身份贯穿外部事务；失效凭据拒，退出还原Context，不按owner ID造人。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89\
  **验证 / 完成条件**：实际红绿、固定SHA复核及组合；不是HTTP权限令牌或新actor框架。

- [x] **T512 · 导出原后台授权上下文薄Port**
  **类型 / Owner**：后端 Application / INT-APP\
  **写入文件**：`src/backend/bisheng/app_runtime/application/runtime_authorization.py`\
  **逻辑 / 测试上下文**：user_authorization_context(context,app,version_id)沿既有可信恢复manager；只导出不更改原授权/tenant/凭据规则。\
  **依赖**：T511\
  **配对测试**：T511\
  **验证 / 完成条件**：真实上下文/失败/恢复测试及APP固定SHA消费者复核。

- [x] **T513 · 审批预览资格复用外部事务红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_review_transaction.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T514 · 审批资格只读外部Session Port**
  **类型 / Owner**：实现 / INT-APP\
  **写入文件**：`src/backend/bisheng/approval/application/app_review.py`；`src/backend/bisheng/approval/domain/repositories/app_review_repository.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T513\
  **配对测试**：T513\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T515 · 已加载应用原动作授权薄Port红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_loaded_authorization.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T516 · 已加载应用授权只读导出**
  **类型 / Owner**：实现 / INT-APP\
  **写入文件**：`src/backend/bisheng/app_runtime/application/authorization.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T515\
  **配对测试**：T515\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T517 · 频道真实新选择和会员原子性红测**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_repository.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T453\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T518 · 频道Repository新选择及会员外事务**
  **类型 / Owner**：实现 / CH\
  **写入文件**：`src/backend/bisheng/channel/domain/repositories/reference_binding_repository.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T517\
  **配对测试**：T517\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T519 · 空名称计划原发行验证红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T477\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T520 · 统一名称Plan当前验证方法**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T519\
  **配对测试**：T519\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [x] **T521 · 冻结模型当前父事实及原actor指纹红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T520\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T522 · 真实冻结模型父事实与原身份完整指纹**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T521\
  **配对测试**：T521\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T523 · APP真实preview route事实红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_repository.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T437\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T524 · APP当前preview route列投影**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T523\
  **配对测试**：T523\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T525 · 频道既有回归等价事务fixture适配 test_unified_permission_creation.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_unified_permission_creation.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T054\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T526 · 频道既有回归等价事务fixture适配 test_unified_permission_update.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_unified_permission_update.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T054\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T527 · 频道既有回归等价事务fixture适配 test_channel_create_quota.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_channel_create_quota.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T054\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T528 · 频道既有回归等价事务fixture适配 test_channel_source_subscription.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_channel_source_subscription.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T054\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T529 · 频道既有回归等价事务fixture适配 test_subscription_state_consistency.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_subscription_state_consistency.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T054\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [x] **T530 · 默认override不能以将消失的自身继承证明共享红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_default_override_sharing.py`\
  **逻辑 / 测试上下文**：源保存/删除的实际接缝；不猜ID/版本/共享，不放宽现有同root及tenant边界，真实SQL红绿。\
  **依赖**：T056\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：固定SHA独立复核及实际组合；不以当前配置保存前许可误当保存后仍可执行。

- [x] **T531 · 默认来源前瞻共享资格排除自身key**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`；`src/backend/bisheng/llm/application/reference_target_owner.py`\
  **逻辑 / 测试上下文**：源保存/删除的实际接缝；不猜ID/版本/共享，不放宽现有同root及tenant边界，真实SQL红绿。\
  **依赖**：T530\
  **配对测试**：T530\
  **验证 / 完成条件**：固定SHA独立复核及实际组合；不以当前配置保存前许可误当保存后仍可执行。

- [x] **T532 · 无保存版本根的真实引用全集盘点红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_ref_root_identity.py`\
  **逻辑 / 测试上下文**：源保存/删除的实际接缝；不猜ID/版本/共享，不放宽现有同root及tenant边界，真实SQL红绿。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：固定SHA独立复核及实际组合；不以当前配置保存前许可误当保存后仍可执行。

- [x] **T533 · 真实无版本SourceRootKey只读合同**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/contracts.py`；`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：源保存/删除的实际接缝；不猜ID/版本/共享，不放宽现有同root及tenant边界，真实SQL红绿。\
  **依赖**：T532\
  **配对测试**：T532\
  **验证 / 完成条件**：固定SHA独立复核及实际组合；不以当前配置保存前许可误当保存后仍可执行。

- [x] **T534 · 频道既有通知与delivery回归等价适配 test_channel_dismiss_notifications.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_channel_dismiss_notifications.py`\
  **逻辑 / 测试上下文**：原actor/current授权/通知/duplicate/顺序保留；测试注入明确admission，生产真实短事务有独立集成覆盖，不加假fallback。\
  **依赖**：T461\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-91\
  **验证 / 完成条件**：固定旧断言与等价fixture、真实组合，不把Double代替生产准入验证。

- [x] **T535 · 频道既有通知与delivery回归等价适配 test_information_knowledge_delivery.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_information_knowledge_delivery.py`\
  **逻辑 / 测试上下文**：原actor/current授权/通知/duplicate/顺序保留；测试注入明确admission，生产真实短事务有独立集成覆盖，不加假fallback。\
  **依赖**：T461\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-91\
  **验证 / 完成条件**：固定旧断言与等价fixture、真实组合，不把Double代替生产准入验证。

- [x] **T536 · 频道既有通知与delivery回归等价适配 test_information_sync_integration.py**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/channel/test_information_sync_integration.py`\
  **逻辑 / 测试上下文**：原actor/current授权/通知/duplicate/顺序保留；测试注入明确admission，生产真实短事务有独立集成覆盖，不加假fallback。\
  **依赖**：T461\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-91\
  **验证 / 完成条件**：固定旧断言与等价fixture、真实组合，不把Double代替生产准入验证。

- [x] **T537 · 原生业务写者复用已注册实例红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_binding_runtime_access.py`\
  **逻辑 / 测试上下文**：遵循W4冻结补充，唯一文件Owner，原身份和外部Session不变；真实生产接缝及反例验证，不以mock外部容器证明实机验收。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：固定提交独立复核、实际定向回归及主集成；未运行真实环境不声称完成。

- [x] **T538 · 原生绑定runtime纯同步公共读取**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/application/access.py`\
  **逻辑 / 测试上下文**：遵循W4冻结补充，唯一文件Owner，原身份和外部Session不变；真实生产接缝及反例验证，不以mock外部容器证明实机验收。\
  **依赖**：T537\
  **配对测试**：T537\
  **验证 / 完成条件**：固定提交独立复核、实际定向回归及主集成；未运行真实环境不声称完成。

- [x] **T539 · 已删应用仅当前销毁任务可读清理事实红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_deleted_runtime_cleanup.py`\
  **逻辑 / 测试上下文**：遵循W4冻结补充，唯一文件Owner，原身份和外部Session不变；真实生产接缝及反例验证，不以mock外部容器证明实机验收。\
  **依赖**：T533\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：固定提交独立复核、实际定向回归及主集成；未运行真实环境不声称完成。

- [x] **T540 · 持久销毁操作绑定的已删应用清理读取**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`；`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`\
  **逻辑 / 测试上下文**：遵循W4冻结补充，唯一文件Owner，原身份和外部Session不变；真实生产接缝及反例验证，不以mock外部容器证明实机验收。\
  **依赖**：T539\
  **配对测试**：T539\
  **验证 / 完成条件**：固定提交独立复核、实际定向回归及主集成；未运行真实环境不声称完成。

- [x] **T541 · 冻结名称模型的原生别名不越槽红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T522\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [x] **T542 · 同原NamePlan解析bare和qualified别名**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T541\
  **配对测试**：T541\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [x] **T543 · APP来源Owner同实例最终绑定红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_model_binding.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T443, T542\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [x] **T544 · APP专属runtime显式来源Owner接缝**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_access.py`；`src/backend/bisheng/app_publish/composition.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T543\
  **配对测试**：T543\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [x] **T545 · 助手来源SQL用例独立注册真实租户表**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_source_owner.py`\
  **逻辑 / 测试上下文**：仅修复组合顺序造成的全局tenant表发现fixture残留，显式纳入本SQL场景实际Assistant/Link/ShareLink/Session表；不改产品源码、不Mock或弱化原跨租户拒绝断言。\
  **依赖**：T362\
  **覆盖 AC**: AC-71, AC-87, AC-89\
  **验证 / 完成条件**：固定a8d7cc28d全F118单路径1129pass/2fail的实际拒绝断言为红；原断言保留且整组合通过，生产AS/C3路径0diff。

- [x] **T546 · API与worker原生共享读前明确READY红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_native_reference_bootstrap.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T432\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [x] **T547 · Celery持久loop准备原生读取权限runtime**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/worker/main.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T546\
  **配对测试**：T546\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [x] **T548 · 检索引擎保原身份进入资源模型准入红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_retrieval_engine_identity.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T498\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [x] **T549 · 检索引擎透传既有完整login_user**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/retrieval_engine.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T548\
  **配对测试**：T548\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [x] **T550 · 删除清理不依赖可执行模型红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_cleanup_model_independence.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T500\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [x] **T551 · 持久文件删除清理走命名非模型构造**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_direct_delete_service.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T550\
  **配对测试**：T550\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [x] **T552 · API启动显式准备原生共享读取权限**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/main.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T546, T504\
  **配对测试**：T546\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [x] **T553 · 清空删除资源模型出向绑定同事务红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_lifecycle_transaction.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T487\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T554 · 模型出向清空删除prepare及SQL原子应用**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T553\
  **配对测试**：T553\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T555 · 业务模型阶段finalize同事务红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_finalize.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T554\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T556 · 业务模型阶段及来源索引一起finalize**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T555\
  **配对测试**：T555\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T557 · 后台原始执行上下文来源证明红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_trusted_worker_context.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T558 · Celery实际header发行回收后台执行上下文**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/core/context/background_execution.py`；`src/backend/bisheng/worker/tenant_context.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T557\
  **配对测试**：T557\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T559 · 知识创建旧补偿用例真实rollback适配**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_create_atomicity.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T491\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T560 · 空间创建旧用例新事务接缝等价适配**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_unified_permission_creation.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T495\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T561 · 默认来源缺可信tenant错误码红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_source.py`；`src/backend/test/knowledge_unification/test_llm_defaults.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T469, T056\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T562 · 默认来源缺tenant按合同10996拒绝**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default_read_identity.py`；`src/backend/bisheng/llm/application/model_default.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T561\
  **配对测试**：T561\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [x] **T563 · 模型名称完整批次只读观察红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T542\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T564 · 名称逐项只读findings无执行authority**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T563\
  **配对测试**：T563\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T565 · 名称Port缺tenant一致错误码红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T564\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T566 · 名称Port缺tenant按10996拒绝**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T565\
  **配对测试**：T565\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T567 · 已保存应用能力失效状态保行红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_saved_capabilities.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T445, T564\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T568 · 应用发布状态基于实际UUID引用inspect**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`；`src/backend/bisheng/app_publish/domain/services/publish_status_service.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T567\
  **配对测试**：T567\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T569 · 旧入口动作及legacy协议fixture适配**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_runtime/test_entry_authz_service.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T052\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T570 · 旧预览入口fixture明确legacy协议**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_runtime/test_preview_entry.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T052\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T571 · 旧模型知识能力测试真实来源适配**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/test_capability_model.py`；`src/backend/test/app_publish/test_capability_knowledge.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T574\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T572 · 旧撤销审计测试全source规则适配**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/test_capability_revoked.py`；`src/backend/test/app_publish/test_capability_audit.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T574\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T573 · 助手管理pin默认模型真实读取适配**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_management_scope.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T479, T473\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T574 · 旧应用测试显式来源SQL辅助fixture**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/reference_fixtures.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T445\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [x] **T575 · 混合own模型批次的tenant辅助锁回归**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_mixed_source_locks.py`\
  **逻辑 / 测试上下文**：即使模型均为own，Tenant拓扑也须在KN业务root之前完成当前锁；无模型union仍调用目标Owner的辅助预锁。SQLite只检查实际SQL顺序，不证明双库锁竞争。\
  **依赖**：T475\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：真实红绿、固定提交复查及混合批次组合通过。

- [x] **T576 · 模型mixed目标阶段锁定tenant拓扑**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：按物理全局模型server/model→Tenant拓扑→KN/default业务root顺序；不把无关default JSON变成共享依赖，不改变逐来源收据。\
  **依赖**：T575\
  **配对测试**：T575\
  **验证 / 完成条件**：定向与主组合通过，真实MySQL/DM8竞争另验。

- [x] **T577 · 旧启动能力环境夹具补真实身份和空来源**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_runtime/test_capability_env_injection.py`\
  **逻辑 / 测试上下文**：固定旧2a4基线同4失败，trace确认legacy capability_env provider已无生产调用方；仅测试改验实际RuntimeDeliveryCoordinator的事务stage、将运行版本derive scopes、平台/存储/应用身份环境、reserved覆盖及失败不保存sealed_env/不wake。旧env={}和provider callback契约明确退役，不能伪造旧调用通过，不改生产guard。\
  **依赖**：T445, T050\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：旧基线同失败集归因明确，新fixture独立复查及相同argv主组合通过。

- [x] **T578 · 旧应用凭据测试明确legacy及Session隔离**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/test_app_credential.py`\
  **逻辑 / 测试上下文**：固定旧2a4基线同21失败，显式legacy v1并注入实际preview异步及guard同步Session；保真实issuer/validate_bearer、prefix、撤销缓存、停用恢复与租户所有断言，不改生产代码。\
  **依赖**：T052\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：旧基线同失败集归因明确，新fixture独立复查及相同argv主组合通过。

- [x] **T579 · 旧默认配置service回归迁移至真实读取门面**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_llm_system_config_service.py`\
  **逻辑 / 测试上下文**：旧测试直连已退役DAO/名称/signature的夹具迁移；保typed配置、管理envelope、调用tenant、局部更新和合法空models的原业务断言。裸tenant覆盖当前上下文及缺tenant回Root的旧口径与冻结合同冲突，明确改为当前tenant一致/10996拒绝并记录，不恢复生产fallback。\
  **依赖**：T479, T473\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：原失败与新合同差异有记录，固定提交复查及相同argv主组合通过，无生产代码改动。

- [x] **T580 · 旧工作台局部更新回归迁移至同事务writer**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_workbench_update_merge.py`\
  **逻辑 / 测试上下文**：旧测试直连已退役DAO/名称/signature的夹具迁移；保typed配置、管理envelope、调用tenant、局部更新和合法空models的原业务断言。裸tenant覆盖当前上下文及缺tenant回Root的旧口径与冻结合同冲突，明确改为当前tenant一致/10996拒绝并记录，不恢复生产fallback。\
  **依赖**：T481\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：原失败与新合同差异有记录，固定提交复查及相同argv主组合通过，无生产代码改动。

- [x] **T581 · 旧默认配置消费形状回归对齐冻结入口**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_llm_system_config_consumers.py`\
  **逻辑 / 测试上下文**：旧测试直连已退役DAO/名称/signature的夹具迁移；保typed配置、管理envelope、调用tenant、局部更新和合法空models的原业务断言。裸tenant覆盖当前上下文及缺tenant回Root的旧口径与冻结合同冲突，明确改为当前tenant一致/10996拒绝并记录，不恢复生产fallback。\
  **依赖**：T479\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：原失败与新合同差异有记录，固定提交复查及相同argv主组合通过，无生产代码改动。

- [x] **T582 · 非法工作台默认对话ID保原10811回归**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_workbench_update_merge.py`\
  **逻辑 / 测试上下文**：实际新writer在原Session接收非法chat_default_model_id，保原WorkbenchChatDefaultModelError10811业务断言，不将ValueError或10996改作测试预期；失败不得部分保存。\
  **依赖**：T481\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92\
  **验证 / 完成条件**：固定新实现实际红、窄修后绿及主组合通过。

- [x] **T583 · 工作台默认对话ID规范化保原业务错误**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default.py`\
  **逻辑 / 测试上下文**：仅修_config非法chat默认ID规范化的异常包装，保原10811和cause，不改完整来源/身份/tenant/收据/批次/commit合同，不恢复退休DAO。\
  **依赖**：T582\
  **配对测试**：T582\
  **验证 / 完成条件**：红绿、固定提交独立复查及主组合通过。

- [x] **T584 · 文档和QA实际向量删除不依赖失效模型红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_vector_cleanup_source.py`\
  **逻辑 / 测试上下文**：trace实际delete_vector_files/delete_vector_data仍调用标准模型准入；以真实own资源/删除模型/外部vector double确认原文件和QA清理不被model失效阻断，校验知识tenant/index漂移拒绝，无provider。\
  **依赖**：T500, T550\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92, AC-94\
  **验证 / 完成条件**：真实固定红→命名清理构造绿，保持原删除过滤字段/上游动作和投影顺序，固定提交独立复查及组合通过。

- [x] **T585 · 文件和QA删除消费命名清理构造**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/api/services/knowledge_imp.py`\
  **逻辑 / 测试上下文**：仅两处delete_vector_files/delete_vector_data消费已验证当前own index的cleanup helper；不改copy/执行调用，不添加文件动作，不跳过原引用/投影门槛。\
  **依赖**：T584\
  **配对测试**：T584\
  **验证 / 完成条件**：配对红绿、固定提交独立复查及主组合通过；不称完整R3已完成。

- [x] **T586 · 知识配置读取和清理的单租户C3回归**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_source.py`；`src/backend/test/knowledge_unification/test_kn_cleanup_model_independence.py`\
  **逻辑 / 测试上下文**：真实Root1资源在multi_tenant.enabled=False且无显式tenant Context时沿C3合法默认1；多租户缺context仍10996且无外部IO，不从显式参数/用户ID补tenant或放宽其他租户。\
  **依赖**：T498, T500\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92\
  **验证 / 完成条件**：真实单租户红→窄修绿及多租户拒绝，固定提交独立复查与主组合通过。

- [x] **T587 · 知识内部读取和清理统一C3有效tenant**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/reference_read_identity.py`；`src/backend/bisheng/knowledge/domain/knowledge_rag.py`\
  **逻辑 / 测试上下文**：移除与既有_resolve_tenant_id冲突的裸get_current存在性门槛；single合法默认1，multi无context捕typedNoTenantContextError→10996保cause。不改W3用户授权、原actor/原事务或后台proof。\
  **依赖**：T586\
  **配对测试**：T586\
  **验证 / 完成条件**：配对红绿、固定提交独立复查及主组合通过，不声称改变多租户fallback规则。

- [x] **T588 · APP保存解析和观察保原非QA能力边界红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_resolve.py`；`src/backend/test/knowledge_unification/test_app_saved_capabilities.py`\
  **逻辑 / 测试上下文**：通用KN生命周期接受0/1/3不代表APP可检索QA；实际APP能力仍0/3。新保存拒QA，历史QA管理保原ID标不可用，不因通用valid假健康。\
  **依赖**：T439, T568\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92\
  **验证 / 完成条件**：真实SQL红绿及主组合，类型1不以fake检索Port证明可运行。

- [x] **T589 · APP来源解析和管理观察保持原支持类型**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_resolution.py`；`src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`\
  **逻辑 / 测试上下文**：来源执行沿实际resolver守APP原0/3，完整来源含QA也须provider前拒；管理观察保ID逐行标unsupported。通用KN TargetOwner仍0/1/3，无新增权限动作或清理历史配置。\
  **依赖**：T588, T590\
  **配对测试**：T588, T590\
  **验证 / 完成条件**：固定提交独立复查及组合通过，不改源码非授权热点。

- [x] **T590 · QA业务能力不能借通用有效目标放行模型**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_model_binding.py`\
  **逻辑 / 测试上下文**：实际QA行与真实Core/APP adapter，Gateway模型guard必须whole-source拒绝；原0/1/3 fake retrieval首次绿改为0/3正例和QA真实拒绝，不伪造旧失败。\
  **依赖**：T544\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92\
  **验证 / 完成条件**：实际SQL红绿、原principal/typed model正例保留，固定提交独立复查。

- [x] **T591 · 旧重建可用性测试改用真实业务命令和stage**
  **类型 / Owner**：测试 / WORKER\
  **写入文件**：`src/backend/test/knowledge/test_rebuild_keeps_container_usable.py`\
  **逻辑 / 测试上下文**：移除只含id/model的旧DAO假资源，以真实当前stage/来源/op/rev/gen和后台上下文验证受控逐文件部分失败仍完成finalize并PUBLISHED。全局异常/过期/guard失败不伪发布成功、不解除pending，保诊断stage；旧无stage消息明确拒绝。\
  **依赖**：T502\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-86, AC-89, AC-92\
  **验证 / 完成条件**：明确旧无条件发布与新stage合同的差异，保受控部分失败文件可用断言；相同argv组合通过，不实现完整Processing框架。

- [x] **T592 · 旧重建metadata schema回归补业务期望透传**
  **类型 / Owner**：测试 / WORKER\
  **写入文件**：`src/backend/test/knowledge/test_rebuild_knowledge_schema.py`\
  **逻辑 / 测试上下文**：旧私有_rebuild_embeddings调用补已冻结pending/op/rev/gen与外部ES double的scope kwargs；保显式KNOWLEDGE_RAG_METADATA_SCHEMA及原向量写入断言，不改生产代码或用模型参数取代资源配置。\
  **依赖**：T502\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-86, AC-89, AC-92\
  **验证 / 完成条件**：明确旧signature失败，固定提交独立复查与组合通过。

- [x] **T593 · 状态查询不得继续派发旧重建消息红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_query_rebuild_side_effects.py`\
  **逻辑 / 测试上下文**：实际Space.info和旧private status只读状态/保原可见授权与响应，不因FAILED/BUILDING在GET派发旧三参消息；部分状态和阶段诊断原行为保留。退休个人库恢复不新增，显式模型变更派发仍沿唯一7字段Owner。\
  **依赖**：T495, T502\
  **覆盖 AC**: AC-34, AC-68, AC-71, AC-79, AC-83, AC-86, AC-89, AC-92\
  **验证 / 完成条件**：两实际查询红→绿，无queue/新operation/模型改动，固定提交独立复查及主组合。

- [x] **T594 · 移除查询中的退休自动重建派发**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/api/endpoints/knowledge.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：仅移除get_knowledge_status/get_space_info对非Published的旧三参自动重建；保查询权限/原状态提示及阶段诊断，不补造stage或新操作、不将visible查询变成重建授权，不增加重试框架。\
  **依赖**：T593\
  **配对测试**：T593\
  **验证 / 完成条件**：固定红绿/独立复查，显式改模型7字段路径及info旧回归保持。

- [x] **T595 · 持久删除残留回归适配命名清理工厂**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_direct_delete_consistency.py`\
  **逻辑 / 测试上下文**：旧ES/Milvus残留及空folder用例的外部工厂double从退休标准RAG入口等价移至named cleanup；保原残留检测、租约/重试/SQL回滚/空范围断言，防止测试漏连真实DB。不改生产清理授权，真实SQL job/manifest核验由T550覆盖。\
  **依赖**：T551\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-91, AC-92, AC-94\
  **验证 / 完成条件**：只迁factory patch层，相同旧断言与主组合通过，固定提交独立复查。

- [x] **T596 · 信息查询诊断回归对齐只读重建状态**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_space_info_optimization.py`\
  **逻辑 / 测试上下文**：旧两tenant自动dispatch断言按T594改为均不派发；保原visible/状态、全部STAGES及失败阶段诊断，rebuild阶段故障注入转只读状态呈现边界，不造job或调用queue，不改其他性能/成员断言。\
  **依赖**：T594\
  **覆盖 AC**: AC-34, AC-68, AC-71, AC-79, AC-83, AC-86, AC-89, AC-92\
  **验证 / 完成条件**：固定旧语义差异有记录，相同诊断回归与主组合通过。

- [x] **T597 · 助手发布模型异常回归补真实知识模型来源**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/assistant/test_publish_knowledge_embedding_error.py`\
  **逻辑 / 测试上下文**：总组4失败因旧_get_knowledge假对象绕过退休入口，改真实Knowledge/模型/R2及实际配置门面，同tenant原AS发布事务。保原10425/库名/cause/状态回滚、Milvus错误不洗白、provided embedding不再初始化provider；完整来源仍先校验，10994不改为成功或10425。\
  **依赖**：T500, T283\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92\
  **验证 / 完成条件**：原4失败有归因，真实读取fixture定向及相同主组合通过，不改生产guard。

## W5消费面接缝补充任务（2026-11-06）

合同见 [wave5-consumers-contract.md](./wave5-consumers-contract.md)。新增六卡仅拆分原需求的前端DTO接缝、旧回归和skill文档，未扩大94条AC；原157待办中本波选择20项。冻结时历史编号603，438已完成/历史交付、163当前待办（原157+6叶子）、2外移，全部待验证后才勾选。

- [x] **T598 · APP动作DTO前端最小兼容红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/frontend/platform/src/test/f114AppActions.test.tsx`\
  **逻辑 / 测试上下文**：以visible/空/未知旧use仅可见不能管理，五类具体管理动作独立，edit+publish才rebuild；保原publish-only深链不加载私有内容。\
  **依赖**：T002\
  **覆盖 AC**: AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：逐卡实际验证、原断言保留、固定SHA复查后由INT勾选；不声称真实环境或全特性验收。

- [x] **T604 · 能力授权旧回归动作及Skill管理语义对齐**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/permission/test_capability_authorization.py`\
  **逻辑 / 测试上下文**：保原租户/owner/撤Source/投影失败断言；退休use成功fixture改为目标化纯可见模型，补Catalog当前作用域；Skill目标visible/edit/delete管理不因disabled被封，运行拒绝由T145真实边界回归。不改业务源码。\
  **依赖**：T146\
  **覆盖 AC**: AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：记录原3个Grant/Catalog fixture既有失败；保拒绝和Source撤销目的，原文件与EDGE/PERM联合组合通过后勾选。

- [x] **T599 · APP动作DTO前端最小兼容**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/frontend/platform/src/controllers/API/hostedApp.ts`；`src/frontend/platform/src/pages/BuildPage/hostedApp/appActions.ts`\
  **逻辑 / 测试上下文**：canonical HostedAppAction替换use为visible；management只认五类已有管理动作，不从未知/visible推导权限。不新增UI/样式，不提前勾完整T193。\
  **依赖**：T598\
  **配对测试**：T598\
  **验证 / 完成条件**：逐卡实际验证、原断言保留、固定SHA复查后由INT勾选；不声称真实环境或全特性验收。

- [x] **T600 · 审批当前可见摘要skill契约同步**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`.claude/skills/approval-module/SKILL.md`\
  **逻辑 / 测试上下文**：只将当前事实use来源文案与T136实际visible实现同步；不改审批引擎/节点/路由/候选/通知/outbox。\
  **依赖**：T136\
  **验证 / 完成条件**：逐卡实际验证、原断言保留、固定SHA复查后由INT勾选；不声称真实环境或全特性验收。

- [x] **T601 · 工具preset原鉴权回归动作对齐**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/tool/test_preset_tool_classification.py`\
  **逻辑 / 测试上下文**：保preset/custom/真实Facade/tenant/非法动作原断言，退休use具体成功输入改visible；旧use兼容仍由统一入口回归。\
  **依赖**：T128\
  **覆盖 AC**: AC-78, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：逐卡实际验证、原断言保留、固定SHA复查后由INT勾选；不声称真实环境或全特性验收。

- [x] **T602 · 系统应用与租户共享旧回归对齐**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_f048_application_adapters.py`；`src/backend/test/permission/test_f048_resource_share_boundary.py`\
  **逻辑 / 测试上下文**：保原租户/allowlist/状态/写动作拒绝等断言，仅将退休use的具体成功输入改visible；不激活新共享类型。\
  **依赖**：T154\
  **覆盖 AC**: AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：逐卡实际验证、原断言保留、固定SHA复查后由INT勾选；不声称真实环境或全特性验收。

- [x] **T603 · 系统Owner投影旧回归对齐**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_f048_owner_projection.py`\
  **逻辑 / 测试上下文**：将原use投影成功输入改visible，保protected/管理等级/失败不finalize和其他动作拒绝，验证无use marker。\
  **依赖**：T225\
  **覆盖 AC**: AC-78, AC-81, AC-83\
  **验证 / 完成条件**：逐卡实际验证、原断言保留、固定SHA复查后由INT勾选；不声称真实环境或全特性验收。

## W6 完成阶段接缝任务（2026-11-06）

- [x] **T605 · W6分批合同及真实前置登记**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/wave6-completion-contract.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`\
  **逻辑 / 测试上下文**：冻结已落地DTO的两端API/Mock子合同，标明尚缺的真实PROC/KN/删除与页面叶子；不猜接口或越过真实端点门禁。用户已授权测试环境，凭据不入文档。\
  **依赖**：T604\
  **验证 / 完成条件**：三方只读核对现有schema与调用面，逐项记录消费者和唯一Owner；本次只冻结第一子合同。

- [x] **T606 · 平台API及缓存范围合同测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/knowledgeSpaceContract.test.ts`（拟新增）；`src/frontend/platform/src/test/knowledgeQueryScope.test.tsx`（拟新增）\
  **逻辑 / 测试上下文**：逐字段DTO与请求路径、两类分页、错误保真、身份/具体租户/管理范围切换和迟到响应隔离；使用同形API测试port，不设生产mock开关。\
  **依赖**：T605\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-49, AC-50\
  **验证 / 完成条件**：先提交测试并记录实际红测；T175实现后同选集验证，不以Mock声称真实API已接线。

- [x] **T607 · 客户端处理API与Mock合同测试**
  **类型 / Owner**：测试 / CLIENT\
  **写入文件**：`src/frontend/client/src/api/knowledgeProcessing.test.ts`（拟新增）\
  **逻辑 / 测试上下文**：镜像现有processing DTO、request封装/envelope、accepted非完成、隐藏项与分页，验证客户端身份/tenant key，不跨应用导入实现。\
  **依赖**：T605\
  **覆盖 AC**: AC-02, AC-12, AC-13, AC-49, AC-50\
  **验证 / 完成条件**：先提交测试，T187后组合绿验；真实页面及接口联调仍分别执行。

## W6 PROC 最小真实前置（同一既定需求）

- [x] **T608 · 持久确认计划仓储测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_operation_plan_repository.py`\
  **逻辑 / 测试上下文**：真实Session覆盖actor/tenant/digest/expiry/consume幂等、同plan异operation拒绝，precheck零业务修改。\
  **依赖**：T605\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：测试先提交，记录真实红/首绿，不在测试卡改生产。

- [x] **T609 · 持久确认计划仓储**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/operation_plan_repository.py`\
  **逻辑 / 测试上下文**：按W6接口外部Session创建/加锁/consume，规范摘要与原修订，绝不自行commit或外部IO。\
  **依赖**：T608\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T608并记录真实结果，完成后由INT集成复核；不以单元测试声称真实E2E。

- [x] **T610 · 任务查询及可靠派发仓储测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_query_dispatch.py`\
  **逻辑 / 测试上下文**：分页稳定/隐藏项/跨租户/最新retry actor/扫描租约到期/旧revision投递与claim CAS，失败恢复不重复接新retry。\
  **依赖**：T605\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：测试先提交，记录真实红/首绿，不在测试卡改生产。

- [x] **T611 · 任务查询及可靠派发仓储**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`\
  **逻辑 / 测试上下文**：复用现有模型字段，job/item分页、最新accepted receipt、具体tenant游标扫描和投递CAS；仅flush。\
  **依赖**：T610\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T610并记录真实结果，完成后由INT集成复核；不以单元测试声称真实E2E。

- [x] **T612 · 知识处理原凭据恢复测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_identity.py`\
  **逻辑 / 测试上下文**：web/API原credential及S/D delegation重验、scope/data_scope取交集、撤销/过期拒绝、无bearer持久化、不从user_id造人。\
  **依赖**：T605\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：测试先提交，记录真实红/首绿，不在测试卡改生产。

- [x] **T613 · 知识处理原凭据恢复窄出口**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/processing_identity.py`；`src/backend/bisheng/open_api/application/knowledge_processing_identity.py`\
  **逻辑 / 测试上下文**：按W6 capture/restore合同，真实原身份、最新retry requester与具体tenant；不复用写死app:manage/S的旧上下文。\
  **依赖**：T612\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T612并记录真实结果，完成后由INT集成复核；不以单元测试声称真实E2E。

- [x] **T614 · 最小真实处理派发测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_dispatch.py`\
  **逻辑 / 测试上下文**：持久intent到broker失败/丢ack/重复消息、tenant headers/proof、revision/lease和obsolete持久化，至少一真实kind闭环。\
  **依赖**：T064, T066\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：测试先提交，记录真实红/首绿，不在测试卡改生产。

- [x] **T615 · 最小真实处理worker与派发**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/processing_jobs.py`\
  **逻辑 / 测试上下文**：只传job/revision，原actor恢复、业务模型读取、受控步骤/SQL finalize重验；未装配kind明确拒绝，不造成功或永远pending。\
  **依赖**：T614\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T614并记录真实结果，完成后由INT集成复核；不以单元测试声称真实E2E。

- [x] **T616 · 处理worker及Beat装配测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_worker_wiring.py`\
  **逻辑 / 测试上下文**：验证真实Celery注册及Beat恢复扫描，使用现有tenant任务包装，不接新任务平台。\
  **依赖**：T615\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：测试先提交，记录真实红/首绿，不在测试卡改生产。

- [x] **T617 · 处理worker及Beat装配**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/config.py`；`src/backend/bisheng/worker/__init__.py`\
  **逻辑 / 测试上下文**：前移T076最小派发装配，最终多kind仍由T076完成；无服务启停或迁移自动执行。\
  **依赖**：T616\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T616并记录真实结果，完成后由INT集成复核；不以单元测试声称真实E2E。

- [x] **T618 · 处理薄路由真实接线测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_endpoints.py`\
  **逻辑 / 测试上下文**：真实Service入口precheck/create/query/retry/settings、envelope/错误及身份管理scope；非fake-only接线，旧文件动作不扩。\
  **依赖**：T617\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：测试先提交，记录真实红/首绿，不在测试卡改生产。

- [x] **T619 · 处理薄路由真实接线**
  **类型 / Owner**：后端 API / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/api/endpoints/processing.py`；`src/backend/bisheng/knowledge/api/router.py`\
  **逻辑 / 测试上下文**：按A1注册顺序和原权限动作调用Service，T124待KN完成后全量复核；此卡只提前最小闭环。\
  **依赖**：T618\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T618并记录真实结果，完成后由INT集成复核；不以单元测试声称真实E2E。

## W6 业务Owner及任务自身切换接缝

- [x] **T620 · 处理任务真实业务Owner测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_owner.py`\
  **逻辑 / 测试上下文**：按W6真实Owner补充合同；同Session实际业务模型读取、显式同模型新操作、原lease/R/G核验及私有事务收据消费。不允许任意before/after推进、不加物理staging、不联动默认Embedding。\
  **依赖**：T613, T609, T611\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先提交场景测试，记录真实红/首绿。

- [x] **T621 · 处理任务真实业务Owner**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/processing_owner.py`\
  **逻辑 / 测试上下文**：按W6真实Owner补充合同；同Session实际业务模型读取、显式同模型新操作、原lease/R/G核验及私有事务收据消费。不允许任意before/after推进、不加物理staging、不联动默认Embedding。\
  **依赖**：T620, T623, T637, T641, T643, T645\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T620及真实Owner组合；相关原回归不退化。

- [x] **T622 · 显式同模型重建业务边界测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_explicit_rebuild.py`\
  **逻辑 / 测试上下文**：按W6真实Owner补充合同；同Session实际业务模型读取、显式同模型新操作、原lease/R/G核验及私有事务收据消费。不允许任意before/after推进、不加物理staging、不联动默认Embedding。\
  **依赖**：T613\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先提交场景测试，记录真实红/首绿。

- [x] **T623 · 显式同模型重建业务边界**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`\
  **逻辑 / 测试上下文**：按W6真实Owner补充合同；同Session实际业务模型读取、显式同模型新操作、原lease/R/G核验及私有事务收据消费。不允许任意before/after推进、不加物理staging、不联动默认Embedding。\
  **依赖**：T622\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T622及真实Owner组合；相关原回归不退化。

- [x] **T624 · 自身切换收据与任务代际测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_cutover_receipt.py`\
  **逻辑 / 测试上下文**：按W6真实Owner补充合同；同Session实际业务模型读取、显式同模型新操作、原lease/R/G核验及私有事务收据消费。不允许任意before/after推进、不加物理staging、不联动默认Embedding。\
  **依赖**：T621, T611\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先提交场景测试，记录真实红/首绿。

- [x] **T625 · 自身切换任务代际收据消费**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`\
  **逻辑 / 测试上下文**：按W6真实Owner补充合同；同Session实际业务模型读取、显式同模型新操作、原lease/R/G核验及私有事务收据消费。不允许任意before/after推进、不加物理staging、不联动默认Embedding。\
  **依赖**：T624, T637, T641, T645\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：运行配对T624及真实Owner组合；相关原回归不退化。

## W6 平台高级写管理头接缝

- [x] **T626 · 平台高级命令管理头路径测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/frontend/platform/src/test/f118ProcessingManagementScope.test.ts`\
  **逻辑 / 测试上下文**：按后端T221路径配对断言advanced允许携带原管理snapshot；所有普通文件写、GET及v2保持原边界，不扩大网页头要求。\
  **依赖**：T605\
  **覆盖 AC**: AC-04, AC-05, AC-33, AC-35, AC-84\
  **验证 / 完成条件**：测试先独立提交再实现，同选集及原具体租户回归全绿；真实API联调另验。

- [x] **T627 · 平台高级命令管理头路径接线**
  **类型 / Owner**：前端 Platform / INT\
  **写入文件**：`src/frontend/platform/src/controllers/managementScope.ts`\
  **逻辑 / 测试上下文**：仅补与后端一致的两个精准路径正则；复用已有request/response范围snapshot，不改身份/tenant权威来源。\
  **依赖**：T626\
  **覆盖 AC**: AC-04, AC-05, AC-33, AC-35, AC-84\
  **验证 / 完成条件**：测试先独立提交再实现，同选集及原具体租户回归全绿；真实API联调另验。

## W6 两端通用授权独立验证接缝

- [x] **T628 · 客户端纯可见授权真实组件回归**
  **类型 / Owner**：测试 / CLIENT\
  **写入文件**：`src/frontend/client/src/components/permission/PermissionGrantTab.test.tsx`；`src/frontend/client/src/components/permission/PermissionListTab.test.tsx`\
  **逻辑 / 测试上下文**：使用真实Grant/List组件，服务器pure模型保原等级、可选可撤/精确Source版本；撤一源保其他源，管理/受保护/继承/停用边界不放宽。\
  **依赖**：T187\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：测试先独立提交，记录真实红/首绿，再按配对生产叶验证；不以mock证明真实FGA/跨租户。

- [x] **T629 · 客户端纯可见模型只读DTO**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/api/permissionTypes.ts`\
  **逻辑 / 测试上下文**：GrantablePermissionModel只补visibility_only?:boolean，原wrapper/Controls无缺陷则不改，不新增actions空过滤或写请求字段。\
  **依赖**：T628\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：测试先独立提交，记录真实红/首绿，再按配对生产叶验证；不以mock证明真实FGA/跨租户。

- [x] **T630 · 平台纯可见只读DTO协议回归**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f048PermissionApi.test.ts`\
  **逻辑 / 测试上下文**：复用catalog/grantable/assignee wire mocks，验证只读字段保真且不自动进入mutation，不改变版本/原错误协议。\
  **依赖**：T175\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：测试先独立提交，记录真实红/首绿，再按配对生产叶验证；不以mock证明真实FGA/跨租户。

- [x] **T631 · 平台纯可见模型只读DTO**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/permission.ts`\
  **逻辑 / 测试上下文**：CatalogModel补visibility_only_resource_types/visibility_level，Grantable模型补visibility_only，均optional；server grantable列表权威。\
  **依赖**：T630\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：测试先独立提交，记录真实红/首绿，再按配对生产叶验证；不以mock证明真实FGA/跨租户。

- [x] **T632 · 平台纯可见授予及来源列表组件回归**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f048PermissionGrantTab.test.tsx`；`src/frontend/platform/src/test/f048PermissionRoster.test.tsx`\
  **逻辑 / 测试上下文**：纯可见原等级授予、inactive撤销、精确assignee/version和其他Source保留；原manage/protected/LOCAL/editable保持，首绿如实记。\
  **依赖**：T631\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：测试先独立提交，记录真实红/首绿，再按配对生产叶验证；不以mock证明真实FGA/跨租户。

- [x] **T633 · 平台全员来源及APP动作组件回归**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/components/bs-comp/permission/AllMembersPermission.test.tsx`；`src/frontend/platform/src/test/f114AppActions.test.tsx`\
  **逻辑 / 测试上下文**：全员pure模型沿服务端key ADD、仅REMOVE服务器来源ID/version；失败不伪成功、无管理不得操作，visible不推导各管理动作。\
  **依赖**：T192\
  **覆盖 AC**: AC-30, AC-31, AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：测试先独立提交，记录真实红/首绿，再按配对生产叶验证；不以mock证明真实FGA/跨租户。

## W6 元数据结构CAS必要存储接缝

- [x] **T634 · 元数据结构独立修订结构测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_schema_revision.py`\
  **逻辑 / 测试上下文**：对应既有expected_schema_revision协议，独立整数server/Python默认0、排除旧响应、DDL幂等且无数据转换、唯一head父链。\
  **依赖**：T605\
  **覆盖 AC**: AC-34, AC-49, AC-54\
  **验证 / 完成条件**：测试先独立红测提交，不能以本卡声称元数据旧写端已接线。

- [x] **T635 · 元数据结构独立修订SQLModel及DDL**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge.py`；`src/backend/bisheng/core/database/alembic/versions/f118_metadata_schema.py`\
  **逻辑 / 测试上下文**：仅加私有metadata_schema_revision非空Integer/default0，与模型/默认配置修订分离；新结构revision挂实际唯一head，guard已有列，不回填内容或重写旧迁移。\
  **依赖**：T634\
  **配对测试**：T634\
  **验证 / 完成条件**：配对测试/既有单head/结构测试与Ruff通过；真实双库后续T202实测。

## W6 PROC 原始审计及真实范围接缝

- [x] **T636 · 任务原始接受修订审计测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_acceptance_revision.py`\
  **逻辑 / 测试上下文**：创建显式保存接受R，expected_R合法推进/重试不覆盖原始R；缺证据拒绝、不由历史参数伪造。\
  **依赖**：T611\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T637 · 任务原始接受修订模型**
  **类型 / Owner**：基础设施 / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_processing_job.py`\
  **逻辑 / 测试上下文**：仅新增accepted_model_config_revision可空审计列；正常创建赋值由T645同一repo叶完成，不加独立模型绑定。\
  **依赖**：T636\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T638 · 任务接受修订结构升级测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_acceptance_migration.py`\
  **逻辑 / 测试上下文**：结构只加nullable审计列、无data copy，幂等且parent为实际唯一head。\
  **依赖**：T635\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T639 · 任务接受修订结构升级**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/core/database/alembic/versions/f118_processing_acceptance.py`\
  **逻辑 / 测试上下文**：挂f118_metadata_schema，仅DDL guard add column，无在线/隐式数据回填。\
  **依赖**：T638, T637\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T640 · 任务自身切换域内收据测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_cutover_receipts.py`\
  **逻辑 / 测试上下文**：伪造receipt、跨事务/job/operation/旧lease/重复消费拒绝，合法同事务Owner切换收据可消费。\
  **依赖**：T613\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T641 · 任务自身切换域内收据窄能力**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/processing_cutover_receipts.py`\
  **逻辑 / 测试上下文**：域内共享私有登记/消费能力，Owner完成实际R2与job guard才签发，Repository不反向依赖application。\
  **依赖**：T640\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T642 · 处理任务真实版本范围仓储测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_owner_repository.py`\
  **逻辑 / 测试上下文**：真实document/version/file正确JOIN及所有版本、指定版本不扩、跨tenant拒绝、外部Session回滚；多文档版本无笛卡尔积。\
  **依赖**：T611\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T643 · 处理任务真实版本范围仓储**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/processing_owner_repository.py`\
  **逻辑 / 测试上下文**：aload_scope原生Session返回真实整版本manifest/稳定顺序，当前租户查询，不自commit或拼独立列表。\
  **依赖**：T642\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先测试再实现，记录真实红/首绿；同Session/真实Owner组合验证，不以fake范围替代生产。

- [x] **T644 · 任务接受修订真实创建仓储回归**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_acceptance_revision.py`\
  **逻辑 / 测试上下文**：在T636模型测试之后补实际acreate接受R、幂等重放不覆盖、retry/后续切换不伪造初值；不把审计存到parameters。\
  **依赖**：T637, T611\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：独立提交实际仓储红测，记录真实结果，不提前修改切换代码。

- [x] **T645 · 任务接受修订真实创建仓储写入**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`\
  **逻辑 / 测试上下文**：仅正常acreate时显式写当前Owner配置R；已存在job/retry/cutover不覆写，旧NULL缺证据不猜。\
  **依赖**：T644\
  **配对测试**：T644\
  **验证 / 完成条件**：T644与原job仓储组合全绿，Owner及收据在后续对应卡组合验证。

## W6 KN 生命周期及清单真实接缝

- [x] **T646 · 普通有界清单与管理员分页测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_list.py`\
  **逻辑 / 测试上下文**：真实SQL seek/tenant/type3、批量权限、100/1000预算、全拒空页进展、NULL时间/同时间稳定翻页及admin角色/DB总数。\
  **依赖**：T605\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-33, AC-35, AC-84\
  **验证 / 完成条件**：先测试独立红/首绿，再实现≤2叶；真实接线与有界行为不能由fake-only Service代替。

- [x] **T647 · 普通有界清单与管理员分页仓储**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/knowledge_space_listing_repository.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：按W6§4新增candidate seek与admin SQL分页、service有界visible清单；不全量枚举FGA，不改变旧mine/joined/managed含义。\
  **依赖**：T646, T082\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-33, AC-35, AC-84\
  **验证 / 完成条件**：先测试独立红/首绿，再实现≤2叶；真实接线与有界行为不能由fake-only Service代替。

- [x] **T648 · 统一创建与清单HTTP接缝测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_creation_api.py`\
  **逻辑 / 测试上下文**：真实路由请求/响应、普通与高级create资格/条件管理头、具体tenant清单与普通CursorPage，保旧字段及错误。\
  **依赖**：T080, T082, T647\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-33, AC-35, AC-84\
  **验证 / 完成条件**：先测试独立红/首绿，再实现≤2叶；真实接线与有界行为不能由fake-only Service代替。

- [x] **T649 · 统一创建与清单HTTP接缝**
  **类型 / Owner**：后端 API / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`；`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`\
  **逻辑 / 测试上下文**：仅新增已冻结两create字段和普通/admin清单，转发可信context，无Endpoint直接SQL、不把body视为权限权威。\
  **依赖**：T648\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-33, AC-35, AC-84\
  **验证 / 完成条件**：先测试独立红/首绿，再实现≤2叶；真实接线与有界行为不能由fake-only Service代替。

- [x] **T650 · 已知生命周期旧adapter回归对齐**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/permission/test_f048_knowledge_space_adapter.py`；`src/backend/test/knowledge/test_managed_spaces_visible_edit.py`\
  **逻辑 / 测试上下文**：原COPYING/FAILED非法资源断言改为真实未知/已删除态；保租户缺失/错误type/快照/隐藏响应及原FGA拒绝断言，不按新已知生命周期误拒。\
  **依赖**：T078\
  **覆盖 AC**: AC-30, AC-31, AC-33, AC-35, AC-48\
  **验证 / 完成条件**：记录语义退休差异，配新旧adapter/preview/download同选集全绿；不得通过删拒绝测试实现。

## W6 LLM 精确影响核心真实接缝

- [x] **T651 · 受信Owner有界入向引用查询测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_reference_owner_paging.py`\
  **逻辑 / 测试上下文**：真实native Session、issued owner scope/transaction/目标全集、稳定页跨tenant与多来源多slot、分页总量无截断/无Cartesian，裸target/跨事务拒绝。\
  **依赖**：T605\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-85, AC-89\
  **验证 / 完成条件**：先真实红/首绿测试再实现，每卡≤2叶；无真实Coverage不能假ready，后续执行/HTTP另验。

- [x] **T652 · 受信Owner有界入向引用仓储**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：仅扩原REF仓储的受信scope seek分页及必要聚合；不开放任意tenant查询，不改R2写协议。\
  **依赖**：T651\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-85, AC-89\
  **验证 / 完成条件**：先真实红/首绿测试再实现，每卡≤2叶；无真实Coverage不能假ready，后续执行/HTTP另验。

- [x] **T653 · 模型删除目标归属原生仓储测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_deletion_repository.py`\
  **逻辑 / 测试上下文**：模型/服务真实归属、具体tenant/固定锁序、retained ID完整性，跨其他Child/异server注入拒绝，读锁无share副作用。\
  **依赖**：T605\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-85, AC-89\
  **验证 / 完成条件**：先真实红/首绿测试再实现，每卡≤2叶；无真实Coverage不能假ready，后续执行/HTTP另验。

- [x] **T654 · 模型删除目标归属原生仓储**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/model_deletion_repository.py`\
  **逻辑 / 测试上下文**：外部Session读取/锁服务及模型完整集合，真实owner验证，不沿用旧bulk无tenant漏口；写DML留后续执行合同。\
  **依赖**：T653\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-85, AC-89\
  **验证 / 完成条件**：先真实红/首绿测试再实现，每卡≤2叶；无真实Coverage不能假ready，后续执行/HTTP另验。

- [x] **T655 · 模型独立持久确认仓储测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_delete_plan_repo.py`\
  **逻辑 / 测试上下文**：模型manifest/space_id=None、稳定原actor排trace、命令/修订/inbound/Coverage/到期绑定、consume幂等和秘密拒绝。\
  **依赖**：T605\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-85, AC-89\
  **验证 / 完成条件**：先真实红/首绿测试再实现，每卡≤2叶；无真实Coverage不能假ready，后续执行/HTTP另验。

- [x] **T656 · 模型独立持久确认仓储**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/model_delete_plan_repository.py`\
  **逻辑 / 测试上下文**：复用现plan表且模型协议独立于PROC，外部Session仅flush；不存API key/服务完整body，不用modelID冒充文件。\
  **依赖**：T655\
  **覆盖 AC**: AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-85, AC-89\
  **验证 / 完成条件**：先真实红/首绿测试再实现，每卡≤2叶；无真实Coverage不能假ready，后续执行/HTTP另验。

- [x] **T657 · 保留失败重建源的检索隔离测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_rebuild_failed_visibility.py`\
  **逻辑 / 测试上下文**：真实SQL文件状态下，保留ES源但空间候选/post-filter排除失败与处理中，仅成功合法版本参与；F048/QA/原显式版本语义及预览下载保持。\
  **依赖**：T605\
  **覆盖 AC**: AC-35, AC-48, AC-49, AC-52, AC-53, AC-54\
  **验证 / 完成条件**：先提交真实状态回归，不能以删ES文本或只清Milvus代替检索裁剪。

- [x] **T658 · 保留失败重建源的检索隔离接线**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_file_visibility_service.py`\
  **逻辑 / 测试上下文**：空间候选与post_filter按现真实成功状态裁剪检索，保权限/primary及原显式版本/QA语义，不扩大edit或禁止预览下载；与066后组合验证。\
  **依赖**：T657\
  **配对测试**：T657\
  **验证 / 完成条件**：配对与原visibility/检索回归全绿，真实ES/Milvus行为由后续E2E验，不先标T102全量完成。

- [x] **T659 · 检索成功态边界旧fixture对齐**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_file_visibility_primary_filter.py`；`src/backend/test/knowledge/test_knowledge_file_visibility_batch.py`\
  **逻辑 / 测试上下文**：原仅权限/主版本的单测补_successful_file_ids成功集合边界，保原FGA/primary拒绝断言；真实SQL状态由T657覆盖，不连接中间件或绕生产过滤。\
  **依赖**：T658\
  **覆盖 AC**: AC-35, AC-48, AC-49, AC-52, AC-53\
  **验证 / 完成条件**：明确原2失败为新增SQL边界缺fixture，新旧同选集全绿；仅两旧测试叶。

## W6 J1 全局finalize恢复必要结构接缝

- [x] **T660 · finalize-only重试收据结构测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_finalize_retry_receipt_schema.py`\
  **逻辑 / 测试上下文**：真实SQL CHECK允许0项恢复receipt但负数/非法身份/修订仍拒绝；业务窄资格由query/job Service测试另验。\
  **依赖**：T645\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先真实红再实现，原正负约束回归保留；仅finalize恢复必须真实Owner组合验证，不伪改成功item。

- [x] **T661 · finalize-only重试收据模型约束**
  **类型 / Owner**：基础设施 / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_processing_retry.py`\
  **逻辑 / 测试上下文**：仅ck_kpr_revision item_count>=0，其余身份与修订约束不变，不把0项伪报1项。\
  **依赖**：T660\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先真实红再实现，原正负约束回归保留；仅finalize恢复必须真实Owner组合验证，不伪改成功item。

- [x] **T662 · finalize-only收据结构升级测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_finalize_retry_receipt_migration.py`\
  **逻辑 / 测试上下文**：DDL-only/实际唯一parent、DM大小写反射、新定义no-op、已知旧check替换、未知定义拒绝，不读写业务数据。\
  **依赖**：T639\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先真实红再实现，原正负约束回归保留；仅finalize恢复必须真实Owner组合验证，不伪改成功item。

- [x] **T663 · finalize-only收据结构升级**
  **类型 / Owner**：基础设施 / INT\
  **写入文件**：`src/backend/bisheng/core/database/alembic/versions/f118_finalize_retry.py`\
  **逻辑 / 测试上下文**：挂f118_processing_acceptance，仅幂等替换已知check为item_count>=0，复用共享DDL guard，真实双库由202验证。\
  **依赖**：T662, T661\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：先真实红再实现，原正负约束回归保留；仅finalize恢复必须真实Owner组合验证，不伪改成功item。

- [x] **T664 · 专用模型ETL mock上游wire契约测试**
  **类型 / Owner**：测试 / MOCK\
  **写入文件**：`src/backend/test/knowledge_unification/test_mock_upstreams_contract.py`\
  **逻辑 / 测试上下文**：真实SDK float32/base64 8/16维、chat两态、真实ETL loader Document、txt/md本地不调ETL、并发一次失败/计数分桶；无远端/DB依赖。\
  **依赖**：T605\
  **覆盖 AC**: AC-06, AC-38, AC-48, AC-49, AC-50, AC-52, AC-53, AC-54\
  **验证 / 完成条件**：先提交实际红再实现，不以测试上游替真实中间件或provider质量验收。

- [x] **T665 · 专用模型ETL mock上游辅助进程**
  **类型 / Owner**：测试基础设施 / MOCK\
  **写入文件**：`src/backend/test/e2e/helpers/f118_mock_upstreams.py`\
  **逻辑 / 测试上下文**：按W6§8既有wire实现单worker FastAPI/uvicorn CLI、确定embedding/chat/ETL、最小内存控制/计数，不导入业务config/DB，不建通用mock平台。\
  **依赖**：T664\
  **配对测试**：T664\
  **验证 / 完成条件**：真实客户端合同全绿，部署与真实中间件/E2E由INT后续验证；只私有测试网络。

## W6 重建保源旧回归夹具对齐

- [x] **T666 · 保源后容器状态旧回归夹具对齐**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge/test_rebuild_keeps_container_usable.py`\
  **逻辑 / 测试上下文**：T066删除失败ES正文清理能力后，旧夹具仍monkeypatch已删除_delete_es_files导致4例在断言前失败；仅移除此失效patch及未用import，保部分失败发布、整体异常/准入失败保pending等原断言。\
  **依赖**：T066, T658\
  **覆盖 AC**: AC-35, AC-48, AC-49, AC-52, AC-53, AC-54\
  **验证 / 完成条件**：记录主组合4项实际夹具失败；原4例及真实新保源/检索/worker组合通过，不恢复已退休删除ES行为。

## W6 KN重建期真实状态接缝

- [x] **T667 · 重建期纯状态判定测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_processing_guard.py`\
  **逻辑 / 测试上下文**：已加载空间的REBUILDING/transition拒10999，其他生命周期仍原业务处理；不授权限、不新增动作，不伪造任务或模型。\
  **依赖**：T078, T605\
  **覆盖 AC**: AC-31, AC-35, AC-48, AC-51\
  **验证 / 完成条件**：先测试独立红/首绿，不在测试卡改生产。

- [x] **T668 · 重建期纯状态判定**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_processing_guard.py`\
  **逻辑 / 测试上下文**：实现W6§9纯业务状态函数，供已授权业务消费，无DB/FGA/新权限层。\
  **依赖**：T667\
  **配对测试**：T667\
  **验证 / 完成条件**：配对与相关生命周期测试通过。

- [x] **T669 · 上传版本移动重建冲突入口测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_rebuild_write_entries.py`\
  **逻辑 / 测试上下文**：真实Space/Version业务及SQL边界覆盖已在重建的上传/网页/目录上传、新版本/主版/合并、移入出；拒绝前零fetch/对象/版本/索引副作用，原权限/开关不放宽，rename/空folder不新增阻断。\
  **依赖**：T668, T082\
  **覆盖 AC**: AC-09, AC-10, AC-17, AC-31, AC-51\
  **验证 / 完成条件**：真实红测后再接生产；不声称覆盖排除的worker在途IO竞态。

- [x] **T670 · 上传版本移动重建冲突接线**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py`\
  **逻辑 / 测试上下文**：只沿W6§9实际写入口调用统一状态函数，保原权限动作及版本/对象语义，不提前改解析调度/J1快照。\
  **依赖**：T669\
  **配对测试**：T669\
  **验证 / 完成条件**：新旧相关上传/版本/移动回归通过；完整T084/T098仍待后续委托。

- [x] **T671 · 重建检索暂停原因真实入口测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_rebuild_retrieval_gate.py`\
  **逻辑 / 测试上下文**：真实SQL空间、原可见授权后，候选及post-filter重建返回10999，未发检索；目录/下载和成功文件/主版裁剪原语义保留。\
  **依赖**：T668, T658\
  **覆盖 AC**: AC-35, AC-48, AC-51, AC-53\
  **验证 / 完成条件**：测试先提交真实红，不mock整个Service。

- [x] **T672 · 重建检索暂停原因接线**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_file_visibility_service.py`\
  **逻辑 / 测试上下文**：实际space候选及post-filter已授权路径调用状态gate，保原QA/显式版本/F048行为，不把暂停当无权限/空结果。\
  **依赖**：T671\
  **配对测试**：T671\
  **验证 / 完成条件**：配对、原检索可见性和重建回归通过；真实索引由E2E验。

## W6文件实际处理及权限正式采集接缝

- [x] **T673 · 文件处理真实Owner快照测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_processing_owner.py`\
  **逻辑 / 测试上下文**：实际File/Document/Version及当前模型/规则，preview零业务修改，接受冻结原source/实际规则，状态及item同TX，相关RG/源变化拒绝。\
  **依赖**：T070, T643\
  **覆盖 AC**: AC-10, AC-43, AC-44, AC-45, AC-49, AC-53, AC-54\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T674 · 文件处理真实Owner及受控状态写**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/processing_owner.py`；`src/backend/bisheng/knowledge/domain/repositories/processing_owner_repository.py`\
  **逻辑 / 测试上下文**：按W6§10扩preview/prepare/complete，外部native Session，真实租户/版本/源/lease/RG；不改模型/R2、不伪造BG或零项任务。\
  **依赖**：T673\
  **覆盖 AC**: AC-10, AC-43, AC-44, AC-45, AC-49, AC-53, AC-54\
  **配对测试**：T673\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T675 · 文件处理确认接收恢复用例测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_processing_service.py`\
  **逻辑 / 测试上下文**：指定版本与opaque覆盖确认、实际规则snapshot、无合法模型拒绝、目标重叠冲突、失败/安全/人工重试，成功项不重跑，改默认不影响既有快照。\
  **依赖**：T674, T064\
  **覆盖 AC**: AC-34, AC-43, AC-44, AC-45, AC-49, AC-50, AC-53, AC-54\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T676 · 文件处理确认接收恢复用例**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/processing_job_service.py`\
  **逻辑 / 测试上下文**：原Service扩两真实kind，只实际装配后接受；接收/重试文件状态和J1同事务，保持原身份、全scope与失效诊断。\
  **依赖**：T675\
  **覆盖 AC**: AC-34, AC-43, AC-44, AC-45, AC-49, AC-50, AC-53, AC-54\
  **配对测试**：T675\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T677 · 文件处理真实HTTP到worker接线测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_processing_wire.py`；`src/backend/test/knowledge_unification/test_processing_endpoints.py`\
  **逻辑 / 测试上下文**：原未装配file_reprocess断言改为仍未装配且DTO合法的metadata_schema_change，保原错误/分页拒绝；真实ASGI/Service/Owner/SQL和两阶段pipeline处理，只指定历史version、不增版本授权、真失败/安全状态、成功保留、旧lease/RG及凭据失效拒绝。\
  **依赖**：T068, T676\
  **覆盖 AC**: AC-10, AC-43, AC-44, AC-45, AC-49, AC-50, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T678 · 文件处理真实worker和HTTP装配**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/processing_jobs.py`；`src/backend/bisheng/knowledge/api/endpoints/processing.py`\
  **逻辑 / 测试上下文**：prepare真实docs后原actor/lease/RG再验写指定file；结果同TX受控落地，不整col reset/cutover；装配available kinds后实际闭环。\
  **依赖**：T677\
  **覆盖 AC**: AC-10, AC-43, AC-44, AC-45, AC-49, AC-50, AC-53, AC-54, AC-86\
  **配对测试**：T677\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T679 · 旧文件规则真实调用端测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_legacy_file_processing_callers.py`\
  **逻辑 / 测试上下文**：旧rebuild精确核file/原请求space归属及原1/4/5/Root重建状态，拒绝前零副作用，不加新权限动作；原save/asave及rebuild消费同adapter，显式null/缺省/每file Excel区分，已有完整规则不套新默认，不改变旧参数/envelope与身份。\
  **依赖**：T070\
  **覆盖 AC**: AC-39, AC-40, AC-43, AC-44, AC-66\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T680 · 旧文件规则真实调用端接线**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_utils.py`\
  **逻辑 / 测试上下文**：旧rebuild精确核file/原请求space归属及原1/4/5/Root重建状态，拒绝前零副作用，不加新权限动作；仅原save/asave与旧rebuild规则适配，SpaceService由KN T084串行接，不改其他API/模型/权限语义。\
  **依赖**：T679\
  **覆盖 AC**: AC-39, AC-40, AC-43, AC-44, AC-66\
  **配对测试**：T679\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T681 · 权限正式原始分页采集测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_migration_snapshot.py`\
  **逻辑 / 测试上下文**：真实native Session采旧use Catalog/原Auth pin，四表PK seek无截断/无Cartesian，inactive/retired保留、坏父链与tenant/bypass拒绝、只读不偷flush。\
  **依赖**：T160, T605\
  **覆盖 AC**: AC-31, AC-56, AC-59, AC-63, AC-78, AC-80, AC-81, AC-83, AC-85\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T682 · 权限正式原始分页采集仓储**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/repositories/f118_migration_snapshot_repository.py`\
  **逻辑 / 测试上下文**：按W6§11精确物理行/原pin分页，外部Session+no_autoflush+strict，无current_catalog在线派生、网络、DDL、停服检测或写副作用。\
  **依赖**：T681\
  **覆盖 AC**: AC-31, AC-56, AC-59, AC-63, AC-78, AC-80, AC-81, AC-83, AC-85\
  **配对测试**：T681\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T683 · 无可重建文件显式模型保存测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_empty_model_change.py`\
  **逻辑 / 测试上下文**：真实物理File/Document/Version完整性和无active任务，合法空/全跳过空间prepare/apply最终current模型/R2；失效目标/漂移回滚，无provider或伪0项job。\
  **依赖**：T674, T258\
  **覆盖 AC**: AC-07, AC-33, AC-48, AC-54, AC-74, AC-87\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T684 · 无可重建文件显式模型保存Owner**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/processing_owner_repository.py`\
  **逻辑 / 测试上下文**：复用原事务身份登记的真实R2 prepare/apply，核实际全物理scope，不冒充BG finalize；HTTP确认/旧响应待KN原T098接线，纯手动0参与rebuild仍不可执行。\
  **依赖**：T683\
  **覆盖 AC**: AC-07, AC-33, AC-48, AC-54, AC-74, AC-87\
  **配对测试**：T683\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

- [x] **T685 · 重建状态gate旧上传夹具对齐**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_space_folder_upload.py`；`src/backend/test/knowledge/test_web_link_import_dedup.py`\
  **逻辑 / 测试上下文**：原Mock/简化space fixture补真实idle state及model_transition=None；新增13例缺fixture导致失败，对照同选集基线10红35绿，保count/depth/同名/重复内容断言，不改其他基线失败。\
  **依赖**：T670\
  **覆盖 AC**: AC-09, AC-14, AC-51\
  **验证 / 完成条件**：按冻结接口先独立真实红测/首绿再生产，≤2叶，记录实际相关组合与未运行项；不以局部helper替代完整调用链。

## W6重建状态检索旧夹具对齐

- [x] **T686 · 原检索权限与主版本夹具对齐**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_file_visibility_batch.py`；`src/backend/test/knowledge/test_knowledge_file_visibility_primary_filter.py`\
  **逻辑 / 测试上下文**：T672增实际root状态检查后原mock补显式idle态和精确root读取边界，root SQL计数1→2仅限实际新增一次状态读；保100批量/峰值IO、F048/primary全部断言，不在生产回退缺字段。\
  **依赖**：T672\
  **覆盖 AC**: AC-08, AC-35, AC-48, AC-51\
  **验证 / 完成条件**：记录旧batch5红9绿及相关主版fixture实际差异；同选集新旧检索边界通过，不删原拒绝断言。

- [x] **T687 · 保源检索SQL夹具补实际空间根**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_rebuild_failed_visibility.py`\
  **逻辑 / 测试上下文**：原真实file/doc/version SQLite补真实Knowledge表和idle root，精确pin原DAO Session；保成功/失败/primary/FGA原断言，不连中间件或用mock替代实际SQL。\
  **依赖**：T672\
  **覆盖 AC**: AC-35, AC-48, AC-51, AC-53\
  **验证 / 完成条件**：原真实SQL保源/状态过滤与新重建暂停组合通过。

## W6迁移持久artifact接缝

- [x] **T688 · 原基线计划artifact完整性测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_artifacts.py`\
  **逻辑 / 测试上下文**：现MinIO async IO边界验证canonical bytes/hash/key、写后读回、已有内容幂等/损坏拒绝、跨run/kind/路径注入拒绝、持久非tmp及有界页面，不以put返回值猜hash。\
  **依赖**：T160\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：先独立真实红，再薄adapter实现；单元边界与后续真实MinIO集成证据分开。

- [x] **T689 · 原基线计划持久artifact适配**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_artifacts.py`\
  **逻辑 / 测试上下文**：实现W6§12精确现MinIO三async方法，无新存储框架/HTTP/SQL/停服控制；只已读回核验指针交ledger，完整tenant冻结由后续编排同TX完成。\
  **依赖**：T688\
  **配对测试**：T688\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：配对、旧ledger/legacy descriptor组合通过；真实MinIO写读后单列证据，不伪称M2正式冻结已完成。

## W6旧表格不限行实际规则兼容接缝

- [x] **T690 · 旧表格不限行快照与请求兼容测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_legacy_unbounded_table_snapshot.py`\
  **逻辑 / 测试上下文**：真实旧renderer对已存None/0/负数、旧3.x明确0/负数、null未指定区分及headers/append实际规则对照；新默认/公开overrides仍拒0及marker，显式正数覆盖和retry实际快照保持。\
  **依赖**：T070\
  **覆盖 AC**: AC-39, AC-40, AC-43, AC-44, AC-45, AC-66\
  **验证 / 完成条件**：先真实红/首绿，不能以猜默认或伪正数隐藏执行override代替实际规则。

- [x] **T691 · 旧表格不限行内部实际规则表达**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/processing_settings.py`；`src/backend/bisheng/knowledge/application/file_processing_adapter.py`\
  **逻辑 / 测试上下文**：W6§10内部LegacyTableRule/legacy稀疏覆盖与实际snapshot分支，保旧规则不套新space；原公开defaults/overrides继续严格正数，无HTTP/DDL扩展。\
  **依赖**：T690\
  **配对测试**：T690\
  **覆盖 AC**: AC-39, AC-40, AC-43, AC-44, AC-45, AC-66\
  **验证 / 完成条件**：配对及旧adapter/真实file pipeline/settings组合通过，实际旧无限行分段对照一致。

- [x] **T692 · 两端只读实际规则镜像补旧分支**
  **类型 / Owner**：前端 DTO / INT\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`；`src/frontend/client/src/api/knowledgeProcessing.ts`\
  **逻辑 / 测试上下文**：仅EffectiveProcessingSnapshot的只读effective_rule联合增加固定0/legacy_unbounded真分支；新默认/命令类型不引该分支，不新增UI能力。\
  **依赖**：T691, T175, T187\
  **覆盖 AC**: AC-40, AC-43, AC-44, AC-66\
  **验证 / 完成条件**：两端既有API合同回归及新增类型诊断0，无依赖/锁文件变化。

## W6六来源正式原始盘点接缝

- [x] **T693 · 六来源原始分页事实仓储测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_inventory_repository.py`\
  **逻辑 / 测试上下文**：真实401+页/单根200+版本、零版本/关联、disabled/非current/删除原状态保留；真实父tenant/type与全局无payload孤儿探针，非法游标/bypass/只读autoflush、<=201预算无Cartesian/OFFSET；目录不按槽重扫，配置不入artifact。\
  **依赖**：T160, T682\
  **覆盖 AC**: AC-55, AC-56, AC-63, AC-64, AC-70, AC-71, AC-80, AC-85, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：先真实红/首绿，真实SQL验证原形状及完整枚举；不把raw事实冒充Source授权/ready。

- [x] **T694 · 六来源原始分页事实仓储**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_inventory_repository.py`\
  **逻辑 / 测试上下文**：按W6§13全部精确方法/闭集Row，外部Session+no_autoflush+strict；Root/版本/整批子页独立，坏链不静默漏；Knowledge0/1/3/退休2原事实保留，raw配置仅内存repr隐藏。\
  **依赖**：T693\
  **配对测试**：T693\
  **覆盖 AC**: AC-55, AC-56, AC-63, AC-64, AC-70, AC-71, AC-80, AC-85, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：配对及既有ledger/permission原采集组合通过，C2静态保持；未集成正式M2/FGA/CLI前不勾完整T162。

## W6平台普通清单与创建真实初值接缝

- [x] **T695 · 创建初值真实HTTP与窄投影测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_creation_settings.py`\
  **逻辑 / 测试上下文**：真实路由经原创建Policy、原identity与外部Session读取工作台原配置；无配置/失效默认保ID、系统规则来自真实schema，错误原样传播且零写、无执行模型准入。\
  **依赖**：T078, T694\
  **覆盖 AC**: AC-06, AC-07, AC-38, AC-39, AC-40, AC-87\
  **验证 / 完成条件**：按冻结合同测试先行、≤2叶；目标检查与既有诊断基线比较，真实HTTP/环境E2E另行举证。

- [x] **T696 · 后台创建初值真实应用与静态路由**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/creation_settings.py`；`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`\
  **逻辑 / 测试上下文**：按W6§14返回闭集ID/名称与系统默认；复用真实Policy及raw default runtime，不跨层查询、不伪资源授权、不返回其他配置。\
  **依赖**：T695\
  **配对测试**：T695\
  **覆盖 AC**: AC-06, AC-07, AC-38, AC-39, AC-40, AC-87\
  **验证 / 完成条件**：按冻结合同测试先行、≤2叶；目标检查与既有诊断基线比较，真实HTTP/环境E2E另行举证。

- [x] **T697 · 平台普通清单与创建scope合同测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/knowledgeSpaceContract.test.ts`；`src/frontend/platform/src/test/knowledgeQueryScope.test.tsx`\
  **逻辑 / 测试上下文**：精确新list/bootstrap/create序列化和conditional管理头，opaque空页继续、身份tenant隔离、迟到mutation不落新scope或跳转、异常保留。\
  **依赖**：T692\
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-07, AC-87\
  **验证 / 完成条件**：按冻结合同测试先行、≤2叶；目标检查与既有诊断基线比较，真实HTTP/环境E2E另行举证。

- [x] **T698 · 平台普通清单与创建API及hook**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`；`src/frontend/platform/src/controllers/hooks/knowledge.ts`\
  **逻辑 / 测试上下文**：按W6§14三方法和scope hooks，现wrapped axios、useInfiniteQuery，普通简化创建不加管理头，高级提交仅捕获的具体管理tenant。\
  **依赖**：T697, T696\
  **配对测试**：T697\
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-07, AC-87\
  **验证 / 完成条件**：按冻结合同测试先行、≤2叶；目标检查与既有诊断基线比较，真实HTTP/环境E2E另行举证。

## W6元数据结构原子准备前置

- [x] **T699 · 元数据完整原始范围与事务仓储测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_processing_repository.py`\
  **逻辑 / 测试上下文**：实际物理File与完整Doc/Version链、401历史版本含失败与安全态、合法空目录和目录坏链、C3/严格Session/noautoflush、线性primary集合与冲突拒绝。\
  **依赖**：T674, T684\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-53, AC-54\
  **验证 / 完成条件**：先真实红/首绿，≤2叶和固定SHA独立复查；不把原生事务核心冒充任务或公开入口完成。

- [x] **T700 · 元数据完整范围原生事务仓储**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/metadata_processing_repository.py`\
  **逻辑 / 测试上下文**：按W6§15提供完整闭集scope及schema CAS需要的原生事务能力；无commit/外部IO/SQL跨层，无model R/G变化、无File状态变更。\
  **依赖**：T699\
  **配对测试**：T699\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-53, AC-54\
  **验证 / 完成条件**：先真实红/首绿，≤2叶和固定SHA独立复查；不把原生事务核心冒充任务或公开入口完成。

- [x] **T701 · 元数据结构原子准备与固定值快照测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_processing_preparation.py`\
  **逻辑 / 测试上下文**：真实preview取消零写，add清残留为空、rename/delete校验及保留非目标字段，schema n→n+1与外部回滚；plan同Session/事务/实例不可伪造，漂移无写。\
  **依赖**：T700\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-53, AC-54\
  **验证 / 完成条件**：先真实红/首绿，≤2叶和固定SHA独立复查；不把原生事务核心冒充任务或公开入口完成。

- [x] **T702 · 元数据结构原子准备内核**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/metadata_processing_service.py`\
  **逻辑 / 测试上下文**：实现W6§15 apreview/aaccept签名和不可伪造同事务plan，只flush真实schema CAS及固定逐项before/after；J1/worker/旧入口后续，不能勾原T072整卡。\
  **依赖**：T701\
  **配对测试**：T701\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-53, AC-54\
  **验证 / 完成条件**：先真实红/首绿，≤2叶和固定SHA独立复查；不把原生事务核心冒充任务或公开入口完成。

## W6正式盘点全局物理目标事实前置

- [x] **T703 · 迁移物理目标与跨租户区分测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_knowledge_targets.py`；`src/backend/test/knowledge_unification/test_migration_model_targets.py`\
  **逻辑 / 测试上下文**：真实local/foreign/Root/offline/type2/缺父/错父/不存在分别保事实；DIR原folder引用不被过滤；200精确PK批量/重复去重/非法输入零SQL、noautoflush/strict/外部TX、无BRR初始化依赖。\
  **依赖**：T694\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-71, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：按W6§16先真实红，性能以真实SQL计数断言；不把physical facts当授权收据或legacy证明。

- [x] **T704 · 两业务Owner迁移物理事实仓储**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_target_repository.py`；`src/backend/bisheng/llm/domain/repositories/migration_target_repository.py`\
  **逻辑 / 测试上下文**：W6§16对应Owner闭集事实、最窄精确PK跨scope只读；存在foreign与坏父不变missing，普通Owner/R2/ready不改，名称与sharing资格后续。\
  **依赖**：T703\
  **配对测试**：T703\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-71, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：配对及原盘点/target边界通过，C2静态及独立固定SHA审；不勾完整M2/回填任务。

## W6平台处理默认受控草稿真实消费前置

- [x] **T705 · 两类默认规则受控字段测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118ProcessingDefaultsFields.test.tsx`\
  **逻辑 / 测试上下文**：真实InputNumber/Checkbox控制保空值与越界输入，文档完整字段、PDF选项、层级6；表格不要求fileList/逐file开关；旧上传原用法回归。\
  **依赖**：T698, T696\
  **覆盖 AC**: AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44\
  **验证 / 完成条件**：先真实红再T178两叶实现，原组件调用及目标lint/strict基线无新增诊断；locale由INT。

- [x] **T706 · 双类型草稿及保存边界测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118ProcessingDefaultsEditor.test.tsx`；`src/frontend/platform/src/test/f118ProcessingDefaultsDialog.test.tsx`\
  **逻辑 / 测试上下文**：真实Editor/Dialog切类型保草稿、双类型完整校验、空值不coerce、取消/失败/CAS不改已存、成功整体提交、切scope与迟到响应隔离。\
  **依赖**：T178, T698\
  **覆盖 AC**: AC-07, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-87\
  **验证 / 完成条件**：先真实红，注入形状同原API port，不造生产mock开关；初值不硬编码。

- [x] **T707 · 双类型默认草稿编辑与持久保存host**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/ProcessingDefaultsEditor.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/ProcessingDefaultsDialog.tsx`\
  **逻辑 / 测试上下文**：W6§17受控Editor与真实settings API/scope hook host，完整draft和expected版本整体提交，仅成功生效，不建历史任务、不扩权限。\
  **依赖**：T706\
  **配对测试**：T706\
  **覆盖 AC**: AC-07, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-87\
  **验证 / 完成条件**：配对、旧规则/上传调用回归、lint/strict新增0，固定独立审；真实页面挂载与E2E另卡。

## W6平台默认策略三语实际词条

- [x] **T708 · 平台默认策略中英文文案**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/zh-Hans/knowledge.json`；`src/frontend/platform/public/locales/en-US/knowledge.json`\
  **逻辑 / 测试上下文**：原平台实际locale源新增knowledge:f118受控默认策略词条，nested snake_case，字段/范围/失败和未来上传提示；不全局改selector或错误码生成文件。\
  **依赖**：T705, T002\
  **验证 / 完成条件**：JSON无重复可解析，原keys原值不变，新键与日文同集且插值一致；原T198整体最终词条门禁另验。

- [x] **T709 · 平台默认策略日文与三语核对**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/ja/knowledge.json`\
  **逻辑 / 测试上下文**：补同一批日文专业词条，保持平台useTranslation命名空间与原键；范围提示、校验和无保存失败结果一致。\
  **依赖**：T708\
  **验证 / 完成条件**：三语新key/插值完全一致，现有i18n检查无新增问题；不把独立文案完成当页面或E2E完成。

## W6迁移APP原名目录线性解析前置

- [x] **T710 · 原名称解析语义与线性复杂度测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_name_index.py`\
  **逻辑 / 测试上下文**：原Port对照bare/qualified/slash/歧义/离线/不可见模型，KN0/3名称及QA/退休排除、显式ID无fallback、坏目录拒绝；大量不同slots真实属性读取预算不形成请求×目录全扫。\
  **依赖**：T694, T704\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-71, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：先真实红/首绿，原语义与性能分别举证；无sharing生产装配不勾M2整卡。

- [x] **T711 · 原APP名称线性索引**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_names.py`\
  **逻辑 / 测试上下文**：W6§18纯一次编译原NameCatalog与KN名字目录，逐slot O(1)索引及原错误；不自授Root共享、不写/查外部系统、不改变声明。\
  **依赖**：T710\
  **配对测试**：T710\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-71, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：配对/原APP解析组合通过，固定独立审、C2静态；不是Source授权或legacy证据。

## W6正式原授权pin的完整共享事实读取

- [x] **T712 · M2原pin与共享流完整性测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_permission_read.py`\
  **逻辑 / 测试上下文**：显式原store/model/checksum与ACTIVE release，错误pin/factory repin/非法原tenant/关闭拒绝；2000共享完整流、畸形/中断不返回部分，专属连接释放且不触发online/停服控制。\
  **依赖**：T682, T704\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：先真实红/首绿，现FGAClient真实流parser单列组合；端口fake不冒称真实OpenFGA环境。

- [x] **T713 · M2原pin共享读取适配**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/permission/application/migration_read.py`\
  **逻辑 / 测试上下文**：W6§19专属context manager+现discovery/FGAClient原pin、全量shared stream，外部native/strict、不走online ready/新模型gate，不写模型或业务。\
  **依赖**：T712\
  **配对测试**：T712\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：配对/旧pin及原NameCatalog边界通过，固定独立审；M2/CLI完整消费仍待后续。

## W6元数据逐版本真实索引handler前置

- [x] **T714 · 元数据完整索引分页与恢复测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_index_worker.py`\
  **逻辑 / 测试上下文**：真实native query_iterator/upsert/ES调用形状，10001+块越界不截断、pk/vector/文本与非目标字段不变；add清残留、rename/delete幂等及ES失败重试，迭代器finally关闭/guard中断和真实统计失败。\
  **依赖**：T702\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54\
  **验证 / 完成条件**：先真实红/首绿，IO边界fakes明确列出；不将native形状测试称真实服务或公开kind完成。

- [x] **T715 · 元数据逐version索引同步native handler**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/metadata_worker.py`\
  **逻辑 / 测试上下文**：W6§20精确原physical indexes全量分页，参数化字段替换、真实count/失败结果、guard/close与幂等，不嵌入、不写SQL或改变原File状态。\
  **依赖**：T714\
  **配对测试**：T714\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54\
  **验证 / 完成条件**：配对/原Chunk与索引相关回归、C2静态及固定独立审，Owner/J1真实装配后才开放kind。

## W6六来源原始引用流真实消费

- [x] **T716 · 六来源原始配置引用流集成测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_source_inventory.py`\
  **逻辑 / 测试上下文**：真实native SQL+13原分页+六extractor+NameIndex/NameCatalog/physical预检，根零版本/历史/disabled/退休与零set；401+页/重复targets有界计数、无raw内容泄漏、全量失败不假ready。\
  **依赖**：T694, T704, T711, T713\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-71, AC-80, AC-85, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：先真实红/首绿，sharing仅HTTP边界fakes且全实际consumer组合；Source头和slot count/digest核对，不能把本流等同全资源M2。

- [x] **T717 · 六来源盘点引用流实际装配**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_sources.py`\
  **逻辑 / 测试上下文**：W6§21生产默认真实Reader/Repository/extractors/NameIndex/physical facts，阶段确定流与闭集records；目录一次、重复slot不重查target，无SQL写/ready/停服检测。\
  **依赖**：T716\
  **配对测试**：T716\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-70, AC-71, AC-80, AC-85, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：配对/原源提取及盘点相关组合、C2/SQL预算/保密静态和固定独立审；全租户正式freeze与回填/转换另验。

## W6平台空间入口与实际创建接线

- [x] **T718 · 空间基本信息API闭集与port测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/knowledgeSpaceContract.test.ts`；`src/frontend/platform/src/test/knowledgeQueryScope.test.tsx`\
  **逻辑 / 测试上下文**：原PUT闭集name/description/is_released，不发model或其他字段，原ApiError与literal API port fixture保持；无新增管理头。\
  **依赖**：T698\
  **覆盖 AC**: AC-02, AC-33, AC-87\
  **验证 / 完成条件**：先真实红/首绿、每卡≤2叶，target lint/strict新增0、固定独立审；完整详情/上传/浏览器E2E另验。

- [x] **T719 · 空间基本信息窄API**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`\
  **逻辑 / 测试上下文**：W6§22 updateSpaceBasicInfo显式三字段投影并入原port，单叶≤600行；原高级模型保存另卡。\
  **依赖**：T718\
  **配对测试**：T718\
  **覆盖 AC**: AC-02, AC-33, AC-87\
  **验证 / 完成条件**：先真实红/首绿、每卡≤2叶，target lint/strict新增0、固定独立审；完整详情/上传/浏览器E2E另验。

- [x] **T720 · 空间创建与基本编辑Dialog实际测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118KnowledgeLibraryDialog.test.tsx`；`src/frontend/platform/src/test/f115KnowledgeCreation.test.tsx`\
  **逻辑 / 测试上下文**：真实Creator settings/model options/双draft/闭集create与edit保持原is_released；scope/late GET/ABA/取消失败与老QA pin不弱化。\
  **依赖**：T719, T707\
  **覆盖 AC**: AC-02, AC-06, AC-07, AC-33, AC-38, AC-40, AC-41, AC-87\
  **验证 / 完成条件**：先真实红/首绿、每卡≤2叶，target lint/strict新增0、固定独立审；完整详情/上传/浏览器E2E另验。

- [x] **T721 · 后台空间创建及基本编辑真实入口**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeLibraryDialog.tsx`\
  **逻辑 / 测试上下文**：W6§22原Dialog改SPACE，scope候选/默认初值/双类型编辑与成功后导航；基本信息不改模型、不回旧type0接口，保原QA创建。\
  **依赖**：T720\
  **配对测试**：T720\
  **覆盖 AC**: AC-02, AC-06, AC-07, AC-33, AC-38, AC-40, AC-41, AC-87\
  **验证 / 完成条件**：先真实红/首绿、每卡≤2叶，target lint/strict新增0、固定独立审；完整详情/上传/浏览器E2E另验。

- [x] **T722 · 平台三tab与真实范围入口测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118KnowledgePage.test.tsx`；`src/frontend/platform/src/test/f051KnowledgeListLazyActions.test.tsx`\
  **逻辑 / 测试上下文**：super真实管理pin/普通menu创建/tenantadmin管理tab，普通游标空页继续与admin DB分页，SPACE懒授权/QA独立、scope退役、未装配操作不借旧接口。\
  **依赖**：T721, T719\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-07, AC-84, AC-87\
  **验证 / 完成条件**：先真实红/首绿、每卡≤2叶，target lint/strict新增0、固定独立审；完整详情/上传/浏览器E2E另验。

## W6平台知识入口统一名称

- [x] **T723 · 平台入口中英文统一空间名称**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`；`src/frontend/platform/public/locales/en-US/bs.json`\
  **逻辑 / 测试上下文**：仅现menu.knowledge导航名按AC01统一知识空间，QA独立页签；不全局替换旧文档/QA selector及权限资源字段。\
  **依赖**：T708, T002\
  **验证 / 完成条件**：原其他keys/值完全不变，三语导航语义一致、i18n无新增漂移；实际页面挂载与门禁由T176验证。

- [x] **T724 · 平台日文入口统一空间名称**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/ja/bs.json`\
  **逻辑 / 测试上下文**：同menu.knowledge日文统一，保持既有namespace与路由/resource key，不修改MainLayout架构或QA名称。\
  **依赖**：T723\
  **验证 / 完成条件**：对应中英同键值语义及原键保留，JSON/插值与现i18n校验通过，不计完整UI验收。

## W6统一列表既有异常能力兼容收口

- [x] **T725 · 统一列表异常标记与SQL筛选测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_space_abnormal_listing_repository.py`；`src/backend/test/knowledge_unification/test_space_abnormal_listing_service.py`\
  **逻辑 / 测试上下文**：真实repo/SQL与service组合，tenant隔离、FILE状态、SQL先筛后分页、游标筛选绑定及最终页一次批量，保普通/管理准入。\
  **依赖**：T717, T698\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：配对及原F064回归、SQL/分页预算、target lint/strict无新增；固定独立复查与主树组合通过，真实环境另验。

- [x] **T726 · 统一列表异常EXISTS与轻DTO**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/knowledge_space_listing_repository.py`；`src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`\
  **逻辑 / 测试上下文**：W6§23复用原复合索引相关EXISTS，严格tenant，末页≤200一次bool读取，不增加业务表字段或逐文件ACL。\
  **依赖**：T725\
  **配对测试**：T725\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：配对及原F064回归、SQL/分页预算、target lint/strict无新增；固定独立复查与主树组合通过，真实环境另验。

- [x] **T727 · 统一列表异常筛选静态接口测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_space_abnormal_listing_api.py`\
  **逻辑 / 测试上下文**：两个真实静态list endpoint解析/转发true、false和None，原page/cursor/envelope及角色边界不变。\
  **依赖**：T726\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：配对及原F064回归、SQL/分页预算、target lint/strict无新增；固定独立复查与主树组合通过，真实环境另验。

- [x] **T728 · 统一列表异常筛选应用与API接线**
  **类型 / Owner**：后端 Service/API / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`；`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`\
  **逻辑 / 测试上下文**：W6§23普通游标和管理SQL分页共同接真实filter/最终页marker；cursor归一上下文，原原身份与权限检查保持。\
  **依赖**：T727\
  **配对测试**：T725, T727\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：配对及原F064回归、SQL/分页预算、target lint/strict无新增；固定独立复查与主树组合通过，真实环境另验。

- [x] **T729 · 既有异常列表测试适配统一scope**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f064KbListFileAbnormal.test.tsx`；`src/frontend/platform/src/test/f118KnowledgePage.test.tsx`\
  **逻辑 / 测试上下文**：仅更新原F064实际query hook/scope夹具，保五项既有行为并验证两view参数与分页重置；不得弱化断言。\
  **依赖**：T728, T722\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：配对及原F064回归、SQL/分页预算、target lint/strict无新增；固定独立复查与主树组合通过，真实环境另验。

- [x] **T730 · 平台列表真实异常字段与查询参数**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`\
  **逻辑 / 测试上下文**：W6§23新增真实bool类型/透传；列表恢复仍原T176生产叶，不改请求层、QA或详情。\
  **依赖**：T729\
  **配对测试**：T729, T697\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：配对及原F064回归、SQL/分页预算、target lint/strict无新增；固定独立复查与主树组合通过，真实环境另验。

- [x] **T731 · 平台目标旧suppression官方收缩**
  **类型 / Owner**：静态验证 / INT\
  **写入文件**：`src/frontend/platform/eslint-suppressions.json`\
  **逻辑 / 测试上下文**：统一入口接线后执行现pnpm lint:prune，自动生成仅已修复项移除；不手改或加规则，不顺带修旧债。\
  **依赖**：T176\
  **配对测试**：T722, T729\
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：配对及原F064回归、SQL/分页预算、target lint/strict无新增；固定独立复查与主树组合通过，真实环境另验。

## W6列表真实异常读取旧夹具接缝

- [x] **T732 · 旧统一列表fixture补真实文件表**
  **类型 / Owner**：测试夹具 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_list.py`\
  **逻辑 / 测试上下文**：T728最终页一次真实异常读取后，旧catalog fixture需创建KnowledgeFile空表并注册knowledgefile tenant过滤；不mock掉新消费、不改旧能力或消费者断言。\
  **依赖**：T728\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：记录原缺表失败，补真实空表后原列表/创建/新异常测试同选集通过，无生产范围变更。

## W6元数据结构实际Owner与账本消费闭环

- [x] **T733 · 元数据精确执行仓储与配置测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_execution_repository.py`\
  **逻辑 / 测试上下文**：实际SQL精确链/父/租户/source/value漂移，after-schema revision/digest及大空间逐item查询预算，无全空间重复扫描。\
  **依赖**：T715\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T734 · 元数据实际配置与逐item值提交仓储**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/metadata_execution_repository.py`\
  **逻辑 / 测试上下文**：W6§24真实Root配置与指定链读取、受控确定after值写；只外部TX、不改File状态或R/G。\
  **依赖**：T733\
  **配对测试**：T733\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T735 · 元数据Owner/J1 schema过期及空范围测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_owner.py`；`src/backend/test/knowledge_unification/test_metadata_job_repository.py`\
  **逻辑 / 测试上下文**：实际core计划+schemaCAS+J1同TX，非空/空结构记录、幂等回滚、schema ABA与RG过期、零伪file。\
  **依赖**：T734\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T736 · 元数据Owner与J1配置合同**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/metadata_owner.py`；`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`\
  **逻辑 / 测试上下文**：W6§24 actual Owner组合、metadata配置可选事实和仅metadata空item已完成记录，其余kind原限制保留。\
  **依赖**：T735\
  **配对测试**：T735\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T737 · 元数据实际预检接收重试与worker测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_job.py`；`src/backend/test/knowledge_unification/test_metadata_job_worker.py`\
  **逻辑 / 测试上下文**：实际ASGI/Service/Owner/J1/Celery路径，cancel零写、历史全版本、索引部分失败/重试、lease/config失效及File值同TX。\
  **依赖**：T736\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T738 · 元数据通用处理Service与业务Owner接线**
  **类型 / Owner**：后端 Service / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/processing_job_service.py`；`src/backend/bisheng/knowledge/application/processing_owner.py`\
  **逻辑 / 测试上下文**：W6§24 metadata独立preview/accept/retry，原kind不变，不进入rebuild切换或File解析。\
  **依赖**：T737\
  **配对测试**：T737, T735\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T739 · 元数据实际Celery分流与租约执行**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/metadata_jobs.py`；`src/backend/bisheng/worker/knowledge/processing_jobs.py`\
  **逻辑 / 测试上下文**：W6§24专用runner逐步原身份/模型/schema/lease/版本guard，真实handler及File值+item完成，部分失败和obsolete落账。\
  **依赖**：T738\
  **配对测试**：T737\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T740 · 元数据真实HTTP装配与kind开放**
  **类型 / Owner**：后端 API / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/api/endpoints/processing.py`\
  **逻辑 / 测试上下文**：全部实际执行/retry路径通过后才开放metadata，现A1 wire及原actor/scope保持。\
  **依赖**：T739\
  **配对测试**：T737, T071\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T741 · 旧metadata SPACE协议事务桥接测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_legacy.py`\
  **逻辑 / 测试上下文**：原三个操作请求/响应字段，SPACE同TX schema+job，不派旧BackgroundTask，空空间无伪文件且实际SQL完成，QA保持。\
  **依赖**：T740\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

- [x] **T742 · 旧metadata业务入口实际桥接**
  **类型 / Owner**：后端 Application/Service / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/metadata_legacy.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_metadata_service.py`\
  **逻辑 / 测试上下文**：W6§24原UserPayload/容器edit，同TX准备接受schema+J1再commit；原协议加只读实际job状态，不以接受报索引完成。\
  **依赖**：T741\
  **配对测试**：T741, T071\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-86, AC-87\
  **验证 / 完成条件**：先真实红/首绿、配对与原kind相关组合，逐叶arch/ruff、native SQL预算和固定独立复核；E2E另验证，未接齐不勾原T072。

## W6旧列表夹具与开放task mode实际消费接缝

- [x] **T743 · 旧管理员清单port夹具补真实批量标记**
  **类型 / Owner**：测试夹具 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_create.py`\
  **逻辑 / 测试上下文**：新真实marker port补AsyncMock空set，原alist_admin exact规范False参数；保所有原角色/身份/tenant断言。\
  **依赖**：T728\
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-87\
  **验证 / 完成条件**：精确旧失败/真实红或首绿、实际SQL与真实consumer相关组合，原协议边界、逐叶静态和固定独立审；真实E2E另验。

- [x] **T744 · 统一列表内部名称模式实际SQL测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_list.py`\
  **逻辑 / 测试上下文**：名称限定/字面%_转义/大小写、DB分页及EOF probe同模式，cursor区分且原keyword语义保持。\
  **依赖**：T728, T732\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-79, AC-82, AC-83, AC-86, AC-87\
  **验证 / 完成条件**：精确旧失败/真实红或首绿、实际SQL与真实consumer相关组合，原协议边界、逐叶静态和固定独立审；真实E2E另验。

- [x] **T745 · 有界空间清单内部名称限定**
  **类型 / Owner**：后端 Repository/Service / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/knowledge_space_listing_repository.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：W6§25内部name_only默认False，SQL先筛候选与probe一致，保原has_abnormal和空间普通权限。\
  **依赖**：T744\
  **配对测试**：T744\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-79, AC-82, AC-83, AC-86, AC-87\
  **验证 / 完成条件**：精确旧失败/真实红或首绿、实际SQL与真实consumer相关组合，原协议边界、逐叶静态和固定独立审；真实E2E另验。

- [x] **T746 · 开放task mode旧查询夹具更新**
  **类型 / Owner**：测试夹具 / PERM\
  **写入文件**：`src/backend/test/open_api/task_mode_support.py`；`src/backend/test/open_api/test_task_mode_config.py`\
  **逻辑 / 测试上下文**：改实际visible键与统一Domain分页消费夹具，保原SA/D、错误、分页投影；不将owner资格借SA。\
  **依赖**：T149\
  **配对测试**：T149\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-79, AC-82, AC-83, AC-86, AC-87\
  **验证 / 完成条件**：精确旧失败/真实红或首绿、实际SQL与真实consumer相关组合，原协议边界、逐叶静态和固定独立审；真实E2E另验。

- [x] **T747 · 开放task mode迁移ID提交回归更新**
  **类型 / Owner**：测试夹具 / PERM\
  **写入文件**：`src/backend/test/open_api/test_task_mode_submit.py`\
  **逻辑 / 测试上下文**：原library槽接受迁移3，保0/3分组、QA/退休/失效/原scope和tenant拒绝，无worker新授权。\
  **依赖**：T149\
  **配对测试**：T149\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-79, AC-82, AC-83, AC-86, AC-87\
  **验证 / 完成条件**：精确旧失败/真实红或首绿、实际SQL与真实consumer相关组合，原协议边界、逐叶静态和固定独立审；真实E2E另验。

## W6元数据双协议原DI实际装配

- [x] **T748 · 原metadata依赖工厂装配真实SPACE writer**
  **类型 / Owner**：后端 API组合 / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/api/dependencies.py`；`src/backend/bisheng/open_endpoints/api/dependencies.py`\
  **逻辑 / 测试上下文**：W6§24.3两个真实API DI调用唯一application组合工厂注入writer，Domain只依赖窄port，v1/v2皆经原facade；保v2原principal及data=True，不走无账本BackgroundTask。\
  **依赖**：T742\
  **配对测试**：T741, T071\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54, AC-66, AC-82, AC-83, AC-86, AC-87\
  **验证 / 完成条件**：真实DI/两protocol及原身份用例通过，架构无Domain反向import application，原QA和其他kind回归不变，独立固定审后原T072才闭合。

## W6开放任务技能旧授权结果夹具兼容

- [x] **T749 · 原任务个人技能fixture改实际visible结果键**
  **类型 / Owner**：测试夹具 / PERM\
  **写入文件**：`src/backend/test/open_api/test_task_mode_personal_skills.py`\
  **逻辑 / 测试上下文**：原permitted假结果仍只含退休use，实际UserSkillsService已使用visible，导致候选与检查两例失败。仅适配结果键并断言真实请求动作；保caller-only、enabled、私有他人、优先级及原错误断言，不改生产技能策略。\
  **依赖**：T146, T150\
  **覆盖 AC**: AC-35, AC-79, AC-82, AC-83, AC-87\
  **验证 / 完成条件**：精确前驱两红保留证据，仅适配后当前Task mode/Skill相关同选集全绿，无新生产叶；不把退休fixture当作产品可忽略失败。

## W6平台实际目录与基础文件动作消费闭环

- [x] **T750 · 平台可信知识页scope抽取测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/knowledgePageScope.test.tsx`\
  **逻辑 / 测试上下文**：super selected/home、普通leaf、未知scope/retry/unmount/ABA及原三tab/QA/menu不变。\
  **依赖**：T176\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T751 · 知识页可信scope共享消费者**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/hooks/useKnowledgePageScope.ts`；`src/frontend/platform/src/pages/KnowledgePage/index.tsx`\
  **逻辑 / 测试上下文**：W6§27抽已验证逻辑为窄hook，保原目录/管理资格及真实当前tenant，不改认证store。\
  **依赖**：T750\
  **配对测试**：T750, T722\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T752 · 真实文件窄API合同测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/knowledgeFilesContract.test.ts`\
  **逻辑 / 测试上下文**：路径/闭集body/真实preview与download分离、数组query、正整数和原ApiError，原空间DTO回归。\
  **依赖**：T751\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T753 · SPACE目录基础动作真实API**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeFiles.ts`；`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`\
  **逻辑 / 测试上下文**：W6§27真实已存在endpoint；原API只补Child真实四字段且≤600，不改公共request或虚造后端能力。\
  **依赖**：T752\
  **配对测试**：T752\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T754 · 实际目录与逐项授权测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118SpaceDirectory.test.tsx`\
  **逻辑 / 测试上下文**：opaque空页/独立search分页、scope-parent-filter ABA、visible preview无download、rename独立及真实行type动作，不借root edit。\
  **依赖**：T753\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T755 · 实际目录与基础文件行消费**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/SpaceDirectoryRow.tsx`\
  **逻辑 / 测试上下文**：W6§27目录/搜索/逐项动作/原文预览/独立download，未接删除移动版本等不借旧接口；重建可读。\
  **依赖**：T754\
  **配对测试**：T754\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T756 · SPACE详情真实挂载与受控标题测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118SpaceDetail.test.tsx`\
  **逻辑 / 测试上下文**：实际路由/scope/父子目录，子树不叠root visible，不读unscoped历史标题，保旧QA Header兼容。\
  **依赖**：T755\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T757 · SPACE详情与受控Header实际挂载**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/detail.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/Header.tsx`\
  **逻辑 / 测试上下文**：W6§27挂实际目录scope/API，SPACE真实标题/面包屑，旧Paragraphs高级与版本/上传另卡，不冒充T177全完。\
  **依赖**：T756, T758, T759\
  **配对测试**：T756, T754\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T758 · 目录基础词条中英文接线**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/zh-Hans/knowledge.json`；`src/frontend/platform/public/locales/en-US/knowledge.json`\
  **逻辑 / 测试上下文**：W6§27六个snake_case业务键，沿现UI语言与用语，不放内部token或改生成错误。\
  **依赖**：T002\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

- [x] **T759 · 目录基础词条日文接线**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/ja/knowledge.json`\
  **逻辑 / 测试上下文**：同六个业务键日文，保其他现值/keys及插值，三语同批可用。\
  **依赖**：T758\
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-09, AC-11, AC-16, AC-30, AC-31, AC-32, AC-34, AC-51, AC-87\
  **验证 / 完成条件**：先真实红/首绿、实际consumer/旧回归组合，目标lint/strict新增0、每叶≤600、i18n与固定独立审；浏览器/E2E另验证。

## W6正式M2原资源只读事实前置

- [x] **T760 · M2原资源物理树与标签分页测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_resource_repository.py`\
  **逻辑 / 测试上下文**：W6§28真实9表PK分页/父链、旧20与neutral7、global异常、未建V1、legacy overdeep、祖先≤500分200、零写/原TX/noauto及大数据查询预算。\
  **依赖**：T717, T704\
  **覆盖 AC**: AC-56, AC-57, AC-58, AC-59, AC-60, AC-62, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：真实红/首绿，native SQL/分页/查询预算与敏感字段repr验证，不把原模型事实当新授权或正式M2全验收。

- [x] **T761 · M2资源物理树与标签只读仓储**
  **类型 / Owner**：后端 Repository / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_resource_repository.py`\
  **逻辑 / 测试上下文**：W6§28闭集Row与9分页、一次global完整性和精确ancestor事实；原数据完整保留且不转换、不猜creator/配额或ready。\
  **依赖**：T760\
  **配对测试**：T760\
  **覆盖 AC**: AC-56, AC-57, AC-58, AC-59, AC-60, AC-62, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：配对/原SourceInventory及MIG相关组合、C2/逐叶arch/ruff、固定独立审；全M2正式artifact/freeze后续另验。

## W6正式盘点创建者、组织及原配额配置事实

- [x] **T762 · 原创建者组织与配额配置事实测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_control_repository.py`\
  **逻辑 / 测试上下文**：W6§29真实模型及SQL分页、UserRole复合seek、历史成员、精确global creator/role、无凭据或跨scope普通页，外部TX零写。\
  **依赖**：T761\
  **覆盖 AC**: AC-56, AC-57, AC-58, AC-62, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：先真实红/首绿，配对及原MIG组合、实际查询预算、逐叶ruff/arch与固定独立审；不以事实helper勾完整M2。

- [x] **T763 · 原创建者组织与配额配置事实仓储**
  **类型 / Owner**：后端 Repository / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_control_repository.py`\
  **逻辑 / 测试上下文**：W6§29只读原Tenant/User/UserTenant/Department/Role/UserRole闭集事实，不新增配额策略或转换。\
  **依赖**：T762\
  **配对测试**：T762\
  **覆盖 AC**: AC-56, AC-57, AC-58, AC-62, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：先真实红/首绿，配对及原MIG组合、实际查询预算、逐叶ruff/arch与固定独立审；不以事实helper勾完整M2。

## W6目录旧静态抑制同步

- [x] **T764 · 新目录实际类型恢复后官方抑制裁剪**
  **类型 / Owner**：静态产物 / INT\
  **写入文件**：`src/frontend/platform/eslint-suppressions.json`\
  **逻辑 / 测试上下文**：T755移除旧Files整体strict ignore后，只运行仓库官方lint:prune清理该叶已失效抑制，不手改、不加新抑制、不扩其他页面。\
  **依赖**：T755\
  **验证 / 完成条件**：官方命令成功、精确差异核对、新目录target lint与22条既有strict诊断对比无新增；真实页面另验。

## W6上传实际规则旧假结果兼容

- [x] **T765 · 上传旧假结果补已保存split_rule**
  **类型 / Owner**：测试夹具 / INT\
  **写入文件**：`src/backend/test/knowledge/test_upload_permission_rollback.py`；`src/backend/test/knowledge/test_department_knowledge_space_upload_permission.py`\
  **逻辑 / 测试上下文**：W6§30真实上传开始按已保存规则生成preview key，两个旧process_one_file假结果split_rule=None造成三例在原权限/审批断言前失败。仅为假创建行补原FileProcessBase已保存JSON并保留所有原业务断言；两个测试叶同一调用约定兼容，不改公共fixture/版本错误口径。\
  **依赖**：T084（§30默认快照首阶段）\
  **覆盖 AC**: AC-09, AC-10, AC-14, AC-43, AC-51\
  **验证 / 完成条件**：同选集前驱对照、原三红变绿、原权限补偿及不建审批断言保持，独立原生快照测试另证真实配置；其他旧版本失败不隐藏或记通过。

## W6全部已声明kind装配后的旧准入夹具

- [x] **T766 · 旧HTTP未装配门禁改为真实受限装配上下文**
  **类型 / Owner**：测试夹具 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_endpoints.py`\
  **逻辑 / 测试上下文**：T740开放metadata后现precheck DTO四种kind均已实际装配，没有合法未装配wire kind。仅原门禁用例以dependency override从实际get_processing_service取得真实Owner/Service并缩窄available_kinds，合法metadata请求仍验证10999；保原分页422，不为测试新增move/copy DTO或改其他默认工厂路径。\
  **依赖**：T739, T740\
  **覆盖 AC**: AC-49, AC-50, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：准确740前后同选集，真实装配缺失10999保留且生产metadata完整链通过；不删除或skip旧断言，不改生产准入门禁。

## W6实际目录面包屑折叠词条

- [x] **T767 · Breadcrumb折叠层数中英词条**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/zh-Hans/knowledge.json`；`src/frontend/platform/public/locales/en-US/knowledge.json`\
  **逻辑 / 测试上下文**：W6§27唯一f118.expand_folders，保{{count}}及原键值，复用现Breadcrumb，无新视觉组件。\
  **依赖**：T758\
  **验证 / 完成条件**：JSON可解析、三语键/占位符一致、旧键值语义完全保持、check-i18n通过，实际consumer另验。

- [x] **T768 · Breadcrumb折叠层数日文词条**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/ja/knowledge.json`\
  **逻辑 / 测试上下文**：W6§27唯一f118.expand_folders，保{{count}}，与中英同键；不改生成错误词条或QA业务文案。\
  **依赖**：T759\
  **验证 / 完成条件**：JSON可解析、三语键/占位符一致、旧键值语义完全保持、check-i18n通过，实际consumer另验。

## W6正式盘点准备上下文及原业务修订

- [x] **T769 · 六来源准备上下文与原业务修订测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_source_context.py`\
  **逻辑 / 测试上下文**：W6§31实际SQL/原共享目录一次准备、跨TX/scope拒绝、六源原update_time及业务状态修订摘要，与neutral独立；无授权或freeze副作用。\
  **依赖**：T717, T763\
  **覆盖 AC**: AC-56, AC-57, AC-58, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：真实红/首绿、原六源及MIG组合、实际SQL预算、逐叶静态和固定独立审，不以context完成完整M2。

- [x] **T770 · 六来源原生准备上下文与业务修订事实**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_sources.py`\
  **逻辑 / 测试上下文**：W6§31同原TX的实际目录/共享事实复用及闭集header business_revision_digest，配置/引用/neutral语义分别保留，不改线上绑定。\
  **依赖**：T769\
  **配对测试**：T769\
  **覆盖 AC**: AC-56, AC-57, AC-58, AC-63, AC-64, AC-85, AC-93\
  **验证 / 完成条件**：真实红/首绿、原六源及MIG组合、实际SQL预算、逐叶静态和固定独立审，不以context完成完整M2。

## W6原来源新增修订事实及分页artifact闭集

- [x] **T771 · 原source header闭集断言补真实业务修订字段**
  **类型 / Owner**：测试夹具 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_source_inventory.py`\
  **逻辑 / 测试上下文**：W6§31只扩原fields精确列表的真实新增business_revision_digest，保全部旧事实和秘密/冻结断言。\
  **依赖**：T770\
  **覆盖 AC**: AC-56, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：原单叶红真实定位新增字段断言，最小适配后原20与新context组合绿，不造业务事实。

- [x] **T772 · 六来源闭集artifact分页编码测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_source_codec.py`\
  **逻辑 / 测试上下文**：W6§32四真实record/双Fact canonical roundtrip、tenant/index/count/闭集/199边界与16MiB、现持久store组合，无授权或M2放行。\
  **依赖**：T769（冻结DTO并行，最终绿需T770）\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：真实缺模块红、实际DTO合同组合绿、固定独立审与静态；不加旧缺字段兼容/不以编码器完成M2。

- [x] **T773 · 六来源闭集canonical分页编码器**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_source_codec.py`\
  **逻辑 / 测试上下文**：W6§32严格纯编解码供正式M2/回填，现四DTO显式字段、原真实Key及双Fact，零DB/网络/ready副作用。\
  **依赖**：T772\
  **配对测试**：T772\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：真实缺模块红、实际DTO合同组合绿、固定独立审与静态；不加旧缺字段兼容/不以编码器完成M2。

- [x] **T774 · 详情与受控Header替换后的官方静态抑制清理**
  **类型 / Owner**：静态集成 / INT\
  **写入文件**：`src/frontend/platform/eslint-suppressions.json`\
  **逻辑 / 测试上下文**：T757替换旧Header后运行原lint:prune，只删除已失效的detail与Header抑制，不新增或扩大其他抑制。\
  **依赖**：T757\
  **验证 / 完成条件**：官方prune退出0；Header空抑制检查零诊断，平台strict与既有22条基线精确比较无新增，目标路径回归通过。

- [x] **T775 · SPACE显式批次规则真实上传接线测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload_overrides.py`\
  **逻辑 / 测试上下文**：W6§33真实请求DTO/handler、process_one_file快照、类型隔离、非法零写及原批量补偿；不fake实际保存快照。\
  **依赖**：T765\
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-38, AC-43, AC-44, AC-45, AC-86\
  **验证 / 完成条件**：先真实红，实际入口和原快照组合绿；固定独立复核，原T083/T084整卡保持未闭。

- [x] **T776 · SPACE显式批次规则真实协议与业务接线**
  **类型 / Owner**：后端 API/Domain / INT\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`、`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`、`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：W6§33可选typed overrides经真实原上传用例与原输入收据；保持旧缺省协议、动作/审批/配额/V1/队列。\
  **依赖**：T775\
  **配对测试**：T775\
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-38, AC-43, AC-44, AC-45, AC-86\
  **验证 / 完成条件**：配对及原上传组合绿，独立复核和静态；不宣称per-file/整上传或真实模型E2E完成。

- [x] **T777 · M2闭集事实与分层manifest编码测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T773\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-78, AC-85, AC-93\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T778 · M2闭集事实与分层manifest编码**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T777\
  **配对测试**：T777\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T779 · 正式M2确定事实完整预检测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_preflight.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T763, T770, T778\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T780 · 正式M2确定事实完整预检**
  **类型 / Owner**：后端 Application/Repository / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_preflight.py`、`src/backend/bisheng/permission/domain/repositories/f118_migration_snapshot_repository.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T779\
  **配对测试**：T779\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T781 · 全租户正式基线原子冻结测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_global_freeze.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T160, T778\
  **覆盖 AC**: AC-56, AC-63, AC-78, AC-85, AC-93\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T782 · 全租户正式基线原子冻结**
  **类型 / Owner**：后端 Repository / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_run_repository.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T781\
  **配对测试**：T781\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T783 · 完整M2应用编排及required事实失败测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_inventory_application.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T780, T782\
  **覆盖 AC**: AC-56, AC-63, AC-78, AC-85, AC-93\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T784 · 完整M2应用入口组合与冻结编排**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_inventory.py`\
  **逻辑 / 测试上下文**：W6§34完整正式M2入口的确定接缝；显式闭集、全租户/原TX、线性聚合、失败封闭，不把required假port当正式freeze。\
  **依赖**：T783\
  **配对测试**：T783\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T785 · 移动索引真实替换与恢复端口测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_worker.py`\
  **逻辑 / 测试上下文**：W6§35真实索引IO、双目标全验证与持久checkpoint先于清源；实际J1/归属/源删除后继未闭。\
  **依赖**：T064\
  **覆盖 AC**: AC-19, AC-20, AC-21, AC-23, AC-24, AC-49, AC-54, AC-86\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T786 · 移动索引真实替换与恢复adapter**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/move_worker.py`\
  **逻辑 / 测试上下文**：W6§35真实索引IO、双目标全验证与持久checkpoint先于清源；实际J1/归属/源删除后继未闭。\
  **依赖**：T785\
  **配对测试**：T785\
  **验证 / 完成条件**：配对真实红绿、固定独立复核与静态；仅完成实际接缝，原完整功能须真实装配/验收后另闭合。

- [x] **T787 · SPACE暂存与注册真实API合同测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/knowledgeUploadsContract.test.ts`\
  **逻辑 / 测试上下文**：W6§36实际暂存→SPACE注册→按真实ID状态，原容器upload_file、scope/parent/ABA退休，不经legacy处理或新增edit。\
  **依赖**：T757\
  **覆盖 AC**: AC-03, AC-09, AC-10, AC-11, AC-30, AC-31, AC-43, AC-55, AC-86\
  **验证 / 完成条件**：配对真实红绿、实际入口组合及固定独立复核；严格类型无新增诊断/抑制，不将普通上传计作完整版本/高级验收。

- [x] **T788 · SPACE暂存与注册真实API**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeUploads.ts`\
  **逻辑 / 测试上下文**：W6§36实际暂存→SPACE注册→按真实ID状态，原容器upload_file、scope/parent/ABA退休，不经legacy处理或新增edit。\
  **依赖**：T787\
  **配对测试**：T787\
  **验证 / 完成条件**：配对真实红绿、实际入口组合及固定独立复核；严格类型无新增诊断/抑制，不将普通上传计作完整版本/高级验收。

- [x] **T789 · 平台SPACE普通上传真实页面测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118SpaceUpload.test.tsx`\
  **逻辑 / 测试上下文**：W6§36实际暂存→SPACE注册→按真实ID状态，原容器upload_file、scope/parent/ABA退休，不经legacy处理或新增edit。\
  **依赖**：T788\
  **覆盖 AC**: AC-03, AC-09, AC-10, AC-11, AC-30, AC-31, AC-43, AC-55, AC-86\
  **验证 / 完成条件**：配对真实红绿、实际入口组合及固定独立复核；严格类型无新增诊断/抑制，不将普通上传计作完整版本/高级验收。

- [x] **T790 · 平台SPACE普通上传路由与队列面板**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/filesUpload.tsx`、`src/frontend/platform/src/pages/KnowledgePage/components/SpaceFileUploadPanel.tsx`\
  **逻辑 / 测试上下文**：W6§36实际暂存→SPACE注册→按真实ID状态，原容器upload_file、scope/parent/ABA退休，不经legacy处理或新增edit。\
  **依赖**：T789\
  **配对测试**：T789\
  **验证 / 完成条件**：配对真实红绿、实际入口组合及固定独立复核；严格类型无新增诊断/抑制，不将普通上传计作完整版本/高级验收。

- [x] **T791 · 目录当前容器上传入口测试**
  **类型 / Owner**：测试 / PLATFORM\
  **写入文件**：`src/frontend/platform/src/test/f118SpaceDirectoryUpload.test.tsx`\
  **逻辑 / 测试上下文**：W6§36实际暂存→SPACE注册→按真实ID状态，原容器upload_file、scope/parent/ABA退休，不经legacy处理或新增edit。\
  **依赖**：T790\
  **覆盖 AC**: AC-03, AC-09, AC-10, AC-11, AC-30, AC-31, AC-43, AC-55, AC-86\
  **验证 / 完成条件**：配对真实红绿、实际入口组合及固定独立复核；严格类型无新增诊断/抑制，不将普通上传计作完整版本/高级验收。

- [x] **T792 · 目录当前容器实际上传入口与工具栏**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`、`src/frontend/platform/src/pages/KnowledgePage/components/SpaceDirectoryToolbar.tsx`\
  **逻辑 / 测试上下文**：W6§36实际暂存→SPACE注册→按真实ID状态，原容器upload_file、scope/parent/ABA退休，不经legacy处理或新增edit。\
  **依赖**：T791\
  **配对测试**：T791\
  **验证 / 完成条件**：配对真实红绿、实际入口组合及固定独立复核；严格类型无新增诊断/抑制，不将普通上传计作完整版本/高级验收。

- [x] **T793 · 普通上传真实状态中英文词条**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/zh-Hans/knowledge.json`、`src/frontend/platform/public/locales/en-US/knowledge.json`\
  **逻辑 / 测试上下文**：W6§36五个真实状态与跟踪提示键，只区分暂存/已提交/取消/状态不可取，不把提交当解析完成。\
  **依赖**：T789\
  **验证 / 完成条件**：保所有旧键值，三语key对齐及check-i18n通过，实际consumer随后T790验证。

- [x] **T794 · 普通上传真实状态日文词条**
  **类型 / Owner**：文案集成 / INT\
  **写入文件**：`src/frontend/platform/public/locales/ja/knowledge.json`\
  **逻辑 / 测试上下文**：与T793同五键，沿原三语生成链，不输出未翻译key。\
  **依赖**：T793\
  **验证 / 完成条件**：保所有旧键值，三语key对齐及check-i18n通过，实际consumer随后T790验证。

- [x] **T795 · M2原固定Store完整tuple流测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_original_tuples.py`\
  **逻辑 / 测试上下文**：W6§37真实FGA transport分页、原pin、一次全Store、未知condition/错client/关闭/中断拒绝，流式无全Store缓存。\
  **依赖**：T713\
  **覆盖 AC**: AC-56, AC-63, AC-78, AC-79, AC-80, AC-85\
  **验证 / 完成条件**：真实缺方法红→实际原client分页绿，旧共享合同回归及固定独立复核；不计完整M2。

- [x] **T796 · M2原固定Store完整tuple只读适配**
  **类型 / Owner**：后端 Permission Application / INT\
  **写入文件**：`src/backend/bisheng/permission/application/migration_read.py`\
  **逻辑 / 测试上下文**：W6§37新增闭集OriginalTupleFact及aiter_original_tuples；保全部原共享方法，禁写/重pin或猜原授权。\
  **依赖**：T795\
  **配对测试**：T795\
  **验证 / 完成条件**：配对及旧共享合同绿、固定独立复核与静态，原正式入口待真实集成。

- [x] **T797 · SPACE上传替换后的官方静态抑制清理**
  **类型 / Owner**：静态集成 / INT\
  **写入文件**：`src/frontend/platform/eslint-suppressions.json`\
  **逻辑 / 测试上下文**：W6§38官方prune仅移除失效旧上传抑制，主树strict原22及空suppression检查，保旧无关诊断。\
  **依赖**：T790\
  **验证 / 完成条件**：实际登记范围验证、独立复核与静态；不得将fixture/adapter绿计作正式迁移或E2E。

- [x] **T798 · 共享SQLite知识schema夹具补真实metadata修订列**
  **类型 / Owner**：测试夹具 / INT\
  **写入文件**：`src/backend/test/fixtures/table_definitions.py`\
  **逻辑 / 测试上下文**：W6§38真实Model/中性DDL已有列补入旧夹具，保原move断言，不改生产或吞行为失败。\
  **依赖**：T766\
  **验证 / 完成条件**：实际登记范围验证、独立复核与静态；不得将fixture/adapter绿计作正式迁移或E2E。

- [x] **T799 · M2原生物理只读及受限artifact存储测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_physical_inventory.py`、`src/backend/test/knowledge_unification/test_migration_minio.py`\
  **逻辑 / 测试上下文**：W6§38真实native调用形状、tenant/身份/分页/对象预算/错误/close、无建桶建索引或模型IO。\
  **依赖**：T778, T796\
  **覆盖 AC**: AC-55, AC-56, AC-58, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：实际登记范围验证、独立复核与静态；不得将fixture/adapter绿计作正式迁移或E2E。

- [x] **T800 · M2原生物理只读及受限artifact存储适配**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_physical.py`、`src/backend/bisheng/knowledge/application/unification_minio.py`\
  **逻辑 / 测试上下文**：W6§38同shape真实ES/Milvus/stat及私有受限artifact get-put，readonly配置和完整native生命周期。\
  **依赖**：T799\
  **配对测试**：T799\
  **验证 / 完成条件**：实际登记范围验证、独立复核与静态；不得将fixture/adapter绿计作正式迁移或E2E。

- [x] **T801 · 版本读取原生链与批量候选仓储测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_version_read_repository.py`\
  **逻辑 / 测试上下文**：W6§39实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T778\
  **覆盖 AC**: AC-09, AC-14, AC-15, AC-16, AC-30, AC-31, AC-55, AC-86\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T802 · 版本读取原生链仓储与候选页DTO**
  **类型 / Owner**：后端 Repository/Schema / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/knowledge_version_read_repository.py`、`src/backend/bisheng/knowledge/domain/schemas/knowledge_version_schema.py`\
  **逻辑 / 测试上下文**：W6§39实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T801\
  **配对测试**：T801\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T803 · 版本读取真实可见性裁剪与兼容测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_version_read.py`\
  **逻辑 / 测试上下文**：W6§39实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T802\
  **覆盖 AC**: AC-09, AC-14, AC-15, AC-16, AC-30, AC-31, AC-55, AC-86\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T804 · 版本读取真实权限服务及旧读委托**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_version_read_service.py`、`src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py`\
  **逻辑 / 测试上下文**：W6§39实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T803\
  **配对测试**：T803\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T805 · 版本读取实际DI与新旧HTTP合同测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_version_read_http.py`\
  **逻辑 / 测试上下文**：W6§39实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T804\
  **覆盖 AC**: AC-09, AC-14, AC-15, AC-16, AC-30, AC-31, AC-55, AC-86\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T806 · 版本读取实际依赖装配与候选页入口**
  **类型 / Owner**：后端 API / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/api/dependencies.py`、`src/backend/bisheng/knowledge/api/endpoints/knowledge_version.py`\
  **逻辑 / 测试上下文**：W6§39实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T805\
  **配对测试**：T805\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T807 · M2原SQL任务只读仓储测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_task_repository.py`\
  **逻辑 / 测试上下文**：W6§40实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T778\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-86, AC-93\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T808 · M2原SQL任务只读仓储**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_task_repository.py`\
  **逻辑 / 测试上下文**：W6§40实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T807\
  **配对测试**：T807\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T809 · M2原Redis调度器及SQL任务真实消费测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_tasks.py`\
  **逻辑 / 测试上下文**：W6§40实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T808, T812\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-86, AC-93\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T810 · M2原Redis调度器及SQL任务只读reader**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_tasks.py`\
  **逻辑 / 测试上下文**：W6§40实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T809\
  **配对测试**：T809\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T811 · M2来源manifest材料与全局任务诊断闭集测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§40实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T778\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-86, AC-93\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T812 · M2来源manifest材料与全局任务诊断闭集**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§40实际确定接缝；原身份/tenant、批量有界读取、明确兼容和失败语义，不假完整功能/正式M2。\
  **依赖**：T811\
  **配对测试**：T811\
  **验证 / 完成条件**：配对真实红绿、独立复核/静态，完整旧协议回归与真实入口组合；本卡不代替未完成后继验收。

- [x] **T813 · 目标FGA模板checksum纯协议测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_target_checksum.py`\
  **逻辑 / 测试上下文**：W6§37仓库SSOT目标模板摘要、无参数/IO/旧pin替代；真实缺方法红。\
  **依赖**：T796\
  **覆盖 AC**: AC-56, AC-63, AC-78, AC-79\
  **验证 / 完成条件**：实际SSOT/应用层架构边界绿，不把纯getter当权限发布或M2完成。

- [x] **T814 · 目标FGA模板checksum应用纯协议**
  **类型 / Owner**：后端 Permission Application / INT\
  **写入文件**：`src/backend/bisheng/permission/application/migration_read.py`\
  **逻辑 / 测试上下文**：W6§37公开无参target_authorization_model_checksum，由permission侧封装SSOT，知识侧不跨core。\
  **依赖**：T813\
  **配对测试**：T813\
  **验证 / 完成条件**：配对及旧pin/tuple回归、逐叶arch绿，无runtime或外部副作用。

- [x] **T815 · 旧版本读取三项夹具接真实新读口**
  **类型 / Owner**：测试夹具 / EDGE\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_version_service_read.py`\
  **逻辑 / 测试上下文**：W6§39已复现新旧控制恰3个新read夹具失败；真实UserPayload/tenant/native factory/loaded F048边界替代MagicMock身份，保原三项业务断言及无链404旧协议。\
  **依赖**：T804\
  **验证 / 完成条件**：三原读断言不削减，实际新read组合与原write控制对比无新增失败；其他13原失败继续如实报告，不顺带改旧写权限或异常语义。

- [x] **T816 · 平台历史功能实际开关映射测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/frontend/platform/src/test/knowledgeVersionFeature.test.tsx`\
  **逻辑 / 测试上下文**：W6§41真实只读历史入口，原feature flag及文件visible，完整scope/parent/file/open隔离；无版本写入或额外空间权限。\
  **依赖**：T806\
  **覆盖 AC**: AC-09, AC-14, AC-15, AC-30, AC-31\
  **验证 / 完成条件**：实际入口、nullable主版本和失败/取消/ABA红绿；独立复核、原目录行为及静态无新增；不代替T177完整高级功能或浏览器E2E。

- [x] **T817 · 平台历史功能实际开关映射**
  **类型 / Owner**：前端 Context/API类型 / EDGE\
  **写入文件**：`src/frontend/platform/src/types/api/app.ts`、`src/frontend/platform/src/contexts/locationContext.tsx`\
  **逻辑 / 测试上下文**：W6§41真实只读历史入口，原feature flag及文件visible，完整scope/parent/file/open隔离；无版本写入或额外空间权限。\
  **依赖**：T816\
  **配对测试**：T816\
  **验证 / 完成条件**：实际入口、nullable主版本和失败/取消/ABA红绿；独立复核、原目录行为及静态无新增；不代替T177完整高级功能或浏览器E2E。

- [x] **T818 · 平台只读版本API与历史面板测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/frontend/platform/src/test/knowledgeVersionsContract.test.ts`、`src/frontend/platform/src/test/f118SpaceVersionHistory.test.tsx`\
  **逻辑 / 测试上下文**：W6§41真实只读历史入口，原feature flag及文件visible，完整scope/parent/file/open隔离；无版本写入或额外空间权限。\
  **依赖**：T817\
  **覆盖 AC**: AC-09, AC-14, AC-15, AC-30, AC-31\
  **验证 / 完成条件**：实际入口、nullable主版本和失败/取消/ABA红绿；独立复核、原目录行为及静态无新增；不代替T177完整高级功能或浏览器E2E。

- [x] **T819 · 平台只读版本API与历史面板**
  **类型 / Owner**：前端 API/组件 / EDGE\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeVersions.ts`、`src/frontend/platform/src/pages/KnowledgePage/components/SpaceVersionHistorySheet.tsx`\
  **逻辑 / 测试上下文**：W6§41真实只读历史入口，原feature flag及文件visible，完整scope/parent/file/open隔离；无版本写入或额外空间权限。\
  **依赖**：T818, T822\
  **配对测试**：T818\
  **验证 / 完成条件**：实际入口、nullable主版本和失败/取消/ABA红绿；独立复核、原目录行为及静态无新增；不代替T177完整高级功能或浏览器E2E。

- [x] **T820 · 平台真实文件行历史入口测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/frontend/platform/src/test/f118SpaceDirectoryHistory.test.tsx`\
  **逻辑 / 测试上下文**：W6§41真实只读历史入口，原feature flag及文件visible，完整scope/parent/file/open隔离；无版本写入或额外空间权限。\
  **依赖**：T819\
  **覆盖 AC**: AC-09, AC-14, AC-15, AC-30, AC-31\
  **验证 / 完成条件**：实际入口、nullable主版本和失败/取消/ABA红绿；独立复核、原目录行为及静态无新增；不代替T177完整高级功能或浏览器E2E。

- [x] **T821 · 平台真实文件行历史入口**
  **类型 / Owner**：前端入口 / EDGE\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`、`src/frontend/platform/src/pages/KnowledgePage/components/SpaceDirectoryRow.tsx`\
  **逻辑 / 测试上下文**：W6§41真实只读历史入口，原feature flag及文件visible，完整scope/parent/file/open隔离；无版本写入或额外空间权限。\
  **依赖**：T820\
  **配对测试**：T820\
  **验证 / 完成条件**：实际入口、nullable主版本和失败/取消/ABA红绿；独立复核、原目录行为及静态无新增；不代替T177完整高级功能或浏览器E2E。

- [x] **T822 · 平台只读版本历史三语词条**
  **类型 / Owner**：国际化 / INT\
  **写入文件**：`src/frontend/platform/public/locales/{en-US,zh-Hans,ja}/knowledge.json`\
  **逻辑 / 测试上下文**：W6§41真实只读历史入口，原feature flag及文件visible，完整scope/parent/file/open隔离；无版本写入或额外空间权限。\
  **依赖**：T806\
  **验证 / 完成条件**：实际入口、nullable主版本和失败/取消/ABA红绿；独立复核、原目录行为及静态无新增；不代替T177完整高级功能或浏览器E2E。

- [x] **T823 · 原生broker配置及JSON协议离线产物测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_broker_codec.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T810\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-86, AC-93\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T824 · 原生broker配置及受限JSON协议codec**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_broker_codec.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T823\
  **配对测试**：T823\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T825 · broker实际业务目标批查仓储测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_task_repository.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T808\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-86, AC-93\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T826 · broker实际业务目标批查仓储**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_task_repository.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T825\
  **配对测试**：T825\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T827 · broker只读流与规模取消安全测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_broker.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T824, T826\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-86, AC-93\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T828 · broker全局原始消息只读reader**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_broker.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T827\
  **配对测试**：T827\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T829 · M2 broker闭集与真实required-port联装测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_inventory_codec.py`、`src/backend/test/knowledge_unification/test_migration_broker_application.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T828\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-86, AC-93\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T830 · M2 broker闭集与全run装配**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_inventory_codec.py`、`src/backend/bisheng/knowledge/application/unification_inventory.py`\
  **逻辑 / 测试上下文**：W6§42真实生效broker配置/原始Redis只读消息，签名与SQL归属闭集，取消/规模有界，原消息零写。\
  **依赖**：T829\
  **配对测试**：T829\
  **验证 / 完成条件**：真实Kombu离线编码与native SQL/只读Redis形状红绿，10001规模/tenant/异常与独立复核；非Redis或缺端口拒绝，不代替正式M2/维护证明。

- [x] **T831 · KN盘点修订SSOT提取与真实Owner摘要对照测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_source_context.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T772\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T832 · KN盘点修订纯SSOT提取**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_sources.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T831\
  **配对测试**：T831\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T833 · 精确SQL阶段转换命令与受限codec测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_conversion_plan.py`、`src/backend/test/knowledge_unification/test_migration_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T832\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T834 · 精确SQL阶段转换计划与闭集codec**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_conversion_plan.py`、`src/backend/bisheng/knowledge/application/unification_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T833\
  **配对测试**：T833\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T835 · 转换Tag关系全局完整性probe测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_resource_repository.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T761\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T836 · 转换Tag关系全局只读完整性probe**
  **类型 / Owner**：后端 Repository / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_resource_repository.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T835\
  **配对测试**：T835\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T837 · M2实际冻结精确转换计划组合测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_preflight.py`、`src/backend/test/knowledge_unification/test_migration_inventory_application.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T834, T836\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T838 · M2精确转换计划实际委托**
  **类型 / Owner**：后端 Application / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_preflight.py`、`src/backend/bisheng/knowledge/application/unification_inventory.py`\
  **逻辑 / 测试上下文**：W6§43仅M2精确SQL阶段计划，原业务/neutral/来源摘要、自然V1键、creation/Tag/default闭集；不执行M3或权限finalize。\
  **依赖**：T837\
  **配对测试**：T837\
  **验证 / 完成条件**：原生数据及真实Owner摘要红绿、分页/多版本/碰撞零写、旧来源完整回归与独立复核；不将纯计划计为M3/正式升级完成。

- [x] **T839 · 原工作台pin回归夹具与可见性断言对齐**
  **类型 / Owner**：测试夹具 / INT\
  **写入文件**：`src/backend/test/workstation/test_workstation_apps_rebac.py`、`src/backend/test/workstation/test_used_app_pin.py`\
  **逻辑 / 测试上下文**：W6§46实际旧回归：仅原use gate断言改visible，真实union已读App的SQLite夹具补空App表，保所有原pin/取消/跨tenant/offline/hidden业务断言。先固定未改生产对照旧失败，不将夹具失败算产品红。\
  **依赖**：T151\
  **验证 / 完成条件**：两旧叶与新入口/原v2身份/invoke组合通过，独立复核不削断言或替真实DAO。

- [x] **T840 · M2原集成夹具补独立required broker端口**
  **类型 / Owner**：测试夹具 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_inventory_application.py`\
  **逻辑 / 测试上下文**：W6§42 root装配required broker后，仅原fixture供独立只读broker port、缺口矩阵补broker；原Catalog/Source/physical/queued/材料与全部原行为断言保持，不fake实际UnificationInventoryApplication。\
  **依赖**：T830\
  **验证 / 完成条件**：原集成与新broker消费测试完整组合、拒绝/误commit零Run、frozen replay零重读；不把fixture计作正式迁移。

- [x] **T841 · SQL转换纯Domain协议与原wire一致性测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_conversion_schema.py`\
  **逻辑 / 测试上下文**：W6§48唯一七dataclass与纯V1模板从App下沉Domain，旧App导出同一class/函数，原artifact字节、hash与自然键模板不变。\
  **依赖**：T838\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-63\
  **验证 / 完成条件**：缺Domain模块真红后同class/模板/codec回归绿；新Domain仅stdlib依赖，不执行SQL、授权或迁移。

- [x] **T842 · SQL转换纯协议唯一Domain所有者**
  **类型 / Owner**：后端 Schema / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/unification_conversion.py`、`src/backend/bisheng/knowledge/application/unification_conversion_plan.py`\
  **逻辑 / 测试上下文**：W6§48仅移动七纯dataclass及initial_version_templates，App显式import/re-export，COMMAND_RECORD_TYPES维持原映射入口；不复制命令/哈希或引新行为。\
  **依赖**：T841\
  **配对测试**：T841\
  **验证 / 完成条件**：原精确计划/codec/Source与新协议组合、Ruff/arch及独立复核；不计M3 SQL或namespace发布完成。


- [x] **T843 · 来源安全展示批量协议测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_disclosure.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T842\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：记录真实红阶段，夹具错误不计产品红。

- [x] **T844 · 来源安全展示批量协议与纯装配**
  **类型 / Owner**：后端 Application/Repository / EDGE\
  **写入文件**：`src/backend/bisheng/resource_reference/application/source_disclosure.py`、`src/backend/bisheng/resource_reference/disclosure_composition.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T843\
  **配对测试**：T843\
  **验证 / 完成条件**：原资格/native SQL/规模及新旧选集通过，独立复核后集成；不代替完整原T112或公开删除。

- [x] **T845 · 工作流来源批量展示测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_workflow_source_disclosure.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T844\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：记录真实红阶段，夹具错误不计产品红。

- [x] **T846 · 工作流来源批量展示**
  **类型 / Owner**：后端 Application/Repository / EDGE\
  **写入文件**：`src/backend/bisheng/workflow/application/reference_source_owner.py`、`src/backend/bisheng/workflow/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T845\
  **配对测试**：T845\
  **验证 / 完成条件**：原资格/native SQL/规模及新旧选集通过，独立复核后集成；不代替完整原T112或公开删除。

- [x] **T847 · 助手来源批量展示测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_assistant_source_disclosure.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T844\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：记录真实红阶段，夹具错误不计产品红。

- [x] **T848 · 助手来源批量展示**
  **类型 / Owner**：后端 Application/Repository / PERM\
  **写入文件**：`src/backend/bisheng/assistant/application/reference_source_owner.py`、`src/backend/bisheng/assistant/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T847\
  **配对测试**：T847\
  **验证 / 完成条件**：原资格/native SQL/规模及新旧选集通过，独立复核后集成；不代替完整原T112或公开删除。

- [x] **T849 · 应用版本来源批量展示测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_source_disclosure.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T844\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：记录真实红阶段，夹具错误不计产品红。

- [x] **T850 · 应用版本来源批量展示**
  **类型 / Owner**：后端 Application/Repository / PERM\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_source_owner.py`、`src/backend/bisheng/app_publish/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T849\
  **配对测试**：T849\
  **验证 / 完成条件**：原资格/native SQL/规模及新旧选集通过，独立复核后集成；不代替完整原T112或公开删除。

- [x] **T851 · 频道同步来源批量展示测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_channel_source_disclosure.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T844\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：记录真实红阶段，夹具错误不计产品红。

- [x] **T852 · 频道同步来源批量展示**
  **类型 / Owner**：后端 Application/Repository / EDGE\
  **写入文件**：`src/backend/bisheng/channel/application/reference_source_owner.py`、`src/backend/bisheng/channel/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T851\
  **配对测试**：T851\
  **验证 / 完成条件**：原资格/native SQL/规模及新旧选集通过，独立复核后集成；不代替完整原T112或公开删除。

- [x] **T853 · 知识空间模型来源批量展示测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_knowledge_source_disclosure.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T844\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：记录真实红阶段，夹具错误不计产品红。

- [x] **T854 · 知识空间模型来源批量展示**
  **类型 / Owner**：后端 Application/Repository / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/reference_source_owner.py`、`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T853\
  **配对测试**：T853\
  **验证 / 完成条件**：原资格/native SQL/规模及新旧选集通过，独立复核后集成；不代替完整原T112或公开删除。

- [x] **T855 · 默认配置模型来源批量展示测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_defaults_source_disclosure.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T844\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：记录真实红阶段，夹具错误不计产品红。

- [x] **T856 · 默认配置模型来源批量展示**
  **类型 / Owner**：后端 Application/Repository / INT\
  **写入文件**：`src/backend/bisheng/llm/application/model_default_source_owner.py`、`src/backend/bisheng/llm/domain/repositories/model_default_repository.py`\
  **逻辑 / 测试上下文**：W6§49≤200轻列与原业务资格，隐藏/foreign零泄露、当前坏链失败、原身份前后重验，无配置整图/N+1/写。\
  **依赖**：T855\
  **配对测试**：T855\
  **验证 / 完成条件**：原资格/native SQL/规模及新旧选集通过，独立复核后集成；不代替完整原T112或公开删除。

- [x] **T857 · M2新建V1时间精度测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_plan_time.py`\
  **逻辑 / 测试上下文**：W6§50真实M2一次时钟含微秒，跨tenant同整秒planned_at与模板摘要；不在M3修改冻结材料。\
  **依赖**：T842\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：真实producer红；无Model/DDL或旧业务时间改写。

- [x] **T858 · M2新建V1统一可表示时间**
  **类型 / Owner**：后端 Application / INT\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_inventory.py`\
  **逻辑 / 测试上下文**：W6§50正式计划生成时一次UTC整秒，原模板/codec/hash算法不改；旧冻结材料拒绝被隐式重写。\
  **依赖**：T857\
  **配对测试**：T857\
  **验证 / 完成条件**：新红绿/原M2/模板/codec选集通过及独立复核。

- [x] **T859 · 迁移指纹Domain迁移与wire一致测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_fingerprints.py`\
  **逻辑 / 测试上下文**：W6§51旧canonical/digest逐字节与拒绝、App同对象、Domain独立导入，无算法重写。\
  **依赖**：T842\
  **覆盖 AC**: AC-56, AC-58, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：先固定旧实际成功/失败全集及缺Domain真实红。

- [x] **T860 · 迁移纯指纹唯一Domain所有者**
  **类型 / Owner**：后端 Domain/Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/unification_fingerprints.py`、`src/backend/bisheng/knowledge/application/unification_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§51仅搬canonical/digest/_invalid并App同对象re-export，不迁闭集codec及权限映射，不改wire。\
  **依赖**：T859\
  **配对测试**：T859\
  **验证 / 完成条件**：字节/拒绝一致、无反向依赖及原选集通过，独立复核。

- [x] **T861 · M3原生SQL转换仓储测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_conversion_repository.py`\
  **逻辑 / 测试上下文**：W6§52真实SQL锁/五命令白名单/写后完整摘要/同TX游标，保File全列、原time、无N²或JOIN乘积；不单独完成M3/覆盖。\
  **依赖**：T860, T858\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：原生SQL/异步取消/200及401/10001规模与真实时间触发器反例，先红后实现。

- [x] **T862 · M3原生SQL精确转换与写后核验**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/unification_conversion_repository.py`\
  **逻辑 / 测试上下文**：W6§52真实SQL锁/五命令白名单/写后完整摘要/同TX游标，保File全列、原time、无N²或JOIN乘积；不单独完成M3/覆盖。\
  **依赖**：T861\
  **配对测试**：T861\
  **验证 / 完成条件**：限定本卡Domain叶，原生SQL与全部原选集通过，独立复核；App和namespace后继未接不能勾原T163164。

- [x] **T863 · M3受控批次与原事务进度测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_conversion_service.py`\
  **逻辑 / 测试上下文**：W6§52真实SQL锁/五命令白名单/写后完整摘要/同TX游标，保File全列、原time、无N²或JOIN乘积；不单独完成M3/覆盖。\
  **依赖**：T862\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：原生SQL/异步取消/200及401/10001规模与真实时间触发器反例，先红后实现。

- [x] **T864 · M3受控批次与原事务进度**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/unification_conversion.py`\
  **逻辑 / 测试上下文**：W6§52真实SQL锁/五命令白名单/写后完整摘要/同TX游标，保File全列、原time、无N²或JOIN乘积；不单独完成M3/覆盖。\
  **依赖**：T863\
  **配对测试**：T863\
  **验证 / 完成条件**：限定本卡Domain叶，原生SQL与全部原选集通过，独立复核；App和namespace后继未接不能勾原T163164。

- [x] **T865 · APP来源SA创建者例外原生预算测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/permission/test_creator_delete_batch.py`\
  **逻辑 / 测试上下文**：W6§54原SQL/F048Runtime 50全拒508及creator-only556 SELECT反例，原策略保持，批量预算与来源撤销/pin/scope。\
  **依赖**：T844\
  **覆盖 AC**: AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：原行为首绿与预算真红分别记录，使用真实SQL/FGA运输边界，不镜像授权实现。

- [x] **T866 · APP来源SA创建者例外批量读取**
  **类型 / Owner**：后端 Permission / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/runtime.py`、`src/backend/bisheng/permission/application/control_state.py`\
  **逻辑 / 测试上下文**：W6§54仅CUSTOM剩余SA delete批一次Catalog/Mode/Grant，原INHERIT fallback与来源/主体判定不变。\
  **依赖**：T865\
  **配对测试**：T865\
  **验证 / 完成条件**：原生策略与有界预算、原single/batch权限选集通过及独立复核，不新授权或DAO。

- [x] **T867 · 模型来源分页纯cursor测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_reference_sources.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T856\
  **覆盖 AC**: AC-01, AC-02, AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：真实缺接口/预算红与策略首绿分列；旧fixture卡只适配原行为不变生产。

- [x] **T868 · 模型来源分页纯cursor与DTO**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/llm/domain/services/model_reference_cursor.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T867\
  **配对测试**：T867\
  **验证 / 完成条件**：固定范围新旧原生选集与规模、独立复核通过，完整公开删除另卡。

- [x] **T869 · 模型来源完整分类与流式摘要测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_refs.py`、`src/backend/test/knowledge_unification/test_model_reference_sources.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T868, T874\
  **覆盖 AC**: AC-01, AC-02, AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：真实缺接口/预算红与策略首绿分列；旧fixture卡只适配原行为不变生产。

- [x] **T870 · 模型影响核心真实来源消费**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/llm/domain/services/model_reference_service.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T869\
  **配对测试**：T869\
  **验证 / 完成条件**：固定范围新旧原生选集与规模、独立复核通过，完整公开删除另卡。

- [x] **T871 · 原SA删除测试夹具补批量端口**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/open_api/test_service_account_creator_delete.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T866\
  **覆盖 AC**: AC-01, AC-02, AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：真实缺接口/预算红与策略首绿分列；旧fixture卡只适配原行为不变生产。

- [x] **T872 · 原APP注册测试对齐可见及可信pin**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/app_runtime/test_app_permission_registration.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T022\
  **覆盖 AC**: AC-01, AC-02, AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：真实缺接口/预算红与策略首绿分列；旧fixture卡只适配原行为不变生产。

- [x] **T873 · 大模型目标集原生查询预算测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_target_scale.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T652, T654\
  **覆盖 AC**: AC-01, AC-02, AC-71, AC-72, AC-73, AC-75, AC-76, AC-89\
  **验证 / 完成条件**：真实缺接口/预算红与策略首绿分列；旧fixture卡只适配原行为不变生产。

- [x] **T874 · 大模型目标集批量删除标记与紧凑谓词**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`、`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：W6§55/56严格原资格、完整计数、有界流/页与原生预算，不新授权或假Coverage。\
  **依赖**：T873\
  **配对测试**：T873\
  **验证 / 完成条件**：固定范围新旧原生选集与规模、独立复核通过，完整公开删除另卡。

- [x] **T875 · 正式冻结产物共享读取测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_frozen_plan_reader.py`\
  **逻辑 / 测试上下文**：W6§57冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T842, T858, T860\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T876 · 正式冻结产物共享读取**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_inventory.py`\
  **逻辑 / 测试上下文**：W6§57冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T875\
  **配对测试**：T875\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T877 · SQL转换页精确反解测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_conversion_codec.py`\
  **逻辑 / 测试上下文**：W6§57冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T876, T862\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T878 · SQL转换页精确反解**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_conversion_codec.py`\
  **逻辑 / 测试上下文**：W6§57冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T877\
  **配对测试**：T877\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T879 · 真实冻结产物SQL执行与恢复测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_conversion_application.py`\
  **逻辑 / 测试上下文**：W6§57冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T878, T864\
  **覆盖 AC**: AC-56, AC-58, AC-59, AC-63, AC-85, AC-93\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T880 · 真实冻结产物SQL执行与恢复**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_conversion.py`\
  **逻辑 / 测试上下文**：W6§57冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T879\
  **配对测试**：T879\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T881 · 初始上传原生全链原子注册测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload_registration_repository.py`\
  **逻辑 / 测试上下文**：W6§58冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T082\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-11, AC-14, AC-43\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T882 · 初始上传原生全链原子注册仓储**
  **类型 / Owner**：后端 Repository / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/upload_registration_repository.py`\
  **逻辑 / 测试上下文**：W6§58冻结边界；真实原生事务、严格身份、完整材料先验与有界读取；不提前验收原整项任务。\
  **依赖**：T881\
  **配对测试**：T881\
  **验证 / 完成条件**：真实红绿、独立固定SHA复核、主树集成；不以本地native替代真实MySQL升级或E2E。

- [x] **T883 · 原上传共享准备与有效快照测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload_preparation.py`\
  **逻辑 / 测试上下文**：W6§59原download/真实大小md5/actual规则和旧caller回归，prepare零SQL或对象写，不新授权。\
  **依赖**：T679\
  **覆盖 AC**: AC-02, AC-10, AC-43, AC-49\
  **验证 / 完成条件**：真实缺接口红/实际输入回归、原caller固定组合，不复制实现。

- [x] **T884 · 原上传共享准备与有效快照提取**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：W6§59仅原process_one_file准备段提取/消费，原dedup/投影/对象/错误保持；SPACE实际接线后继。\
  **依赖**：T883\
  **配对测试**：T883\
  **验证 / 完成条件**：原新组合、静态新增0、独立复核及主树集成；不提前完成T083084。

- [x] **T885 · 原模型绑定证据匹配原生规模测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_original_evidence_scale.py`\
  **逻辑 / 测试上下文**：W6§60单来源401/1001目标实际SQL与候选扫描计数，重复slot一致性/冲突及source版本隔离。\
  **依赖**：T874\
  **覆盖 AC**: AC-71, AC-72, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：先真实平方扫描预算红，再原语义与线性预算绿；不以计时猜性能。

- [x] **T886 · 原模型绑定证据按目标单次分组**
  **类型 / Owner**：后端 Repository / INT\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：W6§60仅内存分组，原_original证据冲突/首行语义、SQL/锁/权限与union分支不变。\
  **依赖**：T885\
  **配对测试**：T885\
  **验证 / 完成条件**：原生有界预算及全部Owner/混合旧路径组合，非作者固定复核和主集成。

- [x] **T887 · 初始上传commit ACK与fresh重绑定测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload_committed_registration.py`\
  **逻辑 / 测试上下文**：W6§61原生root commit/rollback/savepoint/unknown ACK、同次issuer及完整初始链，0外部IO。\
  **依赖**：T882\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43\
  **验证 / 完成条件**：真实缺接口红及旧47全保，私有receipt/commit证据边界与有界native回归。

- [x] **T888 · 初始上传确定key与已ACK短事务重绑定**
  **类型 / Owner**：后端 Repository / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/upload_registration_repository.py`\
  **逻辑 / 测试上下文**：W6§61只扩已确认commit本次初始V1链，不放松原sameTX方法、不授权裸ID或跨进程回收。\
  **依赖**：T887\
  **配对测试**：T887\
  **验证 / 完成条件**：生产仍≤600，原生红绿、非作者复核/主组合；App/Service/DI后继未接不验收T083084。

- [x] **T889 · 重复上传复用原准备快照测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload_duplicate_preparation.py`\
  **逻辑 / 测试上下文**：W6§62真实md5优先/同名选择、tmp及FAILED响应/skip_dedup，零再下载/SQL写/版本/queue。\
  **依赖**：T884\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：真实缺接口红及原业务首绿分列，原上传组合不删断言。

- [x] **T890 · 原重复上传暂存分支唯一复用**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：W6§62只提取原重复分支并由原process调用，消费PreparedUpload，不扩授权/去重或新任务。\
  **依赖**：T889\
  **配对测试**：T889\
  **验证 / 完成条件**：原新组合与静态新增0、固定非作者复核/主树集成；SPACE实际接线后继。

- [x] **T891 · 原引用集合摘要流字节与内存测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_reference_digest_stream.py`\
  **逻辑 / 测试上下文**：W6§63原成功SHA/去重/lex/子类及Unicode一致，有序100001流常数辅助内存，区分原normalize成本。\
  **依赖**：T860\
  **覆盖 AC**: AC-56, AC-63, AC-71, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：新接口真红，旧函数实际oracle锁字节/异常，原R2/M2选集与非作者复核。

- [x] **T892 · 原引用摘要唯一有序累加器**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/resource_reference/application/contracts.py`\
  **逻辑 / 测试上下文**：W6§63旧normalize后委托唯一逐行JSON摘要，所有旧协议不变；M4实际消费者后继。\
  **依赖**：T891\
  **配对测试**：T891\
  **验证 / 完成条件**：原字节/行为与stream内存、static、非作者固定SHA复核及主树集成；不验收Coverage/回填。

- [x] **T893 · 正式原来源闭包及页跨度测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_reference_plan.py`\
  **逻辑 / 测试上下文**：W6§64精确合同，真实材料/原业务边界，不造authority或跨IO事务。\
  **依赖**：T892, T876\
  **覆盖 AC**: AC-56, AC-63, AC-85, AC-87, AC-89, AC-93\
  **验证 / 完成条件**：先真实红再实现、原native组合/静态、新叶≤600、非作者固定复核与主集成；整项与真实E2E继续单列。

- [x] **T894 · 正式原来源闭包及有界引用消费**
  **类型 / Owner**：后端 Application / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/application/unification_reference_plan.py`\
  **逻辑 / 测试上下文**：W6§64精确合同，真实材料/原业务边界，不造authority或跨IO事务。\
  **依赖**：T893\
  **配对测试**：T893\
  **验证 / 完成条件**：先真实红再实现、原native组合/静态、新叶≤600、非作者固定复核与主集成；整项与真实E2E继续单列。

- [x] **T895 · 初始引用索引只读原生分页测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_reference_backfill_repository.py`\
  **逻辑 / 测试上下文**：W6§64精确合同，真实材料/原业务边界，不造authority或跨IO事务。\
  **依赖**：T374\
  **覆盖 AC**: AC-56, AC-63, AC-87, AC-88, AC-89, AC-93\
  **验证 / 完成条件**：先真实红再实现、原native组合/静态、新叶≤600、非作者固定复核与主集成；整项与真实E2E继续单列。

- [x] **T896 · 初始引用索引只读头与实际ID分页**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/reference_backfill_repository.py`\
  **逻辑 / 测试上下文**：W6§64精确合同，真实材料/原业务边界，不造authority或跨IO事务。\
  **依赖**：T895\
  **配对测试**：T895\
  **验证 / 完成条件**：先真实红再实现、原native组合/静态、新叶≤600、非作者固定复核与主集成；整项与真实E2E继续单列。

- [x] **T897 · 普通新上传短事务应用测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_space_upload_application.py`\
  **逻辑 / 测试上下文**：W6§65精确合同，真实材料/原业务边界，不造authority或跨IO事务。\
  **依赖**：T888, T884\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：先真实红再实现、原native组合/静态、新叶≤600、非作者固定复核与主集成；整项与真实E2E继续单列。

- [x] **T898 · 普通新上传短事务应用**
  **类型 / Owner**：后端 Application / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/application/space_upload.py`\
  **逻辑 / 测试上下文**：W6§65精确合同，真实材料/原业务边界，不造authority或跨IO事务。\
  **依赖**：T897\
  **配对测试**：T897\
  **验证 / 完成条件**：先真实红再实现、原native组合/静态、新叶≤600、非作者固定复核与主集成；整项与真实E2E继续单列。

- [x] **T899 · 原SPACE上传入口与真实DI接线测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_space_upload_wiring.py`\
  **逻辑 / 测试上下文**：W6§66原入口+真实App/Repo/Prepared及DI，原权限与队列tenant、配额前置/未知结果/限定补偿。\
  **依赖**：T898, T890\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：真实缺接线红、native组合与非作者复核；外部运输fake不计E2E。

- [x] **T900 · 原SPACE普通上传原子链与应用DI接线**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`、`src/backend/bisheng/knowledge/api/dependencies.py`\
  **逻辑 / 测试上下文**：W6§66两叶接原App factory，不扩动作/格式/审批/worker race；目录网页历史后继。\
  **依赖**：T899\
  **配对测试**：T899\
  **验证 / 完成条件**：原运输及snapshot语义保留、两叶static新增0、固定非作者复核及主集成。

- [x] **T901 · 原上传共享fixture装配实际事务应用**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload.py`、`src/backend/test/knowledge_unification/test_kn_upload_overrides.py`\
  **逻辑 / 测试上下文**：W6§66对齐明确factory依赖，保真实SQL/原准备与原业务断言，仅同upload_file重复复核调用次数按真实入口对齐。\
  **依赖**：T900\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：原fixture在固定旧新源码差异验证；不替新App造同义fake，不删旧effective/版本/队列断言。

- [x] **T902 · 历史版本原子重链仓储测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_version_mutation_repository.py`\
  **逻辑 / 测试上下文**：W6§67仅原link/merge/set-primary整链原子性，原资格及错误不扩。\
  **依赖**：T882\
  **覆盖 AC**: AC-02, AC-10, AC-11, AC-31, AC-43, AC-51\
  **验证 / 完成条件**：真实缺接口/多提交反例与native整链回归、固定独审。

- [x] **T903 · 历史版本原子重链仓储**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/knowledge_version_mutation_repository.py`\
  **逻辑 / 测试上下文**：W6§67同TX私有锁事实、整链唯一提交，非Blob/权限新gate。\
  **依赖**：T902\
  **配对测试**：T902\
  **验证 / 完成条件**：新叶≤600/static、原生规模、非作者固定复核与主组合；入口后继未接不计完成。

- [x] **T904 · 历史版本单次提交应用测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_version_mutation_application.py`\
  **逻辑 / 测试上下文**：W6§67仅原link/merge/set-primary整链原子性，原资格及错误不扩。\
  **依赖**：T903\
  **覆盖 AC**: AC-02, AC-10, AC-11, AC-31, AC-43, AC-51\
  **验证 / 完成条件**：真实缺接口/多提交反例与native整链回归、固定独审。

- [x] **T905 · 历史版本单次提交应用**
  **类型 / Owner**：后端 Application / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/application/knowledge_version_mutation.py`\
  **逻辑 / 测试上下文**：W6§67同TX私有锁事实、整链唯一提交，非Blob/权限新gate。\
  **依赖**：T904\
  **配对测试**：T904\
  **验证 / 完成条件**：新叶≤600/static、原生规模、非作者固定复核与主组合；入口后继未接不计完成。

- [x] **T906 · 新上传数据库更新时间触发器原生反例**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload_database_timestamp.py`\
  **逻辑 / 测试上下文**：W6§68真实SQLite trigger模拟已存在无条件updater，非DM实跑。\
  **依赖**：T888\
  **覆盖 AC**: AC-09, AC-10, AC-43\
  **验证 / 完成条件**：固定父真实红、非时间漂移仍拒、原组合不退化。

- [x] **T907 · 新上传物化时间采用数据库实际事实**
  **类型 / Owner**：后端 Repository / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/upload_registration_repository.py`\
  **逻辑 / 测试上下文**：W6§68只新File物化后update_time采用实际值，全部其他字段/receipt/链不放宽。\
  **依赖**：T906\
  **配对测试**：T906\
  **验证 / 完成条件**：原生红绿/static/非作者固定审及主集成，迁移时间规则不变。

- [x] **T908 · 原v2与MCP普通上传实际工厂测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_open_upload_wiring.py`\
  **逻辑 / 测试上下文**：W6§69真实构造函数消费原operator，独立新App/Session factory，不改wire。\
  **依赖**：T898, T900\
  **覆盖 AC**: AC-02, AC-10, AC-65, AC-68, AC-70\
  **验证 / 完成条件**：准确旧factory红/原调用方组合与static。

- [x] **T909 · 原v2与MCP普通上传原子应用工厂接线**
  **类型 / Owner**：后端 API / INT\
  **写入文件**：`src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`、`src/backend/bisheng/open_mcp/application.py`\
  **逻辑 / 测试上下文**：W6§69只两工厂配同一App，原SA/D/operator保真。\
  **依赖**：T908\
  **配对测试**：T908\
  **验证 / 完成条件**：真实factory/运输边界组合与非作者审，T126132134完整wire仍待后继。

- [x] **T910 · 原重建冲突用例显式装配上传前置**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_rebuild_write_entries.py`\
  **逻辑 / 测试上下文**：W6§66追加，保原busy/idle断言，新必需port与prepare副作用哨兵显式声明。\
  **依赖**：T900\
  **覆盖 AC**: AC-09, AC-51\
  **验证 / 完成条件**：缺port旧fixture失配单列，原native写入口组合全保。

- [x] **T911 · 原历史版本三写实际接线测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_version_mutation_wiring.py`\
  **逻辑 / 测试上下文**：W6§70实际DI/Svc/App/Repo及原HTTP、原审计/错误和unknown，不扩资格。\
  **依赖**：T905, T903\
  **覆盖 AC**: AC-02, AC-10, AC-11, AC-31, AC-43, AC-51\
  **验证 / 完成条件**：缺接线真红、native/ASGI组合、非作者固定审。

- [x] **T912 · 原历史版本三写委托原子应用**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py`、`src/backend/bisheng/knowledge/api/dependencies.py`\
  **逻辑 / 测试上下文**：W6§70两叶退役原多提交写，保wire/原login与开关/错误/审计，不改delete-version。\
  **依赖**：T911\
  **配对测试**：T911\
  **验证 / 完成条件**：完整原生链/HTTP、static新增0、非作者固定复核及主组合。

- [x] **T913 · 原版本重建冲突fixture装配真实原子应用**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_rebuild_write_entries.py`\
  **逻辑 / 测试上下文**：W6§70新的独占native Session而非旧request Session，全部原断言保留。\
  **依赖**：T912\
  **覆盖 AC**: AC-10, AC-51\
  **验证 / 完成条件**：旧fixture失配单列，实际busy/disabled/idle历史native组合。

- [x] **T914 · 原版本遗留原生测试装配与实际契约对齐**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_version_service_link.py`、`src/backend/test/knowledge/test_knowledge_version_service_set_primary.py`\
  **逻辑 / 测试上下文**：W6§71真实User/tenant/独立App，原业务错误与现multi-version源拒绝；无生产变化。\
  **依赖**：T912\
  **覆盖 AC**: AC-10, AC-11, AC-31\
  **验证 / 完成条件**：旧五路径22/10→新21/11失配准确归因，修后实际native组合及固定独审。

- [x] **T915 · 共享上传commit观察者测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload_commit_observer.py`\
  **逻辑 / 测试上下文**：W6§72同次真实native/原资格，no bareID补偿/no跨IO业务TX。\
  **依赖**：T907\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：真实缺接口红或原已修算法等价见证分列、固定独审/主组合。

- [x] **T916 · 共享上传commit观察者**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/upload_commit_observer.py`、`src/backend/bisheng/knowledge/domain/repositories/upload_registration_repository.py`\
  **逻辑 / 测试上下文**：W6§72每实现≤2生产叶、原SSOT唯一复用、不扩动作/框架/worker竞态。\
  **依赖**：T915\
  **配对测试**：T915\
  **验证 / 完成条件**：新叶≤600、原生和scope组合/static、固定非作者复核及主集成。

- [x] **T917 · 目录自有登记与空树收据测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_folder_upload_registration_repository.py`\
  **逻辑 / 测试上下文**：W6§72同次真实native/原资格，no bareID补偿/no跨IO业务TX。\
  **依赖**：T916\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：真实缺接口红或原已修算法等价见证分列、固定独审/主组合。

- [x] **T918 · 目录自有登记与空树收据**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/folder_upload_registration_repository.py`\
  **逻辑 / 测试上下文**：W6§72每实现≤2生产叶、原SSOT唯一复用、不扩动作/框架/worker竞态。\
  **依赖**：T917\
  **配对测试**：T917\
  **验证 / 完成条件**：新叶≤600、原生和scope组合/static、固定非作者复核及主集成。

- [x] **T919 · 同次目录与文件上传应用测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_folder_upload_application.py`\
  **逻辑 / 测试上下文**：W6§72同次真实native/原资格，no bareID补偿/no跨IO业务TX。\
  **依赖**：T918, T898\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：真实缺接口红或原已修算法等价见证分列、固定独审/主组合。

- [x] **T920 · 同次目录与文件上传应用**
  **类型 / Owner**：后端 Application / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/application/space_upload.py`\
  **逻辑 / 测试上下文**：W6§72每实现≤2生产叶、原SSOT唯一复用、不扩动作/框架/worker竞态。\
  **依赖**：T919\
  **配对测试**：T919\
  **验证 / 完成条件**：新叶≤600、原生和scope组合/static、固定非作者复核及主集成。

- [x] **T921 · 目录整次末尾派发接线测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_folder_upload_wiring.py`\
  **逻辑 / 测试上下文**：W6§72同次真实native/原资格，no bareID补偿/no跨IO业务TX。\
  **依赖**：T920, T900\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-14, AC-43, AC-49\
  **验证 / 完成条件**：真实缺接口红或原已修算法等价见证分列、固定独审/主组合。

- [x] **T922 · 目录整次末尾派发接线**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：W6§72每实现≤2生产叶、原SSOT唯一复用、不扩动作/框架/worker竞态。\
  **依赖**：T921\
  **配对测试**：T921\
  **验证 / 完成条件**：新叶≤600、原生和scope组合/static、固定非作者复核及主集成。

- [x] **T923 · 原目录上传测试明确同次应用边界**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_space_folder_upload.py`、`src/backend/test/knowledge/test_knowledge_space_folder_upload_api.py`\
  **逻辑 / 测试上下文**：W6§72只必要factory/边界fixture，保全部原count/depth/name/path/quota/permission/dedup断言。\
  **依赖**：T922\
  **覆盖 AC**: AC-09, AC-10, AC-14\
  **验证 / 完成条件**：准确旧新差异、实际folder App组合，不造兼容fake writer。

- [x] **T924 · 移动F048真实投影闭集证据测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_projection_repository.py`、`src/backend/test/knowledge_unification/test_move_projection.py`\
  **逻辑 / 测试上下文**：W6§73/[移动合同](./move-processing-contract.md)仅P1/K1；真实ledger/全版本native，非fake authority。\
  **依赖**：T026, T027\
  **覆盖 AC**: AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-49, AC-54, AC-87, AC-88\
  **验证 / 完成条件**：真实缺接口红、原生/40110001有界预算与固定独审；K1实际apply最终用P1证据组合。

- [x] **T925 · 移动F048真实投影闭集证据**
  **类型 / Owner**：后端 Application / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/repositories/move_projection_repository.py`、`src/backend/bisheng/permission/application/knowledge_move_projection.py`\
  **逻辑 / 测试上下文**：W6§73只登记两生产叶，新叶≤600，真实issuer/TX/Scope，不开后继kind。\
  **依赖**：T924\
  **配对测试**：T924\
  **验证 / 完成条件**：完整read/证据或切换原子性、SQL规模与static、固定非作者审和主组合；不提前验收整移动。

- [x] **T926 · 整链移动闭集与同TX切换收据测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_scope_repository.py`、`src/backend/test/knowledge_unification/test_move_cutover_repository.py`\
  **逻辑 / 测试上下文**：W6§73/[移动合同](./move-processing-contract.md)仅P1/K1；真实ledger/全版本native，非fake authority。\
  **依赖**：T016, T064\
  **覆盖 AC**: AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-49, AC-54, AC-87, AC-88\
  **验证 / 完成条件**：真实缺接口红、原生/40110001有界预算与固定独审；K1实际apply最终用P1证据组合。

- [x] **T927 · 整链移动闭集与同TX切换收据**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/move_scope_repository.py`、`src/backend/bisheng/knowledge/domain/repositories/move_cutover_repository.py`\
  **逻辑 / 测试上下文**：W6§73只登记两生产叶，新叶≤600，真实issuer/TX/Scope，不开后继kind。\
  **依赖**：T926\
  **配对测试**：T926\
  **验证 / 完成条件**：完整read/证据或切换原子性、SQL规模与static、固定非作者审和主组合；不提前验收整移动。

- [x] **T928 · 网页新建闭集材料与原对象key测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_web_upload_material.py`\
  **逻辑 / 测试上下文**：W6§74原Utils/key/metadata/bytes等价，0 IO/authority。\
  **依赖**：T884\
  **覆盖 AC**: AC-09, AC-10, AC-43\
  **验证 / 完成条件**：真实缺模块红、原实际oracle与repr隔离/native组合。

- [x] **T929 · 网页新建闭集材料计划**
  **类型 / Owner**：后端 Application / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/application/web_link_upload.py`\
  **逻辑 / 测试上下文**：W6§74只纯DTO/材料计划，非第二writer/绑定/actor/散列/对象事务。\
  **依赖**：T928\
  **配对测试**：T928\
  **验证 / 完成条件**：新叶≤600/static、固定非作者复核和主组合；App/Svc后继未接不验收Web。

- [x] **T930 · 移动闭集纯 Domain DTO 同一类型与边界测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_processing_schema.py`\
  **逻辑 / 测试上下文**：W6§75同一DTO reexport、纯值校验、不复制hash/协议；原native闭集与source guard测试保留。\
  **依赖**：T926\
  **覆盖 AC**: AC-13, AC-43, AC-83\
  **验证 / 完成条件**：真实缺模块红或明确首绿，native组合与无新IO/authority。

- [x] **T931 · 移动闭集纯 Domain DTO 前置**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/move_processing.py`\
  **逻辑 / 测试上下文**：W6§75只DTO/类型校验，Scope显式同对象reexport；不为600行制造反向依赖。\
  **依赖**：T930\
  **配对测试**：T930\
  **验证 / 完成条件**：新叶≤600/static、固定非作者复核和主组合；不提前验收移动入口。

- [x] **T932 · 网页同次初始 App 与自有双对象测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_space_web_link_upload_application.py`\
  **逻辑 / 测试上下文**：W6§76 native初始链与两对象同receipt，失败/未知ACK/原身份/无事务跨IO。\
  **依赖**：T929, T920\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-43\
  **验证 / 完成条件**：真实红绿或首绿明确记录，固定非作者复核及相关native组合；不以局部证明冒整卡/E2E。

- [x] **T933 · 网页同次初始上传 App**
  **类型 / Owner**：后端 Application / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/application/space_upload.py`\
  **逻辑 / 测试上下文**：W6§76唯一_register闭集分支与有界attempted keys，普通/Folder不变。\
  **依赖**：T932\
  **配对测试**：T932\
  **验证 / 完成条件**：真实红绿或首绿明确记录，固定非作者复核及相关native组合；不以局部证明冒整卡/E2E。

- [x] **T934 · 网页实际规则和原入口接线测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_space_web_link_wiring.py`\
  **逻辑 / 测试上下文**：W6§77真实SSOT snapshot/HTTP/native链/原去重/覆写边界/tenant/queue。\
  **依赖**：T933\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-11, AC-43\
  **验证 / 完成条件**：真实红绿或首绿明确记录，固定非作者复核及相关native组合；不以局部证明冒整卡/E2E。

- [x] **T935 · 网页实际规则和原入口接线**
  **类型 / Owner**：后端 Domain / INT\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：W6§77原fetch/quota/dedup和scheduler保留，新建同App，覆写只原ID/完整性/规则窄接线。\
  **依赖**：T934\
  **配对测试**：T934\
  **验证 / 完成条件**：真实红绿或首绿明确记录，固定非作者复核及相关native组合；不以局部证明冒整卡/E2E。

- [x] **T936 · 原网页去重夹具适配实际身份和Root**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge/test_web_link_import_dedup.py`\
  **逻辑 / 测试上下文**：W6§77只必要原夹具适配，三个原错误与优先级仍真实验证；原fetch测试不改。\
  **依赖**：T935\
  **覆盖 AC**: AC-09, AC-43\
  **验证 / 完成条件**：真实红绿或首绿明确记录，固定非作者复核及相关native组合；不以局部证明冒整卡/E2E。

- [x] **T937 · 跨空间移动保留网页系统键的真实反例**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_scope_repository.py`\
  **逻辑 / 测试上下文**：W6§78源schema同名字段被移除时Web六系统键仍保，普通同名自定义值仍清；不扩字段禁令。\
  **依赖**：T930\
  **覆盖 AC**: AC-18, AC-21, AC-43\
  **验证 / 完成条件**：root独立真实1红及作者六键native反例，纯helper/Scope与后继policy共享，固定复核。

- [x] **T938 · 移动网页系统键唯一过滤**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/move_metadata_policy.py`；`src/backend/bisheng/knowledge/domain/repositories/move_scope_repository.py`\
  **逻辑 / 测试上下文**：W6§78纯helper+Scope两叶，后继Owner同helper构造原MoveMetadataPolicy，原DTO/hash/Worker不改。\
  **依赖**：T937\
  **配对测试**：T937\
  **验证 / 完成条件**：真实红绿、独立root反例重跑及相关组合，每新叶≤600；不冒整移动验收。

- [x] **T939 · 移动原主体纯SSOT测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_actor_subject.py`\
  **逻辑 / 测试上下文**：W6§79纯typed subject、S/D/audit分离、原move payload字节与原scope/home101保留。\
  **依赖**：T925\
  **覆盖 AC**: AC-43, AC-83, AC-86\
  **验证 / 完成条件**：真实红绿/首绿分列、固定非作者复核及相关组合，新叶≤600；不提前验收move/J1/正式升级。

- [x] **T940 · 移动原主体纯SSOT**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/processing_actor_subject.py`；`src/backend/bisheng/knowledge/application/processing_identity.py`\
  **逻辑 / 测试上下文**：W6§79只move主体提取委托，不复制credential/expiry/ceiling、不扩普通四kind。\
  **依赖**：T939\
  **配对测试**：T939\
  **验证 / 完成条件**：真实红绿/首绿分列、固定非作者复核及相关组合，新叶≤600；不提前验收move/J1/正式升级。

- [x] **T941 · 移动主体私有索引模型测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_actor_subject_schema.py`\
  **逻辑 / 测试上下文**：W6§79两Model nullable/exclude标准类型与Retry真实索引，四kind兼容NULL。\
  **依赖**：T940\
  **覆盖 AC**: AC-43, AC-83, AC-86\
  **验证 / 完成条件**：真实红绿/首绿分列、固定非作者复核及相关组合，新叶≤600；不提前验收move/J1/正式升级。

- [x] **T942 · 移动主体私有索引模型**
  **类型 / Owner**：后端 Model / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_processing_job.py`；`src/backend/bisheng/knowledge/domain/models/knowledge_processing_retry.py`\
  **逻辑 / 测试上下文**：W6§79四nullable字段/一Retry索引，仅观察事实，不扩鉴权或默认audit推断。\
  **依赖**：T941\
  **配对测试**：T941\
  **验证 / 完成条件**：真实红绿/首绿分列、固定非作者复核及相关组合，新叶≤600；不提前验收move/J1/正式升级。

- [x] **T943 · 移动主体中性DDL测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_actor_subject_migration.py`\
  **逻辑 / 测试上下文**：W6§79新revision幂等/单head/DDL-only，字段与Model一致，无JSON或业务回填。\
  **依赖**：T942\
  **覆盖 AC**: AC-57, AC-83\
  **验证 / 完成条件**：真实红绿/首绿分列、固定非作者复核及相关组合，新叶≤600；不提前验收move/J1/正式升级。

- [x] **T944 · 移动主体中性DDL**
  **类型 / Owner**：后端 DDL / INT\
  **写入文件**：`src/backend/bisheng/core/database/alembic/versions/v3_1_0_beta1_f118_move_actor_subject.py`\
  **逻辑 / 测试上下文**：W6§79实施时live head确定parent，四nullable字段及一索引，无move kind接线。\
  **依赖**：T943\
  **配对测试**：T943\
  **验证 / 完成条件**：真实红绿/首绿分列、固定非作者复核及相关组合，新叶≤600；不提前验收move/J1/正式升级。

- [x] **T945 · 移动 owned Root 锚与坏后代闭集反例**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_scope_repository.py`；`src/backend/test/knowledge_unification/test_move_row_repository.py`\
  **逻辑 / 测试上下文**：W6§80实际全局tenant filter下foreign子目录/缺File或Doc/目录被版本引用等不隐藏，原Scope/Schema规模和真P1证据保留。\
  **依赖**：T937\
  **覆盖 AC**: AC-17, AC-18, AC-43, AC-83, AC-85\
  **验证 / 完成条件**：作者独立真实1红固化，不以旧foreign-root例替代；只读零DML及固定非作者复验。

- [x] **T946 · 移动真实 owned Root FK 读取**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/move_row_repository.py`；`src/backend/bisheng/knowledge/domain/repositories/move_scope_repository.py`\
  **逻辑 / 测试上下文**：W6§80提取具体FK reader，Scope同签名消费，原Hash/DTO/权限/worker不变，无bypass/假Root锚。\
  **依赖**：T945\
  **配对测试**：T945\
  **验证 / 完成条件**：两生产叶各≤600，真实红绿和整闭集组合，未闭不验收K1整卡。

- [x] **T947 · 知识目标 tombstone 大集合预算与精确语义反例**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_knowledge_target_scale.py`\
  **逻辑 / 测试上下文**：W6§81真实sync/async owner401/10001及prelock401，6预算真红与原控制绿；精确owner/ancestor/重复/缺失/跨版本与原私有TX证明。\
  **依赖**：T002\
  **覆盖 AC**: AC-43, AC-83, AC-85\
  **验证 / 完成条件**：真实Repo零DML，旧10001 bind/prelock OR深度失败单列，不用skip/xfail抹去未修问题。

- [x] **T948 · 知识目标 tombstone 有界精确元组批锁**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：W6§81仅RRT批锁，完整元组全局lex顺序、每批≤200，同原revision/proof/观察语义，无额外缓存或权限变化。\
  **依赖**：T947\
  **配对测试**：T947\
  **验证 / 完成条件**：预算红转绿、现有Owner/native组合与固定非作者复核，不顺改OR/IN/original_for或读侧叶。

- [x] **T949 · 移动祖先NULL根路径真实反例**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_scope_repository.py`\
  **逻辑 / 测试上下文**：W6§82合法nested tree的Root NULL/空串控制，原路径错误/权限/闭集断言保留。\
  **依赖**：T945\
  **覆盖 AC**: AC-18, AC-19, AC-43, AC-83\
  **验证 / 完成条件**：真实NULL红及空串首绿分列，独立原反例复验。

- [x] **T950 · 移动祖先路径使用原解析语义**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/move_scope_repository.py`\
  **逻辑 / 测试上下文**：W6§82仅沿唯一path_ids规范比较，保原持久编码/DTO/hash/worker，无新路径政策。\
  **依赖**：T949\
  **配对测试**：T949\
  **验证 / 完成条件**：NULL反例绿、原非法格与9path组合通过、固定作者外复验。

- [x] **T951 · 目录历史版本归属的真实Web与闭集反例**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_scope_history.py`\
  **逻辑 / 测试上下文**：W6§83实际Web覆盖历史File后目录移动，Doc/primary在外；唯一/分歧relative、显式File原优先级与线性候选。\
  **依赖**：T950\
  **覆盖 AC**: AC-18, AC-19, AC-24, AC-43, AC-83\
  **验证 / 完成条件**：固定原producer/独立反例保留，正式真实红转绿，不放宽链校验。

- [x] **T952 · 目录覆盖历史文件的整Doc唯一目的归属**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/move_scope_repository.py`\
  **逻辑 / 测试上下文**：W6§83一次按Doc汇总实际选中历史路径，仅唯一候选落位；原Doc/显式File规则、ID链和全版本保持。\
  **依赖**：T951\
  **配对测试**：T951\
  **验证 / 完成条件**：Scope≤600、真实红绿及9path/规模预算、固定非作者复验；未开Owner/worker。

- [x] **T953 · 知识目标原证据大集合与稀疏版本预算反例**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_knowledge_target_original_scale.py`；`src/backend/test/knowledge_unification/test_knowledge_target_scale.py`\
  **逻辑 / 测试上下文**：W6§84原10001异常、单次分桶候选及实际稀疏版本读取预算/精确证据。\
  **依赖**：T948\
  **覆盖 AC**: AC-43, AC-83, AC-85\
  **验证 / 完成条件**：真实红绿/首绿分列、有界native及固定作者外复核；不扩大权限或提前验收完整特性。

- [x] **T954 · 知识目标查询分页及精确原证据分桶**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：W6§84业务numeric页、单版exact键页与多版selected-version原行seek；不版本×targets。\
  **依赖**：T953\
  **配对测试**：T953\
  **验证 / 完成条件**：真实红绿/首绿分列、有界native及固定作者外复核；不扩大权限或提前验收完整特性。

- [x] **T955 · 删除闭集与坏链规模真实反例**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_direct_delete_scope.py`；`src/backend/test/knowledge_unification/test_direct_delete_scope_scale.py`\
  **逻辑 / 测试上下文**：W6§85原单删/批量状态事实、完整及无Version链、真实C3/FK/重叠与规模。\
  **依赖**：T084\
  **覆盖 AC**: AC-12, AC-19, AC-43, AC-83, AC-85, AC-94\
  **验证 / 完成条件**：真实红绿/首绿分列、有界native及固定作者外复核；不扩大权限或提前验收完整特性。

- [x] **T956 · 删除物理闭集事实仓储前置**
  **类型 / Owner**：后端 Repository / PERM\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/direct_delete_scope.py`；`src/backend/bisheng/knowledge/domain/repositories/knowledge_space_delete_repository.py`\
  **逻辑 / 测试上下文**：W6§85两叶只读/可选有序锁读，不替换旧prepare/cutover或签可执行计划。\
  **依赖**：T955\
  **配对测试**：T955\
  **验证 / 完成条件**：真实红绿/首绿分列、有界native及固定作者外复核；不扩大权限或提前验收完整特性。

- [x] **T957 · Source授权读取的实际目标大集合预算反例**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_source_read_target_scale.py`\
  **逻辑 / 测试上下文**：W6§86真实SourceVerifier/SourceRepo/TargetRepo及sync Model、saved/transient和原三槽匹配；不fake scope。\
  **依赖**：T948\
  **覆盖 AC**: AC-37, AC-43, AC-68, AC-83, AC-85, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：真实预算红与原控制，0DML/原identity和tenant保持，private旧复杂度见证保留。

- [x] **T958 · Source授权KN和Model读取的有界查询与证据匹配**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/source_read_target_repository.py`；`src/backend/bisheng/llm/domain/repositories/source_read_target_repository.py`\
  **逻辑 / 测试上下文**：W6§86两叶only，原资格与共享策略不变；scalar精确RRT批锁/业务200ID页/原证据桶，sync与async保同语义。\
  **依赖**：T957, T954\
  **配对测试**：T957\
  **验证 / 完成条件**：预算红绿、原Owner/Source组合及固定作者外复验，≤600/叶，不宣称全局验收。

- [x] **T959 · 原任务接受值同对象及canonical投影测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_processing_job_acceptance.py`\
  **逻辑 / 测试上下文**：W6§87四原kind完整canonical oracle/原验证与类型身份、NaN/重复/空scope规则，实际旧Repo回归。\
  **依赖**：T927\
  **覆盖 AC**: AC-43, AC-49, AC-54, AC-83, AC-86\
  **验证 / 完成条件**：真实缺接口红/原控制分列、纯值无IO及旧原生组合。

- [x] **T960 · 原任务接受值与投影的唯一纯SSOT**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/schemas/processing_job_acceptance.py`；`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`\
  **逻辑 / 测试上下文**：W6§87同对象搬五原DTO及_digest，原manifest/request_facts纯投影原样提取；旧acreate原位置消费不变。\
  **依赖**：T959\
  **配对测试**：T959\
  **验证 / 完成条件**：canonical字节/既有消费同对象、原四kind与metadata空proof不变，固定作者外复验；不提前接受move。

- [x] **T961 · 移动reserved受理与原接受重放native反例**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_job_reservation.py`；`src/backend/test/knowledge_unification/test_move_job_membership.py`\
  **逻辑 / 测试上下文**：W6§89实际K1同SAVEPOINT/Plan→Job完整hash重放/0pending/typed原主体与真实Retry，原四kind控制。\
  **依赖**：T960, T927\
  **覆盖 AC**: AC-18, AC-19, AC-24, AC-43, AC-49, AC-54, AC-83, AC-86\
  **验证 / 完成条件**：真native缺接口红/控制绿，400/10001规模及外catchcommit不留半状态。

- [x] **T962 · 移动reserved接受与原Job持久事实查询**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/move_job_repository.py`；`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`\
  **逻辑 / 测试上下文**：W6§89唯一原K1/acceptance投影，同SAVEPOINT prepare/create/consume及持久重放/有界membership；旧Repo仅注入薄delegate。\
  **依赖**：T961\
  **配对测试**：T961\
  **验证 / 完成条件**：原四kind不变、新Repo≤600、固定非作者复验；不开放ready/Owner/worker/API。

- [x] **T963 · 原OwnerScope引用流规模与完整性反例**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_inbound_owner_stream.py`\
  **逻辑 / 测试上下文**：W6§90真receipts/LEFT完整性/SQL与复核CPU预算、跨yield篡改与TX早拒，不fake authority。\
  **依赖**：T958\
  **覆盖 AC**: AC-43, AC-70, AC-72, AC-76, AC-83, AC-85, AC-94\
  **验证 / 完成条件**：真实接口红/旧控制绿，401/1001/10001页及O(1)内guard验证。

- [x] **T964 · 原OwnerScope精确目标有界引用流**
  **类型 / Owner**：后端 Repository / EDGE\
  **写入文件**：`src/backend/bisheng/resource_reference/domain/repositories/reference_repository.py`\
  **逻辑 / 测试上下文**：W6§90单Repo流+与旧page共用private SQL/校验，无子scope/新authorization。\
  **依赖**：T963\
  **配对测试**：T963\
  **验证 / 完成条件**：真实红绿/规模/末验，旧公开默认方法原义；不预先开D3或删除许可。

- [x] **T965 · 独立迁移等级floor类型与普通visibility对照**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_permission_retired_use_floor_schema.py`\
  **逻辑 / 测试上下文**：修订W6§91独立readonly nullable字段/native Model、controlled canonical与普通visibility旧oracle不变。\
  **依赖**：T002\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83, AC-85\
  **验证 / 完成条件**：缺字段真实红/原控制绿，默认None旧payload/checksum相同，非法与HTTP写拒。

- [x] **T966 · 独立受控retired-use等级事实存储及canonical**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/models/catalog.py`；`src/backend/bisheng/permission/domain/services/model_policy.py`\
  **逻辑 / 测试上下文**：修订W6§91仅独立retired_use_level_floor非None时保floor；不改变visibility_level语义，不改Plan或签发。\
  **依赖**：T965\
  **配对测试**：T965\
  **验证 / 完成条件**：两叶窄增量、原policy/HTTP/native控制；DDL/完整pipeline后继，未完成不发布。

- [x] **T967 · 退役use等级nullable中性DDL测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_permission_retired_use_floor_migration.py`\
  **逻辑 / 测试上下文**：W6§92当前单head、旧表加nullableInteger无default/无回填、重复/已有列/缺表和旧值保持。\
  **依赖**：T966\
  **覆盖 AC**: AC-57, AC-80, AC-83, AC-85\
  **验证 / 完成条件**：真缺revision红→native DDL绿，Model同形且无业务DML/JSON读。

- [x] **T968 · 退役use等级中性结构准备**
  **类型 / Owner**：后端 DDL / INT\
  **写入文件**：`src/backend/bisheng/core/database/alembic/versions/v3_1_0_beta1_f118_retired_use_floor.py`\
  **逻辑 / 测试上下文**：W6§92live head为parent，仅permission_model单nullableInteger列，shared幂等helper，无业务签发。\
  **依赖**：T967\
  **配对测试**：T967\
  **验证 / 完成条件**：单head/offline guard/C2静态，未执行正式数据库升级或pipeline发布。

- [x] **T969 · 删除精确引用SQL事实native反例**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_direct_delete_reference_query.py`；`src/backend/test/knowledge_unification/test_direct_delete_reference_query_scale.py`\
  **逻辑 / 测试上下文**：W6§93实际D1/Owner/stream和Coverage尾验，raw事实不授权，规模/空/坏项。\
  **依赖**：T956, T964\
  **覆盖 AC**: AC-43, AC-70, AC-72, AC-76, AC-83, AC-85, AC-94\
  **验证 / 完成条件**：真实红绿/原控制、native规模或schema parity、固定非作者复验；不提前验收整体。

- [x] **T970 · 删除精确引用内部SQL事实收集**
  **类型 / Owner**：后端 Application / EDGE\
  **写入文件**：`src/backend/bisheng/knowledge/application/direct_delete_reference_query.py`\
  **逻辑 / 测试上下文**：W6§93单叶原公口，不做FGA/披露/新Session或派生child权限。\
  **依赖**：T969\
  **配对测试**：T969\
  **验证 / 完成条件**：真实红绿/原控制、native规模或schema parity、固定非作者复验；不提前验收整体。

- [x] **T971 · move逻辑marker私有模型字段测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_logical_marker_schema.py`\
  **逻辑 / 测试上下文**：W6§94nullable JsonType/原四kind/hash/序列化不变；不是ready签发。\
  **依赖**：T962\
  **覆盖 AC**: AC-24, AC-43, AC-49, AC-54, AC-83\
  **验证 / 完成条件**：真实红绿/原控制、native规模或schema parity、固定非作者复验；不提前验收整体。

- [x] **T972 · move逻辑ready私有持久槽前置**
  **类型 / Owner**：后端 Model / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/models/knowledge_processing_job.py`\
  **逻辑 / 测试上下文**：W6§94只nullable move_logical_marker，无默认ready/无模型引用，不关旧gap。\
  **依赖**：T971\
  **配对测试**：T971\
  **验证 / 完成条件**：真实红绿/原控制、native规模或schema parity、固定非作者复验；不提前验收整体。

- [x] **T973 · move逻辑marker中性DDL测试**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_logical_marker_migration.py`\
  **逻辑 / 测试上下文**：W6§94原live单head、旧值/缺表/重复/create_all/DDL-only。\
  **依赖**：T972\
  **覆盖 AC**: AC-57, AC-83, AC-85\
  **验证 / 完成条件**：真实红绿/原控制、native规模或schema parity、固定非作者复验；不提前验收整体。

- [x] **T974 · move逻辑marker中性结构准备**
  **类型 / Owner**：后端 DDL / INT\
  **写入文件**：`src/backend/bisheng/core/database/alembic/versions/v3_1_0_beta1_f118_move_logical_marker.py`\
  **逻辑 / 测试上下文**：W6§94实施前live parent，单nullable JsonType/无回填签发。\
  **依赖**：T973\
  **配对测试**：T973\
  **验证 / 完成条件**：真实红绿/原控制、native规模或schema parity、固定非作者复验；不提前验收整体。

- [x] **T975 · 权限floor native快照和typed图roundtrip反例**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_permission_floor_inventory_roundtrip.py`\
  **逻辑 / 测试上下文**：W6§95真实SnapshotRepo读FloorNone/3、codec完整记录/页/图、篡改拒，已有事实不丢。\
  **依赖**：T966, T968\
  **覆盖 AC**: AC-57, AC-80, AC-81, AC-83, AC-85\
  **验证 / 完成条件**：真实红绿/原库存和权限控制，exclude不导致snapshot丢事实。

- [x] **T976 · 退役floor既有事实的闭集模型与artifact载入**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/migration/f118_plan.py`；`src/backend/bisheng/knowledge/application/unification_inventory_codec.py`\
  **逻辑 / 测试上下文**：W6§95新Baseline字段与existing floor传递、typed codec白名单同改，无第三Snapshot/新签发。\
  **依赖**：T975\
  **配对测试**：T975\
  **验证 / 完成条件**：原等级门不松、完整native/typed roundtrip、固定非作者复验，不发布。

- [ ] **T977 · 既有floor的Catalog存取和CURRENT原生反例**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_permission_floor_catalog_roundtrip.py`\
  **逻辑 / 测试上下文**：W6§96真实API SQL存取、普通None控制及HTTP拒caller field。\
  **依赖**：T976\
  **覆盖 AC**: AC-78, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：真实红绿、原控制与固定作者外复验；不冒正式发布或E2E。

- [ ] **T978 · Catalog和CURRENT携带既有受控floor**
  **类型 / Owner**：后端 Application / PERM\
  **写入文件**：`src/backend/bisheng/permission/application/catalog_api.py`；`src/backend/bisheng/permission/application/control_state.py`\
  **逻辑 / 测试上下文**：W6§96仅两叶携带验证既有floor，不签新值。\
  **依赖**：T977\
  **配对测试**：T977\
  **验证 / 完成条件**：真实红绿、原控制与固定作者外复验；不冒正式发布或E2E。

- [ ] **T979 · move逻辑ready封口native反例**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_move_job_ready.py`\
  **逻辑 / 测试上下文**：W6§97零项/partial提交/lease/私有marker和有界执行。\
  **依赖**：T974, T962\
  **覆盖 AC**: AC-24, AC-43, AC-49, AC-54, AC-83\
  **验证 / 完成条件**：真实红绿、原控制与固定作者外复验；不冒正式发布或E2E。

- [ ] **T980 · move逻辑ready持久证明与item执行封口**
  **类型 / Owner**：后端 Repository / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/repositories/move_job_ready_repository.py`；`src/backend/bisheng/knowledge/domain/repositories/processing_job_repository.py`\
  **逻辑 / 测试上下文**：W6§97原TX验证、Item先Job后、薄委托及原kind控制。\
  **依赖**：T979\
  **配对测试**：T979\
  **验证 / 完成条件**：真实红绿、原控制与固定作者外复验；不冒正式发布或E2E。

## 自动化覆盖索引

以下仅映射 spec → 本任务清单的测试任务；不引用 QA 表生成开发任务。已完成项见各卡与实施记录；该映射不代表对应业务AC已完成端到端验收。

| AC | 测试任务 |
| --- | --- |
| AC-01 | T205, T722, T725, T727, T729, T867, T869, T871, T872, T873 |
| AC-02 | T083, T121, T196, T205, T228, T606, T607, T646, T648, T697, T718, T720, T722, T725, T727, T729, T732, T743, T750, T752, T754, T756, T867, T869, T871, T872, T873, T881, T883, T887, T889, T897, T899, T901, T902, T904, T908, T911, T915, T917, T919, T921, T932, T934 |
| AC-03 | T081, T121, T204, T606, T646, T648, T697, T722, T725, T727, T729, T732, T743, T787, T789, T791 |
| AC-04 | T081, T121, T196, T204, T220, T265, T606, T626, T646, T648, T722, T725, T727, T729, T732, T743 |
| AC-05 | T081, T121, T196, T204, T220, T265, T606, T626, T646, T648, T697, T722 |
| AC-06 | T079, T121, T205, T646, T648, T664, T695, T697, T720, T750, T752, T754, T756 |
| AC-07 | T079, T121, T205, T646, T648, T683, T695, T697, T706, T720, T722 |
| AC-08 | T077, T101, T121, T204, T686, T750, T752, T754, T756 |
| AC-09 | T083, T205, T669, T685, T750, T752, T754, T756, T765, T775, T787, T789, T791, T801, T803, T805, T816, T818, T820, T881, T887, T889, T897, T899, T901, T906, T910, T915, T917, T919, T921, T923, T928, T932, T934, T936 |
| AC-10 | T067, T083, T125, T205, T669, T673, T677, T765, T775, T787, T789, T791, T881, T883, T887, T889, T897, T899, T901, T902, T904, T906, T908, T911, T913, T914, T915, T917, T919, T921, T923, T928, T932, T934 |
| AC-11 | T083, T205, T750, T752, T754, T756, T775, T787, T789, T791, T881, T902, T904, T911, T914, T934 |
| AC-12 | T085, T105, T205, T607, T955 |
| AC-13 | T085, T105, T205, T607, T930 |
| AC-14 | T079, T083, T121, T165, T205, T685, T765, T801, T803, T805, T816, T818, T820, T881, T887, T889, T897, T899, T901, T915, T917, T919, T921, T923 |
| AC-15 | T079, T121, T205, T801, T803, T805, T816, T818, T820 |
| AC-16 | T205, T750, T752, T754, T756, T801, T803, T805 |
| AC-17 | T087, T089, T206, T669, T924, T926, T945 |
| AC-18 | T087, T089, T206, T924, T926, T937, T945, T949, T951, T961 |
| AC-19 | T073, T091, T206, T785, T924, T926, T949, T951, T955, T961 |
| AC-20 | T073, T091, T206, T785, T924, T926 |
| AC-21 | T087, T091, T206, T785, T924, T926, T937 |
| AC-22 | T087, T089, T206, T924, T926 |
| AC-23 | T073, T091, T206, T785, T924, T926 |
| AC-24 | T073, T089, T091, T206, T785, T924, T926, T951, T961, T971, T979 |
| AC-25 | T081, T095, T206 |
| AC-26 | T095, T206 |
| AC-27 | T095, T206 |
| AC-28 | T103, T105, T109, T202, T206 |
| AC-29 | T103, T105, T107, T109, T202, T206 |
| AC-30 | T023, T077, T101, T202, T204, T239, T240, T241, T242, T251, T628, T630, T632, T633, T650, T750, T752, T754, T756, T787, T789, T791, T801, T803, T805, T816, T818, T820 |
| AC-31 | T023, T077, T085, T099, T157, T202, T204, T239, T240, T241, T242, T251, T628, T630, T632, T633, T650, T667, T669, T681, T750, T752, T754, T756, T787, T789, T791, T801, T803, T805, T816, T818, T820, T902, T904, T911, T914 |
| AC-32 | T077, T121, T202, T204, T750, T752, T754, T756 |
| AC-33 | T071, T077, T097, T099, T123, T202, T204, T220, T626, T646, T648, T650, T683, T699, T701, T714, T718, T720, T733, T735, T737, T741 |
| AC-34 | T063, T071, T097, T123, T202, T204, T593, T596, T608, T610, T612, T614, T616, T618, T620, T622, T624, T634, T636, T638, T640, T642, T644, T660, T662, T675, T699, T701, T714, T733, T735, T737, T741, T750, T752, T754, T756 |
| AC-35 | T025, T051, T101, T123, T129, T131, T133, T141, T147, T149, T151, T196, T202, T204, T210, T220, T222, T226, T229, T265, T626, T646, T648, T650, T657, T659, T666, T667, T671, T686, T687, T744, T746, T747, T749 |
| AC-36 | T101, T202, T204, T222 |
| AC-37 | T029, T037, T041, T045, T101, T129, T137, T169, T202, T203, T204, T222, T281, T282, T297, T315, T321, T329, T355, T359, T364, T366, T367, T369, T375, T380, T382, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T546, T548, T550, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T577, T578, T579, T580, T581, T957 |
| AC-38 | T059, T123, T207, T664, T695, T705, T706, T720, T775 |
| AC-39 | T059, T069, T207, T233, T679, T690, T695, T705, T706 |
| AC-40 | T059, T069, T207, T679, T690, T695, T705, T706, T720 |
| AC-41 | T207, T705, T706, T720 |
| AC-42 | T059, T123, T207, T233, T705, T706 |
| AC-43 | T059, T067, T069, T083, T207, T233, T673, T675, T677, T679, T690, T705, T706, T765, T775, T787, T789, T791, T881, T883, T887, T889, T897, T899, T901, T902, T904, T906, T911, T915, T917, T919, T921, T928, T930, T932, T934, T936, T937, T939, T941, T945, T947, T949, T951, T953, T955, T957, T959, T961, T963, T969, T971, T979 |
| AC-44 | T059, T067, T069, T097, T207, T673, T675, T677, T679, T690, T705, T706, T775 |
| AC-45 | T067, T097, T099, T123, T207, T673, T675, T677, T690, T775 |
| AC-46 | T099, T207 |
| AC-47 | T071, T099, T207, T699, T701, T714, T733, T735, T737, T741 |
| AC-48 | T065, T097, T123, T207, T650, T657, T659, T664, T666, T667, T671, T683, T686, T687 |
| AC-49 | T061, T063, T065, T067, T071, T073, T075, T097, T123, T196, T208, T606, T607, T608, T610, T612, T614, T616, T618, T620, T622, T624, T634, T636, T638, T640, T642, T644, T657, T659, T660, T662, T664, T666, T673, T675, T677, T699, T701, T714, T733, T735, T737, T741, T766, T785, T883, T889, T897, T899, T901, T915, T917, T919, T921, T924, T926, T959, T961, T971, T979 |
| AC-50 | T061, T063, T071, T123, T208, T606, T607, T608, T610, T612, T614, T616, T618, T620, T622, T624, T636, T638, T640, T642, T644, T660, T662, T664, T675, T677, T714, T733, T735, T737, T741, T766 |
| AC-51 | T077, T097, T208, T667, T669, T671, T685, T686, T687, T750, T752, T754, T756, T765, T902, T904, T910, T911, T913 |
| AC-52 | T065, T097, T208, T657, T659, T664, T666 |
| AC-53 | T061, T065, T067, T071, T097, T208, T657, T659, T664, T666, T671, T673, T675, T677, T687, T699, T701, T714, T733, T735, T737, T741, T766 |
| AC-54 | T061, T063, T065, T067, T071, T073, T075, T097, T123, T208, T608, T610, T612, T614, T616, T618, T620, T622, T624, T634, T636, T638, T640, T642, T644, T657, T660, T662, T664, T666, T673, T675, T677, T683, T699, T701, T714, T733, T735, T737, T741, T766, T785, T924, T926, T959, T961, T971, T979 |
| AC-55 | T093, T125, T161, T163, T203, T211, T228, T693, T787, T789, T791, T799, T801, T803, T805 |
| AC-56 | T157, T159, T161, T173, T203, T211, T681, T688, T693, T703, T710, T712, T716, T760, T762, T769, T771, T772, T777, T779, T781, T783, T795, T799, T807, T809, T811, T813, T823, T825, T827, T829, T831, T833, T835, T837, T841, T857, T859, T861, T863, T875, T877, T879, T891, T893, T895 |
| AC-57 | T163, T203, T211, T228, T760, T762, T769, T943, T967, T973, T975 |
| AC-58 | T163, T203, T211, T760, T762, T769, T772, T777, T779, T799, T807, T809, T811, T823, T825, T827, T829, T831, T833, T835, T837, T841, T857, T859, T861, T863, T875, T877, T879 |
| AC-59 | T023, T157, T163, T169, T203, T211, T228, T681, T760, T831, T833, T835, T837, T841, T857, T861, T863, T875, T877, T879 |
| AC-60 | T077, T101, T163, T203, T211, T760, T831, T833, T835, T837 |
| AC-61 | T163, T165, T203, T211, T831, T833, T835, T837 |
| AC-62 | T163, T165, T203, T211, T760, T762, T831, T833, T835, T837 |
| AC-63 | T157, T159, T161, T163, T173, T203, T211, T228, T681, T688, T693, T703, T710, T712, T716, T760, T762, T769, T771, T772, T777, T779, T781, T783, T795, T799, T807, T809, T811, T813, T823, T825, T827, T829, T831, T833, T835, T837, T841, T857, T859, T861, T863, T875, T877, T879, T891, T893, T895 |
| AC-64 | T159, T161, T169, T173, T203, T211, T688, T693, T703, T710, T712, T716, T760, T762, T769 |
| AC-65 | T093, T125, T196, T210, T228, T267, T908 |
| AC-66 | T069, T125, T131, T133, T151, T196, T210, T222, T226, T228, T229, T233, T265, T267, T679, T690, T744, T746, T747 |
| AC-67 | T101, T125, T131, T210, T228 |
| AC-68 | T029, T037, T039, T041, T045, T047, T051, T125, T129, T131, T133, T137, T139, T147, T149, T151, T210, T222, T267, T281, T282, T284, T286, T294, T296, T297, T298, T305, T307, T309, T317, T321, T325, T331, T334, T353, T357, T359, T362, T364, T366, T367, T369, T375, T380, T382, T384, T392, T394, T395, T397, T399, T401, T403, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511, T513, T515, T517, T519, T521, T523, T525, T526, T527, T528, T529, T530, T532, T534, T535, T536, T537, T539, T541, T543, T546, T548, T550, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T582, T584, T586, T588, T590, T591, T592, T593, T595, T596, T597, T744, T746, T747, T908, T957 |
| AC-69 | T125, T133, T210 |
| AC-70 | T093, T111, T113, T115, T119, T202, T209, T651, T653, T655, T693, T703, T710, T712, T716, T908, T963, T969 |
| AC-71 | T029, T031, T035, T037, T043, T045, T047, T049, T053, T055, T057, T093, T111, T139, T167, T202, T209, T276, T286, T319, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T530, T532, T537, T539, T541, T543, T545, T546, T548, T550, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T582, T584, T586, T588, T590, T591, T592, T593, T595, T596, T597, T651, T653, T655, T693, T703, T710, T716, T843, T845, T847, T849, T851, T853, T855, T865, T867, T869, T871, T872, T873, T885, T891 |
| AC-72 | T013, T103, T111, T113, T117, T119, T202, T209, T651, T653, T655, T843, T845, T847, T849, T851, T853, T855, T865, T867, T869, T871, T872, T873, T885, T963, T969 |
| AC-73 | T111, T113, T115, T117, T119, T202, T209, T276, T319, T651, T653, T655, T843, T845, T847, T849, T851, T853, T855, T865, T867, T869, T871, T872, T873 |
| AC-74 | T055, T093, T097, T109, T115, T202, T209, T276, T651, T653, T655, T683 |
| AC-75 | T049, T111, T202, T209, T651, T653, T655, T843, T845, T847, T849, T851, T853, T855, T865, T867, T869, T871, T872, T873 |
| AC-76 | T111, T113, T115, T117, T119, T202, T209, T229, T651, T653, T655, T843, T845, T847, T849, T851, T853, T855, T865, T867, T869, T871, T872, T873, T963, T969 |
| AC-77 | T113, T115, T117, T119, T202, T209, T651, T653, T655 |
| AC-78 | T019, T021, T025, T027, T127, T135, T153, T155, T157, T202, T204, T215, T217, T224, T235, T237, T239, T240, T241, T242, T247, T249, T251, T263, T264, T269, T271, T272, T273, T323, T598, T601, T602, T603, T604, T628, T630, T632, T633, T681, T777, T781, T783, T795, T813, T965, T977 |
| AC-79 | T023, T025, T041, T045, T051, T101, T127, T129, T131, T133, T135, T137, T141, T143, T145, T147, T149, T151, T153, T155, T202, T204, T210, T222, T224, T226, T239, T240, T241, T242, T271, T282, T305, T307, T315, T323, T329, T337, T350, T353, T355, T357, T362, T366, T369, T371, T382, T384, T392, T394, T395, T397, T399, T401, T403, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511, T513, T515, T517, T519, T521, T523, T525, T526, T527, T528, T529, T534, T535, T536, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T582, T584, T586, T588, T590, T591, T592, T593, T595, T596, T597, T598, T601, T602, T604, T628, T630, T632, T633, T744, T746, T747, T749, T795, T813 |
| AC-80 | T019, T023, T027, T153, T157, T161, T169, T173, T202, T203, T204, T211, T215, T217, T228, T235, T239, T240, T241, T242, T249, T251, T263, T264, T269, T271, T272, T323, T681, T693, T716, T795, T965, T967, T975, T977 |
| AC-81 | T019, T021, T023, T027, T135, T153, T157, T202, T203, T204, T211, T215, T217, T224, T228, T235, T237, T239, T240, T241, T242, T247, T249, T251, T263, T264, T269, T271, T272, T323, T598, T602, T603, T604, T628, T630, T632, T633, T681, T965, T975, T977 |
| AC-82 | T019, T025, T041, T051, T127, T129, T131, T133, T135, T137, T141, T143, T145, T147, T149, T151, T155, T202, T204, T210, T222, T226, T239, T240, T241, T242, T601, T744, T746, T747, T749 |
| AC-83 | T021, T023, T025, T027, T041, T045, T051, T101, T127, T129, T131, T133, T135, T137, T141, T143, T145, T147, T149, T151, T153, T155, T157, T196, T202, T204, T210, T215, T217, T222, T224, T226, T235, T237, T239, T240, T241, T242, T247, T249, T251, T263, T264, T269, T272, T273, T282, T315, T323, T329, T350, T353, T355, T357, T362, T366, T369, T371, T382, T384, T392, T394, T395, T397, T399, T401, T403, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511, T513, T515, T517, T519, T521, T523, T525, T526, T527, T528, T529, T534, T535, T536, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T582, T584, T586, T588, T590, T591, T592, T593, T595, T596, T597, T598, T601, T602, T603, T604, T628, T630, T632, T633, T681, T744, T746, T747, T749, T930, T939, T941, T943, T945, T947, T949, T951, T953, T955, T957, T959, T961, T963, T965, T967, T969, T971, T973, T975, T977, T979 |
| AC-84 | T081, T095, T109, T121, T202, T204, T220, T265, T626, T646, T648, T722 |
| AC-85 | T075, T157, T159, T161, T173, T202, T203, T211, T651, T653, T655, T681, T688, T693, T716, T760, T762, T769, T771, T772, T777, T779, T781, T783, T795, T799, T807, T809, T811, T823, T825, T827, T829, T831, T833, T835, T837, T857, T859, T861, T863, T875, T877, T879, T893, T945, T947, T953, T955, T957, T963, T965, T967, T969, T973, T975 |
| AC-86 | T061, T063, T065, T067, T073, T075, T097, T149, T202, T208, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T591, T592, T593, T596, T608, T610, T612, T614, T616, T618, T620, T622, T624, T636, T638, T640, T642, T644, T660, T662, T677, T733, T735, T737, T741, T744, T746, T747, T766, T775, T785, T787, T789, T791, T801, T803, T805, T807, T809, T811, T823, T825, T827, T829, T939, T941, T959, T961 |
| AC-87 | T013, T015, T029, T031, T033, T035, T039, T043, T045, T047, T053, T055, T057, T079, T091, T093, T095, T097, T109, T139, T167, T202, T209, T253, T256, T274, T276, T279, T284, T286, T290, T298, T300, T303, T305, T307, T309, T311, T315, T317, T325, T326, T329, T331, T334, T337, T346, T350, T353, T359, T371, T373, T380, T386, T392, T394, T395, T397, T399, T401, T403, T406, T408, T409, T411, T413, T415, T417, T419, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511, T513, T515, T517, T519, T521, T523, T525, T526, T527, T528, T529, T530, T532, T534, T535, T536, T537, T539, T541, T543, T545, T546, T548, T550, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T683, T693, T695, T697, T703, T706, T710, T712, T716, T718, T720, T722, T725, T727, T729, T732, T733, T735, T737, T741, T743, T744, T746, T747, T749, T750, T752, T754, T756, T885, T891, T893, T895, T924, T926 |
| AC-88 | T013, T015, T031, T033, T035, T037, T039, T043, T045, T047, T049, T053, T055, T057, T091, T093, T109, T167, T202, T209, T253, T256, T257, T274, T279, T284, T286, T290, T296, T298, T300, T303, T305, T307, T309, T311, T317, T325, T326, T331, T334, T337, T367, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T513, T515, T517, T519, T521, T523, T525, T526, T527, T528, T529, T530, T532, T534, T535, T536, T537, T539, T541, T543, T546, T548, T550, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T693, T703, T710, T712, T716, T885, T891, T895, T924, T926 |
| AC-89 | T013, T015, T017, T029, T033, T039, T047, T055, T093, T103, T111, T159, T167, T169, T171, T173, T202, T203, T209, T211, T228, T229, T253, T256, T257, T274, T276, T279, T281, T284, T286, T288, T290, T294, T300, T303, T309, T311, T317, T319, T321, T334, T337, T346, T348, T353, T362, T364, T371, T373, T375, T378, T380, T386, T392, T394, T395, T397, T399, T401, T403, T406, T408, T409, T411, T413, T415, T417, T419, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511, T513, T515, T517, T519, T521, T523, T525, T526, T527, T528, T529, T530, T532, T537, T539, T541, T543, T545, T546, T548, T550, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T582, T584, T586, T588, T590, T591, T592, T593, T595, T596, T597, T651, T653, T655, T693, T703, T710, T712, T716, T843, T845, T847, T849, T851, T853, T855, T865, T867, T869, T871, T872, T873, T885, T891, T893, T895, T957 |
| AC-90 | T017, T103, T109, T117, T119, T171, T202, T209, T229, T257, T279 |
| AC-91 | T015, T017, T037, T039, T041, T045, T049, T053, T103, T109, T117, T129, T139, T141, T167, T202, T209, T253, T256, T257, T274, T279, T281, T282, T288, T294, T297, T309, T315, T321, T326, T329, T331, T346, T353, T355, T357, T359, T364, T366, T367, T369, T375, T378, T380, T382, T384, T392, T394, T395, T397, T399, T401, T403, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T513, T515, T517, T519, T521, T523, T525, T526, T527, T528, T529, T530, T532, T534, T535, T536, T575, T595, T957 |
| AC-92 | T015, T037, T039, T045, T049, T053, T109, T117, T202, T209, T257, T279, T281, T294, T315, T329, T331, T364, T375, T380, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T541, T543, T546, T548, T550, T553, T555, T557, T559, T560, T561, T563, T565, T567, T569, T570, T571, T572, T573, T574, T575, T577, T578, T579, T580, T581, T582, T584, T586, T588, T590, T591, T592, T593, T595, T596, T597, T957 |
| AC-93 | T017, T159, T161, T167, T169, T173, T202, T203, T209, T211, T288, T378, T688, T693, T703, T710, T712, T716, T760, T762, T769, T771, T772, T777, T779, T781, T783, T799, T807, T809, T811, T823, T825, T827, T829, T831, T833, T835, T837, T857, T859, T861, T863, T875, T877, T879, T891, T893, T895 |
| AC-94 | T085, T103, T105, T107, T202, T206, T209, T584, T595, T955, T963, T969 |

## 追加与偏差记录

任务编号保持稳定，新增入口以末尾追加任务并登记依赖/Owner/测试；禁止通过扩大旧卡写入范围掩盖遗漏。实现状态以本轮实施记录为准。

## 2026-11-05 实施记录

- T001：文档checkpoint `0b80802ae`；fetch远端发版线 `9eef0016de`，合并为 `a1b1a2387`。release-contract冲突逐块保留F004/F118；主工作区不变、无远端推送。
- T002：P1/R1/R2/R3/B1/B2/J1/A1已在 [contracts.md](./contracts.md) 冻结；三个独立源码审阅产物由INT合并。T006持久位置修正与T214–T221补充先于对应消费者。
- 基线验证：Python3.11.13、`test/permission/test_f048_action_catalog_policy.py` 5 passed；Alembic唯一head `v310b1_f004_workflow_soft_delete`。测试复用主工作区已存在venv与只读配置路径，PYTHONPATH指向功能源码；未修改配置或锁文件。
- 测试结果按任务交付追加；单元/双库/中间件/E2E/迁移/部署分别记录，不以本地静态或mock替代后者。

### W0/W1集成进度（2026-11-05）

- W0主agent已合流REF/PERM/PROC基础结构，T009–T012含DDL/账本/tenant注册/错误基础。T228结构验证、T229→T230 HTTP状态已红绿闭合；三语13错误键检查通过。
- T220→T221管理写scope已红绿闭合：4失败8通过→12通过；普通space文件写/v2凭证边界保持。
- T233→T234合法空分隔符回归已合流；T059→T060默认优先级与事务CAS已合流；默认设置18项通过；合流引用核心后108项、再合流job存储后126项通过，属于各时点同一套测试的规模，不累计重复次数。
- T013–T018与T253–T258 REF已由PROC固定快照独立复核并主agent合流（64490b9bb），包括Owner真实调用、receipt来源与deleting同步写围栏；真实Coverage账本适配仍由INT/MIG做，未提供adapter不能假ready。
- PERM原三项接缝T247–T252、Port T259及正常startup T269/T270已由REF/PROC分阶段独立复核；T263/T264/T271/T272适配真实当前fixture，T273修正基线已坏的Skill注入断言。逻辑交付c970545d3已合流4932d120de；根T270格式跟进9300b557c无语义变化。
- T061/T062 job_repo已由REF固定ff2672e983独立复核，主agent合流e93ecfb6a；T064须等PERM依赖通过。收据通用审计字段T260已补齐。
- 根模型/错误文件既有ruff告警24/2条已与冻结基线逐项比对，无新增；其余本轮新文件ruff通过。真实MySQL/DM8/OpenFGA、中间件/E2E/迁移及部署未执行，不标作通过。

### 本轮集成出口

- 主agent在合流4932d120de运行三线组合：24个pytest路径，含完整F118目录与权限/API/Worker定向回归，**424 passed**，无skip/fail；日志`/private/tmp/f118-integrated-tests.log`，路径与受测SHA见同名json。不是CI、中间件或端到端证明。
- 80个改动Python文件arch-guard无违规；78文件ruff通过，2个旧文件与基线逐项比对新增诊断0。全提交`git diff --check ed03fd07de..HEAD`与工作区diff-check通过；三语检查通过，Alembic单头f118_knowledge_unification。
- 新增代码与修正均在功能分支本地提交；未推送、未部署、未执行迁移。完成86/273为任务级状态，不等于94条产品AC完成。
- 下一波从六类来源提取/Owner事务适配、PROC应用用例与KN删除协调的已满足依赖卡进入。具体路由、真实Owner/覆盖adapter、两端页面和正式迁移脚本仍待实施；覆盖未ready不得放行删除保护。

## W2业务接线启动（2026-11-05）

从9cbb0141de创建独立WF/AS/TARGET lane，延续已冻结F118基线，不中途拼入其他工作区正在变化的发版线。主工作区本轮初始ac65c2fc5且干净，保持不变。INT统一write runtime/evidence/生产composition，两个业务Owner独立接线；目标Owner前置单独开发，不把测试fake接生产。

T034/T044新Repository/提取器路径按C1纠正，既有DAO不新增入口。实际查明的首次v0、根删除、Agent共用执行与Info失效关联出口补T282–T299，启动登记时为299项（本波后续追加至342项）；不是需求AC变更。R2准备先锁targets再业务root，完整旧/新集合CAS后保存+绑定一次commit；自增新leaf首次flush只为真实ID，现有root再锁后状态不符仍整笔回滚。部署前仍需全部来源回填/覆盖，不以无index自动bootstrap旧资源。


## W2集成出口（2026-11-05）

本波实际写入口、投影回滚、可见性增量及完整root引用盘点已交叉复核并由INT合流；含T337/T338自动租户过滤L1修正。完成166/342项（较W1新增80项完成），94条spec AC不变。主agent受测提交411d4f461473，35个pytest路径821 passed；静态/任务元数据/HTML完整性见[W2集成复查](./wave2-implementation-review.md)。W1的424项是历史验证，不相加。

任务卡标题已将已完成WF current/发布、AS发布与尚未接线的完整运行分开；T282/T302仅明确模型ID不回退，T283共用运行保持未完成。T281、T307初轮即绿，不伪造红阶段；T308仅核对既有正确行为。T328交接真实enqueue和共享读取scope，后续先冻结合同再实施。未推送、部署或执行迁移，真实双库/FGA/队列/检索/E2E及CI均未运行。


## W3运行准入启动（2026-11-05）

从d52825f9e延续功能基线；主工作区ac65c2fc5干净，未合入其并发变化。三agent先只读审计并交叉复核[运行/共享来源合同V1](./execution-read-contract.md)，root修正目标/legacy各入口identity、targets后root重验及canonical JSON/完整graph投影。新增T343–T391，原T041/T042/T283/T294/T295补真实依赖与叶子；不是需求AC变更。

W3基础交付：T346原ModuleNotFound红→T344 DTO 8绿；T348原ModuleNotFound红→T345访问口2绿，组合10通过。T343/352合同、唯一Owner/DAG和343–391叶子登记完成；T349/351为无业务IO的身份getter/Protocol接口，经结构/架构核验。实际Reader、身份fingerprint和SourceOwner尚未装配，不宣称运行准入已上线。


## W3集成出口（2026-11-05）

先冻结[执行/读取合同](./execution-read-contract.md)，WF/AS/REF独立lane并行，INT统一common、原身份与实际API/worker装配；后续评测与原R2 clone加固按显式交接独占叶子。固定SHA交叉复核后主agent合流。T041/T042/T283/T294/T295及T343–T421除T404/T405外完成，当前248/421项，本波较W2新增82项完成；签发ACL与其他未完成业务不勾选。

受测源码0c2587dbe5ec93135e06a45ed7615253a6a46ef1，1199 passed、6 subtests passed（46个pytest路径），无fail/skip；Ruff/格式70文件通过，架构新增违规0且既有6条RULE-1/2条RULE-3已单列。红绿、等价fixture、任务级L1及限制见[W3集成记录](./wave3-implementation-review.md)。W1/W2验证为历史快照，不累计。主工作区保持原ac65c2fc5；无push/部署/迁移，真实双库/FGA/队列/检索/模型/浏览器E2E和CI均未运行。


## W4剩余来源启动（2026-11-06）

基线24481f0ca，421卡248done。三agent只读审计APP/CH/LLM，INT核KN；实际UUID、默认五keys、无tenant同步子表、原principal及真实自动化身份、原生sync和混合root锁序均先在[W4合同](./business-sources-contract.md)冻结。旧T029/T030、T047–T058保编号并按实际叶子补依赖，新增卡承接拆出的文件；不删spec AC，不将旧审批/删除/处理/UI/迁移等前置整体标完成。


## W4集成出口（2026-11-06）

接口合同先冻结，APP/CH/LLM独立lane，CH冻结后显式交KN；最后worker独占三叶再交空闲agent。INT持续负责公共接缝、精确提交合流、任务级L1、静态及组合验证。原T029/T030和T047–T058与T422–T597全部按实际交付完成，当前**438/597项**，较W3新增190项；原94AC/140QA保持，159项其他特性工作未勾选，不把本波任务数当作产品全验收。

主agent受测源码d4d02e48b7d724c9ffe31d9650b75951eeb94e14，81个pytest路径**2390 passed、6 subtests passed**，无fail/skip。170个改动Python文件format通过；Ruff新增0、55条既有诊断逐项/必要时AST比较，架构新增违规0。全部红绿、等价旧测试/退役契约差异、独立review SHA、完整路径及环境限制见[W4集成复查](./wave4-implementation-review.md)。

四类实际剩余来源、RAG/worker和最终provider检查已接线；修复APP业务类型扩张、单租户C3与文件/QA清理漏口，GET不再制造退休三参消息。正式Coverage/回填、完整R3/Processing/页面、分享签发ACL、真实环境与全特性验收仍按159项未完成卡推进。未push/迁移/部署，主工作区原ac65c2fc5保持。

## 剩余任务范围复核收口（2026-11-06）

依据用户决定，T404/T405 移至独立文档，未实施、未计为完成，退出当前任务依赖与 AC 自动覆盖索引；当前待办157项。T135/T136/T193 明确保留发布/分享及其他动作，QA/SDK-MCP/知识任务/type2/迁移CLI等歧义按 [scope-review.md](./scope-review.md) 收紧。原其余157项逐条核对，未再发现需要整项外移的独立需求；本轮未勾选任何代码任务。历史交付报告不重写，当前设计/合同/升级/HTML/导航按新边界同步。

## W5合同冻结启动

从abb8dc822延续范围基线，先三agent只读核接口；本波选EDGE/PERM/API共20项原卡，新增T598–T603六个既有需求接缝叶子。合同冻结后同checkpoint建独立lane，INT负责前端DTO接缝及合流验证。处理任务T063–T076尚缺真实前置，本波不建fake服务或局部改worker。历史157待办是范围复核时点，当前新增叶子和进度以本节及后续交付为准。无push/迁移/部署。

## W5消费面集成出口（2026-11-06）

先冻结d832ac594接口与文件Owner，再由EDGE/PERM/API独立树并行实施，INT负责前端接缝、逐卡L1、固定SHA交叉复查及合流。原157队列完成20项，另7个已确认需求接缝叶子T598–T604全部完成；当前465已完成/历史交付、137待办、2外移（历史604编号、范围内602卡），未新增产品要求。PROC/worker等真实前置不齐卡保持未勾选，T404/T405仍独立待办。

受测干净源码34fcbd7fec1809e5d4dc0513e7c2420f4489f6bc：100路径2852 passed、15 subtests passed；34个变更Python文件Ruff/format与架构违规0，diff-check通过。前端目标6例全绿、全frontend lint通过；平台typecheck22条既有诊断与独立冻结基线相同。扩大APP query/前端回归各25/7个旧失败与同选集基线完全一致，新增失败0，不掩盖这些未绿范围。完整红绿、固定交付/复查、任务级范围和限制见[W5集成记录](./wave5-implementation-review.md)。未运行CI/真实双库及中间件/E2E/迁移/部署，未push。

## W6滚动集成出口（2026-11-06）

已合入两端API/纯可见交互验证、KN创建/有界清单与重建冲突gate、原凭据/Owner/J1、实际文件处理和重建worker、原调用方适配、迁移台账/持久artifact/原始来源盘点及线性权限计划。原137卡完成22项，当前总待办121（原115+新6），详见[W6记录](./wave6-implementation-review.md)。T111/T112的完整来源展示/公开删除、其他kind、上传/移动/删除、正式转换/Coverage、页面及E2E仍未完成；不以helper或部分API代替整特性。

用户免除本轮DM8实测；保C2 Model/Repository/DDL静态，真实事务和升级演练用独立MySQL。109:3005撤回后保持不动，新环境仅标准旧基线与私网mock，为后续迁移准备样本，不代表F118已部署/迁移。
