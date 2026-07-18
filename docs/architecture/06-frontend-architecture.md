# 双前端架构

BiSheng 前端由两个独立的 React 应用构成：**Platform**（管理端）和 **Client**（用户端）。Platform 面向管理员和应用构建者，提供知识库管理、工作流编排、模型配置、系统设置等完整的 DevOps 操作界面；Client 面向终端用户，提供轻量化的对话交互、智能体调用和知识库浏览体验，并支持 PWA 离线访问。两个应用共享同一套后端 API（`/api/v1`、`/api/v2`），通过 Vite 代理分别转发到 FastAPI 后端。

## 应用对比

| 维度 | Platform | Client |
|------|----------|--------|
| 位置 | `src/frontend/platform/` | `src/frontend/client/` |
| 包名 | bisheng | bishengchat |
| 版本 | 2.4.0_beta1 | 2.4.0 |
| React | 18.3.1 | 18.2.0 |
| Vite | 5.3.1 (SWC 编译) | 6.3.6 |
| 开发端口 | 3001 | 4001 |
| 基础路径 | `/`（可配置） | `/workspace` |
| 构建输出 | `build/` | `build/` |
| 定位 | 管理员/构建者界面 | 终端用户对话界面 |
| PWA | 不支持 | 支持（Service Worker 自动更新） |
| 状态管理 | Zustand + React Context | Zustand（18+ slices） |
| 代码编辑器 | react-ace | CodeMirror + Monaco Editor |

## Platform 架构

### 路由体系

Platform 使用 `react-router-dom` 6.x，所有页面组件均通过 `lazy()` 懒加载，路由定义在 `src/frontend/platform/src/routes/index.tsx`。

#### 主路由组（MainLayout 内）

| 路径 | 组件 | 权限 | 说明 |
|------|------|------|------|
| `/filelib` | KnowledgePage | knowledge | 知识库列表 |
| `/filelib/:id` | FilesPage | knowledge | 知识库文件详情 |
| `/filelib/upload/:id` | FilesUpload | knowledge | 文件上传 |
| `/filelib/adjust/:fileId` | AdjustFilesUpload | knowledge | 文件调整上传 |
| `/filelib/qalib/:id` | QasPage | knowledge | QA 问答库 |
| `/build/apps` | Apps | build | 应用列表 |
| `/build/tools` | SkillToolsPage | build | 工具管理 |
| `/build/client` | WorkBenchPage | build | 工作台 |
| `/build/skill` | L2Edit | build | 技能编辑器 |
| `/build/skill/:id/:vid` | L2Edit | build | 技能版本编辑 |
| `/build/temps/:type` | Templates | build | 应用模板 |
| `/model/management` | Management | -- | 模型管理 |
| `/model/finetune` | Finetune | -- | 模型微调 |
| `/sys` | SystemPage | sys | 系统设置 |
| `/log` | LogPage | -- | 应用日志 |
| `/evaluation` | EvaluatingPage | -- | 模型评测 |
| `/dataset` | DataSetPage | -- | 数据集管理 |
| `/label` | LabelPage | -- | 数据标注任务 |
| `/dashboard` | Dashboard | -- | 数据仪表盘 |

#### 独立页面（MainLayout 外）

| 路径 | 说明 |
|------|------|
| `/flow/:id` | 工作流编辑器（全屏） |
| `/skill/:id` | 技能编辑器（全屏） |
| `/assistant/:id` | 助手编辑器（全屏） |
| `/dashboard/:id` | 仪表盘编辑器 |
| `/dashboard/share/:boardId` | 仪表盘分享页 |
| `/chat/assistant/auth/:id` | 助手认证对话 |
| `/chat/flow/auth/:id` | 工作流认证对话 |
| `/chat/:id` | 对话分享页 |
| `/diff/:id/:vid/:cid` | 工作流版本对比 |
| `/report/:id` | 报告查看 |

#### 权限过滤

路由定义中通过 `permission` 字段标记权限要求。`getPrivateRouter()` 根据当前用户的权限列表过滤路由——无权限的路由不会注册到 Router 中，用户无法通过 URL 直接访问。管理员使用 `getAdminRouter()` 获取全部路由，不做过滤。

未登录用户使用 `publicRouter`，仅暴露登录页、密码重置页和对话分享页。

### 状态管理

Platform 采用 **Zustand + React Context** 双层状态管理。

#### Zustand Stores（`src/frontend/platform/src/store/`）

| Store | 职责 |
|-------|------|
| `dashboardStore` | 仪表盘编辑器：撤销/重做栈、图表刷新、布局状态 |
| `editFlowStore` | 工作流编辑器：节点/边操作、画布状态、变量管理 |
| `diffFlowStore` | 工作流版本对比：版本选择、差异高亮 |
| `assistantStore` | AI 助手配置：模型参数、工具绑定、提示词 |

#### React Context（`src/frontend/platform/src/contexts/`）

Context Provider 按固定顺序嵌套（外层到内层），定义在 `contexts/index.tsx`：

```
TooltipProvider          -- Radix UI 工具提示
  ReactFlowProvider      -- @xyflow/react 画布上下文
    DarkProvider         -- 暗色模式切换
      TypesProvider      -- 节点类型注册表
        LocationProvider -- 导航状态追踪
          AlertProvider  -- 全局提示消息
            SSEProvider  -- 服务端推送事件
              TabsProvider     -- 标签页管理
                UndoRedoProvider -- 撤销/重做
                  UserProvider   -- 用户认证信息
                    PopUpProvider -- 弹窗状态
```

Zustand 用于跨页面的复杂业务状态（如编辑器），Context 用于全局基础设施（认证、主题、画布）。两者各司其职，避免单一方案的复杂度膨胀。

## Client 架构

### 路由体系

Client 路由定义在 `src/frontend/client/src/routes/index.tsx`，基础路径为 `/workspace`。整体结构围绕对话体验设计。

#### 主要路由

| 路径 | 组件 | 说明 |
|------|------|------|
| `/` | 重定向到 `/c/new` | 默认进入新对话 |
| `/c/:conversationId?` | ChatRoute | 核心对话界面 |
| `/linsight/:conversationId?` | Sop | Linsight 智能体交互 |
| `/linsight/case/:sopId` | Sop | 智能体案例执行 |
| `/app/:conversationId/:fid/:type` | AppChat | 应用对话（Flow/Assistant） |
| `/apps` | AgentCenter | 智能体/应用中心 |
| `/apps/explore` | ExplorePlaza | 应用探索广场 |
| `/channel` | Subscription | 渠道订阅 |
| `/knowledge` | Knowledge | 知识库浏览 |
| `/knowledge/space/:spaceId` | Knowledge | 知识空间详情 |
| `/knowledge/file/:fileId` | FilePreviewPage | 文件预览 |
| `/share/:token/:vid?` | Share | 分享链接入口 |

Client 保留了旧路由 `/chat/:conversationId/:fid/:type` 的兼容重定向，自动跳转到新路径 `/app/...`。

### PWA 支持

Client 通过 `vite-plugin-pwa` 集成 Progressive Web App 能力：

- **注册方式**：`injectRegister: 'auto'`，自动注入 Service Worker 注册代码
- **更新策略**：`registerType: 'autoUpdate'`，新版本自动激活，无需用户确认
- **缓存范围**：JS、CSS、HTML 文件及应用图标，单文件最大 4MB
- **排除项**：`images/` 目录、Source Map、`index.html`（由网络优先策略处理）
- **导航回退**：排除 `/oauth` 路径，确保 OAuth 回调不被 Service Worker 拦截
- **开发模式**：禁用 Service Worker，避免热更新冲突

### 状态管理

Client 采用纯 Zustand 方案，通过 18 个 slice 组织状态（`src/frontend/client/src/store/`）：

| Slice | 职责 |
|-------|------|
| `families` | 对话/消息家族树 |
| `endpoints` | API 端点配置 |
| `settings` | 用户设置偏好 |
| `language` | 语言切换 |
| `linsight` | Linsight 智能体状态 |
| `prompts` | 提示词模板 |
| `modeltype` | 模型类型定义 |
| `search` | 搜索状态 |
| `submission` | 消息提交队列 |
| `text` | 文本输入缓冲 |
| `toast` | 提示通知 |
| `user` | 用户认证 |
| `artifacts` | 制品/附件管理 |
| `preset` | 预设配置 |
| `temporary` | 临时状态 |
| `misc` | 杂项 |

所有 slice 通过 `store/index.ts` 统一导出，组件按需导入对应的 selector。

## API 通信层

### 请求拦截（Platform）

Platform 的 HTTP 通信基于 Axios 封装（`src/frontend/platform/src/controllers/request.ts`）：

**请求拦截器**：
- 从 `localStorage.ws_token` 读取 JWT token
- 注入 `Authorization: Bearer {token}` 请求头
- 跳过 MinIO 文件请求（`/bisheng` 前缀）的认证头注入

**响应拦截器**：
- 正常响应：解包 `{ status_code, data, status_message }` 格式，`status_code === 200` 时返回 `data`
- Blob 响应：直接返回（用于文件下载）
- 业务错误：将 `status_code` 映射到 i18n 错误消息（`errors.{code}`），找不到翻译则使用原始 `status_message`
- 401：登录过期，清除本地用户信息并刷新页面
- 403/404：GET 请求跳转到对应错误页
- 10599/17005：应用无编辑权限，跳转到应用列表
- 10604：异地登录，触发远程登录回调

**登录认证**：
- RSA 加密密码传输，公钥从 `/api/v1/user/public_key` 获取
- 使用 `jsencrypt` 库进行客户端加密

### API 模块

Platform 的 API 调用函数按功能模块组织在 `src/frontend/platform/src/controllers/API/` 下：

| 模块 | 说明 |
|------|------|
| `index.ts` | 核心 API（知识库、用户、配置、助手、模型等） |
| `workflow.ts` | 工作流 CRUD、节点配置、执行调试 |
| `flow.ts` | Flow 应用管理 |
| `dashboard.ts` | 仪表盘数据查询 |
| `user.ts` | 用户管理、角色、权限 |
| `log.ts` | 日志查询 |
| `finetune.ts` | 模型微调任务 |
| `label.ts` | 数据标注 |
| `evaluate.ts` | 模型评测 |
| `tools.ts` | 工具集成 |
| `linsight.ts` | Linsight 智能体 |
| `assistant.ts` | 助手配置 |
| `workbench.ts` | 工作台 |
| `pro.ts` | 高级功能 |

每个模块导出异步函数，内部调用封装的 Axios 实例。函数命名遵循 `动词 + 名词` 惯例（如 `getKnowledgeList`、`createWorkflow`、`deleteAssistant`）。

## 组件库

### bs-ui 组件体系

Platform 基于 Radix UI 原语 + Tailwind CSS 封装了一套业务组件库，位于 `src/frontend/platform/src/components/bs-ui/`，包含 38 类组件：

| 分类 | 组件 |
|------|------|
| 表单输入 | input, select, checkBox, radio, radio-group, slider, switch, toggle, toggle-group, multiSelect, calendar, upload, voice |
| 数据展示 | table, badge, progress, skeleton, card, separator, label, editLabel |
| 反馈通知 | alert, alertDialog, dialog, toast, tooltip, popover, sheet |
| 导航布局 | accordion, tabs, pagination, step, dropdownMenu |
| 操作按钮 | button, command |

所有组件遵循 Radix UI 的无障碍规范（WAI-ARIA），通过 `class-variance-authority`（CVA）管理样式变体。

### 图标库

`src/frontend/platform/src/components/bs-icons/` 提供统一的 SVG 图标组件，支持大小和颜色自定义。

### 工作流画布

工作流编辑器基于 `@xyflow/react`（v12.8.4）构建，提供节点拖拽、连线、缩放、小地图等交互能力。画布状态通过 `editFlowStore`（Zustand）管理，`ReactFlowProvider`（Context）提供实例访问。

## 国际化

两个前端均使用 `i18next` + `react-i18next` 实现多语言支持。

**支持语言**：
- `zh-Hans` -- 简体中文
- `en-US` -- 英文
- `ja` -- 日文

**命名空间**（Platform）：
- `bs` -- 通用业务文本
- `flow` -- 工作流编辑器专用文本

**动态品牌配置**：通过 `window.BRAND_CONFIG` 注入品牌名称、Logo 等可定制元素，支持不同部署环境的品牌适配。

**翻译加载**：采用 `i18next-http-backend` 按需加载翻译文件，避免首屏加载全部语言包。

## 构建与代理

### Vite 代理配置

开发模式下，两个前端通过 Vite 内置代理将 API 请求和文件服务请求转发到后端。

#### Platform 代理（端口 3001）

| 路径匹配 | 目标 | 说明 |
|----------|------|------|
| `/api/` | `http://127.0.0.1:7860` | FastAPI 后端 API |
| `/health` | `http://127.0.0.1:7860` | 健康检查 |
| `/bisheng` | `http://localhost:9000` | MinIO 对象存储（文件/图片） |
| `/tmp-dir` | `http://localhost:9000` | MinIO 临时文件目录 |

#### Client 代理（端口 4001）

| 路径匹配 | 目标 | 路径重写 | 说明 |
|----------|------|---------|------|
| `/workspace/api` | `http://127.0.0.1:7860` | 去除 `/workspace` 前缀 | 后端 API |
| `/workspace/bisheng` | `http://localhost:9000` | 去除 `/workspace` 前缀 | MinIO 文件 |
| `/workspace/tmp-dir` | `http://localhost:9000` | 去除 `/workspace` 前缀 | MinIO 临时文件 |

Client 的所有代理规则都需要重写路径，去除 `/workspace` 基础路径前缀后再转发。

### 构建分包策略

#### Platform 分包

Platform 按依赖类型拆分为 5 个 vendor chunk，避免单一巨型包：

| Chunk | 包含内容 |
|-------|---------|
| `vendor-pdf` | pdfjs-dist（PDF 渲染） |
| `vendor-xlsx` | xlsx, mammoth 及其传递依赖（文档处理） |
| `vendor-editor` | react-ace, ace-builds, react-syntax-highlighter, vditor（代码/文本编辑） |
| `vendor-markdown` | react-markdown, rehype/remark 插件, MathJax, DOMPurify（Markdown 渲染） |
| `vendor` | 其余所有 node_modules（React, Radix, recharts, xyflow, i18n 等） |

业务代码不做手动分包，依赖 Rollup 根据 `lazy()` 动态导入自动生成 code splitting。

#### Client 分包

Client 采用更细粒度的分包策略，将 30+ 种依赖分别拆分为独立 chunk（sandpack, virtualization, i18n, codemirror 系列, markdown, radix-ui, framer-motion 等），剩余依赖归入通用 `vendor` chunk。业务代码中的 `src/locales/` 翻译文件单独拆分为 `locales` chunk。

## 相关文档

- 系统架构总览 -- `docs/architecture/01-architecture-overview.md`
- 后端领域模块总览 -- `docs/architecture/02-backend-modules.md`
- 部署架构与配置 -- `docs/architecture/08-deployment.md`
