# F062 平台 UI 交付记录

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

> 当前有效修订：用户确认每用户可配多个模型，各模型独立月额度；一期不做限流，配置使用有字段说明的类型对象。DM8 实机本轮暂缓。最新代码、契约变更及实际验证结果见 [逐模型修订验收](./model-quota-revision.md)。下文保留此前检查时点的证据，测试数量不与新版相加。

日期：2026-09-09；B 分支 `feat-3.0.0-beta2-pre`。未提交、未推送。

## 实现范围 T100–108

- T100：规范、现有组件和语言源核对见 `platform-ui-check.md`。
- T101/T102：`bs.json` 三语言新增 DSH 文案；触及旧请求提示同步提取语言键。
- T103：`controllers/API/dsh.ts` + `types/dsh.ts` 对接 config、浏览器 authorize 及八管理接口，分页/许可/策略关键字段校验，所有新管理 GET 可取消。原封装默认行为保留；变更请求可保留 HTTP 冲突证据，依旧执行全局拦截与提示，无业务 403 分支。
- T104：`pages/DshLogin` 固定入口/PKCE 事务确认、真实身份说明、approve/deny、严格 loopback 校验、到期清理、内存票据复制兜底。深链仅 server；可选 VITE_DSH_DOWNLOAD_URL 仅无凭证 HTTPS。下载未配置时说明联系管理员与手动 BASE。授权 API 可选 decision 与既定 access_denied 回调由主线同步契约。
- T105：`SeatsView` 50 条游标页，300ms 搜索、部门/席位/登录筛选，旧请求取消，筛选重置游标。`SeatSessions` 独立 20 条页。操作稳定 UUID + 原 grant_version；超时同 ID 同 body 重试，未确认不显示成功。
- T106：`PolicyView/PolicyEditor/UsageSummary` 当前租户用户搜索、未占席用户预配置、上线 LLM 与共享标识、月总限额、按 model 用量、month/timezone/source/as_of。空集合或零限额允许作为明确禁止策略保存。1500/1000 按真实已用显示；未知与 unavailable 不伪造零、不提供强制清除。expected_version 与保存输入保留；已终结/冲突需要刷新核对后修改。
- T107：`DshManagement/OperationStatus` 许可摘要、两业务视图、所有当前访问操作审计。每个操作独立、最多 30 次自动查询，离开取消；可继续查同 ID。actor、目标、前后值、期望版本、committed/effective 时间均展示。未知响应与 HTTP 请求拒绝不伪装为持久层成功。
- T108：两组 router 均提供 `/desktop-login`，System DSH tab 仅 root/child 管理员。`userContext` 与安全 loginReturnTo 检查支持普通用户经过 SSO 回到授权页，不被管理台门禁提前送去工作台。

## 已完成验证

`pnpm --dir src/frontend/platform test`，选择 F062 测试和已有 `routeFilterPurity/f048DashboardPermissions`：**10 个文件、37 项通过**，其中 F062 新增 26 项，原回归 11 项。

- raw config disabled/畸形、loopback 白名单、剩余 TTL、重复确认抑制、拒绝不发票据、卸载取消。
- 1 万条内存测试数据仅加载 50 行，独立 session 请求、旧筛选响应不能覆盖新列表、同 op ID/版本重试。
- PROCESSING 审计、有界 30 次失败轮询、输入保留与重复变更抑制、实际超额 1500/1000、历史快照和 UNKNOWN 无清除入口。
- wrapper 默认 reject(null)/共享 toast 保持、opt-in 原错误和取消行为；SSO returnTo 同源/时效/一次性；独立授权路由与系统门禁。

最终 lint/typecheck/check-i18n 结果以本记录末尾更新为准。工具日志位于 `/private/tmp/f062-ui-{tests,lint,types,i18n}.log`。

真实本机 Vite + Chrome 访问 `http://127.0.0.1:3062/desktop-login`，页面独立加载，后端未接入时异常态布局正确，截图没有真实票据。单元/组件中的身份与票据仅 fixture；这不是完整浏览器/客户端 E2E。

## 外部联调与限制

- 未连接真实已启用 DSH 的完整平台 Web 会话/SSO/Nginx/桌面客户端，成功 loopback、OS 深链、剪贴板与浏览器混合内容策略需外部联调。用户已允许外部 E2E 环境缺口暂跳过。
- 普通部署需 Nginx/页面策略提供 no-store/no-referrer；授权页自身设置 no-referrer，票据只保留内存且到期清除。已有 SPA 资源加载不等价于服务端响应头验证。
- 原 bs-ui Input 在 jsdom 中有既有 `style jsx` 非布尔属性警告；测试通过，本次未修改设计组件样式。
- 原 prettier.config.js 在本机 Node 下 require ESM Tailwind 插件失败；仅对新增文件使用临时等价基础格式配置格式化，未改项目格式配置。

## 最终检查结果

2026-09-09 本次 UI 最终代码：`pnpm lint`（platform/client/ui/file-viewers）、`pnpm typecheck`（platform/client/file-viewers）、`pnpm check-i18n` 均 exit 0；`git diff --check` 通过。F062 26 项 + 原路由/权限回归 11 项，共 37 项通过。`pnpm --dir src/frontend/platform lint:prune` 自动缩减 3 项既有中文 suppression，未手工改基线。

本机预览服务仍位于 `127.0.0.1:3062`（仅本机、Vite），供主线继续查看；不代表部署。主线可在所有工作完成时停止该服务。
