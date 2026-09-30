# 验证报告 Verification: F083 门户部门简称统一展示

## 结论

- 实现状态：完成。
- 自动化验证：核心后端、两个前端生产构建、独立门户 BFF 与聚焦前端用例均通过。
- 人工验证：真实浏览器跨页面主路径、真实 PDF 下载成品及发布环境混合版本验证标记为 `MANUAL_REQUIRED`，未伪报通过。
- 范围保护：未修改 Platform、门户首页硬编码积分榜、组织同步、Filelib、遥测、中间表、Schema 或 migration。

## 实际证据

### 2026-08-11 T016 授权用户组织树缺陷回归

1. 修复前复现：`npm run test:ci -- src/components/permission/SubjectSearchUserTree.test.tsx --runInBand`
   - 结果：`1 failed, 5 passed`。
   - 失败符合预期：找不到简称“首钢股份”，DOM 实际显示正式名称“北京首钢股份有限公司”，证明根因是 Client 节点渲染未消费展示字段。
2. 最小修复后定向回归：`npm run test:ci -- src/components/permission/SubjectSearchUserTree.test.tsx --runInBand --coverage=false`
   - 结果：`6 passed`。
   - 覆盖：有简称显示简称、无简称回退正式名称、原有展开/分页/搜索分组/选择同步/禁用/重试行为。
3. Permission 共用入口模块回归：`npm run test:ci -- src/components/permission/SubjectSearchUserTree.test.tsx src/components/permission/PermissionGrantTab.test.tsx src/utils/departmentDisplayName.test.ts --runInBand --coverage=false`
   - 结果：`3 suites passed, 25 tests passed`。
   - `PermissionGrantTab` 的既有参数化用例证明 `knowledge_space`、`knowledge_library`、`folder`、`knowledge_file` 均进入同一个用户组织树组件。
   - 输出包含既有 React `act(...)` 警告，但命令退出码为 0，本次改动未新增异步状态逻辑。
4. Client 生产构建：`npm run build`
   - 结果：`PASS (exit 0)`，Vite 转换 6076 个模块并完成生产构建。
   - 输出包含既有 Browserslist、静态资源、`eval` 与 chunk size 警告，不影响构建成功。
5. 范围检查：生产代码仅修改 `SubjectSearchUserTree.tsx` 的部门节点展示字段读取；授权 ID、relation、API 路径、树范围和后端均未修改。

### BiSheng 后端

1. 部门共享规则、用户/PDF、Knowledge、Permission、Approval、QA Expert 定向回归：`65 passed`。
2. Permission/QA Expert/User 补充回归：`28 passed`。
3. 改动模块 `compileall`：通过。
4. 新增共享 helper 与单元测试 `ruff check`：通过。
5. `git diff --check`：通过。

覆盖了空白简称规范化、无简称回退、正式字段保留、双名称搜索、展示排序、逐级展示路径、历史快照不变、当前简称实时投影、新空间默认名称及 PDF 水印。

### BiSheng Client

1. `npm run build`：通过，Vite 共转换 6076 个模块。
2. 部门 helper、成员管理、审批中心、来源部门等聚焦 Jest：43 项通过。
3. 新兼容 helper 覆盖 `display_name → short_name → name`、空白简称和正式名/简称搜索。

已知基线问题：

- `KnowledgePreviewWatermark.test.tsx` 的既有复用聊天水印容器断言失败；本期水印纯函数的简称回退由共享 helper 与独立门户水印用例覆盖，生产构建通过。
- `CreateKnowledgeSpaceDrawer.test.tsx` 有 1 个既有编辑科室知识库选择器断言失败；失败页面已正常显示正式部门名，和本期简称映射无因果关系。

### 独立首钢门户

1. BFF auth/session 与后台部门透明代理聚焦 pytest：`4 passed`。
2. 部门 helper、后台绑定、专家排序、水印聚焦 Node 测试：`20 passed`。
3. `npm run build`：TypeScript 与 Vite 生产构建通过。
4. `git diff --check`：通过。

环境/基线说明：

- 门户 backend 虚拟环境未安装 `ruff`，无法执行该项门禁；Python 聚焦 pytest 已通过。
- 门户全量测试 TypeScript 编译被既有无关测试错误阻断，包括 `adminQaTemplates` 缺失旧 fixture 字段、`adminRestAuthConfig` 模块模式和 `portalContentConfig` 旧导出；本期 20 项用例使用同一编译产物单独执行并全部通过。
- 改动范围 ESLint 命中 `auth.ts`、`ExpertQADetailPage.tsx`、`AdminPage.tsx` 的既有规则问题；新增部门 helper 无 lint 报错，生产构建通过。
- 当前 Node.js 为 20.13.1，Vite 建议 20.19+；本次构建仍成功。

## 验收映射

| 验收标准 | 证据 | 状态 |
|---|---|---|
| AC-01～AC-03 | 共享 helper、五类后端投影及 API 兼容测试 | PASS |
| AC-04、AC-08 | Permission 正式/展示路径、部门树与 Client 成员管理测试 | PASS |
| AC-05～AC-06 | Knowledge、QA Expert 和两个前端的双名称搜索/展示排序测试 | PASS |
| AC-07 | Knowledge 部门选项/树/来源映射、Client 构建；真实交互 | AUTOMATED_PASS / MANUAL_REQUIRED |
| AC-09～AC-10 | 独立门户专家、后台绑定 20 项聚焦测试及构建 | PASS |
| AC-11 | 用户主部门、Client/门户水印函数、服务端 PDF 水印测试；真实 PDF 成品 | AUTOMATED_PASS / MANUAL_REQUIRED |
| AC-12～AC-13 | Approval 当前投影、历史快照不变和失效回退测试 | PASS |
| AC-14 | 新部门知识空间默认名称测试，未写历史空间 | PASS |
| AC-15～AC-17 | 无简称/旧响应回退、正式字段保留、ID payload/绑定不变测试 | PASS |
| AC-18 | 两仓生产 diff 范围审查 | PASS |
| AC-19 | T016 失败复现、用户组织树 6 项回归、四类知识资源共用入口及 Client 构建 | PASS |

## 兼容与发布

- 发布顺序：F082 migration → F083 BiSheng backend → BiSheng Client → 独立门户 BFF/frontend。
- 新前端遇到旧响应时回退正式名称；旧前端会忽略新增字段。
- 回退前端或 BFF 不影响新增只读字段；回退 backend 前应先回退依赖展示字段的新前端。F082 字段与 migration 不随 F083 回退。

## 人工验证清单

1. 使用一个有简称部门和一个无简称部门账号，依次检查知识空间创建、成员管理、审批、专家管理和后台绑定。
2. 在浏览器预览同一文件，确认 Client 与独立门户水印部门文案一致。
3. 下载真实 PDF，确认 PDF 水印与 `/user/info.department_display_name` 一致。
4. 在预发布环境按发布顺序做一次旧前端/新后端与新前端/旧字段 fixture 的混合版本检查。

## 实施偏差与保护项

- 为覆盖专家新增/编辑用户选择器，同步扩展了既有 `/user/list` 的主部门简称/展示字段；正式字段和部门 ID 未改变。
- Permission 部门主体新增 `subject_display_name`，原 `subject_name` 仍保持正式名称。
- QA Expert 关键字查询增加 Department 正式名/简称匹配，筛选 payload 仍使用部门 ID。
- 保留用户已有 `SHOUGANG_PORTAL_CONFIG_KEY = 'shougang_portal_config1'` 改动，未修改或回退。
- 保留独立门户未跟踪 `.coaligne/` 与 `.coaligneignore`，未纳入本功能。
