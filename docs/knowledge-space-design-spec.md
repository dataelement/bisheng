# 知识空间 vNext 视觉与实现规范

版本：1.57
确认日期：2026-11-01  
状态：主体视觉已实施；v1.5 按用户要求补齐局部交互状态，待用户预览验收。

当前页面框架以 [模块首页布局](module-home-layout.md) 为准（v1.39）；卡片桌面尺寸以文末 v1.40 为准，分类栏使用 v1.41 的组件库 Tabs 与 v1.43 的图标库图标，更多按钮使用 v1.42 的组件库 Button，卡片元信息和无边框排序使用 v1.44，卡片标题字号使用 v1.45，卡片颜色使用 v1.46 的共享色彩 Token。固定图标、控件、间距、行高及字号，卡片宽度随内容区伸缩。下文历史记录中的无限宽、页面边距、页头几何、局部胶囊分类栏及视口等比缩放不再作为当前实现要求。

卡片实现以 v1.51 的内容链接和独立操作为准；v1.50 的点击无变色规则继续生效，卡片四边内边距以 v1.52 的 16px 为准。

分类数量使用 v1.53 的 Tabs 原生数字徽标，替代 v1.41 的行内括号计数。

排序方式按 v1.54 保存当前账号在当前浏览器中的上次选择，刷新和切换模块后恢复。

分类图标的深色模式素材以 v1.55 为准，浅色模式沿用原素材。

首页分类空状态以 v1.57 为准，插画与排版使用组件库状态页。

## 1. 依据与确认记录

- 需求文档：`knowledge-space-redesign.docx`，位于本文同级目录。
- 原始设计：[Frame 159:8513](https://www.figma.com/design/ceyPGsiRutsoQcjHleUkl3/DSH-Desktop0924?node-id=159-8513)。用户已将画板宽度调整为 1920。
- 已确认预览：[侧栏展开版 169:156](https://www.figma.com/design/ceyPGsiRutsoQcjHleUkl3/DSH-Desktop0924?node-id=169-156)。
- 宽度对照：[内容扩展上界版 169:450](https://www.figma.com/design/ceyPGsiRutsoQcjHleUkl3/DSH-Desktop0924?node-id=169-450)。该版本移除左侧占用以展示内容扩展上界，不是宿主侧栏真实收起尺寸的测量结果。
- 局部组件与预览说明：[169:35](https://www.figma.com/design/ceyPGsiRutsoQcjHleUkl3/DSH-Desktop0924?node-id=169-35)。

用户确认：设计稿文字及计数仅表示内容类型，没有真实业务含义，不将示例计数差异列为产品问题；“更多”图形统一为 **20×4px**；其余视觉按第二阶段建议值统一。用户预览后确认采用此方案。

Figma MCP 已实际读取目标节点的设计上下文、截图、元数据、变量和代表节点属性。变量工具返回“二级标题1 = #6A7588”；目标原稿未配置 Layout Grid，三列栅格由节点几何关系推导，不能声称它原本包含响应式规则。

### 字体预览限制

正式视觉规范仍为 **PingFang SC，400 / 500 / 600**。Figma MCP 环境无法加载该字体，已确认预览临时使用 **Noto Sans SC，400 / 500 / 700**，其中 700 替代正式规范的 600。该替代是已披露的预览环境限制，不将两种字体或字重视为等价。正式实现需要核验实际字体、回退字体及截断效果。

## 2. 范围与隔离原则

仅调整用户端 `/knowledge` 首页右侧主体：标题、知识广场与创建按钮、四分类及计数、排序、卡片网格、相关局部状态与交互。

禁止修改左侧导航及展开/收起机制、其他页面、全局 CSS、既有全局 Token、主题配置、旧公共组件样式、后端 API 和数据结构。不使用 Figma 自动生成代码替换现有业务。

新设计内部保持一致；旧 Token 只用于理解依赖和评估隔离，不能作为新视觉标准。复用路由、数据、权限、操作及缓存行为，隔离视觉实现。暂不建设完整的新组件库。

## 3. 冻结参数

以下尺寸为 CSS px 候选实施单位，不是 PNG 像素或宿主实测尺寸。Token 完整前缀为 `--vnext-`。页作用域指知识首页局部根；控件作用域包括显式启用同一局部 scope 的弹层。

### 3.1 颜色

| 用途 | Figma 原始值 | 冻结值 | Token 后缀 | 作用域与理由 |
| --- | --- | --- | --- | --- |
| 页面表面 | #FFFFFF | #FFFFFF | surface-page | 页；保留 |
| 卡片默认表面 | #F7F9FB | #F7F9FB | surface-card | 页；保留 |
| 卡片悬停表面 | #EFF2F8 | #EFF2F8 | surface-card-hover | 页；采用原稿悬停示意 |
| 强调文字 | #000000 | #000000 | text-strong | 页、控件 |
| 常规文字、卡片名称 | #333333 | #333333 | text-primary | 页、控件 |
| 描述 | #6A7588 | #626E82 | text-secondary | 页、控件；改善小字对比度 |
| 时间 | #9299A5，重叠旧层另有 #292929 | #626E82 | text-meta | 页；统一元信息 |
| 创建者或团队 | #6A7588，重叠旧层另有约 #181818 | #626E82 | text-owner | 页；统一元信息 |
| 未选中 Tab 文字 | 黑色 60% | rgba(0,0,0,.6) | text-tab | 页；仅文字透明，不影响整个 Tab |
| 选中 Tab 背景 | #E3E7EE | #E3E7EE | surface-tab-selected | 页 |
| 主按钮背景/文字 | 黑/白 | #000000 / #FFFFFF | action-primary-bg / action-primary-fg | 控件 |
| 次按钮背景/文字/边框 | 白/#333/#333 | #FFFFFF / #333333 / #333333 | action-secondary-bg / action-secondary-fg / action-secondary-border | 控件 |
| 排序边框 | #D0D5DE | #D0D5DE | border-control | 控件 |

语义不同的 Token 即使当前同值也保留独立名称。不引用旧视觉变量来定义这些值。按不透明 sRGB 表面计算，#626E82 在默认与悬停卡片表面上的对比度约为 4.89:1、4.60:1。

### 3.2 字体与排版

| 用途 | Figma 原始值 | 冻结值 | Token 后缀 |
| --- | --- | --- | --- |
| 字体 | PingFang SC | "PingFang SC", "Microsoft YaHei", system-ui, sans-serif | font-family |
| 常规/中等/强调字重 | 400 / 500 / 600 | 400 / 500 / 600 | weight-regular / weight-medium / weight-semibold |
| 页面标题 | 42 / 74，600 | 40 / 56，600 | title-size / title-line-height |
| 卡片名称 | 18 / AUTO，600 | 18 / 28，600 | card-title-size / card-title-line-height |
| 描述和元信息 | 14 / AUTO，部分时间行高 22 | 14 / 22，400 | body-size / body-line-height |
| Tab | 14；行高 24 或 74 | 14 / 24；选中 500，未选中 400 | tab-size / tab-line-height |
| 按钮与排序文字 | 14 / AUTO | 14 / 22；主按钮 500，其余 400 | control-size / control-line-height |
| 字间距 | 0 | 0 | letter-spacing |

斜线表示字号/行高。Figma 文本框高度不视为 AUTO 行高的可靠数值。所有排版 Token 限页或控件作用域；不修改全局字号和字体配置。

### 3.3 布局、尺寸与效果

| 用途 | Figma 原始值或几何推导 | 冻结值 | Token 后缀 |
| --- | --- | --- | --- |
| 页面左右 Padding | 两侧各 56 | 40（v1.4用户确认） | page-padding-inline |
| 页面顶部 | 标题框 y=60 | 64 | page-padding-block-start |
| 标题行 | 无统一布局容器 | 56 | header-height |
| 标题行至工具栏 | 原稿无统一值 | 40 | header-toolbar-gap |
| 工具栏至网格 | Tab 底至卡片顶 29 | 32 | toolbar-grid-gap |
| 网格横向间距 | 40；局部偏移产生 43/37 | 24（v1.3用户反馈） | grid-gap-inline |
| 网格纵向间距 | 40 | 24（v1.3用户反馈） | grid-gap-block |
| 卡片常规最小宽 / 紧凑下限 | 固定宽 446，未定义最小宽 | 440 / 350（v1.3） | card-min-width / card-compact-min-width |
| 卡片最小高度 | 175 | 176 | card-min-height |
| 卡片内边距 | 稳定边界为 24 | 24 | card-padding |
| 卡片图标槽位 | 44×44 | 44×44 | space-icon-size |
| 卡片图标与名称间距 | 14 | 16 | card-heading-gap |
| Tab 高度/左右内边距 | 40 / 24 | 40 / 24 | tab-height / tab-padding-inline |
| Tab 图文间距 | 6 | 8 | tab-icon-gap |
| Tab 间距 | 8、11、11 | 8 | tab-gap |
| 顶部按钮间距 | 24 | 24 | header-action-gap |
| 控件高度 | 40 | 40 | control-height |
| 按钮左右内边距 | 24 | 24 | button-padding-inline |
| 排序左右内边距 | 左侧约 17 | 16 | sort-padding-inline |
| 卡片圆角 | 14.9145727 | 16 | radius-card |
| 按钮/排序圆角 | 8 / 9 | 8 | radius-control |
| Tab 圆角 | 高 40、圆角 30 | 999，胶囊 | radius-pill |
| 卡片/按钮阴影 | 检查节点 effects=[] | none | shadow-card / shadow-control |
| 更多图形 | 原稿有 20×4 与 30×30 两类外框 | 20×4 | more-glyph-width / more-glyph-height |

“更多”20×4 定义的是图形尺寸；实际网页命中区可由透明容器扩大，不拉伸图形，也不把 30×30 当成图形标准。

按钮宽度随文字、图标和内边距决定，不固定为原稿的 104/146。图标保留固有比例，不把不同资产强行拉伸到相同宽高。

### 3.4 交互状态

下列补全状态原稿未提供完整状态集，属于第二阶段提出并获准采用的规范化建议，不标注为 Figma 原始参数。

| 状态 | 冻结表现 | Token 后缀或行为 |
| --- | --- | --- |
| 卡片 hover | #EFF2F8 | surface-card-hover |
| 卡片 pressed | 同 hover，不缩放 | surface-card-pressed |
| 键盘焦点 | 2px #333 轮廓，offset 2px，不改变布局尺寸 | focus-color / focus-width / focus-offset |
| 主按钮 hover / pressed | hover为黑色按钮整体opacity .6；pressed #333333（v1.5） | action-primary-hover / action-hover-opacity / action-primary-pressed |
| 次按钮 hover / pressed | hover填充rgba(51,51,51,.05)，描边与整体透明度不变；pressed #EFF2F8（v1.7） | action-secondary-hover / action-secondary-pressed |
| 禁用按钮 | 背景 #E3E7EE，文字 #626E82，无 hover | action-disabled-bg / action-disabled-fg |
| 按钮 loading | 尺寸不变、busy、防止重复点击 | 沿用该按钮视觉 Token |
| Tab hover | #F7F9FB | surface-tab-hover |
| 置顶 pending | 防止重复操作；失败恢复原状态 | 复用现有业务逻辑 |

弹层投影、危险状态及错误/空态的专门视觉值在第二阶段未取得完整设计依据，也未给出可冻结数值。实施中不得冒充原稿参数或自行套用旧视觉标准；需要时先提出本页局部补充并更新本文。

## 4. 自适应与宽度验证

当前规则（v1.40）：使用实际网格宽度 W 决定列数；W 不含页面 Padding，且须扣除实际滚动条等占位。固定最小卡宽 300px、间距 22px，内容列最大 1000px。沿用订阅桌面端原生 auto-fill 排列方式，不读取 Sidebar 状态，不按视口缩放最小卡宽。

```css
grid-template-columns:
  repeat(auto-fill, minmax(min(100%, var(--vnext-card-min-width)), 1fr));
```

三个约束同时成立：页面左右最小 Padding 稳定；卡片横纵 Gap 稳定；每列以 1fr 平分可用宽度。禁止按 Sidebar 展开状态硬编码列数，禁止用 space-between 拉大卡片间距。

三列所需 W≥944px，两列所需 W≥622px；不足两列时一列。容器足够时增列；不足时减列，不横向溢出。卡片图标、字号、圆角、内边距不随卡片宽度同比放大。下方预览与历史验证保留当时参数，当前实测见 v1.40 链接。

### 1920 预览几何（历史Figma参数G=40；当前实现见v1.40）

| 情形 | 内容容器宽 C | 无额外占位的网格宽 W=C−112 | 列数 | 卡片宽 |
| --- | --- | --- | --- | --- |
| 预览侧栏展开，左侧占 389 | 1531 | 1419 | 3 | 446.333… |
| 内容扩展上界，左侧占 0 | 1920 | 1808 | 3 | 576 |

以上尺寸已在生成的 Figma 预览节点中检查。未运行真实页面，未测量宿主侧栏收起宽度、缩放、滚动条占位或 CSS clientWidth，不能写成运行验收通过。

v1.0 固定440下限时，展开几何距三列门槛仅19px。v1.2 经用户反馈允许紧凑卡片，三列门槛改为1100；仍按实际网格宽度计算，不隐藏滚动条。

无额外占位时，内容容器 C 的两/三/四列阈值在v1.4分别为 **804 / 1178 / 1912px**（原v1.0为1032 / 1512 / 1992px）。PNG 的 1646×974 像素尺寸不能直接替代 CSS 视口尺寸。

现有公共 1000px 上限与此三列要求矛盾：1000 < 1098（v1.3三列门槛）。必须在知识首页局部替换该展示约束；禁止修改公共 MODULE_HOME_COLUMN 影响其他模块。

### 局部布局细则

- 顶部 64，标题行高 56，间隔 40，工具栏高 40，再间隔 32，正常宽度下网格 y=232。
- 卡片高度最低 176、内边距 24；标题区高 44；描述及底部元信息保持稳定节奏。
- 名称与描述单行省略；缺失描述不虚构文案。底部元信息稳定对齐，极窄情况下允许换行与卡片增高。
- 工具栏不足时可换行或 Tab 横向滚动；不挤压排序和图标至不可用。
- 桌面宿主嵌入模式即使很窄也可能保持桌面页面，必须以内容宽度处理，不能只依赖 viewport 断点。
- 保留既有移动端页面和详情页；局部 Container Query 如确有需要再使用。
- 页面保留明确的主要滚动容器；不修改全局滚动规则。验收实际滚动条占位与是否出现双滚动。

## 5. 工程落点与防泄漏

代码仓库目录为本文上级目录下的 `bisheng/`；开发分支 `feat/knowledge-space-redesign`，目标合并分支 `feat/3.1.0-beta1`。

拟议本页实现目录：`bisheng/src/frontend/client/src/pages/knowledge/home/vnext/`。尚未创建代码文件。

- `tokens.module.css`：局部 `.scope` 声明 --vnext-*，只在首页主动启用。
- `KnowledgeHomeNext.module.css`：本页布局、卡片、工具栏及状态。
- 工具栏、卡片、菜单等本页组件按职责拆分；第二个复用页面出现后再提取共享层。
- Portal 面板显式附加同一 Token scope 与局部类；根节点变量不会自动穿过 body Portal。
- 不声明 :root、html、body；不使用无作用域元素选择器或全局 role 选择器；不覆盖旧 --brand-*、--text-*、--radius 等。
- CSS Modules 不阻止全局继承，关键字体、表面、控件状态需显式定义和验证。
- 不依赖修改 body class 或卸载清理 CSS；页面被 KeepAlive 缓存也不得影响外部。
- 不修改公共组件以适配本页；无法局部隔离所有视觉状态时，本页封装现有交互基础。
- Figma 预览使用独立 `vNext · Knowledge Preview` 变量集合；不改变原稿共享变量。其变量名用于预览组织，代码以本文 --vnext-* 命名为准。

## 6. 业务复用与数据约束

| 能力 | 实施约束 |
| --- | --- |
| 路由、创建、进入、设置、知识广场 | 复用现有回调及导航，不替换业务流 |
| 三个列表 API、Query Key、刷新 | 复用真实接口和缓存机制 |
| 权限 | 复用按空间懒查询、默认关闭受限操作、失败可重试 |
| 删除、退出、置顶 | 保留确认、权限、额度、乐观更新与失败恢复 |
| 全部空间 | 三个现有分类按 ID 去重；保留来源分类信息供菜单与置顶规则使用 |
| 分类计数 | 使用真实过滤后集合；错误、未加载不得伪装成可信的 0 |
| 创建时间排序 | 后端已有支持；前端需页面适配，不用不安全类型断言伪装共享 hook 已支持 |
| 全部排序 | 合并后统一排序，保留置顶优先和稳定同值顺序 |
| 卡片元信息 | 接口未返回时不伪造创建者、团队、图标；不默认逐卡请求详情制造 N+1 |
| 演示数据 | 设计稿文字仅占位，不能写入产品数据；验收关闭已有 DEV 演示注入 |
| 国际化 | 使用现有体系，新文案同时覆盖项目要求的语言 |

“组织与部门”建议对应现有部门集合；“已加入”当前实际包含其他人创建、权限可见的空间，不限主动加入。用户对占位文字的确认不等于改动接口含义；沿用真实语义，仍需在实现报告说明其口径。

旧 `KnowledgeSpaceSidebar`、`KnowledgeSpaceSections`、`KnowledgeSpaceCardItem` 同时服务移动端及详情场景，不整体换肤。首页优先复用 hooks 和回调，独立展示层。

## 7. 代码定位

以下路径均相对代码仓库 `bisheng/`，位置来自第一、二阶段审计，实施前需复核当前内容。

- `src/frontend/client/src/routes/index.tsx:270`：知识空间路由。
- `src/frontend/client/src/layouts/MainLayout.tsx:199`：公共壳层与右侧 flex 容器。
- `src/frontend/client/src/components/ModuleHome/ModuleHome.tsx:19`：公共框架及 1000px 上限，禁止全局修改。
- `src/frontend/client/src/pages/knowledge/index.tsx:455`：进入空间；508：创建；993：桌面状态分支。
- `src/frontend/client/src/pages/knowledge/KnowledgeHomePage.tsx:32`：桌面首页入口。
- `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx:194`：分类过滤；462：旧内容宽度约束。
- `src/frontend/client/src/pages/knowledge/hooks/useKnowledgeSpaceLists.ts:11`：列表查询。
- `src/frontend/client/src/pages/knowledge/hooks/useKnowledgeSpacePermissions.ts:25`：空间动作权限。
- `src/frontend/client/src/pages/knowledge/hooks/useSpaceActions.ts:192`：置顶及回滚。
- `src/frontend/client/src/api/knowledge.ts:740`：列表 API；345：字段映射。

## 8. 实施前剩余确认与验收

已冻结视觉不因截图或运行限制自行变更。以下项目仍需实测或结合真实数据确认：

1. 基准窗口 CSS 宽度、缩放、侧栏展开/收起后的 C、W、滚动条占位；验证当前1098≤W<1832的三列条件及四列阈值。
2. PingFang SC 实际可用性、600 字重、跨平台回退及中英日截断；不把预览的 700 当作正式值。
3. 三分类口径、缺失元信息、分类图标含义；排序选择各分类独立记忆或统一使用的产品规则。
4. “全部”仍按原分类处理置顶限制，不擅自改成新的全局五个规则。
5. 新版以本次独立浅色视觉为基准，不自动沿用旧品牌/深色视觉；如增加新版主题，先补充局部规范。
6. 弹层、危险、错误与空态未定的专门视觉按需补充，不扩散修改旧公共样式。

验收覆盖：常规/窄容器、侧栏切换、长文本和多语言、加载/空/错/重试、权限加载与拒绝、创建额度、进入/返回、排序、置顶恢复、删除/退出、键盘焦点，以及其他页面和左侧导航的无污染回归。

代码修改前检查 Git status，不覆盖未提交改动。后续按变更运行必要验证，包括项目要求的 lint/typecheck。本文保存阶段仅新增本规范，不安装依赖、不修改业务代码、不提交或推送。

## 9. 变更记录

- 2026-11-01 / v1.0：按用户确认保存；基准宽度更新为 1920；文字与计数明确为占位；更多图形冻结 20×4；记录统一参数、Figma 预览证据、字体限制及待实测项。
- 后续修改冻结值时，先更新本文的版本与理由，再调整实现和验收基准。

### v1.1 素材与接口映射确认

用户确认：组织与部门对应原“部门”接口 `/api/v1/knowledge/space/department`，我的创建对应原“我创建的”接口 `/api/v1/knowledge/space/mine`，已加入空间对应原“我加入的”接口 `/api/v1/knowledge/space/joined`。

卡片分类素材：组织与部门 `card-1.png`、我的创建 `card-2.png`、已加入空间 `card-3.png`。三份原图均为88×88，网页显示仍为44×44；全部空间按照卡片原始分类来源选择素材，保留既有部门优先、创建次之、加入最后的 ID 去重规则。本页分类素材取代旧的通用图标/自定义图标展示优先级，不修改接口、详情页或移动端图标逻辑。

同步接入用户更新的 `clip-2.svg`（原始25×24），替代旧的24×24 PNG，不拉伸其比例。此次仅补充已确认素材映射，其他冻结视觉值保持不变。

### v1.2 响应式修订

用户反馈整个窗口1455px、导航收起时应显示三列。当前预览实测左侧占240，右侧C=1215，网格W=1103；旧固定最小宽440导致仅两列。修订为340–440之间的弹性最小宽，三列优先范围覆盖W=1100至1880。340是本次实施建议值，不是Figma原始参数。Gap40、左右Padding56、图标44、字号及卡片Padding24均保持。

浏览器实测：C=1211/W=1099为两列；C=1212/W=1100为三列340；窗口1455且左侧240时为三列341；1920原展开参考仍为三列446.33；C=1991为三列，C=1992为四列440。未把预览槽位当作真实宿主Sidebar收起宽度。

### v1.3 缩小卡片Gap、提高紧凑卡宽

用户希望Gap在24–36px之间，使1455px窗口中的卡片更宽。实施采用稳定的横纵Gap24px，Page Padding仍为左右56px；紧凑卡宽下限由340提高到350，常规上限仍440。图标、字体、内部Padding、圆角均不改变。

实测：窗口1455、左侧占240时C=1215/W=1103，三列各约351.67px（此前341px）。1920原展开参考C=1531/W=1419为三列457px。C=1209为两列，C=1210为三列350px；C=1943为三列，C=1944为四列440px。缩小Gap后四列阈值相应提前，这是本次参数变更的自然结果。长文本测试无横向溢出。

### v1.4 页面左右Padding改为40px

用户明确要求左右Page Padding由56改40，横纵卡片Gap保持24。仅修改知识空间局部Token；顶部64、卡片内部Padding24、图标44、字号、圆角及350–440的弹性最小宽规则保持。当前左右总占位为80px，网格宽W=C−80（须扣实际滚动条占位）。本修订覆盖此前各版本中的56px页面边距及相应容器阈值。

浏览器实测：窗口1455、左侧占240时，C=1215/W=1135，三列各约362.33px，比v1.3再增加约10.67px。1920原展开参考C=1531/W=1451，三列约467.67px。C=1177为两列，C=1178为三列350px；C=1911为三列，C=1912为四列440px。长文本无横向溢出。导航占位仍为预览几何，不代表真实宿主联调。

### v1.5 Explicit interaction updates

These user-requested states supersede earlier defaults without changing layout tokens.

- More glyph: opacity .6 on hover, press and while its menu is open; restored to1 otherwise. Hit area and focus indicator remain unchanged.
- Create button: whole-button opacity .6 on hover, black base background. Disabled buttons do not acquire hover styles.
- Unpinned icon: retain original #6A7588 stroke at opacity .5 by default. A page-local hover derivative changes only stroke-opacity to1, keeping the original25x24 geometry. Pinned artwork is unchanged.
- Sort arrow: explicitly user-authorized local drawing,12x8, #333333 fill/stroke,2px round join giving1px outer corner radius. This is not a newly retrieved Figma asset.
- Sorting uses the already-installed Radix Select primitives with local CSS and an explicitly scoped Portal. Border defaults to#D0D5DE; hover/open uses#333333; closed and not hovered resets to default. No outer outline or shadow remains after dismissal. Keyboard focus uses an underlined value instead of an outer ring.
- Existing sort values, data sorting and keyboard selection remain intact. No global Select or shared component style changes.
- Deletion remains gated by real delete permission. The fixture has no such permission, so no fake delete action is shown. Rename is deferred to backend integration as explicitly permitted by the user.

Browser checks: create hover .6; more open .6; unpinned hover layer1/default layer0; arrow12x8; open border rgb(51,51,51); after selection and mouse-out border rgb(208,213,222), outline-style none and box-shadow none. Escape closes the list and restores focus. These checks use fixture data, not live backend integration.

### v1.6 Outline-only discovery hover and dark design preview

The user requested that Knowledge Square hover keep its white surface and text unchanged, lowering only the border opacity to60%. Implemented locally as rgba(51,51,51,.6), with button opacity1. Preview card titles/descriptions/owners now come from a test-only Chinese fixture JSON; production data is unchanged.

Current theme implementation: `client/src/hooks/ThemeContext.tsx` toggles light/dark on the html element, persists color-theme and supports system preference. The shared Tailwind preset uses class-based dark mode. `packages/ui/src/styles/tokens.css` supplies the Arco dark gray ramp and semantic aliases; `client/src/style.css` retains separate legacy/shadcn surface tokens. These two token families coexist. The vNext page currently declares fixed light scoped values and color-scheme:light, so it does not yet follow global dark mode. No website dark-mode styling has been implemented in this pass.

Two editable Figma proposals were created by reusing existing local components, with a separate preview-only variable collection. Original light screens/components/global tokens are unchanged:
- Wide right-content1531: https://www.figma.com/design/ceyPGsiRutsoQcjHleUkl3/DSH-Desktop0924?node-id=181-493
- Compact right-content1215: https://www.figma.com/design/ceyPGsiRutsoQcjHleUkl3/DSH-Desktop0924?node-id=181-931
- Source/limitation notes: node181:1369.

Proposed role mapping from current code: page#121212 (--bg-page), card#17171A (--fill-1), hover/selected#2E2E30 (--fill-2), strong#F6F6F6 (--text-1), secondary#ABABAC (--text-2), metadata/icons#929293 (--text-3), border#484849 (--border-base). Monochrome primary uses the legacy dark primary/on-primary pair#FAFAFA/#171717. The source values exist in code; assigning these values to vNext roles is an adaptation proposal, not an approved or already-implemented theme. No host Sidebar is drawn in these right-content previews.

Layout stays Padding40/Gap24/cardPadding24/icon44. Wide cards467.67x176; compact cards362.33x176. The preview keeps existing Figma Noto Sans SC fonts (Bold700 substitutes for the formal PingFang SC600); this known limitation is labeled on the canvas. Figma screenshots were visually reviewed.

### v1.7 Light-mode hover revision and accepted dark preview

The user accepted the Figma dark previews. They remain unchanged; no website dark-mode implementation is requested or applied in this pass. Font limitations and proposal-to-code distinctions recorded in v1.6 remain applicable.

Light-mode Knowledge Square hover now uses rgba(51,51,51,.05) fill with its original #333 border and whole-button opacity1. This supersedes the previous60% border-opacity hover. Sort hover/open uses the same5% #333 fill, keeping its default #D0D5DE border; the former hover/open border darkening is removed. When closed and not hovered, the surface returns to white with no outer ring or shadow.

The local sort-arrow.svg and rendered image are both8x4, preserving#333333 and the round-joined geometry. This supersedes the former12x8 size. All changes remain scoped to the knowledge homepage; layout and real sorting logic are unchanged.

Browser measured: Knowledge Square hover background rgba(51,51,51,.05), border rgb(51,51,51), opacity1; sort open background rgba(51,51,51,.05), border rgb(208,213,222), arrow8x4. Closed/mouse-out restores white with outline-style none and box-shadow none.

### v1.8 Pin action ownership and final More-menu contract

The user confirmed that pin/unpin belongs exclusively to the card's pin button, not the More menu. The card button reuses the existing handlePinSpace action, category-specific quota, pending lock and optimistic rollback behavior. Pin priority in sorting is unchanged.

After integration, the knowledge-home More menu must contain only Rename and Delete, each gated by the appropriate real permission. Pin/unpin, Settings and Leave are removed from this homepage menu. Existing details/mobile flows are not modified. Rename remains deferred to backend integration as previously authorized; Delete retains its permission check and confirmation. No permission is inferred from creator/team text. When permissions provide no available action, the menu displays a disabled localized no-actions row rather than an empty popup or a fake operation.

The test-only preview now maintains local pinned IDs so clicking card pin buttons visibly toggles them. This fixture state is separate from production hooks and makes no backend writes. The first-card pin checkbox reflects the same local state.

Browser verified the card button toggles aria-pressed false/true and labels Pin/Unpin; the fixture More menu contains no pin item. Unit tests cover card unpin arguments without entering the space, repeated pin locking, delete confirmation/permission, and no Settings/Leave/Pin items even for joined spaces with edit-like permissions. Backend quota, persistence, rename and permission integration still require a real environment.

### v1.9 置顶顺序与卡片移动

置顶区按置顶先后顺序排列（先置顶在前），独立于右侧排序；取消置顶后参与当前普通排序，重新置顶排到置顶区末尾。保留原有置顶接口、权限、数量限制和失败回滚。

复用已安装的 Framer Motion，卡片采用 position layout 动画360ms，其他卡片按目标位置每张错开20ms、最多120ms；整个卡片平移，不缩放内部文字和图标，不用JS手动布局。只在卡片ID顺序变化时测量动画，容器缩放继续由CSS Grid控制。系统减少动态效果偏好下关闭移动。

当前接口只返回 is_pinned，不返回置顶时间或序号；因此本页面会话内记录新置顶顺序，已存在的置顶按首次读取顺序稳定显示，不能声称刷新/跨设备恢复真实历史顺序。后端个人置顶表已有 create_time，联调需将该时间或稳定 pin_order 暴露到列表响应，前端再以它作为排序依据。本次未修改后端。

验证：20项单元测试通过；定向ESLint和生产构建通过。浏览器验证连续置顶、切换名称排序、取消及重新置顶；移动期间测得translate矩阵（scale为1），结束后transform为none。1455窗口/240导航占位下保持3列，卡片约362.33px、Gap24。系统减少动态偏好分支已实现，未在浏览器切换该系统设置验证。真实后端与跨设备验证尚未执行。

### v1.10 置顶顺序修正

用户确认：最后置顶的排在第一个。新置顶或重新置顶均放到置顶区最前，替代v1.9的先置顶在前规则；取消置顶后恢复当前普通排序。动画与其他规则不变。接口尚无置顶时间，刷新/跨设备的真实历史顺序仍需联调支持。

### v1.11 紧凑卡片（2026-11-02 用户确认）

常规卡片高度142px；上下Padding16px、左右24px。标题行36px，分类图标36×36，标题16/24px、字重600。标题至描述12px，描述14/22px单行截断、缺失时保留行高，描述至元信息18px，底部信息行22px。总高16+36+12+22+18+22+16=142px。

置顶素材缩至原尺寸75%：已置顶18×18px，未置顶18.75×18px，按钮点击区域仍28×28px。Grid Gap24px、Page Padding及卡片列宽规则不变。使用min-height而非裁切固定高度，极窄容器允许标题或元信息换行撑高，防止重叠。

### v1.12 菜单、空说明与页头（2026-11-02）

更多菜单新增重命名，仅edit权限可见；复用handleUpdateSpace及其缓存更新/失败回滚，标题行内编辑，去除首尾空格、最长50字符、空名不提交，Enter保存、Escape取消、失焦保存。菜单关闭后再聚焦编辑框，避免焦点恢复提前结束编辑。删除原有权限及确认流程保持，本轮不执行真实删除或重命名提交。

空白或未填写说明显示“暂无说明”，使用原说明颜色并设置opacity .6，保留单行与原行高。页面标题字号28px；右上知识广场与创建知识空间按钮从40px减为32px。其余标题行高和布局间距保持。所有视觉规则仅作用于知识空间主页。

### v1.13 页头尺寸微调（2026-11-02）

页面标题字号由28px改为32px，原行高保持。右上知识广场、创建知识空间两个按钮高度由32px改为36px，左右Padding各从24px减为22px（单个按钮总宽减少4px），上下Padding6px。仅修改知识空间页头，其他控件不变。

### v1.14 排序控件宽高及截断（2026-11-02）

排序触发框固定128×36px，128px沿用原五字选项宽度（文字70+左右Padding32+Gap16+箭头8+边框2）。选中文字使用单行ellipsis，切换短选项不收窄。展开面板独立按最长文字自然宽度展开，最大200px，并受可用视口宽度限制；移除原触发框等宽和菜单160px最小宽限制。选项超出时单行ellipsis，复用公共Tooltip组件显示全文，仅实际截断时启用，支持悬停和键盘聚焦。不修改公共组件样式。

浏览器实测：普通面板120px，超长测试面板200px；短、长选项下触发框均128px宽/36px高，长文字宽336px、触发文字可用70px，面板文字可用150px。独立测试页已验证完整文字气泡。22项测试及类型检查通过。

### v1.15 页头位置与小图标（2026-11-02）

以现有侧栏品牌链接y20/高32的中心y36为基准，将右侧页头56px行框的起点改为y8（Page Padding top64→8），标题中心同为y36，不修改侧栏。标题至工具栏间距40→28px（减少12px）。排序选中文字左对齐，移除聚焦文字下划线，保持无外围黑边。

创建者图标20→16px，更多可见图形20×4→16×3.2px（80%），原SVG透明画布30→24px，对应裁切偏移-4/-11.2px。图标在原按钮区域内居中，点击区域不缩小；卡片Padding16/24px和图文Gap8px保持。浏览器实测上述几何值与截断规则正常。

### v1.16 页头顶部对齐（2026-11-02）

按用户修正，以左侧BISHENG品牌标题区域顶部y20为基准，右侧标题行顶部也改为y20；Page Padding top8→20px。替代v1.15的垂直居中对齐，标题至工具栏28px及其他布局不变。

### v1.17 页头与工具栏间距（2026-11-02）

Header下移4px，Page Padding top20→24px。Header至Toolbar间距28→24px，Toolbar至卡片网格间距32→24px。其余布局参数保持。

### v1.18 Tab状态、标题字重与备注位置（2026-11-02）

Tab选中填充色改为#EFF2F8，Tab高度40→36px，选中文字字重改为400，与未选中一致，仅保留文字/背景变色。页面标题与卡片标题统一Medium500。备注上边距12→16px，下边距18→14px，使备注下移4px，保持底部信息位置与卡片常规142px高度。均为知识空间局部样式。

### v1.19 Tab选中色与卡片悬停共用来源（2026-11-02）

选中Tab填充Token引用--vnext-surface-card-hover，不再独立维护色值；当前两者均为#EFF2F8，未来卡片悬停色调整时同步生效。

### v1.20 创建按钮字重（2026-11-02）

知识空间主页的“创建知识空间”按钮字重由Medium500降至Regular400，其他按钮样式不变。

### v1.21 卡片圆角（2026-11-02）

知识空间主页卡片圆角由16px改为14px，使用页面局部--vnext-radius-card，其他组件圆角不变。

### v1.22 页面整体下移（2026-11-02）

知识空间右侧页面顶部Padding24→32px，使Header、Toolbar与卡片整体下移8px，内部间距及左侧导航不变。

### v1.23 卡片标题与图标对齐（2026-11-02）

标题行图文Gap16→14px；标题字号16px不变，行高24→36px，与36px分类图标等高，保留Flex居中。标题编辑框也限制为36px，避免进入重命名时撑高。标题行整体仍36px，不改变卡片142px常规高度及备注/底部位置。

### v1.24 现有产品组件对比版本（2026-11-02）

按用户要求，排序切为@bisheng/ui Select（medium/outlined、宽128px），分类切为Tabs（medium/neutral、无底部分隔线、线形选中指示），更多面板切为Dropdown/DropdownItem；全部使用库原生视觉，不覆盖公共组件样式。原胶囊Tab、Radix局部Select/菜单及其CSS保持。home/vnext/componentMode.ts中的USE_PRODUCT_COMPONENTS=true启用产品组件，设false可一起恢复原版。

共享组件采用自身32px尺寸阶梯和原生选中/焦点/面板规则，暂不强制套用此前36px与200px面板视觉参数。分类图标暂不带入原生线形Tabs，保留真实名称与计数。数据、筛选、排序、置顶、重命名、权限与删除确认沿用原逻辑。新样式只在知识空间主动启用，不修改全局Token/共享组件。

验证：Typecheck通过；22项旧版保留路径回归测试通过；浏览器使用隔离fixture验证共享Tabs筛选（我的创建3张）、Select按名称切换和Dropdown权限空态。真实后端此前返回空数组，未用fixture替换真实页面数据，也未执行远端写操作。

### v1.25 移除知识广场入口（2026-11-02）

移除知识空间主页右上方知识广场按钮，仅保留创建知识空间。其他既有广场路由和业务入口不变。

### v1.26 创建入口使用共享Button（2026-11-02）

产品组件模式下创建知识空间改用@bisheng/ui Button，primary/solid/medium，原生32px高度、主题色、图标、Padding、圆角和交互状态。保留原创建回调及enabled门控，不增加远端写操作。旧版按钮和样式保留，可随componentMode开关恢复；不将旧页头36px/22px或透明度样式覆盖到共享按钮。

### v1.27 备注文字透明度（2026-11-02）

卡片正常备注使用原备注颜色的60%透明度；空备注占位使用同一原色的30%透明度，覆盖而非叠乘正常备注opacity。占位现有文案“暂无说明”保持，位置、字号及行高不变。

### v1.28 使用Segmented分类栏（2026-11-02）

按用户要求将产品组件模式的分类栏由线形Tabs改为共享Segmented medium32px，直接使用组件原生选中态。恢复组织与部门、我的创建、已加入空间左侧原始menu-1.svg/menu-2.svg/menu-3.png，按16×16容纳且保持原比例；全部空间沿用原先无图标。保留真实计数、筛选与键盘操作，窄容器横向滚动。旧局部胶囊Tab仍可随componentMode关闭恢复；Select、Dropdown和创建按钮保持产品组件。

### v1.29 分类栏恢复局部胶囊样式（2026-11-02）

仅分类栏恢复之前的局部胶囊Tab（36px、选中色引用卡片hover、常规字重、原分类图标），不再使用Segmented。排序Select、更多Dropdown、创建Button继续使用现有产品组件；计数和筛选逻辑保持。预览入口切回真实环境/workspace/knowledge，不使用fixture替换真实数据。

### v1.30 编辑空间菜单与置顶显隐（2026-11-02）

移除行内重命名，菜单恢复“编辑空间”，复用宿主onSpaceSettings及既有/knowledge/space/{id}/settings页面和接口流程，edit或manage_permission可见。编辑与删除均使用产品原有Outlined.Edit/Outlined.Delete图标。主页不单独提交名称更新。

未置顶按钮默认透明隐藏且不接收指针，卡片hover或focus-within时显示；已置顶按钮常驻。无hover设备常显未置顶按钮以保持可操作，键盘Tab仍可聚焦并显示。按钮位置和点击范围保留，不引发布局位移。

### 推送整合记录（2026-11-02）

整合最新feat/3.1.0-beta1时去除MainLayout重复useGetBsConfig导入。桌面首页分类绑定路由tab查询参数并保留其他查询参数，支持进入详情、文件夹、返回、前进后退以及缓存模块恢复；新增all类别可随路由携带，默认仍全部空间。更新上游返回分类测试以匹配新版Tab UI，保持原回归行为检查，不改变视觉方案。


## v1.31 — 1440px 预览与几何自适应（2026-11-02）

用户要求保留全部字号，图标、间距和组件几何按 1520px 视口基准随浏览器 CSS 视口宽度等比变化，当前验收预览固定为 1440px。此前固定 Gap / Padding 的约定由本条替代；网格仍根据右侧实际容器宽度自动排布，不根据 Sidebar 状态指定列数。

- 缩放基准为 `viewportWidth / 1520`，1440px 时约为 0.947368。局部 `--vnext-layout-unit` 通过 vw 实现，不采用页面 zoom / transform，不缩放字体。低于 1216px 时几何缩小下限为 80%，保留窄容器换行、滚动及卡片自然增高能力。
- 页面与卡片标题字号仍为 32px、16px，备注及页内普通文字仍为 14px；字重、颜色不变。共享弹层保留原组件字体。正文、控件与页面标题行高保持原值，卡片标题行高与缩放后的主图标槽位一致。
- 图标保留原素材与宽高比，包括三个 Tab 图标分别由原始 14×14、14×17、18×18 缩放。卡片内边距、间距、圆角及最小宽高随局部几何单位计算。
- 共享 Button / Select / Dropdown 保留组件实现与颜色、状态；仅通过此页 className / panelClassName 接入局部几何尺寸。Portal 使用仅含几何单位的 `.geometry`，不导入页面旧色彩或字体。未修改公共组件或全局 Token。
- Sidebar 尺寸与布局保持原样，因此可用卡片宽度由剩余空间计算，不承诺整个浏览器每个区域严格同比缩放。字号固定也意味着卡片实际高度可以高于缩放后的最小高度。

1440×787 真实数据页面实测：Sidebar 占用 240px，右侧容器 1200px，左右 Padding 37.8947px，网格宽 1124.21875px，Gap 22.7368px，三列各约 359.58px。主图标 34.10px，卡片自然高度约 136.83px（几何最小高度 134.53px，由未缩小的文字行高撑开）。创建按钮约 137.05×30.31px，排序触发器约 121.26×30.31px，Tab 高约 34.10px。页面与卡片标题和备注字号实测仍为 32 / 16 / 14px，无页面横向溢出。

当前用户可见真实环境预览保持 1440px CSS 视口；测试夹具默认宽度同步为 1440px、侧栏占位 240px。预览宽度设置不限制生产用户窗口尺寸。


## v1.32 — 方形 SVG 素材与字号调整（2026-11-03）

按用户更新的 design/asset 接入全部十个原始 SVG；卡片图标从 PNG 切换为对应 SVG，已加入 Tab 从 PNG 切换为 SVG。素材业务映射保持 department / mine / joined 原样。素材画布统一为正方形：卡片 44×44、Tab 18×18、元信息/操作图标 20×20；页面按已有槽位和视口几何单位显示，保留内部留白和宽高比。未修改左侧导航、全局 Token 或公共组件实现。

页面标题字号改为 24px，卡片标题改为 14px，保留字号不随视口缩放。卡片标题与主图标间距基准 14→12px（1440px 下约 11.37px）。更多图形缩小至先前的 80%：基准可见宽 16→12.8px、高 3.2→2.56px；采用完整的方形 SVG 画布 12.8×12.8px，不沿用旧裁切偏移，按钮点击区域保持不变。置顶图标统一为方形槽位，悬停派生图根据新 SVG 更新。当前真实数据预览保持 1440px 视口。


## v1.33 — 恢复 PNG、缩小置顶图标与尺寸取整（2026-11-03）

卡片图标恢复使用 design/asset 中三个 88×88 PNG，以保留设计导出的模糊与透明叠层效果。其他操作及 Tab 图标继续使用现有 SVG。置顶/未置顶两层图形统一按原来的 80% 缩小，再执行尺寸取整；按钮热区保持原有独立尺寸。

页面配置的几何长度统一向下取偶数 CSS px，字号、字重、透明度及素材内部矢量坐标不参与取整。仍以 viewport / 1520 计算目标值，再用 round(down, …, 2px) 量化；不支持 CSS round 的旧浏览器使用预先计算的 1440px 偶数长度。1px 边框和辅助隐藏元素保留整数，不为取偶数而增粗。

1440px 的主要值：页面 Padding 30px 36px 52px；Header/Toolbar/Grid 间距与网格 Gap 为 22px；卡片 Padding 14px 22px，主图标 34px，标题图文间距 10px；置顶图标由约 17.05×80%=13.64 向下取偶数为 12px；更多画布 12px。标题仍为 24px，卡片标题仍为 14px。

支持 CSS 长度除法和 round 的浏览器同时将网格列宽向下取偶数，余量留在网格右侧，不使用 space-between 或放大 Gap。旧浏览器保留原有自动弹性栅格，列宽可能含小数。字体字形的天然度量、文字内容自适应控件宽度与居中偏移不强制改写，以免截字或改变排版；取整覆盖设计配置的几何尺寸及支持环境中的卡片列宽，不承诺所有 DOM 文本边界坐标为偶数。

当前 1440×787 真实数据实测：右侧容器 1200px，网格宽 1128px，3 列各 360px，Gap 22px，右侧剩余 4px；卡片 360×134px，置顶/未置顶图形均为 12×12px。PNG 正常加载且 naturalWidth=88；页面无横向溢出。


## v1.34 — 卡片标题与紧凑纵向布局（2026-11-03）

卡片标题恢复为 16px，行高与图标槽位保持原样。卡片上下内边距、标题至备注间距、备注至页脚间距分别在前版取整后的值上减少 4px；左右内边距各减少 2px。页脚换行时行间距同样减少 4px，最低保留 2px。卡片最小高度相应减少 16px，极窄容器仍允许内容自然撑高。卡片之间的网格 Gap 不变。

1440px 真实数据实测：卡片 360×118px（原 360×134px），Padding 10px 20px，备注 margin 10px 0 8px，标题字号 16px，无卡片内容溢出。置顶图标、主图标、页面标题及 Sidebar 保持前版。


## v1.35 — 卡片内边距微调（2026-11-03）

按用户要求，卡片 Padding 固定为 14px 18px；标题至备注、备注至页脚的间距保留 v1.34（1440px 下分别 10px、8px）。卡片最小高度由 118px 增至 126px，较窄容器或更大内容仍可自然撑高；标题字号 16px、网格间距与其他布局不变。


## v1.36 — 备注下移 2px（2026-11-03）

备注 margin-top 增加 2px，margin-bottom 减少 2px，卡片高度及页脚位置不变。1440px 下 CSS margin 为 12px 0 6px；实测备注行框距标题/图标行底部 12px，距页脚行框顶部 8px（6px margin-bottom 加上页脚自动分配的 2px）。卡片高度仍为 126px。这里描述的是布局行框间距，非字形墨迹之间的距离。


## v1.37 — 卡片移动动画放慢（2026-11-03）

按用户要求，置顶、取消置顶和切换分类/排序时共用的卡片位置动画时长由 0.36 秒增加至 0.86 秒（增加 0.5 秒），原有缓动及依次移动延迟不变。置顶移动卡片的临时提升层级保持时间由 600ms 延长至 1100ms，覆盖较长的动画过程。仅调整知识空间卡片移动，不更改全局页面路由过渡；系统减少动态效果偏好继续生效。排序及后端调用逻辑不变。


## v1.38 — 卡片移动动画 0.6 秒（2026-11-03）

用户将置顶、取消置顶和分类/排序切换时共用的卡片移动时长定为 0.6 秒，替代 v1.37 的 0.86 秒。缓动和依次移动延迟保持不变。


## 最新发布分支整合验证（2026-11-03）

功能分支 feat/knowledge-space-redesign 已从 f442bf0ad 快进到 origin/feat/3.1.0-beta1 的 d8979cdf7，拉入 80 个提交；未发生合并冲突，既有本地知识空间修改逐文件与备份对比保持一致。保留远程空间设置错误处理及上传 API 拆分更新，无需覆盖业务实现。

整合后客户端 56 项相关测试、严格类型检查和生产构建通过。1440×787 真实联调页面实测：全部 73、部门 35、我的创建 31、已加入 7；卡片 360×126、Padding 14px 18px、Gap 22px、页面标题24px/卡片标题16px、置顶图标12px、备注margin 12px 0 6px（距页脚实测8px）、Sidebar240px，无卡片溢出。菜单保留编辑空间与删除空间，未执行删除或保存业务数据。卡片移动时长仍为0.6秒。未推送或部署。

## v1.39 — 模块首页框架统一（2026-11-03）

用户要求同时规整知识空间、订阅、应用、工具与技能首页，并选择最大 1000px 的居中内容列。知识空间接入公共 ModuleHome 页头与页面留白；统一参数和测量记录只维护于 [模块首页布局](module-home-layout.md)。该决定替代早期「只改知识空间、禁止调整公共框架」以及无限宽内容区的约定。卡片局部设计与业务回调继续沿用；正文独立滚动，页头与筛选保留在顶部。

## v1.40 — 桌面窗口变化保持组件尺寸（2026-11-03）

用户确认「卡片随内容区伸缩，只固定内部尺寸和字号」。取消 v1.31–v1.33 引入的 `viewport / 1520` 几何缩放；局部尺寸固定为此前 1440px 下的偶数像素值，覆盖页面和弹层。主图标 34px、Tab 高 34px、排序触发器 120×30px、网格 Gap 22px、卡片 Padding 14px 18px、最小高度 126px、圆角 12px、备注 Margin 12px 0 6px。页面标题 24/32px、卡片标题 16/34px、正文 14/22px；共享创建按钮继续使用原生 medium（高 32px）。

用户补充要求默认一行三张，并参考订阅模块的内容断点。订阅桌面端采用 `auto-fill + 固定最小卡宽`；知识空间沿用该方式，最小卡宽定为 300px，保留自身 22px 间距，替代随视口缩放的 350–440 基准区间及动态三等分下限。不能直接照搬订阅的 320px 最小宽：知识空间有列间距，三列需 `3×320+2×22=1004px`，超过默认内容列。

列数只由实际内容区宽度决定，缩窄不会增加列数。内容宽度 ≥944px 三列、≥622px 且 <944px 两列、<622px 一列；最大 1000px 下默认三列。列宽交给原生 auto-fill 弹性网格分配，可含小数；取消手算列数及列宽取偶数，避免浮点向下取整让恰好容纳两列的 622px 容器误判为一列。配置的内部几何尺寸继续使用偶数 px。极窄容器和长内容继续允许自然换行撑高，不缩小文字或图标。

根因、真实登录页面的修复前后测量及验证边界见 [桌面尺寸验证](verification/knowledge-home-desktop-sizing-20261103.md)。

## v1.41 — 分类栏切换为 Tabs（2026-11-03）

按用户要求，将四分类由局部胶囊切换为 `@bisheng/ui` 原生线型 Tabs，使用 medium、默认品牌选中态和底部分隔线。分类栏高 32px、字号 14px，替代 v1.40 的 34px 胶囊高度。保留组织与部门、我的创建、已加入空间的原有三个图标，使用固定 16px 槽位；全部空间仍无图标。保留标题后的括号数字，包括 `(0)`；加载或错误时继续显示 `—`，不使用会隐藏零值的数字徽标。

分类沿用受控状态与原路由回调；键盘切换、选中下划线及溢出滚动由共享 Tabs 管理。正文保留外置滚动面板，按共享 Tabs 生成的活动 Trigger ID / Content ID 同步 `aria-labelledby` / `id`，让 `aria-controls` 指向实际面板。移除被替代的胶囊样式与 Token，焦点样式使用 Tabs 原生内描边。卡片、排序和页头布局保持当前规则。

验证：真实登录页显示原三个图标、四分类括号计数及部门 `(0)`，Tabs 高 32px、字号 14px，活动页签与正文关联正确；知识首页、数据排序与路由返回三套既有测试 33 项通过，客户端 lint 与严格类型检查通过。既有测试改用原生 Tabs 的鼠标按下事件，并等待方向键异步移动焦点；未增加业务请求或修改共享组件。

## v1.42 — 更多按钮使用组件库 Button（2026-11-03）

按用户要求，卡片更多按钮使用 `@bisheng/ui` 的 `Button`：`default / text / small / iconOnly`，原生 24×24px 按钮与 14px `Outlined.More` 图标，带既有本地化无障碍标签与共享 Tooltip。页面旧更多 SVG 槽位、尺寸 Token 和透明度覆盖移除；默认态、悬停、菜单展开态及键盘焦点均使用按钮原生样式。Tooltip 放在菜单外侧布局容器上，Dropdown 与 Tooltip 的触发事件不会相互吞掉；按钮继续作为实际菜单触发器。现有菜单内容、权限、删除确认及面板样式保持原逻辑。

验证：真实登录页实测按钮 24×24px、图标 14×14px、卡片高 126px；点击正常显示编辑 / 删除菜单，浏览器原生 Esc 关闭后焦点回到触发按钮，并显示更多操作 Tooltip。知识首页、排序与路由返回回归 33 项通过，客户端 lint、严格类型检查、架构守卫和差异空白检查通过。

## v1.43 — 图标库升级与 Tabs 图标接入（2026-11-03）

按用户要求，将工作区 `bisheng-icons` catalog 升至 `^0.2.37`，锁文件解析为 0.2.37；client 改为引用同一 catalog，避免与 platform、共享 UI、chat 和 file-viewers 的版本分叉。使用项目指定的 pnpm 9.15.9 安装，锁文件仅更新本包版本、校验值及 client catalog 引用，保留其他依赖版本和平台元数据。

知识空间 Tabs 图标改为新版本实际导出的 `Filled.Departure`（组织与部门）、`Filled.Person`（我的创建）、`Filled.Tag`（已加入空间）；全部空间仍无图标。移除页面三个 SVG 导入及局部 img 尺寸样式，由共享 medium Tabs 统一为 16×16px。图标使用 currentColor，选中时与文字一起显示当前品牌色。分类计数、零计数、受控路由与筛选保持原逻辑；原素材只作为非活动设计参考保留。

依据 `client/AGENTS.md` 和组件库 `00-总纲.md` §七升级注意事项，清理 client / platform 的 Vite 预构建缓存并以 `--force` 重启两个开发服务。两端日志均确认强制重建，预构建文件哈希变化且包含新图标导出，避免旧缓存造成 `Element type is invalid` 白屏。

验证：npm 发布包 SHA-512 与注册表一致，各调用方实际安装版本均为 0.2.37；真实登录页面三个分类均渲染 SVG、无旧 img，图标 16×16px，切换我的创建后 SVG 填充色与品牌文字色一致、显示 3 张卡片、卡片仍高 126px，页面无横向溢出且无浏览器错误日志。知识首页相关 33 项 Jest 回归、工作区配置 37 项测试、全仓类型检查及 client / UI lint 通过。全仓 lint 仍受管理端三份未改文件中的 8 处既有错误阻断，未将其计为通过。

## v1.44 — 卡片元信息与无边框排序（2026-11-03）

按用户标注，将卡片页脚的创建人和更新时间使用 `text-caption`（桌面 12px / 20px）。创建人图标从 `menber.svg` 改为 `bisheng-icons` 的 `Outlined.People`，固定 14×14px，颜色继承创建人文字；原素材作为非活动设计参考保留。卡片标题 16px、备注 14px 与既有业务取数逻辑保持。

排序使用共享 Select 的原生 `medium / ghost` 无边框形态，替代 outlined；移除页面对触发器宽高、内边距和箭头尺寸的覆盖。触发器高 32px、宽度随当前文字，默认无底无边，悬停和展开铺组件原生浅灰底。排序选项、回显和回调沿用现有实现。

真实登录页面 1440px 视口实测：四张卡片创建人和时间均为 12px / 20px，创建人均渲染 14px SVG；卡片仍为三列、高 126px，标题 16px、备注 14px。排序触发器当前值为「按创建时间」时 106×32px，收起 / 展开边框均为 0px，切换「按名称」后正确回显并选中，再恢复「按创建时间」。无横向溢出及浏览器错误日志。相关 33 项 Jest 回归、客户端 lint、全仓类型检查、架构守卫及差异空白检查通过。

## v1.45 — 卡片标题 14px（2026-11-03）

按用户要求，将卡片标题字号从 16px 调整为固定 14px。保留 500 字重、34px 行高及既有图文间距；创建人和更新时间仍为 12px，卡片其他布局和交互沿用当前实现。

## v1.46 — 卡片颜色接入共享 Token（2026-11-03）

用户授权自行选取现有色板中相近的颜色。卡片局部变量改为引用 `@bisheng/ui` 的语义色彩，不新增全局色值或调色板：

| 部位 / 状态 | 共享 Token | 浅色取值 |
|---|---|---|
| 卡片默认 / 悬停 / 按下底色 | `fill-1` / `fill-2` / `fill-3` | `#F8F8F8` / `#F3F3F4` / `#E5E6E9` |
| 卡片标题 | `text-1` | `#1D2129` |
| 创建人、更新时间及创建人图标 | `text-2` | `#525865` |
| 备注与置顶图标 | `text-3` | `#898F9C` |
| 空备注占位 | `text-4` | `#CACDD4` |
| 页底色 | `bg-page` | `#FFFFFF` |

备注取消局部透明度调色，直接使用语义颜色；置顶图标沿用原 SVG 的形状和透明度，用 CSS alpha mask 继承 currentColor，避免文件内固定颜色阻断 Token。三个分类 PNG 保留原设计插画。局部禁用态引用组件库禁用 Token，键盘焦点引用 `text-2`；移除页面强制浅色色彩方案，颜色取值随共享 Token 解析。按下规则位于悬停规则之后，使按下色能正确覆盖悬停色。

真实登录页面浅色验证：默认背景为 248/248/248，标题为 29/33/41，创建人和时间为 82/88/101，空备注为 202/205/212，置顶图标为 137/143/156；卡片仍三列、高 126px，标题 14px、页脚 12px。更多菜单仍能展开和关闭，无浏览器错误日志。相关 33 项 Jest、客户端 lint、全仓类型检查、架构守卫和差异空白检查通过；全仓 lint 仍受管理端三份未改文件中的 8 处既有错误阻断。

## v1.47 — 部门页签名称（2026-11-03）

按用户要求，将知识首页的「组织与部门」页签改名为「部门知识空间」，同步英文 `Department knowledge spaces` 和日文 `部門ナレッジスペース`。沿用现有翻译键、图标、括号计数及 department 分类值，筛选和路由保持现有行为。

## v1.48 — 窄屏列表按空间类型显示分类图标（2026-11-03）

按用户提供的桌面图标参考，将 768px 断点以下的知识空间列表图标切换为同一套分类 PNG：部门空间使用蓝色组织图标 `card-1.png`，我创建的使用橙色人物图标 `card-2.png`，我加入的使用绿色标签图标 `card-3.png`。桌面卡片与窄屏列表通过 `knowledgeSpaceIcons.ts` 共用映射，依据既有来源分类取图，避免三类空间再次统一为通用文件夹。窄屏按用户后续要求统一改为 32×32px；现有布局切换条件仍为宽度 <768px。

验证：390px、767px 实页中创建与加入空间的图标均加载成功且为 48×48px；768px 和恢复后的 1187px 仍为桌面卡片。当前账号部门列表为空，部门素材与映射已静态核对。相关 33 项 Jest、客户端 lint、全仓类型检查、架构守卫及差异空白检查通过；全仓 lint 仍受管理端三份未改文件的 8 处既有错误阻断。测试使用临时进程配置避开未构建的可选 canvas，并从现有 pnpm store 补充 Babel runtime 搜索路径，未改仓库测试配置或安装依赖。

尺寸修订验证：用户后续指定 32px，统一调整为 `size-8` 与图片宽高属性 32；390px 实页中创建及加入空间图标均实测为 32×32px。定向 ESLint、架构守卫与差异空白检查通过。

## v1.49 — 更多菜单与提示的焦点协作（2026-11-04）

更多菜单关闭后只恢复按钮焦点，不自动重新打开 Tooltip，替代 v1.42 验证记录中的恢复焦点即显示提示。修复位于共享 Tooltip，页面无需新增开关；交互规则及实现依据统一维护于 [Tooltip 规范 §6](../src/frontend/packages/ui/docs/组件-Tooltip文字提示.md#6-触发与时序)。共享 Select / Cascader 触发器保留 asChild 注入的 DOM 属性及事件，与自身字段事件合并。

## v1.50 — 卡片点击直接进入（2026-11-04）

按用户要求，移除卡片整体的 `:active` 变色及对应的按下色 Token，点击沿用原有空间导航回调直接进入，不增加闪烁、缩放或点击动画。悬停提示、键盘焦点，以及更多 / 置顶按钮各自的交互仍按现有组件规则处理。

验证：共享 Tooltip / Tabs / 权限面板相关 26 项交互回归及知识首页 33 项回归通过，全仓 lint、类型检查、架构守卫和差异空白检查通过。真实浏览器中点击「111」进入 `/workspace/knowledge/space/5?tab=all`；更多菜单按 Esc 关闭后焦点仍留在更多按钮，卡片提示未重新出现。

## v1.51 — 卡片结构整理（2026-11-04）

按用户要求整理卡片实现。外层保留 `article` 及位置动画，内容区改用真实 `Link` 包含图标、标题、描述和元信息，移除标题 `button::after` 的整卡覆盖层。置顶按钮和更多菜单作为链接的同级元素，分别定位到右上与右下，内容预留对应空间，无交互元素嵌套及额外覆盖层层级。普通点击和 Enter 继续调用既有空间选择回调，以保留即时详情数据与加载逻辑；Ctrl / Cmd / Shift 等修饰点击交给原生链接，目标 URL 保留当前列表 Tab。演示卡片链接留在当前首页，沿用既有只读提示和操作禁用限制。

`KnowledgeHomeCard` 只负责组合展示、导航和置顶入口；`KnowledgeHomeCardMenu` 使用组件库的 Button / Dropdown / DropdownItem / Tooltip，集中处理菜单权限、加载态与删除确认，删除旧局部 Radix 菜单分支；`useKnowledgeHomeCardCreator` 保留可见后补查创建人的查询与缓存策略。卡片 CSS 独立到 `KnowledgeHomeCard.module.css`，清除覆盖层、旧内联重命名和无效按钮样式。既有卡片尺寸、标题 14px、元信息 12px、色彩 Token 和点击无变色要求保持。

验证：知识首页、排序与真实路由返回共 44 项 Jest 回归通过，涵盖内容点击、键盘进入、修饰点击、演示数据、独立操作及菜单关闭后的 Tooltip；全仓 lint、类型检查、架构守卫和差异空白检查通过。浏览器自动化连接目标标签页失败，重构后的实页视觉尚未核验。

## v1.52 — 卡片四边内边距 16px（2026-11-04）

按用户要求，将卡片上下内边距从 14px、左右内边距从 18px 统一调整为 16px。内容链接、置顶按钮和更多菜单共用这两个内边距变量，操作入口随内容边界同步对齐；卡片继续允许内容自然撑高。

## v1.53 — Tabs 原生计数（2026-11-04）

按用户要求，将四个分类的数量传给组件库 `Tabs.items[].badge`，`label` 仅保留分类文案。数字徽标的外观、间距及主题色使用组件默认实现，既有图标、分类筛选和路由状态沿用。遵循原生规则，计数为 0 时不显示徽标；加载中或加载失败时传 `undefined`，不显示尚未确认的数量或自定义占位文字。

## v1.54 — 记住排序方式（2026-11-04）

原排序仅由 `useState('create_time')` 保存，知识首页重新挂载或刷新时恢复默认。改由 `useKnowledgeHomeSort` 管理，以 `localStorage` 的 `knowledge-home-sort:<userId>` 按账号保存最近一次排序选择；页面首次渲染即恢复合法配置，四个分类继续共用同一排序方式。离开模块再进入或刷新后，选择器回显与卡片顺序均按已保存的选择恢复；置顶优先的规则保持。

未登录或身份尚未加载时不写入账号偏好，身份切换时恢复对应账号的值，且仅在用户选择时写入，避免默认值或上一账号状态覆盖已有配置。采用独立键名，使现有登录时对 `bs:*` 聊天参数的清理不影响列表偏好。缺失或不合法的值使用原默认「按创建时间」；浏览器存储不可用时，当前页面仍可正常切换排序。

验证：知识首页、实际路由往返、排序规则及偏好存储共 57 项回归通过；覆盖三种排序的写入与重新挂载恢复、分类切换后保留、离开模块再返回、账号切换、身份延迟加载、无效配置与存储不可用。全仓 lint、类型检查、架构守卫和差异空白检查通过。

## v1.55 — 深色模式分类图标（2026-11-04）

采用用户提供的三张 132×132 RGBA PNG，原字节复制入库：蓝色 `Space icon · blue.png` 对应部门知识空间，橙色 `Space icon · orange.png` 对应我的创建，绿色 `Space icon · green.png` 对应已加入空间。素材的透明层、光晕与模糊保留原样，不重新绘制或调色。

`knowledgeSpaceIcons.ts` 维护每个分类的 light / dark 素材，`KnowledgeSpaceCategoryIcon` 通过应用现有 `.dark` 主题类切换可见图片，桌面卡片与窄屏列表共用。跟随应用手动主题切换及系统主题解析结果，不单独订阅系统偏好；浅色素材和当前 34px / 32px 显示尺寸不变，分类业务来源、卡片结构和图文间距沿用。

验证：三张入库 PNG 与用户源文件逐字节一致，SHA256 已登记素材 README；主题可见性样式已通过实际 Tailwind 编译，浅色隐藏深色图，`.dark` 下显示深色图并隐藏浅色图。相关 63 项回归、全仓 lint、类型检查、架构守卫和差异空白检查通过。浏览器连接仍因 `timeoutMs` 工具异常失败，实页视觉未复核。

## v1.56 — 更多与排序弹层恢复组件默认尺寸（2026-11-06）

此前 v1.31 的局部几何缩放覆盖了卡片更多菜单和首页排序下拉框。按用户要求，两处弹层均沿用共享 Dropdown / Select 的默认尺寸，不再传入页面的 `.geometry` / `.productMenu`；本条替代 v1.31 对这些弹层的尺寸约定。页面与卡片自身的几何配置仍由本页维护。

排序只保留共享 Select，删除旧 Radix 排序预览分支及其菜单样式；`componentMode` 只控制剩余的创建按钮预览。首页回归直接使用真实共享 Select，覆盖排序选择、重新挂载恢复和 Escape 关闭后保留触发器焦点。

验证：搜索 Client / Platform 源码确认上述菜单缩放类已无引用；空间内部文件排序、侧边栏项目及对话菜单未使用这套覆盖。知识首页 28 项回归、全前端 lint / typecheck、架构守卫与差异空白检查通过；Jest 通过临时进程配置忽略本机未编译的可选 canvas 依赖。真实浏览器中已展开首页排序和卡片更多菜单核对外观，并验证排序按 Escape 关闭后焦点保留。

## v1.57 — 分类空状态（2026-11-09）

首页分类为空时使用组件库 `StateView` 和 `EmptyStateIllustration`。图文在工具栏下方的列表区域水平、垂直居中，沿用页面级 120px 插画和 16px 图文间距。内容区不足 320px 宽或 200px 高时降为组件库的内联档。加载、出错和有内容的页面仍走原有分支。

我的创建显示「现在还没有内容，立即创建」，已加入空间显示「现在还没有内容，前往广场看看吧」。操作是句内的品牌色链接按钮，分别调用现有创建和广场入口。全部空间及部门知识空间各有对应提示。`com_knowledge.home_next` 增加 `empty_all`、`empty_content`、`empty_created`、`empty_department`、`empty_joined` 五个三语文案键。

验证：44 项首页与导航回归、全前端 lint / typecheck 通过。真实浏览器实测「已加入空间」的插画为 120×120px，图文组在列表区域内居中，区域没有新增滚动条；点击「前往广场」进入知识广场。「立即创建」的文案和回调由回归测试覆盖。
