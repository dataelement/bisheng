# 验证结果

日期：2026-11-17；基线 33bcadaa3e；独立分支 codex/3.1.0-beta1/tenant-model-metadata-fixes-20261117。使用现有 Python 3.11 venv 和 pnpm workspace 依赖进行本地验证。没有将新构建部署到 116，没有恢复任务或修改角色绑定。

## 针对性回归

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 后端主套件 | 80 passed | role display/effective roles、management directory scope、managed tenant members、assistant management scope、manual model status/cache、visible tool management scope、source move input protection |
| 目录 enrich 原单测 | 3 passed | test_department_service.py -k get_members；角色 owner 隔离，真实接线另由主套件验证 |
| 昵称编辑相关回归 | 16 passed | test_member_nickname_edit.py 独立执行，确认未改变既有人员修改逻辑 |
| 前端主套件 | 45 passed | 文件元数据 11、空间元数据 10、文件详情 10、工作流模型 3、成员角色 3、模型 query scope 2、provider 行 6 |
| 旧模型参数组件相关检查 | 12 passed | ModelPage/manage/ModelItem 及 i18n，非工作流同名组件 |
| opt-in 现场只读 E2E | 5 skipped | 未提供升级后专用环境；不是通过，详见 e2e-checklist.md |

主后端命令（backend 目录，设置当前环境 config 及 PYTHONPATH；本轮使用已有 venv 的 pytest）：

```sh
pytest test/role/test_member_role_display.py test/role/test_effective_roles.py \
  test/department/test_management_directory_scope.py test/department/test_managed_tenant_members.py \
  test/llm/test_model_status_verify.py test/llm/test_assistant_management_scope.py \
  test/tool/test_visible_list_management_scope.py test/knowledge_unification/test_source_move_input.py -q
pytest test/department/test_department_service.py -q -k get_members
pytest test/department/test_member_nickname_edit.py -q
```

前端主套件（platform 目录）：

```sh
pnpm exec vitest run src/test/spaceFileMetadataDialog.test.tsx \
  src/test/spaceMetadataPanel.test.tsx src/test/knowledgeSpaceFileDetail.test.tsx \
  src/pages/BuildPage/flow/FlowNode/component/ModelItem.test.tsx \
  src/pages/DepartmentPage/components/MemberRoleSummary.test.tsx \
  src/pages/ModelPage/manage/queryModelMigration.test.tsx \
  src/pages/ModelPage/manage/ModelProviderRow.test.tsx --maxWorkers=1 --minWorkers=1
```

覆盖包括：合法 Root 共享与本租户角色、四类失效绑定、非超管不含诊断、foreign-home 不泄露角色、业务范围与物理存储分离；模型默认顺序、下线状态、共享撤销/归属不一致、配置失败、所选目标无效、共享禁止探测；字段选择与创建、三类型值、全量替换与移除、失败草稿、未知确认同键重试、文件/空间/租户切换后旧预检不得确认及旧保存响应失效；工具既有 actor 修复与失败源任务保护。

## 质量门禁

- `pnpm lint`：通过，覆盖 Platform、Client 及脚本列出的共享包；仅删除工作流 ModelItem 已失效的一条 no-unused-vars 抑制。
- `pnpm typecheck`：通过，Platform/Client 和共享包；新增文件未添加 ts-strict-ignore。
- `pnpm check-i18n`：通过，无新增漂移；已有 85 个 frontend-only 错误码提示为信息级存量记录。新增文案包含中/英/日。
- `pnpm build:platform`：通过；既有大 chunk 提示保留。
- Ruff format：全部变更 Python 文件完成。Ruff check 的当前诊断 83 条，与 HEAD 基线同文件诊断 83 条逐规则/消息计数比较无新增；新 Python 文件无诊断。存量中文标点、旧测试未使用变量等未扩大修复范围。因此是增量通过，不能称全仓 Ruff 无报错。
- 架构守卫：对全部变更/新增文件逐个执行，无 VIOLATION。RULE-7 在旧 department service 单测中的测试字面值产生一个 WARNING；原 HEAD 文件同样触发，新增代码未引入凭据。
- 变更 locale JSON 全部解析成功；test-cases.md 表格八列校验通过；git diff --check 通过。

## 扩大回归的基线限制

以下不计入本次通过数，也未通过放宽生产校验来消除：

| 旧套件 | 当前结果 | 原 HEAD owning service 对照 | 观察 |
| --- | --- | --- | --- |
| test_department_service.py 整文件独立执行 | 34 passed / 8 failed | 同为 34 passed / 8 failed，失败用例集合完全一致 | 旧角色 catalog 预期、未隔离的 MySQL 连接、旧同步 mock 与异步调用不匹配 |
| LLM tenant isolation service + system config service/router | 39 passed / 8 failed | 同为 39 passed / 8 failed，失败集合完全一致 | 缺真实租户 ContextVar、旧 Root 默认假设与旧配置/路由 mock 不匹配 |

基线对照从 git show HEAD 的 owning service 源码在独立 pytest 进程内加载，未覆盖工作区文件。混合运行旧部门全套与已启用 tenant-filter 事件的 SQLite 套件时有更多上下文相关失败（94 passed / 24 failed），不具备全量回归通过结论。昵称套件在这种混跑下也受上下文影响，独立当前及基线均为 16 passed。运行被阻断的外部 MySQL 连接未升级权限重试，避免对本轮只读 116 进行非隔离写测试。

## AC 验收与限制

AC-01/02/04/05/06/07：本地服务/SQLite/组件自动化已覆盖；真实浏览器及 MySQL/DM8/FGA/worker 协同仍待部署验收。AC-03：已确认基线含 133f8a37ee，既有工具回归通过，116 容器旧实现证据已记录。AC-08：现场证据及恢复核查清单已交付，源任务保护原规则测试通过，没有执行空间删除或任务恢复。

完整环境 E2E 状态 PARTIAL，不能用本地验证或旧环境截图代替升级后的验收。
