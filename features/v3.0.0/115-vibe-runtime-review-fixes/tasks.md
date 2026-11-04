# Tasks：F115 应用运行信息、审批当前可见范围与知识库创建

**关联**：[spec.md](./spec.md) · [design.md](./design.md)。版本 v3.0.0。

## 状态

|步骤|状态|备注|
|---|---|---|
|discovery|✅ 已确认|2026-11-02，D1–D4|
|spec.md|✅ 已评审|用户单独确认，52 条 AC|
|design.md|✅ 已评审|用户单独确认后进入任务与开发|
|tasks.md|✅ 已拆解|44 项，21 项清单自审，依赖和 AC 静态校验|
|实现|进行中|44 / 44 代码与本地验证任务完成；真实 E2E 尚未执行；只做本功能定向验证|
|真实 E2E|未执行|服务更新与写入未由本轮设计确认自动授权|

## 开发约束

按以下依赖顺序单代理实施；测试先于配对后端实现，测试任务只写测试。无新表/DDL，无 Worker 改动，无数据迁移；原创建补偿保持。共享文件只修改本功能触及段，不扩展复制或其它审批场景。技能与命名空间实际接线校验若发现仅文件路径差异，在此修正元数据并同步设计，不改变已确认业务边界。每个实现任务完成执行 task-review，最后按 sdd-code-review 对固定基线审查。真实 E2E 待明确环境授权后执行，不虚报通过。

## Tasks

### T001 · 基础设施

- [x] **T001**：Web 新建前置 DTO 与错误码

**文件**：`src/backend/bisheng/common/errcode/knowledge.py`；`src/backend/bisheng/knowledge/domain/schemas/knowledge_create_schema.py`。\
**逻辑/上下文**：定义未占用10993及仅Web使用的expected_tenant_id请求，原KnowledgeCreate不扩展目标租户。\
**依赖**：无。\

### T002 · 基础设施

- [x] **T002**：业务错误三语（中文、英文）

**文件**：`src/frontend/packages/locales/src/api_errors/zh-Hans.json`；`src/frontend/packages/locales/src/api_errors/en.json`。\
**逻辑/上下文**：增加10993所属租户已变化文案，不改已有错误码。\
**依赖**：T001。\

### T003 · 基础设施

- [x] **T003**：业务错误日文

**文件**：`src/frontend/packages/locales/src/api_errors/ja.json`。\
**逻辑/上下文**：增加10993日文；共享locale源为准。\
**依赖**：T001。\

### T044 · 基础设施

- [x] **T044**：E2E精确清理护栏

**文件**：`src/backend/test/e2e/helpers/cleanup.py`；`src/backend/test/knowledge/test_f115_e2e_cleanup.py`。\
**逻辑/上下文**：共享helper只清理e2e-f115精确名称且当前owner/tenant一致的库，跨租户/非测试名称先拒绝；无新增业务能力。\
**依赖**：无。\

### T004 · 测试

- [x] **T004**：v2运行观测配对测试

**文件**：`src/runtime-manager/tests/test_f115_observation.py`；`src/runtime-manager/tests/test_k8s_observe.py`。\
**逻辑/上下文**：精确绑定、HTTP事实、0/null、启动、停止、缺失和替换，mock只读平台/容器；拒绝写操作。\
**依赖**：无。\
**覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10

### T005 · 后端 Domain

- [x] **T005**：执行器观察事实

**文件**：`src/runtime-manager/runtime_manager/executors/docker.py`；`src/runtime-manager/runtime_manager/executors/kubernetes.py`。\
**逻辑/上下文**：observe添加nullable当前应用容器事实及probe_state，保留原生命周期ready规则，不混init/旧容器。\
**依赖**：T004。\

### T006 · 后端 API

- [x] **T006**：v2只读状态归一化

**文件**：`src/runtime-manager/runtime_manager/api/platform_observe.py`；`src/runtime-manager/runtime_manager/observation.py`。\
**逻辑/上下文**：统一观察字段及绑定前后校验；无绑定/执行体丢失分开，观测失败不可用；不回到v1。\
**依赖**：T005。\

### T007 · 测试

- [x] **T007**：后端当前实例字段测试

**文件**：`src/backend/test/app_runtime/test_f115_instance_observation.py`。\
**逻辑/上下文**：mock原可读资源与编排器，证明字段白名单/nullable和16121，404不回退旧实例。\
**依赖**：无。\
**覆盖 AC**: AC-01, AC-04, AC-06, AC-08, AC-09, AC-10, AC-52

### T008 · 后端 Domain

- [x] **T008**：实例响应去掉历史事实回退

**文件**：`src/backend/bisheng/app_runtime/domain/services/app_query_service.py`。\
**逻辑/上下文**：增加observation_state，只转发真实字段，旧模糊404报无法确认，保留原状态阅读门禁。\
**依赖**：T006,T007。\

### T009 · 测试

- [x] **T009**：当前人员与Web创建身份

**文件**：`src/backend/test/user/test_f115_current_identity.py`。\
**逻辑/上下文**：人员启停、唯一成员、迁租户、JWT版本/期限和关闭多租户，无额外成员行不拒绝有效单租户。\
**依赖**：无。\
**覆盖 AC**: AC-27, AC-28, AC-29, AC-35, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-47, AC-52

### T010 · 后端 Domain

- [x] **T010**：人员事实和新建身份薄入口

**文件**：`src/backend/bisheng/user/domain/repositories/runtime_identity.py`；`src/backend/bisheng/user/application/runtime_identity.py`。\
**逻辑/上下文**：新增批量当前人员事实和Web创建用途身份，原runtime/preview入口严格语义不改；SQL只在仓储。\
**依赖**：T009。\

### T011 · 测试

- [x] **T011**：业务主体目录资格

**文件**：`src/backend/test/tenant/test_f115_visibility_subjects.py`。\
**逻辑/上下文**：同租户有效人员/部门/组与停用迁离/歧义/目录失败分离，不展开成员，名称完整才能确认。\
**依赖**：T010。\
**覆盖 AC**: AC-23, AC-24, AC-25, AC-27, AC-28, AC-29, AC-37, AC-52

### T012 · 后端 Domain

- [x] **T012**：主体批量只读解析

**文件**：`src/backend/bisheng/tenant/domain/repositories/permission_subject_repository.py`；`src/backend/bisheng/tenant/domain/services/f048_permission_subject.py`。\
**逻辑/上下文**：批量解析有效/失效/不可确认并保留userset；通过user应用读取人员事实，不改授权写入。\
**依赖**：T011。\

### T013 · 测试

- [x] **T013**：F048 action 来源完整性

**文件**：`src/backend/test/permission/test_f115_action_sources.py`。\
**逻辑/上下文**：action而非名称/level、CUSTOM/INHERIT、CURRENT、分页推进/预算、Catalog或版本变化fail closed。\
**依赖**：无。\
**覆盖 AC**: AC-23, AC-26, AC-27, AC-28, AC-33, AC-34, AC-37, AC-52

### T041 · 后端 Domain

- [x] **T041**：来源一致性仓储读取

**文件**：`src/backend/bisheng/permission/domain/repositories/grant_repository.py`。\
**逻辑/上下文**：精确资源及严格租户内读取最多5001条Grant，用于前后版本复核；不改授权写入。\
**依赖**：T013。\

### T014 · 后端 Domain

- [x] **T014**：F048可信来源读取

**文件**：`src/backend/bisheng/permission/application/runtime.py`；`src/backend/bisheng/permission/application/control_state.py`。\
**逻辑/上下文**：添加read_effective_action_sources，复用目录与投影，每页500条/最多5000来源，前后版本复核；原通用roster仍manage_permission。\
**依赖**：T013,T041。\

### T015 · 测试

- [x] **T015**：当前授权摘要业务测试

**文件**：`src/backend/test/app_publish/test_f115_current_visibility.py`。\
**逻辑/上下文**：合法阅读上下文、绑定、真实owner资格、多类对象、owner-only/无对象/删除/失败；无历史写入。\
**依赖**：T010,T012,T014。\
**覆盖 AC**: AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-52

### T016 · 后端 Domain

- [x] **T016**：应用当前摘要协调

**文件**：`src/backend/bisheng/app_publish/domain/services/app_publish_current_visibility_service.py`；`src/backend/bisheng/app_publish/domain/schemas/current_visibility.py`。\
**逻辑/上下文**：只在已验证审批阅读上下文内核对app/tenant，调用permission应用及目录；预算与异常显式unavailable，owner不用reader缓存。\
**依赖**：T015。\

### T017 · 测试

- [x] **T017**：审批详情三入口与其它场景

**文件**：`src/backend/test/approval/test_f115_current_detail.py`。\
**逻辑/上下文**：原鉴权优先，合法任务/个人/管理可读增量且snapshot不变，拒绝者不调摘要；其它场景无额外查询。\
**依赖**：T016。\
**覆盖 AC**: AC-22, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-52

### T018 · 后端 Domain

- [x] **T018**：审批场景补充接线

**文件**：`src/backend/bisheng/approval/domain/services/approval_center_service.py`；`src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py`。\
**逻辑/上下文**：在原校验通过后用场景Handler可选只读补充；原场景决策/路由/outbox不动。\
**依赖**：T017。\

### T019 · 后端 Domain

- [x] **T019**：发布Handler与审批参考同步

**文件**：`src/backend/bisheng/app_publish/domain/services/app_publish_scenario_handler.py`；`.claude/skills/approval-module/SKILL.md`。\
**逻辑/上下文**：新增read_current_detail，使用服务器上下文而非请求app_id；同步详情增量参考。\
**依赖**：T018。\

### T020 · 测试

- [x] **T020**：Web知识库创建资格

**文件**：`src/backend/test/knowledge/test_f115_creation_policy.py`。\
**逻辑/上下文**：租管无菜单允许Doc/QA，普通菜单/部门管理/跨租户/撤资格/旧会话配对；copy无扩大。\
**依赖**：T001,T010。\
**覆盖 AC**: AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-52

### T021 · 后端 Domain

- [x] **T021**：知识库新建策略

**文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_creation_policy.py`。\
**逻辑/上下文**：服务端真实会话与expected所属租户比较，原菜单或当前租管资格，只产生短时服务器上下文。\
**依赖**：T020。\

### T022 · 测试

- [x] **T022**：创建入口写前门禁

**文件**：`src/backend/test/knowledge/test_f115_creation_entry.py`。\
**逻辑/上下文**：原模型校验后、实际写入前重验；失败无资源/索引；开放通道不带Web门禁，copy保持原规则。\
**依赖**：T021。\
**覆盖 AC**: AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-52

### T023 · 后端 API

- [x] **T023**：Web新建与原异步创建复用

**文件**：`src/backend/bisheng/knowledge/api/endpoints/knowledge.py`；`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`。\
**逻辑/上下文**：Web DTO接线至已有acreate_knowledge，写前重验上下文；严格所属tenant scope，原模型/投影/索引继续。\
**依赖**：T022。\

### T024 · 测试

- [x] **T024**：Platform运行和审计交互

**文件**：`src/frontend/platform/src/test/f115RuntimeReview.test.tsx`。\
**逻辑/上下文**：运行0/null/未知和时间，真实访客混合/空/搜索空/失败重试/范围变化，使用现有RTL与API mock。\
**依赖**：无。\
**覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-51, AC-52

### T025 · 前端 Platform

- [x] **T025**：当前实例显示

**文件**：`src/frontend/platform/src/controllers/API/hostedApp.ts`；`src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/PublishTab.tsx`。\
**逻辑/上下文**：nullable计数、observation_state及时间校验，未知不raw英文不??0，业务状态独立。\
**依赖**：T008,T024。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T026 · 前端 Platform

- [x] **T026**：模型用户过滤状态

**文件**：`src/frontend/platform/src/pages/LogPage/runtime/RuntimeAuditPanel.tsx`。\
**逻辑/上下文**：共享Select空/搜索/加载文案与失败重试，key完整，范围变化重置旧身份搜索，不改接口/账本。\
**依赖**：T024。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T027 · 测试

- [x] **T027**：Platform新建与管理审批摘要

**文件**：`src/frontend/platform/src/test/f115KnowledgeCreation.test.tsx`；`src/frontend/platform/src/test/f115ApprovalVisibility.test.tsx`。\
**逻辑/上下文**：Doc/QA按钮与copy拆分，固定leaf租户；异常详情当前范围刷新及scope隔离、不可确认。\
**依赖**：无。\
**覆盖 AC**: AC-22, AC-24, AC-25, AC-28, AC-29, AC-30, AC-32, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52

### T028 · 前端 Platform

- [x] **T028**：新建复制条件分离

**文件**：`src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx`；`src/frontend/platform/src/pages/KnowledgePage/KnowledgeQa.tsx`。\
**逻辑/上下文**：本租管加入新建条件，copy仍原菜单/超管与源读取资格。\
**依赖**：T027。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T029 · 前端 Platform

- [x] **T029**：两类表单固定所属租户

**文件**：`src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeLibraryDialog.tsx`；`src/frontend/platform/src/pages/KnowledgePage/components/QaLibraryDialog.tsx`。\
**逻辑/上下文**：打开时固定leaf_tenant_id发送expected_tenant_id，无有效归属不提交，非管理视角。\
**依赖**：T023,T027。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T030 · 前端 Platform

- [x] **T030**：管理摘要类型与重查

**文件**：`src/frontend/platform/src/controllers/API/approval.ts`；`src/frontend/platform/src/pages/ApprovalPage/useApprovalExceptions.ts`。\
**逻辑/上下文**：同级current_visibility类型；按scope/instance重查，展开或刷新不使用永久旧授权缓存。\
**依赖**：T019,T027。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T043 · 前端 Platform

- [x] **T043**：管理异常页刷新接线

**文件**：`src/frontend/platform/src/pages/ApprovalPage/useApprovalController.ts`。\
**逻辑/上下文**：将真实重查回调传给异常详情；租户切换沿既有全页重载清空内存缓存。\
**依赖**：T030。\

### T031 · 前端 Platform

- [x] **T031**：异常详情只读摘要

**文件**：`src/frontend/platform/src/pages/ApprovalPage/ExceptionPanel.tsx`；`src/frontend/platform/src/pages/ApprovalPage/CurrentAppVisibility.tsx`。\
**逻辑/上下文**：小型只读区域，当前/owner-only/无对象/删除/不可确认三语，不复制client页面或增加审批权限。\
**依赖**：T030,T043。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T032 · 前端 Platform

- [x] **T032**：中文与英文文案

**文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`；`src/frontend/platform/public/locales/en-US/bs.json`。\
**逻辑/上下文**：新增运行未知、访客无记录、审批当前授权与资格反馈；沿现有命名空间。\
**依赖**：T025,T026,T028,T029,T031。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T033 · 前端 Platform

- [x] **T033**：日文与运行既有命名空间

**文件**：`src/frontend/platform/public/locales/ja/bs.json`。\
**逻辑/上下文**：日文与中文英文同义；新增提示显式使用bs命名空间，不修改共享生成文案。\
**依赖**：T032。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T034 · 测试

- [x] **T034**：Client当前审批范围

**文件**：`src/frontend/client/src/components/approval/AppPublishDetailPanel.test.tsx`；`src/frontend/client/src/components/approval/CurrentAppVisibility.test.tsx`。\
**逻辑/上下文**：当前DTO优先、快照不变、首发非必owner-only、失败/删除/真实对象、权限不扩展、刷新回调。\
**依赖**：无。\
**覆盖 AC**: AC-22, AC-24, AC-25, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-51, AC-52

### T035 · 前端 Client

- [x] **T035**：当前摘要类型与渲染

**文件**：`src/frontend/client/src/api/approval.ts`；`src/frontend/client/src/components/approval/CurrentAppVisibility.tsx`。\
**逻辑/上下文**：独立current_visibility字段，旧后端显示未知，冻结区域不读动态payload，刷新通过父层回调。\
**依赖**：T019,T034。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T042 · 前端 Client

- [x] **T042**：Client发布卡片当前摘要接线

**文件**：`src/frontend/client/src/components/approval/AppPublishDetailPanel.tsx`。\
**逻辑/上下文**：移除旧可见范围快照渲染，接入独立当前摘要；其它冻结内容保持。\
**依赖**：T035。\

### T036 · 前端 Client

- [x] **T036**：审批父层刷新

**文件**：`src/frontend/client/src/components/approval/ApprovalDetailPanels.tsx`；`src/frontend/client/src/components/approval/ApprovalPane.tsx`。\
**逻辑/上下文**：在已核实父层接入详情重查，打开/刷新重新鉴权，不混SPA。\
**依赖**：T035,T042。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T037 · 前端 Client

- [x] **T037**：中文英文当前摘要文案

**文件**：`src/frontend/client/src/locales/zh-Hans/translation.json`；`src/frontend/client/src/locales/en/translation.json`。\
**逻辑/上下文**：补当前范围、管理员说明、无对象/失败/删除/refresh，纯文本对象名称。\
**依赖**：T035。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T038 · 前端 Client

- [x] **T038**：日文当前摘要文案

**文件**：`src/frontend/client/src/locales/ja/translation.json`。\
**逻辑/上下文**：日文与中文英文含义一致。\
**依赖**：T037。\
**验证**：配对组件测试、三语和局部静态检查；实际页面检查见 E2E 清单。

### T039 · 测试

- [x] **T039**：定向E2E脚本和页面清单（已准备；真实执行待授权）

**文件**：`src/backend/test/e2e/test_e2e_f115_runtime_review.py`；`features/v3.0.0/115-vibe-runtime-review-fixes/e2e-checklist.md`。\
**逻辑/上下文**：专用e2e-f115数据，只跑四链路；真实部署与写入须独立环境授权，未执行如实登记，禁止全量测试。\
**依赖**：T006,T008,T019,T023,T026,T029,T031,T036,T038。\
**覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52

### T040 · 后端 Domain

- [x] **T040**：定向门禁与L1/L2报告

**文件**：`features/v3.0.0/115-vibe-runtime-review-fixes/verification.md`；`features/v3.0.0/115-vibe-runtime-review-fixes/code-review.md`。\
**逻辑/上下文**：记录精确命令/结果/环境边界、task-review及7维特性审查；同步设计实际接线和完成状态，不将未部署E2E标完成。\
**依赖**：T039。\

## 实际偏差记录

开发接线新增四个原子任务 T041–T044；修正实际文件名及父层路径，业务边界不变。共享错误码产物由 locales build 生成，不手工编辑。T039 完成脚本/清单与离线收集，不代表真实 E2E 通过；真实验收保持未执行。Jest 依赖启动受阻时，使用临时 Vitest 兼容副本验证相同组件和断言，未改仓库测试框架。L1 逐项结果及 L2 见 verification.md / code-review.md。

## tasks 自审

LGTM

按当前 tasks-checklist 实际21项自审：AC定义连续且测试覆盖全部52条；依赖均存在且在前；后端测试在配对实现前；每项至多2个文件；Platform/Client分区；无Worker/DDL不适用项已说明。每项明确文件、具体产出与上下文，无测试降级或业务TODO。仅开发阶段所需定向测试和门禁，不包含环境部署授权。
