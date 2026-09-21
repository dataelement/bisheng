# F062 平台 UI 实施核对

核对日期：2026-09-09。工作树：`feat-3.0.0-beta2-pre`。

## 规范与复用

实现前读取当前 `platform/AGENTS.md`、`packages/ui/docs/index.md`、实际存在的 `packages/ui/docs/components/index.md`（任务所写 `index.mdx` 不存在），以及字体、色彩、阴影与圆角、多端、Button、Modal 规范。Button 已落地；其余未定稿组件遵循当前 `SystemPage/components/OrgSync` 和平台现有实现。没有修改设计规范、共享组件样式或引入库。

| 用途 | 复用位置 |
| --- | --- |
| 按钮 | `platform/src/components/bs-ui/button` |
| 输入 | `platform/src/components/bs-ui/input` |
| 筛选 | `platform/src/components/bs-ui/select` |
| 模型复选 | `platform/src/components/bs-ui/checkBox` |
| 管理分页表格 | `platform/src/components/bs-ui/table` |
| 系统与 DSH 分页签 | `platform/src/components/bs-ui/tabs` |
| 撤销与重分配确认 | `platform/src/components/bs-ui/alertDialog/useConfirm` |
| 布局参考 | `platform/src/pages/SystemPage/components/OrgSync` |

授权页复用平台背景、border、rounded-lg、text-muted-foreground 和 Button。使用 max-w-xl 与弹性换行，未添加玻璃模糊、视觉组件或新增设计规则。所有组件为命名导出，所有新增文件少于 600 行。

## 数据与边界

- 请求统一使用 `controllers/request`；新 API 为 `controllers/API/dsh.ts`，DTO 为 `types/dsh.ts`。没有 store HTTP 或新增 react-query 导入。
- 裸 config 仅在该请求的 transformResponse 中适配既有解包器；八管理请求使用既有统一 envelope。变更请求 opt-in preserveError，在共享拦截与提示之后保留原错误，旧调用行为不变。
- 用户选择复用 `/api/v1/user/list` 的 20 条分页和搜索，包含未占用席位用户；模型复用 `/api/v1/llm`，保留 Root 共享标识，只列上线 LLM，最终准入由服务端验证。
- 页内状态不与 Client 的 Recoil/组件混用。系统入口仅显示给全局或子租户管理员；普通身份可以访问独立 `/desktop-login`。
- 文案位于 `public/locales/{zh-Hans,en-US,ja}/bs.json` 的 `dsh`。旧请求封装的两个登录过期提示同步提取为 `request.session_expired/sign_in_again`。未手工编辑生成的 api_errors 文件。
