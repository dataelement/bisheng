# Wave 12 记录：前端 Platform（T076–T080）

## 自己定的决定

- 环境｜worktree 起点是 main（af1894a538），不含 Wave 0–7｜用 `git switch -C` 把本 worktree 自己的分支指到 `feat/v3.0.0/132-long-term-memory` 的 b6a036d4b4（Wave 7 accepted）后再开工｜任务要求的基线是含 Waves 0–7 的提交，worktree 干净，切分支只影响本 worktree。
- 环境｜`platform/node_modules` 整体软链到主检出后，`@bisheng/ui` 等工作区包的相对链接解析到主检出的 `packages/ui`（版本不同，引用了未安装的 `react-day-picker`），vitest 与 typecheck 都报错｜把 `platform`、`client`、`packages/chat`、`packages/file-viewers` 的 `node_modules` 改成本地目录：其余条目逐个软链到主检出，`@bisheng/*` 重新建相对链接指向本 worktree 的 packages｜不安装依赖，只换软链；改后基线 `pnpm typecheck` 退出码为 0。这些目录被 gitignore，不进提交。
- 全部｜测试放置位置｜用 tasks.md 点名的 `__tests__/` 路径（V6 说两种都可被 include 匹配）｜验收命令按名字过滤，任务路径与文件名一一对应，便于追溯。
- T076｜节点分组名在模板里一直是中文字面量，并兼作 i18n key（`node.<type>.<分组名>`）｜新分组名用英文 key：`retrieval_settings`、`output`（检索节点），`memory`（开始节点）｜源码不新增中文字面量；渲染方式 `t(\`node.${type}.${name}\`)` 不变。
- T076｜图标｜`bisheng-icons` 的 `Outlined.Notebook`，底色 `bg-[#E4D7FF]`｜平台规定优先用 bisheng-icons，色值与现有节点区分。
- T076｜单节点运行按钮｜不给记忆检索节点加"运行此节点"｜单节点运行不建 GraphEngine，`chat_id` 为空，节点只会输出空数组（V4）。
- T077｜存量工作流的开始节点没有 `memory_enabled`，作者无法开启｜在 `util/flowCompatible.ts` 的 `comptibleStart` 末尾幂等补上"记忆"分组（值为关），不改 `v`｜不补的话 AC-70 对存量工作流不可达；不改 `v`，后端开始节点 `v` 判定不受影响；缺失仍按关处理。
- T077｜AC-75 说明要"在开关旁"｜给 `SwitchItem` 增加可选 `desc` 字段，开关下方常显一行说明；`desc` 不设时渲染与原来一致（仅外层多一层 div）｜tooltip 需要悬停才能看到，不满足"旁边说明"。
- T077｜保存路径原本不调用 `validateNodes`｜在 `Header.tsx` 的 `handleSaveClick` 与 `handleSaveNewVersion` 里加 `validateMemoryLimits`，不合法时提示范围并不保存；`validateNodes`（运行、上线）也校验 limit；上线额外传 `{ publish: true }` 检查开关｜AC-80 要求保存时拒绝；AC-85 只约束上线，画布调试不拦（调试 `chat_id` 为空，本来就取不到记忆）。`Header.tsx` 不在任务文件清单里，是接入点所需。
- T077｜纯函数位置｜判定逻辑放新文件 `util/workflowMemory.ts`（模板分组工厂、limit 判定、开关判定），`useNodeEvent.ts` 导出 `validateMemoryLimits` 与常量｜模板、存量升级、校验三处共用一份定义。
- T077｜limit 判定｜接受 1–100 的整数和纯数字字符串，拒绝 0、101、1.5、空串、非数字｜`InputItem` 的数字输入把值存成数字或空串，导入的旧数据可能是字符串。
- T078｜开关放在哪｜设置页末尾新增"记忆"标题块（不放折叠面板里），开关加常显说明｜折叠面板默认收起，说明会被藏住；`memory_enabled` 经 `dispatchAssistant('setting')` 写入状态，`handleSave` 以 `...assistantState` 原样提交。
- T079｜下拉的选项来源｜用 `useModel()` 的 LLM 选项（与工作台模型页 `WorkbenchModel` 同源），控件用现有 `ModelSelect`（Cascader，`close` 可清空）｜沿用现有组件；保存时空值写 `null`，加载时 `memory_model_id` 转成字符串。
- T079｜测试里 `t` 必须稳定｜全局 setup 的 `useTranslation` 每次返回新 `t`，`useChatConfig` 的 effect 依赖 `t`，会无限重载｜测试文件内改用稳定的 `t` mock（与 `menuNameSave.test.tsx` 同法）。
- T080｜识别规则｜工具名（`tool_key`/`tool_name`/`name`）以 `memory_` 开头，或载荷本身/`input_str`/`output`/`args`/`results` 等任一字段含 `redacted: true`，即视为记忆操作｜后端脱敏遗漏时也按工具名兜住，比只认 `redacted` 更严。
- T080｜助手/工作流页｜在 `PlatformConversationMessages` 里对 `run` 卡片做映射：`raw.thought`、`raw.intermediate_steps`、`raw.message`、`text` 全部换成占位，`payload` 只留 `tool_key` 与 `redacted`；`runPresentation` 对同一判定返回 `{ title: '记忆操作', unavailable: false }`｜按 R7，不改共享包；标题不再显示"工具已删除"。
- T080｜日常页｜`extractDisplayText` 在事件里有记忆工具调用时不再回落原始 JSON：有正文只显示正文，无正文显示占位；`t` 经 ref 读取｜封住 `dailyChatDetail.tsx` 回落 raw 的泄漏口；用 ref 避免 effect 依赖 `t` 造成重复请求。
- T080｜locale｜占位文案放 `bs.json` 顶层 `memory.operation`｜两处页面都用 bs 命名空间。

## 需要用户确认

无。

## 实际偏差

- T077 改了任务文件清单之外的 `flow/Header.tsx`（保存与上线入口）、`flow/FlowNode/component/SwitchItem.tsx`（常显说明）、`util/flowCompatible.ts`（存量开始节点补开关），新增 `util/workflowMemory.ts`。
- T079 新增 `bench/MemoryModelConfig.tsx`；"工作台默认模型"的说明除占位文字外还有一个问号提示（`chatConfig.memoryModelHint`）。
- T080 实际改动点是 `PlatformConversationMessages.tsx` 与 `dailyChatDetail.tsx`（按 R7 / V6），`DailyMessageContent.tsx` 未改；新增 `components/bs-comp/appChat/memoryPlaceholder.ts`。
- 不涉及后端，未改任何 `src/backend` 文件与既有测试。

## 验收输出

`cd src/frontend/platform && pnpm exec vitest run memoryRetrieverTemplate memorySwitchValidate memorySwitch memoryConfig memoryPlaceholder`：

```
 Test Files  5 passed (5)
      Tests  35 passed (35)
```

`cd src/frontend && pnpm lint && pnpm typecheck && pnpm check-i18n`：退出码 0，最后几行：

```
> @bisheng/api-client@0.1.0 typecheck .../src/frontend/packages/api-client
> tsc --noEmit
[check-i18n] info: 84 frontend-only error code(s) (dead-key candidates / gateway codes)
[check-i18n] OK — no new i18n drift
```

对改动的前端文件逐个运行 `scripts/arch-guard.sh`：无 VIOLATION。

与本 Wave 无关、基线上就失败的平台测试（未改动相关文件）：`src/utils/dshRequestError.test.ts`（4 条）、`src/pages/BuildPage/bench/IconUploadSection.test.tsx`（4 条）、`src/pages/LogPage/systemLog/index.test.tsx`（1 条，`@/controllers/API/log` mock 缺 `actionToI18nKey`）。
