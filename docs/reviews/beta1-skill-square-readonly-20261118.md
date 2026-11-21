# 技能广场详情移除启用开关（2026-11-18）

范围：客户端 `/workspace/square?type=skills&skill=<id>` 的技能详情。沿当前独立 bugfix 分支交付至 `feat/3.1.0-beta1`，不修改审批源码、技能状态 API 或数据。

原因为广场向共用详情传了 noop，但详情无条件渲染启用 Switch，导致只读入口显示不可持久化的开关。`onToggle` 改为可选，仅在真实调用方提供回调时显示；广场省略该回调，其他管理入口保持原调用。技能 ID、状态标签、详情/预览、管理操作与文案样式均沿原实现。

验证：

- 全量前端 `pnpm lint` 通过，改动文件 ESLint、architecture guard、diff whitespace 检查通过。
- 既有 `SkillCenterPane.test.tsx` 4 项通过，涵盖语言/搜索/详情及其他入口的真实启停调用。
- 原 Jest 启动因本机可选 `canvas` 缺失原生 binary 失败；仅在测试进程通过临时 Node preload 将可选 canvas 视为未安装后执行上述用例。未安装依赖、未改锁文件/测试配置，不涉及画布功能验证。
- 全量 typecheck 在 platform 阶段止于既有 `sidebarSpaceActions.test.tsx:175,180` 两个 TS2349；没有新增诊断，后续 workspace 类型检查未执行。
- 静态核对唯一两个调用方：广场无 `onToggle`；管理 Pane 仍传 `handleToggle`。未部署、未做真实浏览器页面验收；QA 部署后需打开广场技能详情确认无 Switch、仍显示状态和文件，并回归管理入口启停。

按 `.claude/skills/sdd-code-review/SKILL.md` 审查 hotfix：边界（可选回调）、认证权限（无新写入）、并发（无异步变化）、信息泄漏（无新数据）、测试（既有管理入口回归）、代码风格（复用组件）、文档同步均 PASS。无新依赖、后端或数据合同。
