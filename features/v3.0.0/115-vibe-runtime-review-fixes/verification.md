# F115 开发与定向验证记录

日期：2026-11-02。分支 `codex/vibe-runtime-review-20261102`；源码基线 `497256d289793ce016df07cf8ab38f32988faca4`。规格52条及设计均获用户分别确认。本轮未部署；不运行全量测试。

## 本次 Git 交付安排

用户在本地开发与验收缺口已披露后，明确要求“提交推送 feat/3.0.0 分支”。按该指令先提交本功能、合入最新远端发版线并推送，保留目标分支后续增强。真实部署 E2E 及既有类型门禁问题仍按下表记录，不将 Git 交付视为部署验收完成。本次不更新环境或存量资源。

## 本地结果

| 范围 | 实际结果 | 证据/限制 |
|---|---|---|
| 后端新增链路与直接相关知识库回归 | 63 passed；5个真实E2E用例默认skipped | pytest实际组合运行；非空业务断言、拒绝先于名单、原子创建补偿及开放API兼容 |
| manager Docker/K8s只读观察 | 71 passed | test_f115_observation.py + test_k8s_observe.py；fake外部平台/执行器，非真实部署 |
| Platform组件和直接审计回归 | 19 passed / 4 files | 运行状态、候选失败/空/切范围、知识库两种入口与旧表单、审批重查 |
| Client审批组件/父层相关断言 | 22 passed / 3 files | 现有Jest受未构建canvas与ESM p-limit启动问题阻断；临时Vitest兼容副本仅替换测试全局名称/模块定位和JSX运行配置，执行真实产品组件及同一断言。没有修改仓库runner或依赖安装 |
| 前端 lint | PASS | 按根脚本检查两个SPA与共享包 |
| i18n与错误码产物 | PASS | check-i18n；locales build/check，三语源和6个生成文件 |
| 前端类型门禁 | 未全绿；无新增诊断 | 同一基线/同一依赖对照：Platform23条、Client134条；依赖缺失、旧图标/API等既有报错。本轮曾新增一处测试fixture类型错误，已修正并重新验证 |
| Ruff | 无新增问题 | 修改文件与git HEAD同配置对照；旧文件剩余问题按基线登记，新文件通过。所有修改Python执行format及未定义名检查 |
| 架构守卫 | 无VIOLATION | knowledge endpoint旧database/models导入仅RULE-3既有WARNING |
| 真实部署 E2E | 未执行 | 5个用例只作离线收集/默认skip；未访问或写入116/189。必须依e2e-test及design §7.2在明确授权和部署后执行 |

## 可复现命令

工作目录分别为worktree的 `src/backend`、`src/runtime-manager`、`src/frontend/platform`。Python复用主工作区现有venv；config只指定既有本地文件路径，不复制或输出凭据。pytest使用 `-q -p no:cacheprovider --tb=short --disable-warnings`。

```text
pytest test/app_runtime/test_f115_instance_observation.py test/user/test_f115_current_identity.py test/tenant/test_f115_visibility_subjects.py test/permission/test_f115_action_sources.py test/app_publish/test_f115_current_visibility.py test/approval/test_f115_current_detail.py test/knowledge/test_f115_creation_policy.py test/knowledge/test_f115_creation_entry.py test/knowledge/test_f115_e2e_cleanup.py test/knowledge/test_knowledge_create_atomicity.py test/knowledge/test_v2_filelib_unified.py test/e2e/test_e2e_f115_runtime_review.py
pytest tests/test_f115_observation.py tests/test_k8s_observe.py
vitest run src/test/f115RuntimeReview.test.tsx src/test/f115KnowledgeCreation.test.tsx src/test/f115ApprovalVisibility.test.tsx src/test/runtimeAudit.test.tsx
pnpm lint
pnpm typecheck
pnpm check-i18n
node packages/locales/scripts/build.mjs --check
```

临时日志位于 `/private/tmp/f115-*.log`；兼容运行及基线只存在临时目录，没有提交对依赖或测试环境的改写。

## task-review（L1）

44个原子任务逐项检查命名/分层、响应序列化、SQL归属与严格租户、权限应用端口、两SPA/i18n、敏感信息、设计同步。实现任务配对用例及修改文件与tasks对应；基础设施和测试任务按skill的差异化清单检查。代码项PASS；前端旧类型/Ruff基线与真实E2E门禁为显式备注，不能记作远端已验收。

- T001–T003：10993未冲突、Web专用DTO不扩展共享创建目标、三语产物一致。
- T004–T008：真实当前绑定/UID、HTTP事实、nullable/0及UTC归一；旧观察404不回退历史AppInstance。
- T009–T016、T041：实时人员资格、批量目录、CURRENT及完整分页/版本复核；真实owner资格与阅读者分离，普通审批人不获得manage_permission。
- T017–T019：三类详情均在原守卫后追加；非app场景无动态查询，两个snapshot不写回。
- T020–T023：准备和写前重验，严格所属租户；copy/开放API不增加菜单门禁，原创建补偿保留。
- T024–T033、T043：前端状态与真实字段一致，表单固定leaf、不以当前管理视角写入；管理异常页重查与序号拒绝旧响应。
- T034–T038、T042：Client当前范围只读、typed userset、失败/删除/owner-only与冻结区域分开，父层真实API刷新。
- T039、T044：专用E2E准备、显式启用和精确清理护栏；非测试名称与跨租户清理用例拒绝。
- T040：记录本页和L2结论，完整实现52条目标的本地接线，不声称52条均在真实环境验收。

## AC追溯

下表中的“本地”指单元/组件/相关回归与代码路径核对；所有真实部署项均待验，具体步骤见 [e2e-checklist.md](./e2e-checklist.md)。不把测试任务写过覆盖编号当成真实验收证据。

| AC | 本地证据入口 | 真实环境 |
|---|---|---|
| AC-01 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-02 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-03 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-04 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-05 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-06 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-07 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-08 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-09 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-10 | manager test_f115_observation/test_k8s_observe；backend instance；Platform f115RuntimeReview | 待部署验收 |
| AC-11 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-12 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-13 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-14 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-15 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-16 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-17 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-18 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-19 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-20 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-21 | 既有审计repository可信身份过滤核对；runtimeAudit及f115RuntimeReview组件 | 待部署验收 |
| AC-22 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-23 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-24 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-25 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-26 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-27 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-28 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-29 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-30 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-31 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-32 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-33 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-34 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-35 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-36 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-37 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-38 | action_sources/current_identity/visibility_subjects/current_visibility/current_detail；两端CurrentAppVisibility | 待部署验收 |
| AC-39 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-40 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-41 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-42 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-43 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-44 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-45 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-46 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-47 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-48 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-49 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-50 | creation_policy/creation_entry；knowledge_create_atomicity/v2_filelib；Platform f115KnowledgeCreation | 待部署验收 |
| AC-51 | 三语/架构守卫/拒绝场景与对应路径 | 待部署验收 |
| AC-52 | 三语/架构守卫/拒绝场景与对应路径 | 待部署验收 |
