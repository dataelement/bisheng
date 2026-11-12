# 后台空间 UI 验证记录

验证日期：2026-11-12。基线 `c9918ba14e`，目标为本修复分支。按 e2e-test 技能分类：本次 AC 为 UI 展示和既有能力回归，无新增后端 API，不另造后端 CRUD 测试。

## 已执行

- [x] AC-01：组件验证三组、排序、置顶、新建及广场回调，真实浏览器查看三组布局与目录展开。
- [x] AC-02：组件验证空游标页、续页、深链跨页祖先展开、加载失败重试；实际 KnowledgePage 路由验证目录选中和原 query 保留。
- [x] AC-03：列表/卡片切换、服务端排序与搜索、缩略图及破图回退；偏好跨目录保持，非法值/存储不可用不阻断页面。
- [x] AC-04：当前上传入口、版本操作和加工入口定向回归通过；原数据/权限/确认生命周期实现复用。
- [x] AC-05：组件验证 scope 切换及 A→B→A 迟到响应隔离、缺失范围阻断、tenant 不匹配行过滤；真实路由验证 QA 与管理页签独立。
- [x] AC-06：广场回调组件测试，代码核对指向工作台 `/knowledge?square=1`。
- [x] 本地 Chromium fixture smoke：真实 KnowledgePage/Workspace/SpaceDetail/Files，1024px 内容宽度无横向溢出；列表切卡片、两层目录导航、卡片偏好保持、选中路径、独立管理页签均通过，控制台无 error。

浏览器使用只读固定 API fixtures，所有真实后端代理关闭，写操作拒绝；不代表真实鉴权或服务端 E2E。临时预览入口在验证后删除。

## 自动检查

- `pnpm lint`：通过，全前端 workspace。
- `pnpm typecheck`：通过，全前端 workspace。
- `pnpm check-i18n`：通过。
- 定向 Vitest：7 文件 / 53 项通过，包括新侧栏 9、workspace 文件 UI 6、真实路由集成 3、原列表 14、上传 10、版本操作 8、文件工具 3。
- `arch-guard`：18 个变更源码/测试文件通过；`git diff --check`：通过。

## 基线失败与未验收边界

另跑原目录、历史和详情测试有 7 项失败，已使用 Vite preload 加载 `c9918ba14e` 的原始 Files/SpaceDirectoryRow/detail/Header 复现相同失败：

- `f118SpaceDirectory.test.tsx` 1 项：mock 未提供现有文件工具的 `checkResourceActionApi`，影响错误 spy 断言。
- `f118SpaceDirectoryHistory.test.tsx` 2 项：测试期待 is_multi_version 门槛，基线代码仅使用功能开关与 file_type。
- `f118SpaceDetail.test.tsx` 4 项：现有文件工具调用权限 check，测试仍期待该 spy 未调用。详情测试现已改挂实际 KnowledgePage/Workspace，仍为同四项失败，其余 19 项通过。

- [ ] 真实部署上的鉴权、上传、移动、删除、审批和后台加工写入验收。
- [ ] 真实账号下的部门/加入列表及超管切换管理租户业务验收。
- [ ] 完整 QA 与生产部署；本轮仅交付独立修复分支。
