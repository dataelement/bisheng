# 组件总览

组件库的实时 demo 页。每个组件页用 `@rspress/plugin-preview` 直接渲染 `src/frontend/client/src/components/ui/` 下的**真实业务组件**——所见即业务页所得，组件代码一改，这里同步变。

规范正文（定义、取值、状态矩阵、迁移台账）在顶部导航「文档」；组件页以演示为主，只穿插最要紧的使用规则。

## 组件清单

| 组件 | 状态 | 内容 |
|---|---|---|
| [Typography 字体](/components/typography) | ✅ 规范 v1 | 字体栈实时示例 / 九档字号阶梯（实时渲染 + 移动端重映射）/ 两档字重 / 使用规则 |
| [Color 色彩](/components/color) | ✅ 规范 v1 | 品牌色蓝绿双 ramp 色块 / 灰阶 1–10（实时取 var）/ semantic 层对照 + 实时示例 / 语义色四组 / 标签色 |
| [Button 按钮](/components/button) | ✅ demo 齐全 | 常用类型 6 别名 / color×variant 3×5 全矩阵 / 尺寸三档 + iconOnly / 内容形态（纯文字、纯 icon square+circle、文字+icon、icon 在右）/ disabled + loading |
| [Modal 弹窗](/components/modal) | 🟨 标准未定稿 | 基准候选壳（OGDialogTemplate）demo / 壳规格已定项 / 过渡期规则 / CommentDialog 共享壳 |
| [Confirm 二次确认](/components/confirm) | ✅ 已定稿 | useConfirm() destructive / default 两档可打开 demo / 规格 Anatomy / 使用规则 |
| [Feedback 点赞点踩](/components/feedback) | ✅ 已收敛 | MessageFeedbackButtons 三种初始状态（回调可视化）/ 延迟点踩规则 |
| [Icon 图标](/components/icon) | ✅ 规范 v1 | bisheng-icons 全量清单（遍历库导出，升版自动同步）/ 尺寸六档 + strokeWidth 补偿 / 着色 / 使用规则 |
| [Illustration 插画](/components/illustration) | ✅ | 7 个主题化插画 × 蓝 / 绿 / 灰稿三态切换 / 调色板 |
| Select / Dropdown / Input / Tabs | ⬜ 待补 | 规范待建 |

## demo 书写约定（给补页面的窗口）

- 每个 `tsx` 围栏代码块必须是**自包含完整组件**（有 `export default`），plugin-preview（internal 模式）才会渲染成 demo。
- 组件从 `~/components/ui/*` 导入，图标从 `bisheng-icons` 导入（`Outlined.*` 优先）——与画廊同款写法。
- 用到 `useLocalize` / `useConfirm` 的组件，demo 里要自带脚手架：`<RecoilRoot initializeState={({ set }) => set(store.lang, 'zh-Hans')}>`（+ `ConfirmProvider`）包一层，并 `import '~/locales/i18n'`（不固定 lang 会跟浏览器语言走成英文）；业务页无需这样做。
- demo 内布局用内联 style，别用 app CSS 里不存在的 Tailwind 任意值类（文档站的样式来自 app 构建产物，docs 目录不在 tailwind content 扫描范围）。
- 本目录只能用 **ASCII 文件名**（中文子目录路由会空白）。
- 文档站为默认蓝主题（没有 theme-green），品牌色显示蓝色是正常的。
