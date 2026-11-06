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
| 实现 | W0/W1、W2及W3运行准入已合流，完整特性仍在开发 | 296 / 574 项；W4来源合同先冻结、按依赖实施中；独立复查/组合测试见[W3记录](./wave3-implementation-review.md)，未运行迁移 |

## 领取与执行规则

每卡最多 2 个写入文件，目标约 30 分钟；已有文件增量过大先拆卡。文件显示“拟新增”表示实现计划，未声称已有行为。任务直接追溯 spec AC，不依赖 QA 用例表；设计论证见 design，接口论证见 parallel-development。基础定义排在业务之前；后端配对测试先红后绿，最终集成测试按真实环境执行。

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

- [ ] **T029 · 应用声明名称到真实目标合同：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_resolve.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：同名歧义拒绝，唯一名称解析与运行一致；历史 manifest 不修改；无法解析旧目标不得猜 ID 标为存量失效；冻结后名称重新指向另一ID时运行/预览失败，不调用未绑定目标。\
  **依赖**：T016, T026, T258, T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T030 · 应用声明名称到真实目标合同**
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

- [ ] **T047 · 不可变应用版本插入同事务：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_snapshot.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：绑定错误版本行不落盘；历史管理预览版本保护；新版本只修新配置，旧绑定继续存在。\
  **依赖**：T439, T443, T512, T018, T258\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T048 · 不可变应用版本插入同事务**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/version_service.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：_insert_version 建立 app/version 引用集合并同事务提交；新版本/复制/导入应用新配置拒绝非法目标；历史保存版本均计引用，不按 terminal/current 过滤，不改写 AppVersion 内容。\
  **依赖**：T047\
  **配对测试**：T047\
  **验证 / 完成条件**：运行配对测试 T047；验证本卡预期，相关范围检查通过。

- [ ] **T049 · 应用删除解除与历史预览失效：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_lifecycle.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：停止不解除，真正删除才解除；旧历史引用失效可见，预览失败不fallback，不因评测结果拦删除。\
  **依赖**：T048, T441\
  **覆盖 AC**: AC-71, AC-75, AC-88, AC-91, AC-92\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T050 · 应用删除解除与历史预览失效**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_runtime/domain/services/app_state_service.py`；`src/backend/bisheng/app_publish/domain/services/preview_instance_service.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：沿现有应用删除生命周期解除被真正删除来源；停止应用不解除。预览/重新启用保留不可变历史并检测失效；不新增历史编辑/退役。\
  **依赖**：T049, T540\
  **配对测试**：T049\
  **验证 / 完成条件**：运行配对测试 T049；验证本卡预期，相关范围检查通过。

- [ ] **T051 · 应用能力执行可见准入：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_entry.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：仅可见主体可调用但超 capability/scope 拒绝；旧 manifest 不要求重新发布。\
  **依赖**：T050, T445, T026\
  **覆盖 AC**: AC-35, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T052 · 应用能力执行可见准入**
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

- [ ] **T055 · 租户/Root 默认槽位绑定：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_defaults.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：五类业务默认全部覆盖；共享模型跨租户有真实原始来源，替换只改本槽；绑定失败不保存默认。\
  **依赖**：T018, T258, T467\
  **覆盖 AC**: AC-71, AC-74, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T056 · 租户/Root 默认槽位绑定**
  **类型 / Owner**：后端 Domain / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default.py`；`src/backend/bisheng/llm/domain/services/llm.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：覆盖 knowledge/assistant/workflow/evaluation/workbench 默认保存，原始 Root 槽位及租户 override 同事务；继承消费者不复制绑定，不把评测任务当来源。暂不接删除服务逻辑。\
  **依赖**：T055\
  **配对测试**：T055\
  **验证 / 完成条件**：运行配对测试 T055；验证本卡预期，相关范围检查通过。

- [ ] **T057 · 恢复默认继承入口：先写测试**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_inherit.py`\
  **逻辑 / 测试上下文**：W4按真实入口核对；拆出额外叶子见新卡，不扩大旧卡：恢复继承不删 Root/其他租户默认；默认与绑定故障同回滚。\
  **依赖**：T056\
  **覆盖 AC**: AC-71, AC-87, AC-88\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T058 · 恢复默认继承入口**
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

- [ ] **T063 · 任务接收与恢复应用用例：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_job_service.py`（拟新增）\
  **逻辑 / 测试上下文**：提交不报完成；故障可恢复且不重复；无合法配置/已删模型明确失败，不回退历史参数。\
  **依赖**：T062, T026, T243, T244\
  **覆盖 AC**: AC-34, AC-49, AC-50, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T064 · 任务接收与恢复应用用例**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/processing_job_service.py`（拟新增）\
  **逻辑 / 测试上下文**：accepted 后通过既有投递模式可恢复派发，不创建任务模型引用；任务详情按最新文件可见性裁剪，隐藏内容只数状态；模型从所属当前业务读，校验相关 revision/generation。\
  **依赖**：T063\
  **配对测试**：T063\
  **验证 / 完成条件**：运行配对测试 T063；验证本卡预期，相关范围检查通过。

- [ ] **T065 · 重建全量分页保留源分段：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_rebuild_page.py`（拟新增）\
  **逻辑 / 测试上下文**：10001+ Chunk 数量及内容一致，失败源仍在；另一空间不阻塞；tenant headers 缺失拒绝，重试只失败项且配置过期拒绝。\
  **依赖**：T064\
  **覆盖 AC**: AC-48, AC-49, AC-52, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T066 · 重建全量分页保留源分段**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/rebuild_knowledge_worker.py`\
  **逻辑 / 测试上下文**：复用现有 Chunk/metadata，分页超过 10000；失败保留 ES 重试源、只切成功文件检索，不重切分/丢人工修改。tenant_id 从 Celery headers 注入 ContextVar，使用业务模型配置。\
  **依赖**：T065\
  **配对测试**：T065\
  **验证 / 完成条件**：运行配对测试 T065；验证本卡预期，相关范围检查通过。

- [ ] **T067 · 文件处理实际快照与恢复：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_worker.py`（拟新增）\
  **逻辑 / 测试上下文**：指定版本重处理只改其内容；异常结果真实，重投不重复版本；陈旧任务新步骤拒绝，无配置不能用历史模型。\
  **依赖**：T066\
  **覆盖 AC**: AC-10, AC-43, AC-44, AC-45, AC-49, AC-53, AC-54, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T068 · 文件处理实际快照与恢复**
  **类型 / Owner**：Worker / PROC\
  **写入文件**：`src/backend/bisheng/worker/knowledge/file_worker.py`；`src/backend/bisheng/knowledge/rag/knowledge_file_pipeline.py`\
  **逻辑 / 测试上下文**：接入 J1 分类型实际配置/文件版本快照与任务项结果；领取及可控步骤重验相关模型/索引，SQL finalize 核 generation/lease；不加外部在途 I/O 围栏。tenant_id headers→ContextVar，不存 bearer。\
  **依赖**：T067\
  **配对测试**：T067\
  **验证 / 完成条件**：运行配对测试 T067；验证本卡预期，相关范围检查通过。

- [ ] **T069 · 旧 FileProcessBase 与专用规则适配：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_file_process_adapter.py`（拟新增）\
  **逻辑 / 测试上下文**：旧文档/表格/网页/音视频请求回归，优先级与类型参数不串用。\
  **依赖**：T068\
  **覆盖 AC**: AC-39, AC-40, AC-43, AC-44, AC-66\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T070 · 旧 FileProcessBase 与专用规则适配**
  **类型 / Owner**：后端 API / PROC\
  **写入文件**：`src/backend/bisheng/api/v1/schemas.py`\
  **逻辑 / 测试上下文**：保持旧上传请求与 FileProcessBase 字段兼容，将实际显式值传 J1 解析，不新增不支持参数；不把单次配置污染默认，提交语义不报 completed。\
  **依赖**：T069\
  **配对测试**：T069\
  **验证 / 完成条件**：运行配对测试 T069；验证本卡预期，相关范围检查通过。

- [ ] **T071 · 元数据结构任务：先写测试**
  **类型 / Owner**：测试 / PROC\
  **写入文件**：`src/backend/test/knowledge_unification/test_metadata_job.py`（拟新增）\
  **逻辑 / 测试上下文**：新增空值、取消零改动；rename/drop 错误不报成功，指定 version 值更新结果正确且不可见详情裁剪。\
  **依赖**：T064\
  **覆盖 AC**: AC-33, AC-34, AC-47, AC-49, AC-50, AC-53, AC-54\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T072 · 元数据结构任务**
  **类型 / Owner**：后端 Domain / PROC\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/metadata_processing_service.py`（拟新增）\
  **逻辑 / 测试上下文**：新增字段历史为空，rename/drop 冻结前后 schema 与范围且二次确认，SQL/索引实际结果计 item，不用 accepted 冒充完成；仍原容器 edit，失败可恢复。\
  **依赖**：T071\
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

- [ ] **T077 · 资源访问生命周期与动作映射：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_auth.py`（拟新增）\
  **逻辑 / 测试上下文**：继承/自定义同有效动作；only rename 能重命名而不能容器 edit；重建可下载目录，写入和检索暂停；未发布可合法处理。\
  **依赖**：T026, T064\
  **覆盖 AC**: AC-08, AC-30, AC-31, AC-32, AC-33, AC-51, AC-60\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T078 · 资源访问生命周期与动作映射**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_permission_service.py`\
  **逻辑 / 测试上下文**：将处理态与可访问生命周期分离；重建仍目录/预览/下载，写入冲突单独控制；有效权限统一解析继承/自定义，rename 原动作，Chunk/metadata原容器 edit，原文件 retry 原rename，不加文件 edit/额外可见 gate。\
  **依赖**：T077\
  **配对测试**：T077\
  **验证 / 完成条件**：运行配对测试 T077；验证本卡预期，相关范围检查通过。

- [ ] **T079 · 统一空间创建：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_creation.py`（拟新增）\
  **逻辑 / 测试上下文**：两端默认相同，后台显式配置生效；无权模型及绑定失败不创建残留空间。\
  **依赖**：T078, T018, T060, T258\
  **覆盖 AC**: AC-06, AC-07, AC-14, AC-15, AC-87\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T080 · 统一空间创建**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：前台只简化业务项沿当前默认，后台可信入口可选模型和分类型默认；同R2保存模型槽，审批/安全/格式/配额沿已有用例。\
  **依赖**：T079\
  **配对测试**：T079\
  **验证 / 完成条件**：运行配对测试 T079；验证本卡预期，相关范围检查通过。

- [ ] **T081 · 管理员具体租户清单与操作上下文：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_create.py`（拟新增）\
  **逻辑 / 测试上下文**：菜单不等于资源权限；空tenant/汇总拒绝，直接请求普通/admin矩阵；管理业务校验不跳。\
  **依赖**：T080\
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-25, AC-84\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T082 · 管理员具体租户清单与操作上下文**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：admin仅超管/相应租管、一次具体tenant，超管默认所属可切，租管仅所属；普通列表不借admin扩大，owner/dept不准入。copy保创建者限制。\
  **依赖**：T081, T080\
  **配对测试**：T081\
  **验证 / 完成条件**：运行配对测试 T081；验证本卡预期，相关范围检查通过。

- [ ] **T083 · 后台文件上传与整版本注册：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_upload.py`（拟新增）\
  **逻辑 / 测试上下文**：同文件前后端版本路径一致，保留历史；格式/审批/配额失败无残留版本；相似文档按现有开关选择保留/新版本。\
  **依赖**：T082, T070\
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-11, AC-14, AC-43\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T084 · 后台文件上传与整版本注册**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`\
  **逻辑 / 测试上下文**：后台调用同目录/文件夹/网页/新版本用例，沿既有审批、内容安全、格式/大小/深度/重名/配额与开关；统一 document/version 关系，只有成功主版本检索；J1 实际配置委托。\
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
  **写入文件**：`src/backend/test/knowledge_unification/test_qa_bindings.py`（拟新增）\
  **逻辑 / 测试上下文**：同步/异步创建QA都有零集或真实模型绑定，失败整事务回滚；clear不解除模型、delete才解除；不把QA转换SPACE。\
  **依赖**：T092, T018, T258\
  **覆盖 AC**: AC-55, AC-65, AC-70, AC-71, AC-74, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T094 · QA 创建删除清空的模型槽位**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：QA type1保持独立入口与原业务；create_knowledge/create_knowledge_base/acreate_knowledge_base和delete_knowledge使用R2维护当前模型槽，删除QA解除出向模型绑定，clear保留；模型修改接既有processing切换规则。\
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
  **依赖**：T058, T104\
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

- [ ] **T127 · 工具/Skill 使用准入切换：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_tool.py`（拟新增）\
  **逻辑 / 测试上下文**：每类工具/Skill可见无use可调用，无可见/无scope/停用仍拒绝；活动动作响应无use。\
  **依赖**：T026\
  **覆盖 AC**: AC-78, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T128 · 工具/Skill 使用准入切换**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/tool/domain/services/f048_tool_permission.py`；`src/backend/bisheng/linsight/domain/services/f048_skill_permission.py`\
  **逻辑 / 测试上下文**：各资源system/custom原独立use检查改visible，保tenant/身份/scope/可执行状态，不给额外动作；调用现有统一 PermissionService，历史保存协议只兼容解释。\
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
  **依赖**：T132\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-69, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T134 · SDK/MCP 协议端回归**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/dev_toolkit/sdk_compat.py`；`src/backend/bisheng/open_mcp/compatibility.py`\
  **逻辑 / 测试上下文**：适配 SDK/MCP 旧 type/ID/固定 use 字段为统一空间/可见性语义，保持原请求响应与错误，旧发布不重写；调用统一业务服务，保身份白名单。T001清单逐入口核对，剩余叶子先拆补充任务，未闭合不能完成。\
  **依赖**：T133\
  **配对测试**：T133\
  **验证 / 完成条件**：运行配对测试 T133；验证本卡预期，相关范围检查通过。

- [ ] **T135 · 应用可见资格与能力 DTO：先写测试**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_visibility.py`（拟新增）\
  **逻辑 / 测试上下文**：可见无use可发布/调用但缺其他动作不越权；Source变化复查，旧协议只解释不保存。\
  **依赖**：T052, T026\
  **覆盖 AC**: AC-78, AC-79, AC-81, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T136 · 应用可见资格与能力 DTO**
  **类型 / Owner**：后端 Domain / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/app_publish_current_visibility_service.py`；`src/backend/bisheng/app_runtime/domain/schemas/app_authorization.py`\
  **逻辑 / 测试上下文**：应用当前发布资格/owner与来源复查改visible，活动能力DTO不形成独立use；保生命周期、capability范围和Source一致性。\
  **依赖**：T135\
  **配对测试**：T135\
  **验证 / 完成条件**：运行配对测试 T135；验证本卡预期，相关范围检查通过。

- [ ] **T137 · 助手 HTTP 动作默认与选择器：先写测试**
  **类型 / Owner**：测试 / AS\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_http.py`（拟新增）\
  **逻辑 / 测试上下文**：旧query默认/显式use按visible；失效助手失败，隐藏知识不暴露；无菜单机器凭证按原scope。\
  **依赖**：T046, T295\
  **覆盖 AC**: AC-37, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T138 · 助手 HTTP 动作默认与选择器**
  **类型 / Owner**：后端 API / AS\
  **写入文件**：`src/backend/bisheng/api/v1/assistant.py`\
  **逻辑 / 测试上下文**：列表/运行旧默认use解释visible，当前输出action不含use；委托AS统一服务，保scope/tenant/执行状态，不重写历史配置。\
  **依赖**：T137\
  **配对测试**：T137\
  **验证 / 完成条件**：运行配对测试 T137；验证本卡预期，相关范围检查通过。

- [ ] **T139 · 应用模型执行逐槽核对冻结ID：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_model_binding.py`（拟新增）\
  **逻辑 / 测试上下文**：版本绑定模型M1，之后同名解析为M2不能调用；模型删除失效明确失败，允许声明名不等于允许任意同名ID。\
  **依赖**：T136, T134\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-91\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T140 · 应用模型执行逐槽核对冻结ID**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/open_api/domain/services/model_range_policy.py`；`src/backend/bisheng/open_api/domain/services/model_gateway_service.py`\
  **逻辑 / 测试上下文**：消费 APP 版本SourceKey及冻结slot目标映射，保原名称协议但最终实际ID必须匹配该版本绑定；改名/同名解析漂移明确失败，不转用新模型。预览/运行共检查，历史manifest原文不改。\
  **依赖**：T139\
  **配对测试**：T139\
  **验证 / 完成条件**：运行配对测试 T139；验证本卡预期，相关范围检查通过。

- [ ] **T141 · 聊天准入与管理器：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_chat.py`（拟新增）\
  **逻辑 / 测试上下文**：可见无use可进入，缺scope/已删来源仍拒绝；历史会话快照不改写，不以对话记录建立引用。\
  **依赖**：T134\
  **覆盖 AC**: AC-35, AC-79, AC-82, AC-83, AC-91\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T142 · 聊天准入与管理器**
  **类型 / Owner**：后端 API / EDGE\
  **写入文件**：`src/backend/bisheng/api/v1/chat.py`；`src/backend/bisheng/common/chat/manager.py`\
  **逻辑 / 测试上下文**：原使用准入显式改visible并保持原actor/tenant/凭证、资源业务状态；失效配置明确错误，不能以兼容为由静默fallback。\
  **依赖**：T141\
  **配对测试**：T141\
  **验证 / 完成条件**：运行配对测试 T141；验证本卡预期，相关范围检查通过。

- [ ] **T143 · 工具枚举与实际执行：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_tool_call.py`（拟新增）\
  **逻辑 / 测试上下文**：列出与执行相同准入；可见无use可执行，disabled和无scope拒绝；剩余use调用方清单闭合。\
  **依赖**：T128\
  **覆盖 AC**: AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T144 · 工具枚举与实际执行**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/tool/domain/services/tool.py`；`src/backend/bisheng/tool/domain/services/executor.py`\
  **逻辑 / 测试上下文**：get_tool_list默认和executor执行统一visible，保preset/owner/tool enabled与既有运行条件，不因仅删use分支丢禁用校验。\
  **依赖**：T143\
  **配对测试**：T143\
  **验证 / 完成条件**：运行配对测试 T143；验证本卡预期，相关范围检查通过。

- [ ] **T145 · Skill 枚举与启用校验：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_skill.py`（拟新增）\
  **逻辑 / 测试上下文**：批量结果不漏仅可见，停用仍不可运行、无scope拒绝，tenant隔离。\
  **依赖**：T144\
  **覆盖 AC**: AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T146 · Skill 枚举与启用校验**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/linsight/domain/services/user_skills.py`；`src/backend/bisheng/linsight/domain/services/skill_permission.py`\
  **逻辑 / 测试上下文**：user_skills批量过滤及skill_permission原use分支转visible，同时独立保enabled等业务校验；不要因动作改名使disabled可执行。\
  **依赖**：T145\
  **配对测试**：T145\
  **验证 / 完成条件**：运行配对测试 T145；验证本卡预期，相关范围检查通过。

- [ ] **T147 · DSH 工具能力目录：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_dsh.py`（拟新增）\
  **逻辑 / 测试上下文**：能力枚举/工作执行一致，仅可见可用但缺scope/停用仍拒绝。\
  **依赖**：T146\
  **覆盖 AC**: AC-35, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T148 · DSH 工具能力目录**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/dsh/domain/services/capability_catalog.py`；`src/backend/bisheng/dsh/domain/services/work_capabilities.py`\
  **逻辑 / 测试上下文**：明确tool list准入visible，保原DSH身份上下文、声明范围、内容安全/配额/状态；旧工具绑定不改写。\
  **依赖**：T147\
  **配对测试**：T147\
  **验证 / 完成条件**：运行配对测试 T147；验证本卡预期，相关范围检查通过。

- [ ] **T149 · 开放 task mode 领取与提交准入：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_taskmode.py`（拟新增）\
  **逻辑 / 测试上下文**：提交与执行两阶段同可见语义；missing模型配置明确失败，队列参数不复活旧模型；scope/跨tenant拒绝。\
  **依赖**：T148\
  **覆盖 AC**: AC-35, AC-68, AC-79, AC-82, AC-83, AC-86\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T150 · 开放 task mode 领取与提交准入**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/open_api/domain/services/task_mode_service.py`\
  **逻辑 / 测试上下文**：提交知识来源批量action和任务执行阶段均按visible，仍读业务资源模型/索引配置和旧ID；保凭证、业务状态，任务不绑定模型。\
  **依赖**：T149\
  **配对测试**：T149\
  **验证 / 完成条件**：运行配对测试 T149；验证本卡预期，相关范围检查通过。

- [ ] **T151 · 工作台及开放工作流入口：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_edge_apps_rpc.py`（拟新增）\
  **逻辑 / 测试上下文**：实际旧调用default/explicit use都兼容；无scope/业务停止等原限制保持。\
  **依赖**：T150, T042\
  **覆盖 AC**: AC-35, AC-66, AC-68, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T152 · 工作台及开放工作流入口**
  **类型 / Owner**：后端 API / EDGE\
  **写入文件**：`src/backend/bisheng/workstation/api/endpoints/apps.py`；`src/backend/bisheng/open_endpoints/api/endpoints/workflow.py`\
  **逻辑 / 测试上下文**：HTTP委托统一visible使用准入，保原路由及请求/错误格式；历史应用/工作流发布与knowledge类型照常解释，无权内容不返回。\
  **依赖**：T151\
  **配对测试**：T151\
  **验证 / 完成条件**：运行配对测试 T151；验证本卡预期，相关范围检查通过。

- [ ] **T153 · 系统应用与租户分享纯可见：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_perm_shared.py`（拟新增）\
  **逻辑 / 测试上下文**：工作流/助手/tool/library系统分享无use，原范围不扩；撤来源不删他源，QA与文档映射正确。\
  **依赖**：T026\
  **覆盖 AC**: AC-78, AC-79, AC-80, AC-81, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T154 · 系统应用与租户分享纯可见**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/api/services/f048_application_permission.py`；`src/backend/bisheng/tenant/domain/services/resource_share_service.py`\
  **逻辑 / 测试上下文**：系统应用动作集和tenant share标准集合移除use，保visible、原主体/Source及分享管理资格；合法纯可见仍可撤销，不改租户原共享边界。\
  **依赖**：T153\
  **配对测试**：T153\
  **验证 / 完成条件**：运行配对测试 T153；验证本卡预期，相关范围检查通过。

- [ ] **T155 · 频道只读准入集合：先写测试**
  **类型 / Owner**：测试 / CH\
  **写入文件**：`src/backend/test/knowledge_unification/test_ch_permission.py`（拟新增）\
  **逻辑 / 测试上下文**：普通只读频道可见可用、无编辑能力，tenant和停用状态按原业务执行。\
  **依赖**：T054, T026\
  **覆盖 AC**: AC-78, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T156 · 频道只读准入集合**
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
  **依赖**：T028, T120\
  **覆盖 AC**: AC-31, AC-56, AC-59, AC-63, AC-78, AC-80, AC-81, AC-83, AC-85\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T158 · 全平台权限停服子计划与校验**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/migration/f118_plan.py`（拟新增）；`src/backend/bisheng/permission/migration/f118_verify.py`（拟新增）\
  **逻辑 / 测试上下文**：仅停服后正式盘点原model/Grant/Source/visibility/non-use(含rename)/Catalog/checksum并并入同run/plan/hash；转换纯可见合同与投影，不用维护前快照；按冻结原基线列use预期差异及其他零差异。\
  **依赖**：T157\
  **配对测试**：T157\
  **验证 / 完成条件**：运行配对测试 T157；验证本卡预期，相关范围检查通过。

- [ ] **T159 · 停服 run/计划/检查点持久账本：先写测试**
  **类型 / Owner**：测试 / MIG\
  **写入文件**：`src/backend/test/knowledge_unification/test_migration_ledger.py`（拟新增）\
  **逻辑 / 测试上下文**：重复run同计划幂等；hash变化拒绝，M2前不能M3，转换中断沿原checkpoint，无停服检测参数。\
  **依赖**：T158, T011\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-85, AC-89, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T160 · 停服 run/计划/检查点持久账本**
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
  **依赖**：T162\
  **覆盖 AC**: AC-55, AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T164 · type/版本/标签转换与来源配额**
  **类型 / Owner**：后端 Domain / MIG\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/unification_conversion_service.py`（拟新增）\
  **逻辑 / 测试上下文**：按冻结计划 type0→3、type1保留/type2退休；保ID原对象/模型/索引，不解析重嵌；补首版本/标签去重，durable origin不额外文件用量，存量private迁移不清授权、不默认广场发布。\
  **依赖**：T163\
  **配对测试**：T163\
  **验证 / 完成条件**：运行配对测试 T163；验证本卡预期，相关范围检查通过。

- [ ] **T165 · 迁移空间配额显示与创建统一：先写测试**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_quota.py`（拟新增）\
  **逻辑 / 测试上下文**：换用户/重启后豁免仍在；tenant超限新增拒绝，文件存储不因转换翻倍，部门原限额有效。\
  **依赖**：T164\
  **覆盖 AC**: AC-14, AC-61, AC-62\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T166 · 迁移空间配额显示与创建统一**
  **类型 / Owner**：后端 Domain / KN\
  **写入文件**：`src/backend/bisheng/role/domain/services/quota_service.py`\
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
  **依赖**：T170\
  **覆盖 AC**: AC-56, AC-63, AC-64, AC-80, AC-85, AC-89, AC-93\
  **验证 / 完成条件**：以本卡样例构造 fixture，记录红阶段；不得在测试任务修改实现。

- [ ] **T174 · 停服升级入口/报告/恢复命令**
  **类型 / Owner**：后端 API / MIG\
  **写入文件**：`src/backend/scripts/unify_knowledge_spaces.py`（拟新增）\
  **逻辑 / 测试上下文**：只调盘点/预检/冻结/convert/backfill/verify及checkpoint resume，输出run/hash/范围/失效清单/差异；不探测端口/进程/Worker/停服标记，不启停/等待服务；失败不自动恢复业务。\
  **依赖**：T173\
  **配对测试**：T173\
  **验证 / 完成条件**：运行配对测试 T173；验证本卡预期，相关范围检查通过。

- [ ] **T175 · 平台 API 与合同 Mock**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/controllers/API/knowledgeSpace.ts`；`src/frontend/platform/src/controllers/hooks/knowledge.ts`\
  **逻辑 / 测试上下文**：按A1/J1/R3冻结 DTO封装普通/admin、settings、jobs、预检确认；react-query key带身份/租户/范围，Mock与真接口可替换；HTTP只在API层。\
  **依赖**：T002, T007, T003, T006\
  **验证 / 完成条件**：Mock序列化与合同一致；切租户/身份不复用缓存，平台类型检查；关联规格：AC-02, AC-03, AC-04, AC-05, AC-49, AC-50。

- [ ] **T176 · 平台入口/三页签与创建**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/index.tsx`；`src/frontend/platform/src/pages/KnowledgePage/detail.tsx`\
  **逻辑 / 测试上下文**：统一命名、QA独立；普通可见列表/admin仅超管租管具体租户；后台创建预选同默认可选模型/默认策略，前台跳转入口可解析ID。\
  **依赖**：T175\
  **验证 / 完成条件**：菜单与角色/租户切换、无权直链、QA入口；Zustand不直接HTTP；关联规格：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-16, AC-84。

- [ ] **T177 · 平台目录/上传/版本**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`\
  **逻辑 / 测试上下文**：复用空间树/文件夹上传/网页/预览下载rename版本，按相同开关相似文档/标签，按钮来自现有效动作，不新增fileedit。\
  **依赖**：T176\
  **验证 / 完成条件**：多层目录、新版本历史与主版本选择、rename-only行为；两端同数据人工验证；关联规格：AC-09, AC-10, AC-11, AC-14, AC-15, AC-30, AC-31。

- [ ] **T178 · 平台分类型策略草稿**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/pages/KnowledgePage/components/RuleFile.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/RuleTable.tsx`\
  **逻辑 / 测试上下文**：类型切换保各草稿，save/create成功才生效，取消/校验/服务器失败不改已保存默认；支持已有选项和范围，表格不套文档。\
  **依赖**：T177\
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

- [ ] **T187 · 客户端 API 与 Mock**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/api/knowledge.ts`；`src/frontend/client/src/pages/knowledge/SpaceDetail/knowledgeSpaceTypes.ts`\
  **逻辑 / 测试上下文**：A1/J1/R3前台简化状态/预检/任务DTO，React-query/Recoil保持，身份/租户key隔离；无后台高级配置。\
  **依赖**：T002, T007, T003, T006\
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

- [ ] **T192 · 平台通用授权纯可见模型**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/components/bs-comp/permission/PermissionGrantTab.tsx`；`src/frontend/platform/src/components/bs-comp/permission/PermissionListTab.tsx`\
  **逻辑 / 测试上下文**：当前动作不显示use；纯可见模型虽动作数组为空仍展示有效主体、原Source与可撤销能力，等级按服务端；普通非法空模型不允许授予。\
  **依赖**：T186, T022\
  **验证 / 完成条件**：所有资源权限弹窗use-only迁移授权可授予/列出/撤销，其他Source仍生效，file rename不被edit替代；关联规格：AC-78, AC-81, AC-83。

- [ ] **T193 · 平台全员与托管应用动作**
  **类型 / Owner**：前端 Platform / PLATFORM\
  **写入文件**：`src/frontend/platform/src/components/bs-comp/permission/AllMembersPermission.tsx`；`src/frontend/platform/src/pages/BuildPage/hostedApp/appActions.ts`\
  **逻辑 / 测试上下文**：全员纯可见和app操作能力按服务端visible解释，不再独立use；保护原管理等级和可撤销性，不凭可见显示edit/delete。\
  **依赖**：T192, T136\
  **验证 / 完成条件**：全员Source撤销/其他来源并集，app可见但无编辑动作按钮矩阵；历史审计文字不改写；关联规格：AC-78, AC-79, AC-81, AC-83。

- [ ] **T194 · 客户端通用授权展示**
  **类型 / Owner**：前端 Client / CLIENT\
  **写入文件**：`src/frontend/client/src/components/permission/PermissionListTab.tsx`；`src/frontend/client/src/components/permission/UnifiedPermissionControls.tsx`\
  **逻辑 / 测试上下文**：当前模型动作去use，合法纯可见主体及Source继续显示、管理和撤销；保既有管理能力/等级，继承模式统一解析。\
  **依赖**：T191, T022\
  **验证 / 完成条件**：仅use迁移后列表不消失、可撤单来源，其他来源仍有效；view不能edit/download/rename；关联规格：AC-30, AC-31, AC-78, AC-81, AC-83。

- [ ] **T195 · 客户端纯可见授予选择**
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

- [ ] **T202 · 双库事务/投影/并发回归执行**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_cross_domain_integration.py`（拟新增）\
  **逻辑 / 测试上下文**：按固定锁序覆盖保存vs普通/强删、服务清单原子性、同来源多版本CAS、FGA失败/SQL失败/清理失败分阶段恢复；执行MySQL及项目集中DM8回归，真实中间件证据分别记录。\
  **依赖**：T200, T201, T174\
  **覆盖 AC**: AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-70, AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-77, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84, AC-85, AC-86, AC-87, AC-88, AC-89, AC-90, AC-91, AC-92, AC-93, AC-94\
  **验证 / 完成条件**：不得以mock通过声称双库集成通过；未配置环境明确待执行，失败修复先补独立叶子任务。

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
- [ ] **T224 · 资源Owner系统动作白名单：先写测试**
  **类型 / Owner**：测试 / PERM\
  **写入文件**：`src/backend/test/knowledge_unification/test_permission_owner_actions.py`\
  **逻辑 / 测试上下文**：Owner管理受保护系统Source的白名单移除use，合法viewer纯可见识别；保protected/原管理等级及移交规则，不顺带赋予可见主体管理能力。；可见无use可用、无可见/无凭证scope拒绝，旧协议不形成独立授权。\
  **依赖**：T216, T218\
  **覆盖 AC**: AC-78, AC-79, AC-81, AC-83\
  **验证 / 完成条件**：先记录红阶段，不修改实现。

- [ ] **T225 · 资源Owner系统动作白名单**
  **类型 / Owner**：后端 Domain / PERM\
  **写入文件**：`src/backend/bisheng/permission/domain/services/owner_service.py`\
  **逻辑 / 测试上下文**：Owner管理受保护系统Source的白名单移除use，合法viewer纯可见识别；保protected/原管理等级及移交规则，不顺带赋予可见主体管理能力。\
  **依赖**：T224\
  **配对测试**：T224\
  **验证 / 完成条件**：配对测试转绿、相关既有回归及架构检查通过。
- [ ] **T226 · 工具HTTP旧动作参数适配：先写测试**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/knowledge_unification/test_tool_http_action.py`\
  **逻辑 / 测试上下文**：当前默认visible、保受支持旧use query按visible解释；经原服务鉴权，旧请求/返回结构维持，活动动作不输出use。；可见无use可用、无可见/无凭证scope拒绝，旧协议不形成独立授权。\
  **依赖**：T136\
  **覆盖 AC**: AC-35, AC-66, AC-79, AC-82, AC-83\
  **验证 / 完成条件**：先记录红阶段，不修改实现。

- [ ] **T227 · 工具HTTP旧动作参数适配**
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

- [ ] **T404 · 分享链接签发资源授权红测（独立待办）**
  **类型 / Owner**：测试 / EDGE\
  **写入文件**：`src/backend/test/share_link/test_source_link_issuance.py`\
  **逻辑 / 测试上下文**：已确认旧generate接口仅JWT并直接持久resource/meta，需独立验证share动作/真实会话归属与来源，不与本波ACTIVE查看兼容混称闭合。\
  **依赖**：T396\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91\
  **验证 / 完成条件**：保存实际红绿/固定SHA独立复核及主集成结果，真实环境验证单列，未完成发行前待办不得勾选。

- [ ] **T405 · 分享链接签发授权加固（发行前待办）**
  **类型 / Owner**：后端 Domain / EDGE\
  **写入文件**：`src/backend/bisheng/share_link/domain/services/share_link_service.py`；`src/backend/bisheng/share_link/domain/repositories/source_link_repository.py`\
  **逻辑 / 测试上下文**：待单独明确旧token信任/撤销兼容后落实，不能把生成端缺ACL转成新Root/任意Child源读取。本波不改变既有ACTIVE/expiry语义。\
  **依赖**：T404\
  **配对测试**：T404\
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

- [ ] **T436 · 应用版本与凭据事实外部事务红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T437 · 应用真实根版本和凭据Repository**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/repositories/reference_source_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T436\
  **配对测试**：T436\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T438 · APP同Session解析及完整名称计划红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_resolution.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T030, T437, T477, T520\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T439 · APP模型知识真实ID冻结解析**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_resolution.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T438\
  **配对测试**：T438\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T440 · 应用真实来源及原principal红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_source_owner.py`；`src/backend/test/knowledge_unification/test_app_read_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T439, T514, T516\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T441 · 应用来源Owner与原principal身份适配**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_source_owner.py`；`src/backend/bisheng/app_publish/application/reference_read_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T440\
  **配对测试**：T440\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T442 · APP专属实际authority装配红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_reference_composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T441, T377, T379\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T443 · APP只读显式access和生产装配**
  **类型 / Owner**：实现 / INT-APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_access.py`；`src/backend/bisheng/app_publish/composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T442\
  **配对测试**：T442\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T444 · APP能力总线完整来源准入红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_model_binding.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T443, T048\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T445 · APP能力总线按冻结版本准入**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T444, T544\
  **配对测试**：T444\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T446 · 实际provider实例化前冻结ID红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_gateway_binding.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T445\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T447 · 模型gateway与range最终ID核验**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/open_api/domain/services/model_gateway_service.py`；`src/backend/bisheng/open_api/domain/services/model_range_policy.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T446\
  **配对测试**：T446\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T448 · 托管知识调用透传原principal红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_filelib_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T445\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T449 · 托管知识入口原principal接线**
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

- [ ] **T464 · 真实五key默认模型槽红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T465 · 五key实际默认槽提取器**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/default_reference_extractor.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T464\
  **配对测试**：T464\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T466 · 默认own原始与真实继承SQL红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T465\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T467 · 默认模型外部事务Repository**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/model_default_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T466\
  **配对测试**：T466\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T468 · 默认原ambient及SourceOwner红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_source.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T467\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T469 · 默认模型双模式身份与Owner**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default_read_identity.py`；`src/backend/bisheng/llm/application/model_default_source_owner.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T468\
  **配对测试**：T468\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T470 · 原生同步真实Model目标红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_default_native_target.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T426, T432\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T471 · Model只读Owner原生同步适配**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/source_read_target_owner.py`；`src/backend/bisheng/llm/domain/repositories/source_read_target_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T470\
  **配对测试**：T470\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T472 · 默认全源严格双模式读取红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_read.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T469, T471, T428\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T473 · 默认原始与执行读取facade**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default_read.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T472\
  **配对测试**：T472\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T474 · 混合来源MODEL物理预锁红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_mixed_source_locks.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T435\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T475 · MODEL混合root纯物理预锁**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/reference_target_owner.py`；`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T474\
  **配对测试**：T474\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T476 · APP同Session完整名称计划红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T477 · LLM唯一uncached名称计划Port**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T476\
  **配对测试**：T476\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T478 · 默认实际消费不回退原ID红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_consumers.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T473, T056\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T479 · LLM默认管理与运行消费者接线**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/services/llm.py`；`src/backend/bisheng/llm/api/router.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T478, T058\
  **配对测试**：T478\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T480 · 工作台默认与空间模型全事务联动红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_workbench_reference_atomicity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T475, T489, T056\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T481 · 工作台默认统一知识业务联动**
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

- [ ] **T486 · 知识模型来源唯一写口红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_bindings.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T485, T435\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T487 · 知识模型来源创建变更应用用例**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T486, T538\
  **配对测试**：T486\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T488 · 完整空间清单及默认联动计划红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_workbench_model_batch.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T487, T475\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T489 · 知识空间完整清单批量模型计划**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T488\
  **配对测试**：T488\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T490 · 旧库QA空间创建同事务来源红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_creation.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T487\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T491 · 真实知识创建接入模型来源**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T490, T538\
  **配对测试**：T490\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T492 · 旧embedding更新及清空出向来源红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_mutation.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T491\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T493 · QA旧库embedding及删除来源接线**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`；`src/backend/bisheng/knowledge/api/endpoints/knowledge.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T492\
  **配对测试**：T492\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T494 · 空间模型出向删除及保频道失效红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_space_reference_lifecycle.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T493, T054\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T495 · 空间模型来源及移除自动清频道**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T494\
  **配对测试**：T494\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T496 · 知识完整模型双模式读取红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_source.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T487, T426, T471, T428\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T497 · Knowledge模型SourceOwner与身份**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/reference_source_owner.py`；`src/backend/bisheng/knowledge/application/reference_read_identity.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T496\
  **配对测试**：T496\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T498 · Knowledge模型执行读取facade**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference_read.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T497\
  **配对测试**：T496\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T499 · 实际RAG消费模型原配置准入红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_rag_model_admission.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T498\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T500 · 知识RAG原生模型来源准入**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/knowledge_rag.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T499\
  **配对测试**：T499\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T501 · 模型任务从业务配置及过期拒绝红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_worker_model_source.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T498, T493\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T502 · 旧重建worker读取业务模型并finalize**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/worker/knowledge/rebuild_knowledge_worker.py`；`src/backend/bisheng/worker/knowledge/qa.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T501\
  **配对测试**：T501\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T503 · API启动不得在线转换默认JSON红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_default_startup_migration_boundary.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T504 · 取消默认配置在线自动转换**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/main.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T503\
  **配对测试**：T503\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T505 · 四类来源真实生产装配红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_business_sources_composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T455, T498, T443, T473\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T506 · 完整来源API与worker实际装配**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/resource_reference/read_composition.py`；`src/backend/bisheng/resource_reference/composition.py`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T505\
  **配对测试**：T505\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T507 · W4真实来源合同和设计同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/business-sources-contract.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/design.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T506, T502, T481, T050, T052, T447, T449, T461, T463\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T508 · W4任务及并行交付同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/tasks.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/parallel-development.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T507\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T509 · W4升级及导航同步**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`features/v3.1.0-beta1/118-knowledge-space-unification/upgrade-guide.md`；`features/v3.1.0-beta1/118-knowledge-space-unification/README.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T508, T504\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T510 · W4 HTML与固定提交验证**
  **类型 / Owner**：文档 / INT\
  **写入文件**：`docs/architecture/review/2026-11-03-bisheng-knowledge-unification-technical-review.html`；`features/v3.1.0-beta1/118-knowledge-space-unification/wave4-implementation-review.md`\
  **逻辑 / 测试上下文**：按W4业务来源合同，原身份/tenant不切换，外部Session及完整来源；固定红绿/复核/集成，未运行真实环境不声称完成。\
  **依赖**：T509\
  **验证 / 完成条件**：实际红绿或无行为接口核验、固定提交独立复核及主集成；未做迁移/真实环境验收不得标通过。

- [ ] **T511 · 版本写原冻结凭据上下文红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_runtime_authorization_context.py`\
  **逻辑 / 测试上下文**：保既有真实credential_ref恢复语义，原yield身份贯穿外部事务；失效凭据拒，退出还原Context，不按owner ID造人。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-89\
  **验证 / 完成条件**：实际红绿、固定SHA复核及组合；不是HTTP权限令牌或新actor框架。

- [ ] **T512 · 导出原后台授权上下文薄Port**
  **类型 / Owner**：后端 Application / INT-APP\
  **写入文件**：`src/backend/bisheng/app_runtime/application/runtime_authorization.py`\
  **逻辑 / 测试上下文**：user_authorization_context(context,app,version_id)沿既有可信恢复manager；只导出不更改原授权/tenant/凭据规则。\
  **依赖**：T511\
  **配对测试**：T511\
  **验证 / 完成条件**：真实上下文/失败/恢复测试及APP固定SHA消费者复核。

- [ ] **T513 · 审批预览资格复用外部事务红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_review_transaction.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [ ] **T514 · 审批资格只读外部Session Port**
  **类型 / Owner**：实现 / INT-APP\
  **写入文件**：`src/backend/bisheng/approval/application/app_review.py`；`src/backend/bisheng/approval/domain/repositories/app_review_repository.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T513\
  **配对测试**：T513\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [ ] **T515 · 已加载应用原动作授权薄Port红测**
  **类型 / Owner**：测试 / INT-APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_loaded_authorization.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T422\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [ ] **T516 · 已加载应用授权只读导出**
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

- [ ] **T519 · 空名称计划原发行验证红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T477\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [ ] **T520 · 统一名称Plan当前验证方法**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`\
  **逻辑 / 测试上下文**：实际接线审计追加；复用原规则/权限，原Session及同一原identity；不扩审批流转或凭据权限。\
  **依赖**：T519\
  **配对测试**：T519\
  **验证 / 完成条件**：实际红绿、固定SHA交叉复核及主agent组合；不删原断言，不假称真实双库/FGA通过。

- [ ] **T521 · 冻结模型当前父事实及原actor指纹红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T520\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [ ] **T522 · 真实冻结模型父事实与原身份完整指纹**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T521\
  **配对测试**：T521\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [ ] **T523 · APP真实preview route事实红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_repository.py`\
  **逻辑 / 测试上下文**：W4真实入口审计追加；保同Session/原身份/原业务断言，不使用旧DAO或伪actor回退，production不装测试fake。\
  **依赖**：T437\
  **覆盖 AC**: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：实际红绿或旧fixture基线归因、固定SHA复核与最终组合，单叶测试不得删原行为断言。

- [ ] **T524 · APP当前preview route列投影**
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

- [ ] **T530 · 默认override不能以将消失的自身继承证明共享红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_default_override_sharing.py`\
  **逻辑 / 测试上下文**：源保存/删除的实际接缝；不猜ID/版本/共享，不放宽现有同root及tenant边界，真实SQL红绿。\
  **依赖**：T056\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89, AC-91\
  **验证 / 完成条件**：固定SHA独立复核及实际组合；不以当前配置保存前许可误当保存后仍可执行。

- [ ] **T531 · 默认来源前瞻共享资格排除自身key**
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

- [ ] **T539 · 已删应用仅当前销毁任务可读清理事实红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_deleted_runtime_cleanup.py`\
  **逻辑 / 测试上下文**：遵循W4冻结补充，唯一文件Owner，原身份和外部Session不变；真实生产接缝及反例验证，不以mock外部容器证明实机验收。\
  **依赖**：T533\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89\
  **验证 / 完成条件**：固定提交独立复核、实际定向回归及主集成；未运行真实环境不声称完成。

- [ ] **T540 · 持久销毁操作绑定的已删应用清理读取**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`；`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`\
  **逻辑 / 测试上下文**：遵循W4冻结补充，唯一文件Owner，原身份和外部Session不变；真实生产接缝及反例验证，不以mock外部容器证明实机验收。\
  **依赖**：T539\
  **配对测试**：T539\
  **验证 / 完成条件**：固定提交独立复核、实际定向回归及主集成；未运行真实环境不声称完成。

- [ ] **T541 · 冻结名称模型的原生别名不越槽红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T522\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [ ] **T542 · 同原NamePlan解析bare和qualified别名**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T541\
  **配对测试**：T541\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [ ] **T543 · APP来源Owner同实例最终绑定红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_model_binding.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T443, T542\
  **覆盖 AC**: AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [ ] **T544 · APP专属runtime显式来源Owner接缝**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/application/reference_access.py`；`src/backend/bisheng/app_publish/composition.py`\
  **逻辑 / 测试上下文**：严格原NamePlan/真实principal/外部Session，不扩声明或新锁；当前请求别名与原冻结语义槽及实际provider ID/server一致。\
  **依赖**：T543\
  **配对测试**：T543\
  **验证 / 完成条件**：真实红绿、固定提交独立复查和主集成；保原SDK别名/范围/头错误顺序，不调用真实provider。

- [ ] **T545 · 助手来源SQL用例独立注册真实租户表**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_source_owner.py`\
  **逻辑 / 测试上下文**：仅修复组合顺序造成的全局tenant表发现fixture残留，显式纳入本SQL场景实际Assistant/Link/ShareLink/Session表；不改产品源码、不Mock或弱化原跨租户拒绝断言。\
  **依赖**：T362\
  **覆盖 AC**: AC-71, AC-87, AC-89\
  **验证 / 完成条件**：固定a8d7cc28d全F118单路径1129pass/2fail的实际拒绝断言为红；原断言保留且整组合通过，生产AS/C3路径0diff。

- [ ] **T546 · API与worker原生共享读前明确READY红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_native_reference_bootstrap.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T432\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [ ] **T547 · Celery持久loop准备原生读取权限runtime**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/worker/main.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T546\
  **配对测试**：T546\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [ ] **T548 · 检索引擎保原身份进入资源模型准入红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_retrieval_engine_identity.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T498\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [ ] **T549 · 检索引擎透传既有完整login_user**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/retrieval_engine.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T548\
  **配对测试**：T548\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [ ] **T550 · 删除清理不依赖可执行模型红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_cleanup_model_independence.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T500\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [ ] **T551 · 持久文件删除清理走命名非模型构造**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_direct_delete_service.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T550\
  **配对测试**：T550\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [ ] **T552 · API启动显式准备原生共享读取权限**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/main.py`\
  **逻辑 / 测试上下文**：按真实已核启动/业务调用路径，显式权限READY或保留原身份/删除manifest；不在native getter懒桥async DB，不以FakeEmbeddings作为通用运行permit。\
  **依赖**：T546, T504\
  **配对测试**：T546\
  **验证 / 完成条件**：实际红绿、固定源码独立复核及组合通过，未运行真实middleware不称验收完成。

- [ ] **T553 · 清空删除资源模型出向绑定同事务红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_lifecycle_transaction.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T487\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T554 · 模型出向清空删除prepare及SQL原子应用**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T553\
  **配对测试**：T553\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T555 · 业务模型阶段finalize同事务红测**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge_unification/test_kn_model_finalize.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T554\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T556 · 业务模型阶段及来源索引一起finalize**
  **类型 / Owner**：实现 / KN\
  **写入文件**：`src/backend/bisheng/knowledge/application/model_reference.py`；`src/backend/bisheng/knowledge/domain/repositories/model_reference_repository.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T555\
  **配对测试**：T555\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T557 · 后台原始执行上下文来源证明红测**
  **类型 / Owner**：测试 / INT\
  **写入文件**：`src/backend/test/knowledge_unification/test_trusted_worker_context.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T422\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T558 · Celery实际header发行回收后台执行上下文**
  **类型 / Owner**：实现 / INT\
  **写入文件**：`src/backend/bisheng/core/context/background_execution.py`；`src/backend/bisheng/worker/tenant_context.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T557\
  **配对测试**：T557\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T559 · 知识创建旧补偿用例真实rollback适配**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_knowledge_create_atomicity.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T491\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T560 · 空间创建旧用例新事务接缝等价适配**
  **类型 / Owner**：测试 / KN\
  **写入文件**：`src/backend/test/knowledge/test_unified_permission_creation.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T495\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T561 · 默认来源缺可信tenant错误码红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_llm_default_source.py`；`src/backend/test/knowledge_unification/test_llm_defaults.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T469, T056\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T562 · 默认来源缺tenant按合同10996拒绝**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default_read_identity.py`；`src/backend/bisheng/llm/application/model_default.py`\
  **逻辑 / 测试上下文**：按已冻结真实业务接缝及唯一叶Owner实施；不伪造User/worker标记、不分事务补R2、不扩重建并发治理，不把fixture问题当业务红。\
  **依赖**：T561\
  **配对测试**：T561\
  **验证 / 完成条件**：固定提交独立复查、真实定向/组合回归，原行为断言保留；未跑真实环境不称验收。

- [ ] **T563 · 模型名称完整批次只读观察红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T542\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T564 · 名称逐项只读findings无执行authority**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`；`src/backend/bisheng/llm/domain/repositories/model_name_resolution_repository.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T563\
  **配对测试**：T563\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T565 · 名称Port缺tenant一致错误码红测**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_name_resolution.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T564\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T566 · 名称Port缺tenant按10996拒绝**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_name_resolution.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T565\
  **配对测试**：T565\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T567 · 已保存应用能力失效状态保行红测**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/knowledge_unification/test_app_saved_capabilities.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T445, T564\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T568 · 应用发布状态基于实际UUID引用inspect**
  **类型 / Owner**：实现 / APP\
  **写入文件**：`src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`；`src/backend/bisheng/app_publish/domain/services/publish_status_service.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T567\
  **配对测试**：T567\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T569 · 旧入口动作及legacy协议fixture适配**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_runtime/test_entry_authz_service.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T052\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T570 · 旧预览入口fixture明确legacy协议**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_runtime/test_preview_entry.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T052\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T571 · 旧模型知识能力测试真实来源适配**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/test_capability_model.py`；`src/backend/test/app_publish/test_capability_knowledge.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T574\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T572 · 旧撤销审计测试全source规则适配**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/test_capability_revoked.py`；`src/backend/test/app_publish/test_capability_audit.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T574\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T573 · 助手管理pin默认模型真实读取适配**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_as_management_scope.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T479, T473\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T574 · 旧应用测试显式来源SQL辅助fixture**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/reference_fixtures.py`\
  **逻辑 / 测试上下文**：按冻结观察/身份/真实来源合同实施；管理观察不授执行，失效保原ID逐行展示；旧fixture保原正反断言，运行时不自动造index，不以Mock替代事务证明。\
  **依赖**：T445\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：定向真实红绿/等价fixture、固定提交独立复查及主组合通过，不声称真实中间件验收。

- [ ] **T575 · 混合own模型批次的tenant辅助锁回归**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/knowledge_unification/test_model_mixed_source_locks.py`\
  **逻辑 / 测试上下文**：即使模型均为own，Tenant拓扑也须在KN业务root之前完成当前锁；无模型union仍调用目标Owner的辅助预锁。SQLite只检查实际SQL顺序，不证明双库锁竞争。\
  **依赖**：T475\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91, AC-92\
  **验证 / 完成条件**：真实红绿、固定提交复查及混合批次组合通过。

- [ ] **T576 · 模型mixed目标阶段锁定tenant拓扑**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/domain/repositories/reference_target_repository.py`\
  **逻辑 / 测试上下文**：按物理全局模型server/model→Tenant拓扑→KN/default业务root顺序；不把无关default JSON变成共享依赖，不改变逐来源收据。\
  **依赖**：T575\
  **配对测试**：T575\
  **验证 / 完成条件**：定向与主组合通过，真实MySQL/DM8竞争另验。

- [ ] **T577 · 旧启动能力环境夹具补真实身份和空来源**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_runtime/test_capability_env_injection.py`\
  **逻辑 / 测试上下文**：固定旧2a4基线同4失败，trace确认legacy capability_env provider已无生产调用方；仅测试改验实际RuntimeDeliveryCoordinator的事务stage、将运行版本derive scopes、平台/存储/应用身份环境、reserved覆盖及失败不保存sealed_env/不wake。旧env={}和provider callback契约明确退役，不能伪造旧调用通过，不改生产guard。\
  **依赖**：T445, T050\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：旧基线同失败集归因明确，新fixture独立复查及相同argv主组合通过。

- [ ] **T578 · 旧应用凭据测试明确legacy及Session隔离**
  **类型 / Owner**：测试 / APP\
  **写入文件**：`src/backend/test/app_publish/test_app_credential.py`\
  **逻辑 / 测试上下文**：固定旧2a4基线同21失败，显式legacy v1并注入实际preview异步及guard同步Session；保真实issuer/validate_bearer、prefix、撤销缓存、停用恢复与租户所有断言，不改生产代码。\
  **依赖**：T052\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：旧基线同失败集归因明确，新fixture独立复查及相同argv主组合通过。

- [ ] **T579 · 旧默认配置service回归迁移至真实读取门面**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_llm_system_config_service.py`\
  **逻辑 / 测试上下文**：旧测试直连已退役DAO/名称/signature的夹具迁移；保typed配置、管理envelope、调用tenant、局部更新和合法空models的原业务断言。裸tenant覆盖当前上下文及缺tenant回Root的旧口径与冻结合同冲突，明确改为当前tenant一致/10996拒绝并记录，不恢复生产fallback。\
  **依赖**：T479, T473\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：原失败与新合同差异有记录，固定提交复查及相同argv主组合通过，无生产代码改动。

- [ ] **T580 · 旧工作台局部更新回归迁移至同事务writer**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_workbench_update_merge.py`\
  **逻辑 / 测试上下文**：旧测试直连已退役DAO/名称/signature的夹具迁移；保typed配置、管理envelope、调用tenant、局部更新和合法空models的原业务断言。裸tenant覆盖当前上下文及缺tenant回Root的旧口径与冻结合同冲突，明确改为当前tenant一致/10996拒绝并记录，不恢复生产fallback。\
  **依赖**：T481\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：原失败与新合同差异有记录，固定提交复查及相同argv主组合通过，无生产代码改动。

- [ ] **T581 · 旧默认配置消费形状回归对齐冻结入口**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_llm_system_config_consumers.py`\
  **逻辑 / 测试上下文**：旧测试直连已退役DAO/名称/signature的夹具迁移；保typed配置、管理envelope、调用tenant、局部更新和合法空models的原业务断言。裸tenant覆盖当前上下文及缺tenant回Root的旧口径与冻结合同冲突，明确改为当前tenant一致/10996拒绝并记录，不恢复生产fallback。\
  **依赖**：T479\
  **覆盖 AC**: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92\
  **验证 / 完成条件**：原失败与新合同差异有记录，固定提交复查及相同argv主组合通过，无生产代码改动。

- [ ] **T582 · 非法工作台默认对话ID保原10811回归**
  **类型 / Owner**：测试 / LLM\
  **写入文件**：`src/backend/test/llm/test_workbench_update_merge.py`\
  **逻辑 / 测试上下文**：实际新writer在原Session接收非法chat_default_model_id，保原WorkbenchChatDefaultModelError10811业务断言，不将ValueError或10996改作测试预期；失败不得部分保存。\
  **依赖**：T481\
  **覆盖 AC**: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92\
  **验证 / 完成条件**：固定新实现实际红、窄修后绿及主组合通过。

- [ ] **T583 · 工作台默认对话ID规范化保原业务错误**
  **类型 / Owner**：实现 / LLM\
  **写入文件**：`src/backend/bisheng/llm/application/model_default.py`\
  **逻辑 / 测试上下文**：仅修_config非法chat默认ID规范化的异常包装，保原10811和cause，不改完整来源/身份/tenant/收据/批次/commit合同，不恢复退休DAO。\
  **依赖**：T582\
  **配对测试**：T582\
  **验证 / 完成条件**：红绿、固定提交独立复查及主组合通过。

## 自动化覆盖索引

以下仅映射 spec → 本任务清单的测试任务；不引用 QA 表生成开发任务。已完成项见各卡与实施记录；该映射不代表对应业务AC已完成端到端验收。

| AC | 测试任务 |
| --- | --- |
| AC-01 | T205 |
| AC-02 | T083, T121, T196, T205, T228 |
| AC-03 | T081, T121, T204 |
| AC-04 | T081, T121, T196, T204, T220, T265 |
| AC-05 | T081, T121, T196, T204, T220, T265 |
| AC-06 | T079, T121, T205 |
| AC-07 | T079, T121, T205 |
| AC-08 | T077, T101, T121, T204 |
| AC-09 | T083, T205 |
| AC-10 | T067, T083, T125, T205 |
| AC-11 | T083, T205 |
| AC-12 | T085, T105, T205 |
| AC-13 | T085, T105, T205 |
| AC-14 | T079, T083, T121, T165, T205 |
| AC-15 | T079, T121, T205 |
| AC-16 | T205 |
| AC-17 | T087, T089, T206 |
| AC-18 | T087, T089, T206 |
| AC-19 | T073, T091, T206 |
| AC-20 | T073, T091, T206 |
| AC-21 | T087, T091, T206 |
| AC-22 | T087, T089, T206 |
| AC-23 | T073, T091, T206 |
| AC-24 | T073, T089, T091, T206 |
| AC-25 | T081, T095, T206 |
| AC-26 | T095, T206 |
| AC-27 | T095, T206 |
| AC-28 | T103, T105, T109, T202, T206 |
| AC-29 | T103, T105, T107, T109, T202, T206 |
| AC-30 | T023, T077, T101, T202, T204, T239, T240, T241, T242, T251 |
| AC-31 | T023, T077, T085, T099, T157, T202, T204, T239, T240, T241, T242, T251 |
| AC-32 | T077, T121, T202, T204 |
| AC-33 | T071, T077, T097, T099, T123, T202, T204, T220 |
| AC-34 | T063, T071, T097, T123, T202, T204 |
| AC-35 | T025, T051, T101, T123, T129, T131, T133, T141, T147, T149, T151, T196, T202, T204, T210, T220, T222, T226, T229, T265 |
| AC-36 | T101, T202, T204, T222 |
| AC-37 | T029, T037, T041, T045, T101, T129, T137, T169, T202, T203, T204, T222, T281, T282, T297, T315, T321, T329, T355, T359, T364, T366, T367, T369, T375, T380, T382, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505 |
| AC-38 | T059, T123, T207 |
| AC-39 | T059, T069, T207, T233 |
| AC-40 | T059, T069, T207 |
| AC-41 | T207 |
| AC-42 | T059, T123, T207, T233 |
| AC-43 | T059, T067, T069, T083, T207, T233 |
| AC-44 | T059, T067, T069, T097, T207 |
| AC-45 | T067, T097, T099, T123, T207 |
| AC-46 | T099, T207 |
| AC-47 | T071, T099, T207 |
| AC-48 | T065, T097, T123, T207 |
| AC-49 | T061, T063, T065, T067, T071, T073, T075, T097, T123, T196, T208 |
| AC-50 | T061, T063, T071, T123, T208 |
| AC-51 | T077, T097, T208 |
| AC-52 | T065, T097, T208 |
| AC-53 | T061, T065, T067, T071, T097, T208 |
| AC-54 | T061, T063, T065, T067, T071, T073, T075, T097, T123, T208 |
| AC-55 | T093, T125, T161, T163, T203, T211, T228 |
| AC-56 | T157, T159, T161, T173, T203, T211 |
| AC-57 | T163, T203, T211, T228 |
| AC-58 | T163, T203, T211 |
| AC-59 | T023, T157, T163, T169, T203, T211, T228 |
| AC-60 | T077, T101, T163, T203, T211 |
| AC-61 | T163, T165, T203, T211 |
| AC-62 | T163, T165, T203, T211 |
| AC-63 | T157, T159, T161, T163, T173, T203, T211, T228 |
| AC-64 | T159, T161, T169, T173, T203, T211 |
| AC-65 | T093, T125, T196, T210, T228, T267 |
| AC-66 | T069, T125, T131, T133, T151, T196, T210, T222, T226, T228, T229, T233, T265, T267 |
| AC-67 | T101, T125, T131, T210, T228 |
| AC-68 | T029, T037, T039, T041, T045, T047, T051, T125, T129, T131, T133, T137, T139, T147, T149, T151, T210, T222, T267, T281, T282, T284, T286, T294, T296, T297, T298, T305, T307, T309, T317, T321, T325, T331, T334, T353, T357, T359, T362, T364, T366, T367, T369, T375, T380, T382, T384, T392, T394, T395, T397, T399, T401, T403, T404, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511 |
| AC-69 | T125, T133, T210 |
| AC-70 | T093, T111, T113, T115, T119, T202, T209 |
| AC-71 | T029, T031, T035, T037, T043, T045, T047, T049, T053, T055, T057, T093, T111, T139, T167, T202, T209, T276, T286, T319, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505 |
| AC-72 | T013, T103, T111, T113, T117, T119, T202, T209 |
| AC-73 | T111, T113, T115, T117, T119, T202, T209, T276, T319 |
| AC-74 | T055, T093, T097, T109, T115, T202, T209, T276 |
| AC-75 | T049, T111, T202, T209 |
| AC-76 | T111, T113, T115, T117, T119, T202, T209, T229 |
| AC-77 | T113, T115, T117, T119, T202, T209 |
| AC-78 | T019, T021, T025, T027, T127, T135, T153, T155, T157, T202, T204, T215, T217, T224, T235, T237, T239, T240, T241, T242, T247, T249, T251, T263, T264, T269, T271, T272, T273, T323 |
| AC-79 | T023, T025, T041, T045, T051, T101, T127, T129, T131, T133, T135, T137, T141, T143, T145, T147, T149, T151, T153, T155, T202, T204, T210, T222, T224, T226, T239, T240, T241, T242, T271, T282, T305, T307, T315, T323, T329, T337, T350, T353, T355, T357, T362, T366, T369, T371, T382, T384, T392, T394, T395, T397, T399, T401, T403, T404, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511 |
| AC-80 | T019, T023, T027, T153, T157, T161, T169, T173, T202, T203, T204, T211, T215, T217, T228, T235, T239, T240, T241, T242, T249, T251, T263, T264, T269, T271, T272, T323 |
| AC-81 | T019, T021, T023, T027, T135, T153, T157, T202, T203, T204, T211, T215, T217, T224, T228, T235, T237, T239, T240, T241, T242, T247, T249, T251, T263, T264, T269, T271, T272, T323 |
| AC-82 | T019, T025, T041, T051, T127, T129, T131, T133, T135, T137, T141, T143, T145, T147, T149, T151, T155, T202, T204, T210, T222, T226, T239, T240, T241, T242 |
| AC-83 | T021, T023, T025, T027, T041, T045, T051, T101, T127, T129, T131, T133, T135, T137, T141, T143, T145, T147, T149, T151, T153, T155, T157, T196, T202, T204, T210, T215, T217, T222, T224, T226, T235, T237, T239, T240, T241, T242, T247, T249, T251, T263, T264, T269, T272, T273, T282, T315, T323, T329, T350, T353, T355, T357, T362, T366, T369, T371, T382, T384, T392, T394, T395, T397, T399, T401, T403, T404, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511 |
| AC-84 | T081, T095, T109, T121, T202, T204, T220, T265 |
| AC-85 | T075, T157, T159, T161, T173, T202, T203, T211 |
| AC-86 | T061, T063, T065, T067, T073, T075, T097, T149, T202, T208, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505 |
| AC-87 | T013, T015, T029, T031, T033, T035, T039, T043, T045, T047, T053, T055, T057, T079, T091, T093, T095, T097, T109, T139, T167, T202, T209, T253, T256, T274, T276, T279, T284, T286, T290, T298, T300, T303, T305, T307, T309, T311, T315, T317, T325, T326, T329, T331, T334, T337, T346, T350, T353, T359, T371, T373, T380, T386, T392, T394, T395, T397, T399, T401, T403, T404, T406, T408, T409, T411, T413, T415, T417, T419, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511 |
| AC-88 | T013, T015, T031, T033, T035, T037, T039, T043, T045, T047, T049, T053, T055, T057, T091, T093, T109, T167, T202, T209, T253, T256, T257, T274, T279, T284, T286, T290, T296, T298, T300, T303, T305, T307, T309, T311, T317, T325, T326, T331, T334, T337, T367, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505 |
| AC-89 | T013, T015, T017, T029, T033, T039, T047, T055, T093, T103, T111, T159, T167, T169, T171, T173, T202, T203, T209, T211, T228, T229, T253, T256, T257, T274, T276, T279, T281, T284, T286, T288, T290, T294, T300, T303, T309, T311, T317, T319, T321, T334, T337, T346, T348, T353, T362, T364, T371, T373, T375, T378, T380, T386, T392, T394, T395, T397, T399, T401, T403, T404, T406, T408, T409, T411, T413, T415, T417, T419, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505, T511 |
| AC-90 | T017, T103, T109, T117, T119, T171, T202, T209, T229, T257, T279 |
| AC-91 | T015, T017, T037, T039, T041, T045, T049, T053, T103, T109, T117, T129, T139, T141, T167, T202, T209, T253, T256, T257, T274, T279, T281, T282, T288, T294, T297, T309, T315, T321, T326, T329, T331, T346, T353, T355, T357, T359, T364, T366, T367, T369, T375, T378, T380, T382, T384, T392, T394, T395, T397, T399, T401, T403, T404, T406, T408, T409, T411, T413, T415, T417, T419, T421, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505 |
| AC-92 | T015, T037, T039, T045, T049, T053, T109, T117, T202, T209, T257, T279, T281, T294, T315, T329, T331, T364, T375, T380, T424, T427, T429, T431, T433, T436, T438, T440, T442, T444, T446, T448, T450, T452, T454, T456, T458, T460, T462, T464, T466, T468, T470, T472, T474, T476, T478, T480, T482, T484, T486, T488, T490, T492, T494, T496, T499, T501, T503, T505 |
| AC-93 | T017, T159, T161, T167, T169, T173, T202, T203, T209, T211, T288, T378 |
| AC-94 | T085, T103, T105, T107, T202, T206, T209 |

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
