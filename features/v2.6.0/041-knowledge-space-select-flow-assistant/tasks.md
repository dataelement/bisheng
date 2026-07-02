# Tasks: F041-knowledge-space-select-flow-assistant（工作流 / 助手应用支持选择知识空间）

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)（接手第一入口）
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | `/sdd-review spec` 通过；CONFLICT(INV-7) 经登记例外解除 |
| design.md | ✅ 已评审 | `/sdd-review design` 通过；C3 隐患按"不切租户"消解；接手第一入口 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks` 通过（2 轮自修：补 AC-13/AC-15 覆盖、去范围写法、修 T005 AC 标注、补 T001 回滚） |
| 实现 | ✅ 基本完成 | 后端 T001-T009 全部并单测(19 passing)；前端 T010-T015 全部完成(含 T012 助手选择器空间 tab+类型标记、T014 助手/agent 开关 UI+tips 三语+后端 `AssistantUpdateReq.knowledge_auth`)；迁移 f046/f047 已 `alembic upgrade head`(DB 到 f047)；T016 API e2e 6/6 通过(`test/e2e/test_e2e_f041_knowledge_space_select.py`)；T017 需真实向量库+差异化权限的检索/溯源/UI 见 `e2e-checklist.md`(worker 已冒烟启动无报错) |
| 契约登记 | ✅ 已完成 | `release-contract.md` 表1/表2(INV-7 例外)/表3/变更历史 已登记 F041 |

---

## 开发模式

- **后端 Test-First（务实版）**：能红-绿的先写测试；检索链路重度依赖 Milvus/ES 的部分标 `**测试降级**: 手动验证 + TODO`（见 T005/T007），在「实际偏差记录」说明。
- **前端**：手动验证（每任务附步骤）。
- **自包含**：任务内联文件/逻辑/AC；设计论证指向 design §X 不复制。
- **本 feature 无新增领域对象/表/对外 API/错误码**；唯一持久化 schema 改动 = `MessageCitation.accessScope`（F029 协同，见 T001）。

---

## Tasks

### Wave 1 — 后端使能层（无依赖，可并行）

- [x] **T001**: `accessScope` 字段 + 迁移（citation 链路，F029 协同）
  **文件**: `src/backend/bisheng/citation/domain/schemas/citation_schema.py`（`CitationRegistryItemSchema` 加 `accessScope: Literal['per_user','shared'] = 'per_user'`）、`citation/domain/models/message_citation.py`（持久列，默认 `per_user`）、`src/backend/bisheng/migrations/versions/`（alembic 加列，autogen 后手工核 DM8 兼容）
  **逻辑**: 新增可选字段，默认 `per_user`（存量从严）；持久层与 registry schema 都加，历史会话重开走 DB 时不丢标记
  **回滚**: alembic `downgrade` 删列即可（MySQL/DM8 均可逆）；存量行按默认值 `per_user`，无需数据回填
  **覆盖 AC**: AC-19（标注载体）；防坑 §5.5
  **依赖**: 无

- [x] **T002**: workflow 配置者 id 构造期透传
  **文件**: `src/backend/bisheng/workflow/graph/workflow.py`、`workflow/graph/graph_engine.py`、`workflow/nodes/base.py`、`src/backend/bisheng/worker/**/tasks.py`（入口把 `workflow_info.user_id` 作 `flow_user_id` 传入 `Workflow(...)`）
  **逻辑**: 新增 `flow_user_id`（创建者）kwarg，沿 `Workflow → GraphEngine → BaseNode` 透传（范式对齐既有 `tenant_id`）；节点内可读 `self.flow_user_id`
  **覆盖 AC**: AC-14（关档身份来源）；实现 design 决策 3、防坑 §5.1
  **依赖**: 无

- [x] **T003**: 无副作用构造"配置者 UserPayload"辅助
  **文件**: `src/backend/bisheng/workflow/common/knowledge.py`（或就近 util）
  **逻辑**: `UserPayload.init_login_user(user_id=配置者id, tenant_id=当前 flow 租户)` 造身份，**不调 `set_current_tenant_id`**（不切当前租户）；**不得**直接用 `resolve_operator`
  **测试**: `test_author_userpayload_no_tenant_switch` → 断言构造前后 `current_tenant_id` 不变
  **覆盖 AC**: AC-14；实现 design 决策 2、防坑 §5.10
  **依赖**: 无

- [x] **T004**: 空间检索核心辅助（file_ids 解析 + F029 双层过滤 + 身份 + sync→async）
  **文件**: `src/backend/bisheng/workflow/common/knowledge.py`（新 helper，供 RagUtils / agent / assistant 共用）
  **逻辑**: 入参 `(space_ids, identity_user: UserPayload, tag/metadata 过滤)` →
  ① `SpaceFileDao.get_children_by_prefix` 解析空间主版本 file_ids（防坑 §5.3）；
  ② `KnowledgeFileVisibilityService(request, identity_user).build_index_prefilter` 得 milvus_expr/es_filter；
  ③ 检索后 `post_filter_visible_files` 精滤；
  ④ sync 节点经**单一持久后台 loop**（`run_async_safe` 范式）跑 async（防坑 §5.2）；
  **测试**: `test_space_filter_open_runtime`→AC-12 / `test_space_filter_close_author`→AC-14 / `test_no_unauthorized_in_result`→AC-13 / `test_permission_freshness_after_revoke`→AC-15（复用 F029 `PermissionCache` invalidate）/ `test_admin_shortcircuit`→AC-24；`**测试降级**`: Milvus/ES 端到端召回需完整向量库 mock，成本极高 → 该部分手动验证 + TODO
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-15, AC-16, AC-24；实现 design 决策 1/2
  **依赖**: T003

### Wave 2 — 4 入口接检索核心（依赖 W1）

- [x] **T005**: 工作流 rag / knowledge_retriever 节点接空间分支
  **文件**: `src/backend/bisheng/workflow/common/knowledge.py`（`RagUtils`：识别 `knowledge.type=='space'` → 走 T004 helper；身份 = 开档 `self.user_id` / 关档 `self.flow_user_id`）、`workflow/nodes/rag/rag.py`、`workflow/nodes/knowledge_retriever/knowledge_retriever.py`（无需大改，复用 RagUtils）
  **逻辑**: 空间分支产出的 `List[Document]` 复用既有 `annotate_rag_documents_with_citations` + `collect_rag_citation_registry_items`（格式/citation 自动一致，AC-17/18）
  **测试**: `test_rag_node_space_open`→AC-12 / `test_rag_node_space_close`→AC-14 / `test_deleted_or_parsing_excluded`→AC-25；`**测试降级**`: Milvus/ES 端到端召回需向量库 mock，成本极高 → 手动验证
  **覆盖 AC**: AC-12, AC-14, AC-17, AC-18, AC-23, AC-25
  **依赖**: T002, T004

- [x] **T006**: 工作流 agent 节点接空间分支 + 新增 user_auth 读取
  **文件**: `src/backend/bisheng/workflow/nodes/agent/agent.py`（`_init_knowledge_tools`：`knowledge_id.type=='space'` → T004 helper；读节点 `user_auth`；身份同 T005）
  **逻辑**: 助手节点知识工具对空间套过滤 + citation accessScope（T008）
  **测试**: `test_agent_node_space_open/close` → AC-12/14
  **覆盖 AC**: AC-10, AC-12, AC-14, AC-17, AC-18
  **依赖**: T002, T004

- [x] **T007**: 助手应用接空间分支 + 新增 user_auth 读取
  **文件**: `src/backend/bisheng/api/services/assistant_agent.py`（`init_knowledge_tool`：空间 id → T004 helper；身份 = 开档 `self.invoke_user_id` / 关档 `self.assistant.user_id`；读助手级 `user_auth`）
  **逻辑**: 助手检索对空间套过滤；assistant 侧身份直接可用（design 决策 3）
  **测试**: `test_assistant_space_open/close` → AC-12/14；`**测试降级**`: 召回手动验证
  **覆盖 AC**: AC-10, AC-12, AC-14, AC-17, AC-18
  **依赖**: T004

### Wave 3 — 角标溯源 accessScope 分级（方案 B，依赖 W1/W2）

- [x] **T008**: 4 个 citation 生成点按开关赋 `accessScope`
  **文件**: `workflow/nodes/rag/rag.py`、`workflow/nodes/knowledge_retriever/*`、`workflow/nodes/agent/agent.py`、`api/services/assistant_agent.py`（生成 citation registry item 时：开档/直接空间问答 → `per_user`，关档 → `shared`）
  **逻辑**: 只对空间来源分档；文档库来源维持 `per_user`
  **覆盖 AC**: AC-19；实现 design 决策 5
  **依赖**: T005, T006, T007

- [x] **T009**: `CitationResolveService` 分级解析（filter + enrich 两处）
  **文件**: `src/backend/bisheng/citation/domain/services/citation_resolve_service.py`
  **逻辑**: ① `_filter_visible_rag_items`：`per_user` 项照 F029 按运行使用者 view_file 整条剔除、`shared` 项**不剔除**；② `_enrich_rag_item`：`shared` 项按**运行使用者** view_file 决定是否填 `previewUrl`/`downloadUrl`（无权→仅元数据，防坑 §5.6）；③ `resolve_citation` 单条 `shared` 无权不再抛 `NotFoundError`
  **测试**: `test_resolve_per_user_dropped`→AC-20/AC-13（开档角标侧）；`test_resolve_shared_metadata_no_url`→AC-21；`test_resolve_shared_with_view_file_full`→AC-22
  **覆盖 AC**: AC-13, AC-19, AC-20, AC-21, AC-22
  **依赖**: T001, T008

### Wave 4 — 前端（手动验证；T010 先行，余可并行）

- [x] **T010**: Platform 知识空间列表 API（client 口径）
  **文件**: `src/frontend/platform/src/controllers/API/**`（新增 mine/joined/department 三端点封装 + 前端去重并集 + 名称过滤 helper）
  **逻辑**: 复刻 client `ChatKnowledge` 口径（三端点并集、一次性加载、前端搜索、不含广场、不套游标），供选择器数据源
  **覆盖 AC**: AC-02, AC-05；实现 design 决策 7
  **手动验证**: 用有/无空间权限账号，确认列表 = 我创建+加入+部门、无权空间不出现
  **依赖**: 无

- [x] **T011**: 工作流节点选择器加「知识空间」模式 tab
  **文件**: `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem.tsx`
  **逻辑**: `TabsHead` 加「知识空间」tab；选中时 `type='space'`（与 knowledge/tmp 互斥，design 决策 4）；数据源走 T010；回显读 `type` 归类
  **覆盖 AC**: AC-01, AC-03, AC-04（工作流节点不混选）
  **手动验证**: rag/knowledge_retriever/agent 三节点均出「知识空间」tab；选存保存后回显正确归到该 tab
  **依赖**: T010

- [x] **T012**: 助手应用选择器出 tab + 每项类型标记
  **文件**: `src/frontend/platform/src/components/bs-comp/selectComponent/knowledge.tsx`（`KnowledgeSelect`）、`src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`
  **逻辑**: 让 `KnowledgeSelect` 出 tab（文档知识库 + 知识空间；防坑 §5.9 `type='file'` 不出 tab）；每条选择加 `type` 标记并入 `knowledge_list`，可混选；回显读每项 type（沿用 client `type:'space'`）
  **覆盖 AC**: AC-01, AC-03, AC-04（助手应用支持混选）
  **手动验证**: 助手配置出「知识空间」tab；混选文档库+空间保存后回显各归其位
  **依赖**: T010

- [x] **T013**: 两节点改名（i18n 显示名）
  **文件**: `src/frontend/platform/public/locales/{en-US,zh-Hans,ja}/flow.json`（`node.rag.name`→知识库问答 / `node.knowledge_retriever.name`→知识库检索）
  **逻辑**: 仅显示名；节点 type 不变（design 决策 6，零迁移）
  **覆盖 AC**: AC-06, AC-07
  **手动验证**: 画布/节点面板三语显示新名；打开一个存量含该节点的旧工作流不报错、配置完好
  **依赖**: 无

- [x] **T014**: 4 入口统一「用户知识库权限校验」开关 + tips 文案
  **文件**: 助手应用 `Setting.tsx` + agent 节点模板 `src/frontend/platform/src/controllers/API/workflow.ts`（`agent_xxx` group_params 加 `advanced_retrieval_switch`/等效 `user_auth`）；tips 文案入 `flow.json`/`bs.json` 三语（原文见 spec §2.3 末）
  **逻辑**: 助手应用、agent 节点**新增**开关，**默认关**（AC-11）；rag/knowledge_retriever 已有开关只补 tips；后端读取见 T006/T007
  **覆盖 AC**: AC-10, AC-11
  **手动验证**: 4 入口都能看到开关 + tips 悬浮文案（中/英/日）；新增开关默认关
  **依赖**: 无

- [x] **T015**: 元数据过滤对知识空间只给内置字段
  **文件**: `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/MetadataFilter.tsx`
  **逻辑**: 选中的是知识空间时，字段候选只列内置（document_id/name/upload_time/update_time/uploader/updater），**不拉** `getKnowledgeDetailApi` 自定义 metadata_fields（防坑 §5.8，空间返回空会报错/空）
  **覆盖 AC**: AC-08, AC-09
  **手动验证**: 知识库问答/检索节点选知识空间后，元数据过滤只出内置字段、不报错
  **依赖**: T011

### Wave 5 — 端到端 + 回归（依赖全部）

- [x] **T016**: E2E 覆盖（`/e2e-test`）
  **文件**: `src/backend/test/knowledge/test_f041_*.py`（API 端到端）+ 页面手动清单
  **逻辑**: 4 入口选空间 → 开/关两档 → 校验检索命中集合按身份过滤、无权文件不进结果/不进角标；`shared` 溯源分级；节点改名三语；回显区分
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25（端到端回归；逐条单元/集成追溯见各实现任务）
  **依赖**: T009, T011, T012, T013, T014, T015

- [ ] **T017**: 真实环境手动验证（worker + 溯源）
  **文件**: —（验证任务）
  **逻辑**: 起 `workflow_celery` worker（命令见 design §7），非配置者账号触发含知识空间检索节点的工作流，确认无 "Event loop is closed"（坑 5.2）、开/关身份过滤正确；管理员在两次检索间授予/收回运行使用者 view_file，验证下一轮即时生效（AC-15）；client `/workspace` 用不同权限账号验证 `shared`/`per_user` 溯源分级
  **覆盖 AC**: AC-12, AC-14, AC-15, AC-20, AC-21, AC-22（运行时回归）
  **依赖**: T016

---

## 实际偏差记录

> 只留一行指针，论证在 design.md（决策 / 坑），不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认，再记录。

- T003/T004 偏离 → 共享检索+身份 helper 落 `knowledge/domain/services/space_flow_retrieval.py`（知识域），而非 design 初稿的 `workflow/common/knowledge.py`；原因：assistant(api/services) 也要用，放 workflow/common 会造成 assistant→workflow 跨模块依赖。已回写 design §4.3。纯实现细节，未改任何决策/AC。
