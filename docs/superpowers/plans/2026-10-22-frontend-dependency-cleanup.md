# Frontend Dependency Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 清理无效依赖，将两端仍在使用的列表排序切到受维护的实现，保持业务行为与页面样式。

**Architecture:** 已有 pnpm workspace + catalog 继续作为共享版本入口。列表排序采用 `@hello-pangea/dnd`，通用拖拽仍按实际用途保留 `react-dnd`；先证明旧组件不可达再删除依赖，不为清理依赖重新接回旧功能。

**Tech Stack:** React 18.3.1、TypeScript、pnpm 9.15.9、Vitest / Jest；固定 `@hello-pangea/dnd` 18.0.1、共享 `react-window` 1.8.11。

**Spec:** 本会话确认的依赖治理方向及下述验收范围；用户于 2026-10-22 批准实施；开发和技术验证完成，真实业务环境验收待用户执行，见同目录 verification 文档。

## Global Constraints

- 先拉取最新 `feat/3.0.0`，已在 `codex/frontend-dependency-cleanup` 分支执行，基线为 `6331d7cfc`。
- 走 `docs/SDD-Guide.md` §1 维护路径：依赖替换、删除不可达代码，不改变产品契约。出现排序语义、交互或数据契约变化时，暂停该项并找用户判断。
- 不升级 React，不全局开启 StrictMode；在隔离测试中验证拖拽组件兼容 StrictMode。
- 不调整视觉，不迁移状态库，不顺带替换 `react-color` 或尚在使用的 `react-dnd`。
- 每个状态只有一个来源；保持原有排序 ID、保存接口、提交时机和顺序持久化行为。
- 真正跨应用共用的依赖纳入 catalog；客户端专用依赖仍在 client 管理，不为形式统一扩大共享范围。
- 不使用整仓 stash/reset/clean/restore，不收录其他任务的文档；不自动推送或同步 release。
- 测试单 worker，两个生产构建串行；避免全工作区重装引起 canvas 等无关依赖变化。
- 修改带旧中文字符串的源文件时按仓库 i18n 规则处理；若形成明显额外工作量，单列说明，不借机重构业务。

## Review Focus

1. 工作流选项拖动后仍能继续编辑文字，取消或拖回原位置不误保存。
2. 抽屉、弹窗和滚动容器内拖动位置正确，滚动、点击、输入不会被拖拽劫持。
3. 排序保存后刷新仍保持一致；空列表、单条、列表重新加载不丢失或重复项目。
4. 鼠标和键盘排序可用；隔离 StrictMode 测试没有注册丢失或节点定位错误。
5. 清理旧拖拽文件不恢复已经移除的第二条文件上传监听，单次拖入只上传一次。

## 现状与范围

- `react-beautiful-dnd` 13.1.1：platform 8 个源文件、client 1 个源文件直接导入。其中 `TaggingSheet` 的已知调用被注释，先追踪入口再决定删除或迁移。
- `@types/axios` 0.14.4：platform 的废弃占位类型包，Axios 已自带类型。
- `react-virtualized` 9.22.6：直接引用仅见于 client 的 `Mention.tsx` / `PromptsCommand.tsx`，初查未找到组件调用，需排除动态导入与导出链。
- `react-window`：两端实际锁定均为 1.8.11，只统一声明，不跨到新的大版本。
- `react-dnd` / `react-dnd-html5-backend` 16.0.1：client 仍有收藏拖拽等引用，保留；旧 `DragDropWrapper` 不重新接入。
- `react-color` 2.19.3：platform 的主题和看板配色仍使用，本轮保留并继续冻结新增调用。

## 第一批：低风险清理和版本集中管理

**Files:** `src/frontend/platform/package.json`、`src/frontend/client/package.json`、`src/frontend/pnpm-workspace.yaml`、`src/frontend/pnpm-lock.yaml`；按入口审计结果删除 client 的 `src/components/Chat/Input/{Mention,PromptsCommand}.tsx`，更新对应 app 的 `AGENTS.md` / ESLint 规则。

**接口边界：** 不改变运行中的组件或 API；删除项必须有完整的入口不可达证据。

- [x] 记录当前 lint / 类型基线和构建大小；建立依赖及调用入口清单，覆盖静态引用、导出链、路由、动态导入与 glob 加载。
- [x] 删除 `@types/axios` 声明及只属于它的锁文件节点；运行 platform 类型检查，与基线逐项比较。
- [x] 证明两个旧输入组件不可达后，一起删除旧文件及 `react-virtualized` 声明；共享工具只删除确认没有其他调用者的部分。如果发现有效入口，保留该项并单独记录待迁移，不强删。
- [x] 将两端 `react-window` 改用 catalog，固定 1.8.11；不升级其他依赖。核对 `react-dnd` 的有效入口并保留依赖和 Provider。
- [x] 收缩生成的 ESLint suppressions，不手工放宽规则；验证被删组件不存在运行时引用，确认原有冻结规则覆盖剩余遗留依赖。
- [ ] 串行构建两端已通过；文件预览长列表、真实聊天上传和收藏入口仍待业务验收。
- [x] 单独提交本批清理结果，记录删除依据与依然保留的依赖。

## 第二批：按业务模块替换列表排序

**共同修改：** 两端 `package.json`、workspace catalog / lockfile，以及冻结规则和文档。拟采用的 18.0.1 官方 peer 声明支持 React 18 / 19；实施前再次核对已发布包元数据、许可证和安装来源。新包自带类型，不新增旧库的类型依赖。

**接口边界：** 保留现有组件 Props、业务排序 ID 和持久化回调；不抽象新的通用业务组件，不维护两套列表排序实现。

| 顺序 | 模块 | 修改文件（相对 `src/frontend/`） | 人工验收 |
| --- | --- | --- | --- |
| 1 | 工作流交互选项 | `platform/src/pages/BuildPage/flow/FlowNode/component/DragOptions.tsx` | 输入/输出节点选项排序、继续编辑、删除、保存再打开 |
| 2 | 工作台配置 | `platform/src/components/LinSight/ToolSelector.tsx`；`platform/src/pages/BuildPage/bench/{OrgKbConfig,RecommendedAppsConfig}.tsx` | 工具、知识库、推荐应用排序和保存 |
| 3 | 知识库切分规则 | `platform/src/pages/KnowledgePage/components/FileUploadSplitStrategy.tsx` | 多条规则排序、编辑与保存 |
| 4 | 变量和应用模板 | `platform/src/components/VariablesComponent/VarDialog.tsx`；`platform/src/pages/BuildPage/appTemps.tsx` | 变量顺序、模板顺序，刷新后结果一致 |
| 5 | 客户端应用分类 | `client/src/pages/apps/components/MarkLabel.tsx` | 分类排序、取消、保存后应用导航顺序 |

每个模块执行相同的小闭环：

- [x] 先记录现有排序结果和保存载荷；补一个真实交互回归，而不只 mock 排序库调用回调。
- [x] 引入 catalog 固定的新包，迁移该模块导入和确有必要的类型/兼容处理；遇到拖拽占位、ref 或数据属性依赖时逐处核对。
- [x] 用隔离 StrictMode 测试执行至少一次键盘排序，断言顺序、回调次数和项目 ID；取消操作不产生保存。工作流复用并补强 `DragOptions.test.tsx`，明确覆盖排序后继续编辑。
- [ ] 已用真实组件和隔离 API 验证鼠标/键盘、滚动和保存载荷，工作流/模板重载通过；各模块真实后端保存后刷新待业务验收。
- [x] 测试通过后按模块提交，避免把多个尚未验收的模块混成一次提交。

收尾：

- [x] 再次追踪 `platform/src/components/bs-comp/sheets/TaggingSheet.tsx`；确认无入口则删除死组件及无效引用，否则按相同规则迁移并列入验收。
- [x] 全仓搜索后移除两端 `react-beautiful-dnd` 声明、锁文件节点及旧类型残留；保留禁止重新引入旧库的 lint 规则。
- [x] 不改 `react-dnd` 收藏拖拽，不重新连接旧文件上传拖拽监听。

## 第三批：整体验证和交付

- [x] 检查 catalog 与锁文件：两端排序库版本唯一；`react-beautiful-dnd` / `@types/axios` 不再解析；`react-virtualized` 删除或有明确保留入口与理由。
- [x] 在 `src/frontend/` 运行 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`、`pnpm test:config`；已有问题逐项对照基线，不新增 suppression 或 strict-ignore。发生新错误必须修复。
- [x] 运行各模块的 Vitest / Jest 回归，单 worker；按上表逐模块完成浏览器验证，不用纯单元测试代替真实拖动。
- [x] 串行运行 `pnpm build:platform`、`pnpm build:client`；检查生产页面启动，以及拖拽模块按需加载没有运行时错误。
- [x] 用相同压缩与构建口径比较本批前后产物；记录 gzip 差异，不预先承诺一定减少体积。
- [ ] 特别回归工作流画布拖动/缩放、代码编辑、文件上传一次、长列表预览及主题/看板配色；已通过相关输入/文件/配色自动化测试，真实页面组合验收待用户执行。
- [x] 完成对照 `feat/3.0.0` 的独立维护变更 review（无 spec/design，按维护路径审查），交付测试结果和逐模块验收表；用户明确要求后再合并、推送和删除开发分支。

## 暂不实施

- 不统一所有拖拽场景到一个库：列表排序、画布拖拽、文件上传的语义不同。
- 不替换 `react-color`，不新增颜色选择器设计；后续由共享库已有设计和落地组件决定。
- 不迁移 Recoil，不扩大本轮为框架或 React 大版本升级。

## Sources

- 官方归档与替代方向：https://github.com/atlassian/react-beautiful-dnd/issues/2672
- 拟采用包的版本、类型和 React peer 声明：https://github.com/hello-pangea/dnd/blob/main/package.json
- 工作区真实版本与入口：`src/frontend/{client,platform}/package.json`、`src/frontend/pnpm-lock.yaml` 及上述业务文件（2026-10-22 核查）。
