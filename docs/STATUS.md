## 2026-10-20 — 会话内技能选择与旧菜单统一

- 已有 Chat 会话的输入框以 allowConfiguration=false 隐藏技能入口和挂载资源；该配置仅控制首页配置项，技能入口按用户任务能力与实际执行回调判断，已选技能随当前输入框显示。
- 技能菜单统一复用可执行 SkillSelector，选择状态由所属输入框传入；任务页与移动端菜单沿用同一状态，旧技能中心详情导航从输入菜单移除。ChatKnowledge 旧菜单使用调用方提供的技能选择器。
- 定向 ESLint 与 diff-check 通过；构建及 3006 会话内交互验证进行中。桌面共享分支已核验 232d860；账号控件运行页样式表缺失，完整重启后恢复，同事设置与字号源码保持。

## 2026-10-20 — 输入框技能挂载与深色表面归属

- Chat 的预览技能入口接入了技能中心详情导航。输入框统一使用平台可执行 SkillSelector 与现有选择状态；选择技能就地开启已有任务执行通路并挂载资源卡，保留输入草稿和当前路由，取消技能详情导航。入口遵循任务能力权限；名称与描述继续使用统一字号，指令布局保留单行说明。
- 输入框移除通用 bg-white 类，表面由 dsh-composer-bg 管理，避免桌面深色通用背景转换把它映射为页面底色。
- 定向 ESLint、生产构建和 diff-check 通过；3006 已发布 8e5e22a05，461 文件校验、健康检查与其他容器保持通过。网页和桌面实际选择 Excel 技能后在原 /c/new 路由显示资源卡，移除保留输入草稿；沿用已有任务执行协议，本轮未发送模型任务。深色输入框与 Work 多点取色均为 RGB(44,44,46)，随后恢复浅色设置。证据：主工作区 outputs/skill-mount-dark-20261020。

## 2026-10-20 — 技能选择器文字对齐 Work

- Work Harness 0.2.0-rc.2 的 popupSelect 使用名称 12px、描述 11px；Chat 原来为 13px / 12px，名称字重已为 400。技能内容来源与文字样式独立处理。
- Chat 技能页使用 12px 名称 / 11px 描述及原有 400 字重、主次文字颜色；字号由菜单层级变量统一提供，一级菜单继续 13px / 12px，名称优先与描述省略保持。
- 验证与发布：生产构建、diff-check、3006 的 460 文件哈希及健康检查通过，其他容器保持。已发布 0c25d997e，浏览器实测名称 12px / 400、描述 11px / 400；桌面嵌入 Chat 刷新后技能列表显示正常。证据：主工作区 outputs/skill-typography-20261020。一级菜单及 Work 原生代码沿用当前版本。

## 2026-10-20 — 欢迎语移除上下切换动画

- 按用户最新反馈删除欢迎语过渡 hook、事件监听和动画测试；标题直接呈现，统一欢迎语、Logo 配置来源及已确认的首页布局保持。
- 定向 ESLint、2 项品牌与桌面桥接测试、生产构建及 diff-check 通过。部署沿用 3006 当前完整前端源，保留同事页面变更，发布 bisheng-work-120-2c78fbfcf-welcome-static-20261020；460 文件校验、路由与 API 健康检查通过，其他容器保持。
- 桌面整合最新 V1.2.0@15a65b4 后重启，Chat / Work 首页双向切换显示正常。当前使用本地开发版；证据：主工作区 outputs/welcome-static-20261020。

## 2026-10-20 — 桌面 Chat 欢迎语向下滑入

- 内嵌 Chat 首页监听宿主的欢迎区进入事件，标题采用 6px / 180ms 滑入，Logo、字号和最终位置保持。独立网页沿用静态标题；支持减少动态效果，重复进入取消旧动画，组件卸载释放监听与动画。
- 定向 3 套件 / 3 项回归、ESLint 与生产构建通过。3006 已发布 d59254119，460 个文件校验与健康检查通过；桌面 Chat 刷新加载新代码，鼠标/键盘往返后欢迎区布局正常。动画时长和取消/reduced-motion 由行为回归验证，静态截图用于确认最终布局。证据：主工作区 outputs/welcome-title-motion-20261020。

## 2026-10-20 — Chat 与 Work 统一欢迎区配置

- Landing 与桌面呈现桥复用 workbenchBranding，从构建→工作台既有 assistantIcon、welcomeMessage 生成相同的欢迎区；支持图标隐藏、绝对资源 URL 与应用相对路径。默认欢迎语统一为“来一起创造”，保留管理员当前配置与图片；用户继续在后台上传图标。
- 桌面呈现报告仅增加公开欢迎语与图标字段；Work 消费同一配置，不传递完整工具或模型配置。桌面对应基线 bisheng-work/V1.2.0 a77dd7612 / Harness 0.2.0-rc.2。
- 自动验证：2 套件 / 2 项定向回归、定向 ESLint、生产构建与 locale 生成检查通过。3006 已发布 374bba73e，460 个构建文件校验及健康检查通过，其它容器保持；保留当前部署的 aiAccess 桌面设置能力。原生开发客户端重新启动并刷新 Chat，Chat 与 Work 读取相同现有图标、欢迎语和位置，当前图标配置保持。截图见主工作区 outputs/welcome-branding-20261020。

## 2026-10-20 — Chat 输入框原生细节对齐

- 参照当前 Work / Harness conversation 与 model-selection UI 0.2.0-rc.2，Chat 卡片采用 28px + superellipse(1.5) 连续圆角；发送按钮采用原生 16px 实心箭头。
- 模型按钮独立拥有 13px/400 字体与左右 8px/4px 内边距，采用原生 14px 下拉图形，保留 Work 模型与操作区之间的活动槽留白；窄卡片按容器宽度收紧留白。首页已确认的标题与卡片布局保持。
- 定向 ESLint、生产构建、diff-check 通过；3006 已发布 037d2a0ed，459 个构建文件校验与健康检查通过，其他容器保持。Chrome 实测卡片 114px、28px + superellipse(1.5)，模型 13px/400、左右内边距 8px/4px，下拉可打开并关闭。桌面 Chat 聚焦刷新后，和同窗口 Work 截图核对：发送箭头相对边界一致，禁用按钮底色均为 RGB(185,200,241)，模型下拉与发送间距一致；标题与卡片位置保持。证据：主工作区 outputs/home-controls-20261020。

## 2026-10-20 — Chat / Work 首页布局对齐

- Work 参照为正在运行的 bisheng-work-chat-work@1f3bbb041、Harness 与 conversation UI 0.2.0-rc.2；远端 V1.2.0 当前 a77dd7612。此次改动集中在 Chat 网页首页。
- Chat 采用 Work 的 40px 空标题栏、34px 品牌标记、26px/32px 标题、居中 244px 基础布局（含输入区底部 4px 留白）及 952px 最大输入框；标题与卡片之间保留 Work 中间控件占用的间距。输入框圆角 28px、正文 14px/24px、工具栏 42px、加号 28px、发送 34px，首页阴影与颜色采用当前 Work 对应值。窄窗口输入框保持 16px 侧边距。
- 定向 ESLint、生产构建、3006 发布哈希及健康检查通过，其他容器保持原状态。同一原生桌面窗口对照：Work 与 Chat 标题文字上下边缘均为截图 y=886..933；两种首页输入框高度 114px。网页实际量测圆角 28px、加号 28px、发送 34px，输入启用发送且卡片高度稳定，当前窗口无横向溢出。证据：主工作区 outputs/home-alignment-20261020。

## 2026-10-20 — 技能选择移除悬停说明

- 技能行直接呈现名称和单行描述，移除完整说明 Tooltip 及截断测量逻辑。
- 定向 ESLint、生产构建、3006 发布检查通过，其他容器保持原状态；网页技能列表确认 Tooltip 元素和触发器均为 0，桌面 Chat 刷新后技能聚焦仅呈现列表。证据：主工作区 outputs/skill-picker-tooltip-20261020。

## 2026-10-20 — 技能列表与一级菜单文字统一

- 技能名称和描述复用加号一级菜单的文字类：名称 13px/400、描述 12px/400，行高 20px；名称优先完整呈现，描述占用剩余宽度并省略。技能名称沿用菜单固定字号，统一窗口宽度变化时的呈现。
- 定向 ESLint、生产构建和 3006 发布检查通过，其他容器保持原状态。Chrome 计算样式对比确认两级菜单均为名称 13px、描述 12px、字重 400、行高 20px；原生桌面 Chat 刷新后两级菜单截图核对通过。证据：主工作区 outputs/skill-picker-type-20261020。

## 2026-10-20 — 桌面 Chat 技能菜单实际验收

- 原生 Electron 窗口的 Chat 保留着发布前的页面文档；聚焦 Chat 后执行刷新，加载 3006 最新构建。
- 实际打开加号→技能：列表正常显示，“上传技能”“管理技能”和“可用技能”标题均已移除。桌面程序沿用运行版本，本次生效于内嵌网页。
- 截图：主工作区 outputs/skill-picker-heading-20261020/desktop-skill-menu.png。

## 2026-10-20 — 精简技能菜单标题

- 移除技能选择面板的“可用技能”分组标题，列表直接接在返回栏下方。定向 ESLint 通过。
- 3006 当前基线 desktop-settings-20261020-r2 含同事的桌面设置更新；使用该版客户端源码叠加本次单文件修改构建。生产构建、发布哈希和路由健康检查通过；Chrome 实际打开技能菜单确认列表直接接在返回栏下方。部署只重建前端容器。

## 2026-10-20 — 输入框技能菜单专注选择

- 统一移除 Chat 首页、会话及深度研究技能选择菜单底部的上传与管理入口，清理菜单专用上传弹窗宿主和回调。技能中心页面继续提供管理功能。
- 定向 ESLint、生产构建、diff-check 通过。3006 已发布 de5abeeb3 前端构建，458 个构建文件校验通过，其他容器保持原状态；Chrome 实际打开技能菜单，技能列表正常呈现且底部管理入口已移除。桌面 Chat 复用该网页，刷新后加载此版本。

## 2026-10-20 — Work 知识空间检索接口

- 新增 POST /api/v1/knowledge/space/retrieve，复用登录态 KnowledgeSpaceChatService 及其空间/文件权限过滤，限定 query、space_ids、top_k 与内容长度，返回文档来源信息。
- 在 3006 后端依赖环境运行 4 项端点回归：范围去重与来源、权限失败、登录依赖、输入边界均通过；ruff format/check 与 diff-check 通过。真实非管理员权限矩阵另行验收。
- 以 3006 当前 desktop-settings-20261019-r1 复制候选发布，保留同事既有变更，只加入上述接口和 schema；已切换 work-resources-20261020-r1 并重建 API 容器。API 健康 200、匿名检索 401、网页与后台 200；其它容器身份保持。
- 源码共享分支已同步同事 9e9019575（企业市场席位快照/npm 导入）；本次部署以现有已运行发布为基础，仅加入知识检索接口，源码与整包发布范围分别记录。桌面真实请求一次调用 bisheng_knowledge_search，在选中空间返回 hdc-BISHENG.pdf 与摘要，验收通过。

## 2026-10-19 — 技能独立选择菜单与本地发布

- 加号菜单点击技能进入独立列表页，支持搜索、返回和关闭后重置；名称优先占位，描述紧随名称并在空间不足时省略。移除根菜单重复分组标题。
- 3006 实机使用企业目录入口，已为该目录与可执行选择器统一同行排版；目录点击仍按既有逻辑进入技能详情，执行接入按接口合同推进。
- 验证：菜单与知识空间 2 套件 / 11 项回归通过，1457 个 strict 文件检查、变更文件 lint、三语言一致性、生产构建通过。实际组件预览确认名称与描述同行显示及独立菜单交互。
- 3006 已发布 15f319c06，前端内容哈希一致，后台及其他容器保持原实例；本轮发布记录见主工作区 outputs/composer-release-20261019/catalog/deployment.json。桌面实机已确认点击技能进入独立目录、名称与描述同行、超长描述省略；截图 desktop-skill-menu.png。桌面 V1.2.0 a73f871 / Harness 0.2.0-rc.2 已完成打包、签名及 DMG 完整性校验并安装启动；Chat 使用 3006 内容。首次打包延迟来自 Electron 下载超时，改用本机同版本 43.0.0 后完成。
- 企业 Work 技能目录同步和本地执行仍按 ENTERPRISE_SKILL_EXECUTION_CONTRACT.md 单独跟进。

## 2026-10-19 — Chat 输入框上方的能力面板

- 源码基线：`feat/bisheng-work-120@e85f8ef210a035a87309c76c5f2be0816d0edb2b`；工作目录 `.worktrees/bisheng-desktop-navigation`。本轮修改平台 client，桌面嵌入 Chat 加载同一前端。Work 原生参考版本为 bisheng-work `feee3b5b14ced1cead6bcd09ca69b7d777e888c9` / Harness `@deepseek-ai/dsh@0.2.0-rc.2`；桌面共享 V1.2.0 已有后续提交 a73f871，本轮保持桌面代码独立。
- 加号展开为输入框同宽、顶部间隔 4px 的面板，按添加资源/工具组织；已配置工具共用已有选择状态，在加号右侧显示可取消标签。技能在面板内展开和搜索，选中后沿用平台任务模式提交路径。知识空间弹窗保留草稿确认语义，增加资源图标、修改时间和选中底色。
- 组件实现使用平台现有 Radix 菜单、技能选择器和语义主题变量，对齐 Harness 面板布局。Chat 远程页面与 Work 原生渲染进程继续使用各自组件运行环境。
- 验证：3 个套件 / 15 项定向回归、变更文件 ESLint、1456 个 strict 文件类型检查、i18n 一致性及生产构建通过。实际组件示例预览验证浅色/深色、技能展开选择、知识空间勾选确认、工具标签与 Escape 后焦点返回。窗口尺寸变化由自动回归覆盖。全量 client lint 报告 22 errors / 1 warning，均位于本轮保持原样的四个文件；变更文件单独检查通过。预览资源为测试数据；真实企业执行、3006 发布和安装包验收分别记录。
- 用户确认企业执行边界：毕昇统一管理技能和授权，Chat 在平台执行，Work 在桌面执行。目前平台任务模式已有技能选择与提交链路；统一授权目录、Work 本地同步与运行时注册列入后续接口工作，见 `ENTERPRISE_SKILL_EXECUTION_CONTRACT.md`。
- 本轮证据位于主工作区 `outputs/composer-panel-20261019`。此记录对应本地源码和组件验证，部署状态以发布记录为准。

## 2026-10-19 — 桌面导航桥接

基于 4269304db 接入桌面共享菜单；功能页沿用设计师最新实现，导航入口沿用既有账号权限及开关。生产构建、strict typecheck 与改动文件 lint 通过。详见 DESKTOP_NAVIGATION_CONTRACT.md。3006 已部署首轮导航桥接 93d4df622，原生窗口已成功打开订阅、应用与技能中心。实测发现嵌入内容区触发 H5 布局，统一布局策略现明确使用桌面布局，浏览器保持原有响应式规则；回归 3 套件通过，构建与变更 lint 通过。知识空间 mine/department 接口返回 500，后端日志显示历史 auth_type=review 与当前枚举 PUBLIC/PRIVATE/APPROVAL 不匹配，作为独立服务端问题记录。

## 2026-10-19 — Desktop Chat session exchange restored

- Shared baseline: `feat/bisheng-work-120@562ee4e6a`. The full-stack migration omitted the prior desktop session exchange route and its HTTP/WebSocket validators, causing desktop Chat to receive 404 while browser login remained available.
- Restored `POST /api/v1/dsh/web-session`: authenticate the desktop access grant, issue a browser JWT for at most 300 seconds, and retain the original credential only in server-side Redis. Browser requests and WebSocket connection authorization recheck the desktop identity, tenant, seat and grant. Ordinary browser session policy remains separate; HTTP token-version checks remain active for both.
- Automated verification: 51 tests passed in an isolated container using the deployed backend dependencies, covering exchange, expiration, revoked grants, tenant changes, credential routing and HTTP/WebSocket integration. Changed-file Ruff checks and architecture guard passed; the existing auth.py lint findings match the baseline.
- Real-client validation exposed the companion JWT signer lifetime parameter omitted during migration. `AuthJwt.create_access_token` now accepts the explicit short lifetime while keeping the configured default for ordinary browser login; a real-signer regression verifies both expiration contracts.
- Deployment and real desktop acceptance are recorded separately in the deployment evidence. No schema or dependency change is required.

# 2026-10-16 Chat 交付到 feat/bisheng-work-120

- 当前协作仓库：`dataelement/bisheng`，共享分支：`feat/bisheng-work-120`。已确认当前账号具有 push 权限，按用户要求直接提交到该分支。
- 基线：`d8326651b4b34d10dc244b156c199b603185a9fe`。从 PR #2495 的 `ba002ab0facd54099b88cce3ca598b6e93c86aff` 迁移 Chat 净改动，沿用 120 的依赖、文件类型校验、媒体解析提示、按顺序渲染附件及引用功能。
- 包含 DSH Chat 样式、嵌入导航与主题同步、首次发送状态、统一资源卡片、知识空间弹窗、加号能力菜单、已选能力标签和模型选择列表。源码范围为 client 和文档。
- 验证：锁文件安装、生产构建、1389 个 strict 文件检查通过；26 套件 / 236 项回归通过。变更文件 ESLint 通过。全量 client lint 的 22 errors / 1 warning 与干净 120 基线逐条一致。
- 独立基线问题：`useSaveArtifactToKnowledge.test.ts` 因 filenamify 的 ESM 加载失败，干净 120 同样复现，单独记录。DOM 测试使用 jsdom 的可选 canvas 缺省路径；本机原生 canvas 二进制缺失。
- 运行环境：3006 保持已部署的 beta4 `chat-model-picker-20261016-r2`；本次为 120 源码交付。120 完整企业登录、真实模型请求和全格式文件预览实机复验待执行。桌面代码继续在 `dataelement/bisheng-work / V1.2.0` 协作。
- 下方为历史实施、发布及验收记录；当前协作分支以本节为准。

# 2026-10-16 Chat 模型列表与 Work 对齐

- AiModelSelect 采用已有 Radix Popover 与 Ariakit Combobox：默认向上、右侧对齐，搜索框、34px 列表行、右侧选中勾选、键盘选择与关闭后焦点恢复。尺寸沿用 Harness 0.2.0-rc.2 ModelSelect：240–420px 响应宽度、360px 最大高度、13px 模型文字。
- Chat 保留毕昇配置的模型列表、去重与无效模型修复，手动选择和默认值修复分别回调；Work 保留本机及企业模型来源。Chat 接口当前提供模型名称和说明，分组需要真实供应商字段。
- 自动验证：模型选择 3 项及会话模型记忆 16 项，共 19 项通过；变更文件 ESLint、beta5/beta4 生产构建通过。beta5 严格类型检查继续报告基线 useAiChat.test.ts:294 的测试数据类型问题，本轮文件检查通过。
- 3006 发布 chat-model-picker-20261016-r2，422 项源码/构建文件哈希校验通过，前后端健康 200，其余服务保持；beta4 语言包同步补齐搜索无结果文案。
- 企业测试客户端基线 bisheng-work/V1.2.0@e9f2063，Harness 0.2.0-rc.2。实际检查浅色/深色浮层、搜索无结果、清空搜索、键盘选择及焦点返回；恢复浅色与原知识空间、联网搜索、深度研究草稿。当前 Chat 仅配置 qwen，多模型筛选由自动测试覆盖。本轮验证范围为选择器交互，模型请求及完整 beta5 企业环境验收沿用此前边界。
- 截图与发布证据：workbuddy/outputs/chat-model-picker-20261016。网页交付进入 PR #2495，目标 feat/bisheng-work-103；桌面继续加载已更新的 3006 Chat。

# 2026-10-16 加号右侧显示已选能力

- 联网搜索、深度研究启用后在加号右侧显示可取消标签；关闭后收起，菜单和标签共用现有状态与回调。
- 标签采用紧凑行内布局，窄窗口可横向滚动；新建/已有会话沿用现有配置边界。
- 自动验证：菜单及标签双向同步 3 项通过，变更文件 lint、beta4/beta5 生产构建通过。3006 发布 chat-active-capabilities-20261016-r1，前后端健康 200，其余服务保持。企业客户端实测两项同时显示、标签取消及菜单勾选同步；未发送模型请求。截图见 workbuddy/outputs/chat-active-capabilities-20261016/selected-capabilities.png。

# 2026-10-16 Chat 加号菜单收拢

- 加号采用 Harness 0.2.0-rc.2 InputBar 的 28px 圆形按钮、14px/1.3px 图标与居中布局。
- 文件、知识空间、联网搜索、深度研究及可用技能统一在加号菜单中操作；输入框底部显示加号、模型、发送/停止。
- 工具选择复用现有初始化、企业配置过滤及选中状态，首次发送后沿用原有配置限制。
- 自动验证：3 套件 / 6 项通过，覆盖配置默认值、菜单勾选、重新打开后的状态、研究切换、上传和已有会话入口。变更文件 ESLint、beta5/beta4 生产构建通过；beta5 strict 保留目标基线 useAiChat.test.ts:294 的一项 fixture 类型诊断。
- 3006 已发布 chat-add-menu-20261016-r3，433 项源码/构建文件核验通过；前后端健康 200，其余容器保持。企业 V1.2.0 测试客户端实测圆形加号、联网搜索勾选、深度研究开关、知识空间回显和明暗菜单；最终深色悬停状态复验通过。外观恢复跟随系统，草稿知识空间已恢复。实际联网/研究回答仍沿用此前验收边界，本轮未发送模型请求。
- 交付证据：workbuddy/outputs/chat-add-menu-20261016；网页改动进入既有 PR #2495，目标 feat/bisheng-work-103。

## 2026-10-16 — 输入框、资源卡片与主题统一

- Chat 的加号使用独立 ChatResourceMenu，提供文件上传和知识空间选择；工具、Skill、深度研究回到新建输入框底部。文件、知识空间、目录及技能共用 224×56px 横向资源卡片，支持类型/大小、上传状态、独立移除和横向溢出。沿用企业可见范围、原上传和上下文协议。
- 根因修复：ThemeContext 恢复用户选择的明暗模式，系统监听仅作用于 system；useDesktopAppearance 在独立网页读取页面外观，在嵌入页同步宿主主题到根 class，使 Portal 与页面同源。云端历史标题采用与 Work 一致的缩进及长标题焦点/悬停滚动。
- 自动验证：4 文件 / 11 项实际组件测试通过，覆盖资源删除与键盘动作、上下文保留、发送/停止、选择弹窗和宿主/页面主题。定向 ESLint、多语言一致性、beta5/beta4 生产构建通过；beta4 1281 strict 文件通过，beta5 保留基线 useAiChat.test.ts:294 fixture 类型诊断。旧附件布局的字符串断言由实际组件回归替代。
- 实机：企业客户端完成浅色/深色输入框与知识弹窗、选择回显、焦点返回加号、文件与知识空间同时选中、移除文件后保留知识空间；侧栏标题左距已对齐。外观恢复跟随系统，测试附件已从草稿移除。知识检索实际回答、全部文件格式和 beta5 正式安装包另行验收。
- 3006 beta4 前端已发布 chat-context-resources-20261016-r3，431 项源码/构建文件指纹通过，首页 SHA-256 为 0ce3436f355cc53ec7105d94d7c1c3e6bd7852b913c3682fe1e75d7cebbc9a1f；前后端健康 200、其余容器保持。网页源码进入既有 PR #2495，目标 feat/bisheng-work-103。

## 2026-10-16 — 知识空间统一到添加资料入口

- 新建和已有 Chat 共用“＋ → 选择知识空间”入口；独立知识空间按钮移除。弹窗按部门、我创建的、我加入的显示当前账号可见空间，支持搜索、多选、确认添加、取消和 Esc 放弃草稿，沿用每类 50 项限制。组织知识库及上传入口保留原有权限与协议。
- 选中空间使用现有可移除上下文标签；工具、Skill、深度研究继续只在新建时展示。知识空间与组织知识库按类型及 ID 区分，移除时保持其他类型的同 ID 项。
- 自动验证：5 文件 / 26 项通过；变更文件 ESLint、多语言一致性、beta5/beta4 生产构建通过；beta4 1278 strict 文件通过，beta5 保留目标基线 useAiChat.test.ts:294 fixture 类型诊断。
- 3006 前端发布 chat-knowledge-picker-20261016-r2，425 项文件指纹通过，前后端健康 200，其余服务保持。桌面复用既有企业登录态，已实测新建与续聊入口、搜索、选择确认、选中回显、取消/Esc 保留、清空已选及最终深色弹窗；未发送测试消息。完整知识检索回答及 beta5 安装包端到端验收另行执行。

# 2026-10-16 — 会话输入框能力边界与 CI 核查

- 新建 Chat 保留 Skill、工具、深度研究与知识空间配置。已有会话通过 allowConfiguration=false 收起选择栏、知识空间按钮及已选上下文条带；加号保留文件上传，模型、发送、停止继续可用。原有知识/技能状态继续参与会话，展示切换保持配置。
- 验证：4 文件 / 21 项定向回归通过，含实际 AiChatInput 渲染、会话状态切换、配置保留、附件发送与停止；变更文件 ESLint、多语言一致性、生产构建通过。严格类型检查保持基线 useAiChat.test.ts:294 的一项 fixture 错误。
- CI 实际失败：Frontend Quality run 38873431906 / job 116882714781 停在 Lint platform（93 errors），后续 client lint 和两个 typecheck 步骤跳过。最新 run 38874654073 同样停在该步骤。93 项与干净目标基线一致，涉及 API/Citation 的 any、敏感策略硬编码文案/Hook 依赖及 License 测试文案。工作流评估代码规范与类型，不对视觉质量评分；本 PR 保留现有质量检查和抑制规则。
- 3006 同步采用 beta4 对应实现，并保留 model-discovery-inline-status-20261016 的同期更新。实机已验证新建入口保留、已有会话简化、加号菜单只有上传文件；beta5 PR 的真实服务验收与安装包仍待执行。

# 2026-10-16 — Chat 网页交付到 feat/bisheng-work-103

- Git 交付：用户已授权个人 fork；改动已推送到 SuperstructureJH/bisheng 的 codex/chat-web-103-delivery，并提交 [PR #2495](https://github.com/dataelement/bisheng/pull/2495)，目标为 feat/bisheng-work-103，当前待评审合入。
- 用户指定交付分支：dataelement/bisheng / feat/bisheng-work-103；本次以远端 5beb3bc90b2728dbdee3ae373eda50a01583f1a2（3.0.0-beta5）为基线迁移已在 3006 验收的 Chat 外观、历史侧栏、宿主主题/页面内导航、输入框上方能力栏及会话附件预览。
- 保留该分支的会话模型记忆、知识空间可见权限过滤、任务会话行为、引用对照预览、文件夹上传、推荐应用返回路径，以及企业后台代码。桌面继续由 bisheng-work/V1.2.0 提供左侧导航和本地 Work。
- 追加首次发送修复：ChatView 按当前乐观消息状态上报欢迎页状态，桌面即时收起 Chat / Work；KeepAlive 页面按当前路由过滤，独立网页继续正常运行。新增 2 项行为回归通过，配套桌面改动位于 bisheng-work/V1.2.0。
- 验证：锁文件安装和 client 生产构建通过；9 个定向测试文件 / 117 项通过，覆盖嵌入导航、主题交接、附件收集、预览生命周期、引用导出、模型记忆、权限过滤和任务模式。DOM 测试采用 jsdom 的可选 canvas 缺省路径；本机 canvas 原生二进制缺失，测试范围没有 Canvas 渲染。
- 全仓检查与干净基线对照：平台 lint 同为 93 项既有错误，client lint 同为 21 项既有错误，client strict typecheck 同为 useAiChat.test.ts:294 的一项 ChatMessage fixture 类型错误。本批变更文件定向 lint 与多语言一致性检查通过。
- 3006 保持此前 beta4 环境和 chat-capability-bar-20261016-r1 发布；本次负责 Git 分支交付。下方真实环境记录属于 3006 已发布版本；合入 beta5 后的安装包、企业登录和全文件格式端到端复验另行执行。

# DSH 企业后台交付状态

- 2026-09-22：跟进 #2433 的席位反馈验收。确认“重新分配”后，失败原因以“用户名 + 原因”的单个 toast 展示，约 4 秒自动消失；每次操作的同一失败只提示一次，新操作可再次提示。表格保持原列宽。已撤销席位的管理提示提供明确的重新分配步骤。批量容量错误配套 [Gateway #6](https://github.com/dataelement/bisheng-gateway/pull/6)：新增和待恢复成员统一计入所需席位，容量不足统一返回 seat_limit_reached。
  - 自动化：39 文件 / 333 项 DSH 前端回归、平台全量 lint、467 文件严格类型检查、生产构建、i18n 校验和架构守卫通过。
  - 浏览器：实际 React 组件配合模拟失败回执，确认后显示 toast，随后自动消失；7 列宽度在显示前、显示中和消失后完全一致。
  - 109：此前 Gateway 容量修复已部署，根部门及子部门保存均返回 seat_limit_reached，席位和额度保持原值；本条提交时 toast 前端发布待执行，现场席位为 8/10，真实满席点击复验为 NOT_RUN。

- 2026-09-22：基于 `feat/3.0.0-beta2-pre@a0bd8c768` 修复满席恢复授权的反馈。席位列表“重新分配”和模型额度“重新授权”统一识别持久化操作回执的 `FAILED / seat_limit_reached`，在对应用户旁显示席位不足及扩容、释放席位的处理提示；确定失败后支持使用新操作 ID 重试，请求结果待确认时沿用原操作 ID 查询。模型额度搜索框改为“搜索用户名”。部门和个人额度保存、重新授权统一按服务端错误码展示席位不足、授权过期、授权服务异常等原因，并在请求结果待确认时保留原操作 ID。新增回归覆盖即时回执、延迟结果、连接中断后确认、HTTP/业务错误和成功重试。
  - 自动化：32 个测试文件、283 项 DSH 回归通过；前端工作区 lint、类型检查，管理端生产构建、i18n 校验和架构守卫通过。模型额度保存测试已同步当前 `silent` 请求参数。
  - 真实环境：本次部署、登录态浏览器及真实 Gateway 满席/释放后重新授权验收为 `NOT_RUN`。测试环境的部门保存失败请求实际响应待采集，具体原因待确认。

- 2026-09-20：上游 PR 候选基于 `feat/3.0.0-beta2-pre@dff62d251`，完整保留企业后台整合，并纳入授权树加载稳定性与模型展示名称修复。753 项相关测试、双前端构建及定向检查通过；管理端全量类型检查有两项上游既有错误，真库与登录态验收为 `NOT_RUN`。完整范围、来源和迁移说明见 [上游交付记录](../features/v3.0.0-beta2/062-dsh-desktop-model-access/upstream-pr-delivery.md)。

- 2026-09-20：模型目录和管理端共用展示名称规则，优先采用管理员配置的 `name`，空白名称使用调用名称 `model_name`。内部模型 ID 继续用于调用、权限和额度。定向回归 48 项通过、2 项 Redis 用例按环境跳过，16 项外部数据库变体排除；Ruff 和架构守卫通过。执行方式与环境边界见 [模型名称修复验证](../features/v3.0.0-beta2/062-dsh-desktop-model-access/model-display-verification.md)。
- 2026-09-17：`codex/dsh-enterprise-beta2` 已归并最新看板、部门额度、导航、个人年度用量和隐藏审计入口，进入提测候选。
- 实现、来源、确定性检查和真实环境验收边界见 [提测交付记录](../features/v3.0.0-beta2/062-dsh-desktop-model-access/enterprise-beta2-delivery.md)。
- 当前组合分支基于最新已核验的 beta2-pre 基线；真实数据库与登录态端到端验收由提测执行。


# 3006 Chat 改造与部署历史

## 2026-10-16 — 输入框上方能力选择栏

- Skill、工具、深度研究集中在输入框上方；附件、知识空间、模型、发送保留在输入框内。Skill 使用既有企业可选技能列表、多选状态和进入任务模式的规则，继续由 skillEntry.enabled 控制。
- 3006 发布 chat-capability-bar-20261016-r1，421项源码/构建哈希通过，前后端健康200，其他容器保持。定向ESLint、1277个strict文件检查、生产构建及diff-check通过。
- 网页与桌面新建页、历史会话已验证；工具开启/关闭、深度研究开启/关闭、390px窄屏无横向溢出。桌面恢复到原会话。当前3006企业配置未开放Skill入口，技能选择的真实数据验收待该配置开放；本轮只验证此分支编译。
- 证据：主工作区 outputs/bisheng-capability-bar-20261016，源码仍在工作目录。

## 2026-10-16 — Chat / Work 样式系统核对

- 基于企业 bisheng-work/V1.2.0@5b14db873105d2b3d937e7512619e20e4914507f 与安装的 Harness 0.2.0-rc.2，统一 Chat 输入框、工具栏、气泡、正文与操作行几何；空过程节点仅在有内容时显示。知识空间/工具 Portal 使用 Chat 主题变量，移动标题栏同步主题。
- 知识空间多选、工具独立开关、深度研究切换保持毕昇现有规则；Work 本地执行行为保持。功能和样式协作边界见 docs/CHAT_STYLE_CONTRACT.md。
- 严格类型检查1276文件、定向ESLint、生产构建、diff-check通过。网页1728/1024/390宽度、新建/已有会话、多行草稿、双知识选择、工具和深度研究开关、Markdown预览展开完成实测。桌面企业身份复用、深浅Chat与菜单完成核对；测试偏好已恢复。
- 发布 chat-style-audit-20261016-r3 到3006；428项文件哈希通过，前后端健康200，其他容器保持，前端旧版本保留。证据在主工作区 outputs/bisheng-chat-style-audit-20261016。Web改动仍在工作目录，桌面代码本轮未修改。
- 本轮默认字号14px。Windows、自定义字号同步、所有复杂Markdown及全文件格式回归另行验证。

## 2026-10-16 — Chat 顶部分隔线对齐

- 参照企业版 bisheng-work/V1.2.0 当前工作树 5b14db8 与已安装 Harness 0.2.0-rc.2 的 conversation header。原生 Work 顶部 76px，Chat 原顶部 50px；网页实测额外留白为滚动层 16px 和内容层 8px。
- Chat 使用 30px 标题行、10px 行间距和对话视图区标识，总高 76px；标题中心保持 25px，分隔线位于 75.5px。对话标识对应当前正文，Work 轨迹能力保持原生实现。正文顶部间距由消息行统一提供 16px。
- 实现范围：BISHENG client 的 HeaderTitle、AiChatMessages、chat-surface.css 与三语言文案。桌面共享同一网页布局。
- 自动检查：变更 TSX ESLint、1276 strict files 类型检查、生产构建与 diff-check 通过。
- 发布 chat-header-alignment-20261016-r1。期间同事发布 model-config-alignment-20261016，保护条件先中止发布；比对两版本 client 目录完全一致后，以最新发布为基础保留其平台更新。423 文件校验、前后端健康 200、其余容器身份保持。
- 实测：3006 页面标题栏 76px、标题中心 25px、首条消息距离分隔线 16px；企业版开发窗口重启恢复账号后打开原 Chat，截图中分隔线与原生 Work 同位于 y=151 物理像素。新 Chat 的模式切换仍可见，打开已有会话后隐藏。
- 本轮为桌面尺寸标题和正文顶部布局验收，安装包与移动端专项保持原有验证边界。桌面源码维持 V1.2.0@5b14db8，本次改动由共享 Chat 网页提供。
- 证据：主工作区 outputs/bisheng-header-alignment-20261016/。

## 2026-10-16 — 聊天侧栏统一为标题与时间

- 桌面基线：bisheng-work/V1.2.0@61dfddf7376aaa09e6a2d335dcaec245e513f578，GitHub API 实时复核，Harness 0.2.0-rc.2。移除最近标题栏的刷新按钮、云端气泡图标及本地电脑图标贡献项；自动刷新、按来源导航及项目归属继续由原控制器管理。
- 毕昇网页聊天侧栏采用 280px 宽度、32px 桌面行高、8px 行圆角与标题缩进；历史统一为按更新时间排序的最近列表，右侧显示日期，重命名时让出日期空间。保留平台导航、会话菜单及分页加载。
- 自动验证：桌面 219 文件 / 1869 项通过、1 项跳过，类型检查与构建通过；网页变更文件 ESLint、严格类型检查（1276 strict files）与生产构建通过。原有 slot 断言同步移除已退役图标贡献项。
- 发布：3006 的 chat-sidebar-clean-20261016-r1 基于 model-config-compact-20261016，436 文件哈希验证、前后端健康 200，其余容器身份保持。数据库迁移 none。
- 原生验收：桌面显示标题与时间，原生本地任务可打开；网页最近列表、尺寸、当前消息、会话菜单、重命名入口/取消及桌面尺寸收起展开已验证。640px 页面无水平溢出、行高 40px；窄屏顶部入口使用既有移动菜单，完整抽屉打开未通过本轮验证，列入后续移动端专项。当前实际主题为深色，浅色本轮未完成实测。
- 证据与协作说明：主工作区 outputs/bisheng-sidebar-clean-20261016/；Web 源码在 .worktrees/bisheng-dsh-chat-3006，桌面在 .worktrees/bisheng-work-chat-work。

## 2026-10-16 — 完整网页与桌面聊天嵌入分离

- 产品边界：3006 完整毕昇网页保留平台导航和基础功能，Chat 页面沿用 DSH 风格。桌面仅嵌入聊天内容、输入框和文件预览；导航/历史由桌面提供，Work 继续由本地 Harness 负责。
- 修复 MainLayout 以聊天路由隐藏平台导航的范围错误。平台导航及移动端系统菜单现在以桌面嵌入标识控制；普通网页的知识空间、订阅、应用、权限内管理入口恢复。移动端菜单回到平台功能菜单，聊天记录沿用对话列表入口。
- 自动验证：变更文件 ESLint、生产构建、3 文件/4 项嵌入与导航测试通过；完整 Web 类型检查沿用已有存量诊断记录，本轮未重新执行。
- 发布 chat-platform-nav-20261016-r1，以当前 model-config-parameters-20261016 为基础；先核对其 Chat 构建与 r5 一致，保留同期模型配置更新。420 文件哈希、前后端健康 200、其他容器身份保持；数据库迁移 none。
- 网页实测：完整页平台菜单可见，知识空间及应用可进入；640px 窄窗口菜单能展开平台入口。桌面嵌入页继续只呈现聊天内容。当前验证涵盖入口与页面加载，其他基础功能的业务操作沿用既有实现与验收范围。
- 证据：outputs/bisheng-chat-platform-nav-20261016；用户正在使用的桌面窗口保持当前操作。本轮更新网页显示范围，桌面程序保持上一轮构建。

## 2026-10-16 — Chat 会话布局与页面保留

- 基线实时核验：bisheng-work/V1.2.0@dde330fb7f2ab61ef5baab214a959f3fb437c66e，工作树 .worktrees/bisheng-work-chat-work，分支 codex/chat-work-integration；Harness 0.2.0-rc.2。
- 主进程保留隐藏 Chat 页面的文档、尺寸与背景；模式切换只更新可见性。打开云端记录使用获授权路径映射与页面内路由，旧版网页继续走兼容加载；身份变化时丢弃旧导航完成结果。首屏 HTML 和原生视图直接采用宿主主题背景。
- Chat 正文列补齐内边距占用的 32px，标题行、气泡、输入文字及工具栏按 Work 尺度对齐。隐藏上传控件的空容器原先产生额外 12px flex 间距，现按控件可见状态正确隐藏；工具栏使用 42px 高度。Chat 保留知识空间、工具、深度研究功能，Work 保留轨迹页签。
- 自动验证：桌面定向 16 项、完整 219 文件/1865 项通过，1 项跳过；类型检查及构建通过。完整回归首次遇 Node socket setTypeOfService EINVAL，重跑干净通过。网页定向 4 项、变更文件 lint、生产构建及两仓 diff-check 通过；完整 Web 类型检查仍有存量诊断。
- 实际验收：原生客户端打开云端记录使用同一页面，Work→Chat 返回保留未发送验收草稿。最终 r5 网页实测正文内宽 920px、输入框高 98px、输入文字距卡片顶部 12px、工具栏高 42px；Markdown 右侧预览显示 DSH-CHAT-20261015。浅色 640px 窗口文档宽 640px，输入框宽 616px，控件完整可见。
- 3006 发布 chat-work-beta4-20261016-r5，425 个文件哈希校验、前后端健康 200；其余容器保持，数据库迁移为 none。最终网页样式已验证；用户正在使用的原生窗口保留当前操作，最后一轮样式在 Chat 文档刷新后加载，尚未完成该窗口 r5 最终截图验收。
- 证据：主工作区 outputs/bisheng-chat-polish-20261016/delivery.md。当前运行企业版开发窗口；安装包、Windows、跨端即时推送与全文件格式重验各自保留既有验收边界。

## 2026-10-16 — 项目与最近统一分组、输入框对齐

- 基线实时核验：bisheng-work/V1.2.0@dde330fb7f2ab61ef5baab214a959f3fb437c66e；工作目录 .worktrees/bisheng-work-chat-work，分支 codex/chat-work-integration，Harness 0.2.0-rc.2。
- WorkspaceBrowser 使用同一滚动区呈现项目与最近。项目会话归属由原 Harness sessionIds 决定；未分组 Work 与云端 Chat 按置顶和更新时间混排，电脑/对话图标标识来源，点击记录切换右侧模式。原生项目菜单、归档过滤和搜索保留。
- 当前默认工作区是实际项目，已有会话继续在其中。云端搜索匹配已加载的标题；归档专用视图呈现具有归档状态的本地记录。最近采用更新时间排序，项目原生手动排序保持。
- Chat 首页和会话输入框采用 Work 的响应宽度、114px 首页高度及边距尺度；知识空间、工具、深度研究保留。
- 自动验证：全新 npm ci 重放、typecheck、桌面与网页构建通过；219 个测试文件、1862 项通过、1 项跳过。真实 projection 回归覆盖未分组过滤、项目成员变化、归档过滤、模式选中状态及原生 fallback。
- 原生窗口验证：企业身份自动恢复、项目/最近显示、两种模式切换、云端标题搜索及单列表混排通过；点击历史记录自动进入 Chat 并读到原消息，Markdown 附件右侧预览显示原验收标记。项目成员迁移由自动回归验证，当前真人数据均属于默认工作区。
- 3006 发布 chat-work-beta4-20261016-r3；以 model-config-dialog-20261016-r2 为基础保留同期后台更新。418 个文件哈希、前后端健康 200、其余容器 ID 保持。上次发布的前端版本变化触发保护中止，校验 client 完全相同后再继续发布。
- 证据：主工作区 outputs/bisheng-recent-sidebar-20261016。当前为企业版开发窗口；安装包与跨平台验收另行执行。本轮变更集中于会话组织与布局，文件预览能力沿用上一轮验收记录。

## 2026-10-16 — 桌面共享侧栏的 Chat 嵌入布局

- `/workspace/?embed=dsh` 记录当前浏览会话的呈现标识，路由重定向与刷新后继续由桌面提供导航。Root 的聊天历史/MobileNav 和 MainLayout 的平台导航通过 React 条件挂载；独立浏览器保留原聊天侧栏。
- 3006 发布 chat-work-beta4-20261016-r1，417 个构建文件校验通过，前后端健康 200，其他容器保持，r5 可回退。
- 定向 ESLint、生产构建通过。嵌入持久性、独立网页布局和主题交接 3 项测试在独立 Node Jest 环境通过；项目默认 Jest 环境受现有 canvas.node 缺失影响。
- 真实验收：嵌入 Chat 由桌面统一提供侧栏，独立网页保留聊天导航；网页/桌面双向续聊经刷新或重开通过。Markdown、PDF、DOCX、XLSX 基础预览通过；PPTX 提供下载。完整 Web 类型检查包含存量诊断，本轮四个生产文件没有诊断。
- 桌面原生共享侧栏与历史 API 实现在 bisheng-work/V1.2.0 的 codex/chat-work-integration 分支。运行验收证据汇总于主工作区 outputs/bisheng-shared-sidebar-20261016。

## 2026-10-15 — Chat 侧栏收敛为 DSH 风格聊天历史

- Chat / 深度研究路由仅呈现聊天历史；平台导航在布局层停止挂载。历史栏沿用 DSH 的 280px 宽度、38px 居中新会话按钮、紧凑圆角行、选中底色和顶部折叠入口。窄屏菜单直接展开聊天历史。企业账号继续使用客户端既有设置入口。
- 3006 前端发布 chat-work-beta4-20261015-r5，上一版 r4 可回退。427 个源码/构建文件哈希验证通过，前后端健康 200，其他容器 ID 保持。
- 定向 ESLint、生产构建和 diff-check 通过；ESLint 工具清理已消除的抑制项。完整 TypeScript 检查仍有项目存量问题；本次修改的导航/布局文件没有诊断，Convo 的五项类型诊断与此前基线一致。
- 原生企业客户端复用原账号目录启动，自动进入新版 Chat；历史会话与 Markdown 预览实测通过。网页新会话、历史切换、侧栏收起/展开及 390px 窄屏菜单通过。现有聊天数据保留。
- 证据：主工作区 outputs/bisheng-chat-sidebar-20261015/desktop-chat-sidebar.png、deployment.json、build.log。当前代码位于 codex/dsh-chat-3006，PR 尚未创建。

## 2026-10-15 — 企业账号登录后真实验收

- 用户完成现有企业账号授权后，Chat 直接加载同一账号的毕昇会话；服务重启后重连复用企业身份，持续使用超过 20 分钟保持认证。
- 桌面发送、网页续聊、桌面重新打开会话均通过。网页上传五类附件后桌面可见；桌面上传 Markdown 后网页刷新可见附件与 NATIVE-UPLOAD-OK。同步通过刷新/重开验证，即时推送待验证。
- Markdown、PDF、DOCX、XLSX 基础内容在两端可预览。Markdown 全屏、退出全屏及模式切换后预览保留通过。PPTX 提供下载；原生下载与 fixture SHA-256 一致。
- Work 使用企业 qwen-max 完成计数验收：运行中切换 Chat，返回显示 WORK-SWITCH-OK；Chat 会话和预览保持。默认 DeepSeek 直连模型缺少密钥，验收会话已改用企业模型。
- 根因修复：历史知识空间 auth_type=review 与 beta4 隐式枚举不兼容，导致知识空间接口 500。显式字符串存储兼容历史值并统一写入 review，保留审批权限语义；未知值继续拒绝。2 项存储回归和 8 项会话回归通过；模型 Ruff 存量诊断数量和类型保持一致。
- 3006 当前发布 chat-work-beta4-20261015-r4，后端/前端健康 200，数据库仍为 beta4_merge_3006_history，r3 保留回退。客户端基线 bisheng-work/V1.2.0@dde330fb7f2ab61ef5baab214a959f3fb437c66e，Harness 0.2.0-rc.2。
- 当前能力缺口：PPT 在线预览、qwen 应用图片上传、Excel 无缓存公式计算。PDF 工具栏和网页导航等视觉细节仍待对齐。普通用户/跨租户切换、真实退出撤销、主题切换、Windows、浏览器下载待专项验收。代码在工作分支，PR 尚未创建。
- 证据：主工作区 outputs/bisheng-chat-work-enterprise-20261015/delivery.md、desktop-authenticated-acceptance.png、work-switch-completed.png、download-verification.json。本条更新此前等待企业认证的状态。

# Chat 前端验收状态

2026-10-15：在 r4 DSH 风格 Chat 基础上加入原生 WebContentsView 的外观事件；Markdown 预览选择器跟随 `data-dsh-chat-theme`。定向 ESLint、生产构建及附件及主题初始化 4 项测试通过。3006 已发布 r3，前端 200。真实登录后的消息、附件、预览及深浅主题验收待企业认证完成。
