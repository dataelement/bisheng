# 项目内新建对话：实现说明

## 方案与理由

- 草稿通过 `/c/new?projectId=…` 携带目标；全局新建与已有会话路径不带该参数。沿用现有对话创建流程，空白草稿不预建服务端会话，也不将共享占位 id `new` 写入项目归属。
- `projectChatCreation.ts` 在 SSE 打开时捕获目标，在 `created` 或任务 `linsight_task_handoff` 返回正式 id 时调用现有 `moveChatToProject`。不能等事件到达再读取当前路由，因为用户可能已切换项目；登记前再次确认项目未被删除，同一个流只登记一次。
- 不新增后端字段、API 或状态库。归属仍由 `projectsStore` 持久化；正式会话继续由 react-query 维护。未来后端项目模型落地时，应一起替换项目存储与流式创建归属逻辑。
- “新建对话”放在项目“更多”右侧，按钮组使用 `gap-1` 保持 4px 间距。按用户明确要求，两者使用相同原生 button 与同一份 `PROJECT_ACTION_BUTTON` 样式，复用旧按钮的 20px 尺寸、44px 触屏尺寸、16px 图标、悬停底色及显隐规则；Tooltip 都由相同的有尺寸包装元素承载。
- 对话行“更多”也复用 `sidebarIconButton.ts` 中的同一基础样式及 `Outlined.More`，采用相同的原生 button、Tooltip 和有尺寸包装元素。按用户后续要求，选中状态不再使按钮常驻；桌面端行悬停、键盘 `:focus-visible` 或菜单打开时显示。使用 `:focus-visible` 而非 `:focus-within`，避免鼠标点击会话后残留焦点让按钮继续显示；日期的隐藏条件同步跟随键盘焦点。
- “移入项目”子菜单按“新建项目／已有项目／移出项目”分组，以共享 `DropdownSeparator` 分隔；无项目列表时省略对应分隔线。新建动作等菜单 `onCloseAutoFocus` 释放焦点后打开现有 `ProjectNameDialog`，提交时创建项目并移动当前会话；取消不修改任何数据。
- 会话行分别维护菜单逻辑开关与呈现生命周期：关闭后保留触发按钮布局，直到菜单退出动画完成、`onCloseAutoFocus` 通知 `onMenuExit` 后才收起。否则触发按钮提前变成 `display: none`，仍在淡出的浮层会失去锚点并重新定位到左侧；任务执行中的图标交换也跟随同一呈现生命周期。

## 3.0 适配

原实现依赖 3.1 的移动端工作台导航改造 `7c6abfe027`。该改造让 `WorkbenchSidebar` 统一查询会话列表并管理项目展开状态，再通过 props 传给 `SidebarProjects`。3.0 没有这个改造，因此 3.0 版本做以下取舍：

- `SidebarProjects` 继续自己查询会话列表、自己管理展开状态，只新增 `onStartChat` 一个 prop；`WorkbenchSidebar` 把 `useStartNewChat` 返回的函数传入。
- 3.0 没有窄屏工作台侧边栏，所以不传 `onNavigate`，也不关闭窄屏导航。
- `ConvoOptions` 保留 3.0 的窄屏判断：窄屏下不显示「移入项目」，因为 3.0 窄屏看不到项目区。
- 3.1 专有的 `Convo.navigation.test.tsx` 与 `WorkbenchSidebar.mobile.test.tsx` 不带入。菜单退出生命周期的回归改放在 `Convo.menuExit.test.tsx`，项目内新建入口的回归改放在 `SidebarProjects.newChat.test.tsx`。
- `sidebarIconButton.ts` 与原实现内容相同，包含 `coarse-pointer:size-11`。在触屏宽屏设备上，带操作按钮的行会随 44px 触控尺寸变高。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| SidebarProjects | 展开目标项目、调用新建（3.0 不涉及窄屏导航） |
| WorkbenchSidebar | 保持新建 hook 挂载，向项目提供相同新建入口 |
| NewChat | 携带项目参数，第二次延迟重置前确认仍在同一草稿路径 |
| projectChatCreation / projectsStore | 捕获本次创建意图、检查项目存在并保存归属 |
| useAiChatSSE | 正式会话或任务创建事件接入归属登记 |

## 已知注意点

| 情况 | 处理 |
| --- | --- |
| 首次新建后 300ms 的延迟重置可能覆盖快速发送或其他导航 | 路径与项目参数不匹配则跳过旧重置；再次新建会取消旧计时器 |
| 重复 created 事件可能覆盖用户刚做的移动 | 每个流只执行一次归属登记 |
| Tooltip 的定位锚点使用 display: contents 会缺少尺寸 | 两个包装元素均使用 inline-flex，保留真实定位框 |
| 菜单关闭时立即隐藏其触发按钮，会让浮层在退出动画期间丢失锚点 | Convo 保留操作区域到 onMenuExit；回归用例验证关闭期间仍为 display:flex，退出后才隐藏 |
| 本机可选 canvas 已安装但缺少原生二进制 | 用临时 Node preload 令该可选模块不可解析，恢复 jsdom 的无 canvas 模式，不修改仓库依赖 |

## 修订历史

- 2026-11-02：补全项目内新建；按用户反馈统一两个按钮的实现与交互。
- 2026-11-03：按高优要求移植到 feat/3.0.0，适配 3.0 侧边栏结构（见「3.0 适配」）。
