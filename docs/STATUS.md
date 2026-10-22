## 2026-10-22 — 企业技能运行时接口

- 新增登录态 `/api/v1/linsight/skill/runtime/catalog` 和 `/runtime/{id}/bundle?version=<content_hash>`，供桌面 Work 使用与 Chat 相同的租户已启用技能。管理接口继续使用管理员权限。
- 目录返回稳定记录 ID 和内容版本；完整 ZIP 保留脚本、模板及二进制资产。下载前后检查租户、启用状态与版本；响应附带 SHA-256 和 no-store。
- 自动化：运行时/API/服务测试 53 项通过；运行时及真实租户隔离测试 12 项通过；Ruff 通过。覆盖普通用户、未登录、跨租户、禁用撤销、版本失效及完整包下载。
- 3006 已部署到 `enterprise-skills-20261022-184518`，复用当前发布的前端及环境配置，后端健康检查通过。新版桌面实际读取目录并显示平台 Office 技能。
- 权限语义沿用 Chat 的租户已启用技能规则；Work 本地工具执行继续受桌面权限策略约束。真实 Office 文件生成验收由用户执行。

## 2026-10-22 — 用户可选模型统一配置

- 交付方式按用户确认调整为直接合入 `feat/bisheng-work-120-main`；合并前同步远端 `022aee8cb`，保留 Chat 字体渲染更新，状态文档保留双方记录。

- 布局微调：可见范围标题与按钮统一左对齐，右侧三列使用固定宽度，支持图片和积分倍率整体右移，显示名称区域获得更多空间。定向 ESLint 与管理端构建通过，已部署 3006 `user-models-6dea932e8-20261022`，实际页面截图确认标题与按钮左侧对齐、支持图片及积分倍率右移。

- 基线 `feat/bisheng-work-120-main@b3fbbd166`。统一工作台与桌面端配置，显示实际模型、服务提供方、显示名称、视觉、积分倍率及“配置可见范围”按钮；其他系统配置保持现有流程。
- 管理员专用读取入口保留完整原始元数据，保存名称保留隐藏模型、描述和既有默认值。Chat 与桌面目录使用服务提供方及显示名称，调用和授权继续使用原模型 ID。
- 自动化：后台隔离容器测试 58 项通过、2 项环境用例跳过；管理端相关 28 项通过，严格类型检查 550 文件、定向 ESLint、生产构建及架构检查通过。全局 i18n 检查的两组错误与基线一致（既有日文权限文案及 28001–28009 错误码）。本次新增文案提供中英日三语。
- 3006 已发布 `user-models-2a309aeff-20261022`，后台健康。实际管理员页面验证合并表格、名称保存与重新加载、用户/部门/角色可见范围弹窗、其他模型配置。实际 BISHENG Dev 刷新后，模型选择器显示“阿里云百炼 / Qwen 名称联动验收”；随后恢复原名称 `qwen`，后台和桌面均确认恢复。权限和倍率沿用原值。设计及验收范围见 [配置说明](product/user-selectable-models-20261022.md)。

## 2026-10-22 — Chat 与 Work 字体渲染一致

- Chat 界面采用 Harness Work 的系统字体平滑设置（antialiased / grayscale），欢迎标题沿用共同的 26px / 500 / 32px 字阶。字体族和字号相同时，字形边缘也使用一致的渲染方式。
- 对照已安装 Harness 0.2.0-rc.2 的基础样式完成源码核对；客户端生产构建通过，源码 `022aee8cb` 已推送共同分支。3006 发布到 `chat-font-022aee8cb-20261022`，保留管理端 `user-models-6dea932e8` 版本，前端 HTTP 200。现有桌面包重新加载网页即可生效，视觉效果由用户手动验收。

## 2026-10-22 — 文件预览与深色主题

- 文件画布与应用界面采用独立配色边界。Word、Excel、PDF、HTML 和引用文档保留文件内容配色；预览背景、缩放工具栏、加载与错误状态、文本/Markdown、音视频及产物侧栏使用主题色。
- 文档画布通过 `data-document-canvas` 与桌面宿主约定；宿主为弹出菜单和对话框提供完整深色文字、背景和控件色。
- 客户端生产构建通过。桌面类型检查及相关回归 28 项通过；按用户要求由用户手动验收视觉效果。源码 `b3fbbd166` 已推送 `feat/bisheng-work-120-main`，3006 前端发布到 `dark-preview-b3fbbd166-20261022`，前端容器已启动。

## 2026-10-22 — Chat 输入提示及上下文弹窗交互

- 输入提示随编辑器真实空状态显示，聚焦空输入框保留提示；中文输入法组合输入即时隐藏提示，清空后恢复，文字与光标使用相同的内边距。
- 加号菜单按打开方式恢复焦点：鼠标操作返回编辑器，键盘操作返回触发按钮。知识空间列表采用固定高度，加载与结果变化保持弹窗尺寸。
- 此前输入提示回归 9 项及构建通过；本轮合入集成分支 `94f6380fc` 后，`646980179` 的 Chat 构建通过并推送 `dataelement/bisheng:feat/bisheng-work-120-main`。3006 前端发布目录为 `knowledge-picker-646980179-20261022`，前端容器已重新启动；按用户要求由用户手动验收界面。

# DSH 企业后台交付状态

- 2026-10-22：共同开发与后续交付统一使用 `feat/bisheng-work-120-main`；合入任务模式修复 `51baf285f`，保留消息操作样式提交 `cb4b18018`。合并无代码冲突，后端与已发布到 3006 的修复版本一致，前端与共同分支原有版本一致。

- 2026-10-22：统一 Chat 消息操作为复制、点赞、点踩、导出，采用 DSH Work 0.2.0-rc.2 的原始图标及 28px 按钮、15px 图标、8px 间距；桌面内嵌 Chat 与网页共用此实现，Work 保留新建分支。参考桌面分支 V1.2.0 b510182。复制回归 2 项、前端类型检查、改动文件 ESLint 与客户端构建通过；前端全量 ESLint 在平台既有文件报 95 项错误。本次源码待部署后的视觉验收。

- 2026-10-22：Chat 输入提示改为独立定位，空输入框聚焦仍显示，开始输入（含中文组词）立即隐藏，清空后恢复；提示文字沿用输入框内边距，与光标起点对齐，中文组词期间保持原生输入位置。ComposerEditor 9 项回归和客户端构建通过；3006 预览已验证聚焦显示、输入隐藏、清空恢复及内边距一致，API 返回 200。预览保留任务模式与积分结算更新，等待用户在桌面端验收后推送共享分支。

- 2026-10-22：修复主线迁移后 Desktop Chat 网页会话交换 500：恢复经过校验的 `web_session_cookie_name` 配置，默认使用 `access_token_cookie`；会话测试改用实际 `DshSettings`，覆盖默认配置和自定义入口 Cookie。27 项会话及配置回归与 Ruff 通过；独立容量工厂测试因本地缺少 docstring_parser 待复验。3006 部署复验执行中。

## 2026-10-22：任务模式执行链路补齐（3006 已发布，业务效果待用户验收）

- 基线：`codex/work120-main-integration@480fc2972`，同步 3006 已发布的 Cookie 配置修复 `a01d35a3c`；候选代码在独立工作树开发。
- 已实现：有使用权限时自动装配代码执行器；工具与分类配置统一解析；恢复容器执行器传输；文件落入任务持久化空间并通过稳定路径引用；恢复执行带入原文件、产物及中间文件，后续任务继承原文件和产物；检测交替重复的工具调用。
- 安全边界：权限入口沿用统一工具授权与审计。执行器地址与凭据由后端配置控制，代码执行通过隔离 runner；本机直接执行配置在任务启动时报告配置错误。
- 自动化：96 项定向测试通过，覆盖隐式授权、配置解析、文件回传、隔离传输、任务文件恢复与重复调用。
- 真实环境：3006 隔离执行器探测已通过，后端执行与积分修复均已发布，14 个部署文件与修复清单一致；页面及健康接口返回 200。Excel、Word、PPT 和 Excel 续写任务均完成并返回产物，Excel/Word 下载成功。按用户最新要求，文件打开、内容和版式效果由用户验收。共享结算和 Work 审计边界回归 33 项通过、2 项外部 Redis 用例未运行，完整审计集受测试 ORM mock 初始化问题影响，未计为通过。详细记录见 [任务验收](TASKMODE_EXECUTION_ACCEPTANCE.md)。


## 2026-10-22：Work 120 main 积分与 Chat 集成候选

- 基线：`upstream/feat/bisheng-work-120-main@7c701e86bcdfbafd53a99997f3146097a1497c41`；集成分支：`codex/work120-main-integration`。
- 迁入旧 Work 120 的 Chat 交互与桌面桥接，以及 3007 的统一积分、模型倍率和可见范围；沿用新基线的原生登录与席位移除实现。桌面配套分支为 `dataelement/bisheng-work:codex/v120-unified-credits`，基于 V1.2.0。
- 自动化：Chat 定向测试 101 项、管理端相关测试 213 项、原生认证及迁移测试 11 项、模型审计测试 24 项通过；双前端生产构建与前端工作区类型检查通过。部分测试按运行环境跳过。
- 后台全量 DSH 回归仍有失败及环境错误，涉及旧版按模型额度断言、数据库/Redis 等依赖和测试隔离，当前状态为集成候选。真实数据库迁移、登录、Chat/Work 扣分与权限联调待验收。
- 当前交付为源码分支。3006/3007 部署、共享目标分支合并及桌面安装包发布待后续执行。
- 迁移范围和数据升级路径见 [集成说明](WORK120_MAIN_INTEGRATION.md)。


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


## 2026-10-22 Chat knowledge dialog presentation
- KnowledgeSpaceDialog publishes its open/close lifecycle to the desktop presentation bridge. The dialog portal uses the full desktop window; the underlying chat layout follows the host-provided chat region dimensions.
- The knowledge overlay has an explicit presentation class so the host can apply Work's sampled mask color and alpha. Browser-only dialogs retain the shared Modal behavior.
- Client production build passed. 3006 frontend release: `chat-window-dialog-20261022-1905`, preserving the current enterprise skills, backend and admin deployment. Visual acceptance is assigned to the user.


## 2026-10-22 Select skills before task mode
- Synced `feat/bisheng-work-120-main@fd153d685` before the change.
- Chat exposes the enabled skill picker to users with task-mode access while composing ordinary chat. Selecting a skill retains the selection and activates task mode; further skill selection keeps task mode active. Switching back to ordinary chat clears task skills and keeps the picker available.
- Ten focused composer tests and the client production build passed. Deployed client build to 3006 release `chat-skill-auto-mode-20261022`, preserving the current backend and admin files. Desktop Chat loads this client; visual acceptance remains with the user.
