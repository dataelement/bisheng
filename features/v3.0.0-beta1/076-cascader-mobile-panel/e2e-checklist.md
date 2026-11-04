# E2E 验证清单：Cascader 移动端单面板

日期：2026-11-02。环境：本地 Chrome，组件文档 `http://localhost:3000/components/cascader.html`；使用文档示例数据，无后端写入。仅 UI 功能，API E2E 不适用。

## AC 覆盖

| AC | 操作与观察 | 结果 |
|---|---|---|
| AC-01 | 390×844 打开基础单选：一个锚定浮层、无底部抽屉和遮罩；320×480 打开长列表自动向上展开，边界为 x=49…271、y=8…271，页面宽 320 | PASS |
| AC-02 | 已选第三层只显示「设计组 / 前端组」所在的当前列；返回后显示「产品部 / 交付部」，再返回根级；每次只有一列 | PASS：浏览器 + 组件测试 |
| AC-03 | 长列表真实点击进入后再返回：菜单 scrollTop 102 → 102，页面 scrollY 1388 → 1388；父项继续高亮 | PASS：浏览器 + 组件测试 |
| AC-04 | 选叶子后关闭并回显末级；再次打开恢复已选层级；受控展开及 defaultOpen 均恢复选中路径 | PASS：组件测试；浏览器验证回显与重开 |
| AC-05 | 搜索完整路径、无匹配状态、清空后上下键操作当前层；左右键不跳层，回车选择、ESC 收起 | PASS：组件测试 |
| AC-06 | 多选「售后 FAQ」后立即出现在触发器标签中，面板保持打开；没有完成按钮，再次点触发器收起；父子联动与严格父项选择正常 | PASS：浏览器 + 组件测试 |
| AC-07 | 懒加载失败后重试成功；加载、空数据、禁用、只读、点击外部保持目标焦点与 ESC 回到触发器 | PASS：组件测试 |
| AC-08 | 390×844 深浅色、320×480 窄屏短视口；长列表可滚动，页面不横向溢出；1280×800 桌面恢复三列、无返回按钮 | PASS：浏览器 + 组件测试 |
| AC-09 | Cascader 设计规范与示例同步；Select §9 对齐其当前锚定浮层实现；保留 doneLabel 类型兼容并说明弃用 | PASS：文档检查 |
| AC-10 | 浏览器测量菜单行 32px、返回按钮 24×24、导航行 32px、导航下边框 0px | PASS |

## 自动化检查

- [x] `pnpm exec vitest run src/test/sharedCascader.mobile.test.tsx src/components/bs-comp/formFields/modelOptions.test.ts --maxWorkers=1 --minWorkers=1`（platform）：2 文件、19 项通过。
- [x] `pnpm --filter @bisheng/ui typecheck` 与 `pnpm --filter @bisheng/ui lint`：通过。
- [x] platform 针对 `src/test/sharedCascader.mobile.test.tsx` 的 ESLint：通过。
- [x] frontend 配置的 `pnpm typecheck`：通过。
- [ ] frontend 全量 `pnpm lint`：被未改动的 `platform/src/controllers/API/linsight.ts` 5 处 `any`、`platform/src/test/speechForm.test.tsx` 1 处未使用变量阻断；这两个文件与 HEAD 无差异，本次未修改。
- [ ] 真实手机 Safari 与软键盘弹出场景：本机未验证。

## 截图

- 浅色：`cascader-mobile-compact-light.png`
- 深色：`cascader-mobile-compact-dark.png`

截图保存在当前聊天的 visualization 输出目录；最终回复附深色效果。
