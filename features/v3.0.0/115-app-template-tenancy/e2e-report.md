# F115 验证与部署验收清单

日期：2026-11-02。执行了 e2e-test 的 AC 分类、API 用例生成/运行及页面验证清单流程。

## 本地验证结果

| 验证 | 结果 | 范围和限制 |
|---|---|---|
| 后端模板、报告归属、租户过滤及执行上下文回归 | 71 passed | 本地真实 SQLite + ORM 租户事件；模板 HTTP 通过 ASGI/httpx，身份及源应用授权外部端口被替换 |
| 前端模板能力、助手配置复用、创建弹窗、排序及路由回归 | 41 passed | 5 个测试文件；包括超管/租户管理员/普通用户矩阵、助手与工作流入口、切租户丢弃旧响应、长描述排序、长提示词与保存失败复用草稿 |
| 全前端 workspace lint | 通过 | 含 platform、client、共享包；仅对本次修复的 CreateApp 文件定向 prune 过期 suppression，保留其他已有改动 |
| Ruff | 通过 | 本特性所有 Python 变更与新增测试 |
| arch-guard | 无 VIOLATION | assistant.py 保留了原有 ORM 导入 WARNING，本次只移除错误的 JWT 租户显式赋值 |
| git diff --check | 通过 | 无空白错误 |
| 部署环境 HTTP E2E | 5 skipped | 未提供启用标志、部署服务和专用租户账号；不代表完整鉴权、中间件、OpenFGA 或 MySQL/DM8 实机验证通过 |

执行命令：

```sh
cd src/backend
.venv/bin/pytest test/tenant/test_tenant_filter.py test/tenant/test_tenant_execution_scope.py test/app_template/ test/api/test_report_template_ownership.py test/e2e/test_e2e_app_template_tenancy.py -q
cd ../frontend/platform
pnpm test src/test/appTemplatePermissions.test.tsx src/test/assistantTemplate.test.ts src/test/createAppTemplate.test.tsx src/test/listSorting.test.tsx src/test/resolveRoutePermissions.test.ts
cd ..
pnpm lint
pnpm typecheck
```

## AC 覆盖

| AC | 自动化证据 | 部署后补验 |
|---|---|---|
| AC-01 | 三租户 HTTP 列表/详情、两类型、跨租户拒绝 | 真实账号模板选择器 |
| AC-02 | 超管 management_tenant_scope 逐租户读取；路径规则；根 JWT 下助手持久化到所选子租户 | 超管切租户、旧页写范围冲突 26073 |
| AC-03 | 管理员增改删、错误租户管理员拒绝、前端能力矩阵 | 真实身份解析/OpenFGA |
| AC-04 | 同租户普通用户读取；助手模板配置复用；创建页面接入；原路由能力保留 | 普通用户从两种模板创建应用 |
| AC-05 | 普通用户三类写请求拒绝；管理页加载前拒绝；卡片入口矩阵 | 带 create_app 的真实普通用户 |
| AC-06 | 根/其他子租户详情、修改、删除、来源拒绝，且原数据不变 | 真实 HTTP middleware |
| AC-07 | 创建伪造归属/ID/快照不生效；更新不能重分配归属或替换快照 | 真实库自动填充 |
| AC-08 | 工作流及助手分别读取真实来源；源资源 visible 拒绝与不可用失败；助手可移植配置 | 可用模型下创建并进入编辑页 |
| AC-09 | 跨租户同名成功、同租户重名失败；排序只写当前位置 | 双库并发行为沿用现状，未增加唯一约束 |
| AC-10 | 根历史模板对子租户不可见；无 DDL、数据复制或回填；真实长描述排序回归 | 升级后核对现有模板数与归属 |
| AC-11 | 缺租户上下文 fail closed；前端切换后丢弃旧结果 | 实际会话切换 |
| AC-12 | 单租户默认租户读取回归；管理员能力与菜单独立 | 单租户部署 smoke |
| AC-13 | 当前租户报告 key 可作 fallback，根/其他子租户不可；原报告所有权测试通过 | MinIO/OnlyOffice 文档复制 |

## 部署 E2E 用法

测试文件：`src/backend/test/e2e/test_e2e_app_template_tenancy.py`。按文件说明提供 E2E_API_BASE、F115_TENANT_ID、两种专用源应用、外租户模板标识，以及 admin/user/foreign 三种短期令牌；管理员预先切到测试租户。设置 F115_E2E=1 后运行该文件。

用例只增删独立的 `e2e-f115-` 名称模板，不改源应用、其他模板或租户配置；通过 finally 仅清理本次创建的 ID。测试没有保存或输出令牌。没有可用环境时保持 skip，不借用生产账号或数据库。

## 页面手动验证（待执行）

- [ ] 根租户、子租户 A/B 各自模板列表互不混入；空子租户不补根模板。
- [ ] 超管及当前租户管理员在工作流、助手卡片均可添加模板；普通用户和部门管理员无该动作。
- [ ] 普通用户即使有 create_app，也不能访问 `/build/temps/flow`、`/build/temps/assistant`，但可通过创建应用的选择器使用本租户模板。
- [ ] 两类模板均可新增、使用、删除；删除模板不删除源应用或已创建实例。
- [ ] 助手复用提示词、开场白、问题、温度等配置；采用默认模型，知识库/工具/应用绑定为空，可重新配置；保存失败能重试同一草稿。
- [ ] 超管从根租户切到 A 后用助手模板创建，实例确实归 A；旧标签页/弹窗不带入原租户模板。
- [ ] 根历史工作流模板的长描述不影响拖动排序；排序不改名称、描述。
- [ ] 含报告节点的本租户模板可复制报告文档；外租户模板不可提供额外复制授权。

## 扩大检查中的现有问题

- `pnpm typecheck` 当前被另一个未提交模块 `src/components/Pro/security/AssistantSetting.tsx:58` 的 TS2322（unknown[] → number[]）阻断；本次新增与修改文件没有剩余编译错误，未覆盖该并发改动。
- platform 全套 Vitest：277 文件，254 passed / 23 failed；1549 用例，1482 passed / 67 failed，另 4 个未处理错误。失败主要涉及已有服务账号管理视图 mock、托管应用旧权限测试、审批/DSH/请求兼容测试。没有将该运行称为通过。
- 对与共享卡片有关的 `hostedAppMenuTrim.test.tsx`，用 Git HEAD 原卡片创建临时 baseline 并重跑，仍为相同 4 failed / 3 passed；临时文件已清理。其根因是已有 HostedAppCard 已改读 allowed_actions，而旧测试仍传 canDelete/canManagePermission。本特性没有修改该文件。
- 额外尝试 `test/api/test_build_managed_tenant_scope.py` 时，2 项测试连接不可达外部 MySQL，未作为本特性通过证据，也未替换或改写这些测试。
- 全后端套件包含外部中间件集成，不在本机无环境情况下全跑；MySQL/DM8/OpenFGA 实机与页面验收继续作为发布前门禁。

完整前端失败用例清单见 [frontend-suite-failures.md](./frontend-suite-failures.md)。除共享卡片的 4 项外，未对全部失败单独重建基线，不能将其全部宣称为已证明的既有缺陷。
