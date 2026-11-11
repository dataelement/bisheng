# 昆联 Workflow 编辑与执行直达入口：需求发现

**Feature ID**: F129
**Created**: 2026-11-11
**Status**: 需求发现、spec 及 design 已获用户确认；T001–T003 共享规则已实施，其余待实施，尚未部署。进度及证据见 tasks.md、verification.md。

## 用户需求与已确认决策

1. 昆联能提供一条直接打开指定 Workflow 编辑页的浏览器链接。
2. 昆联能提供另一条直接打开指定 Workflow 执行页的浏览器链接。
3. 2026-11-11 用户确认执行页采用「运行当前已发布上线版本，复用现有执行页，发布新版本后链接不变」。页面使用实际用户登录及权限校验，进入后由用户发起运行。
4. 沿用当前同源站点及 3001 端口。此次增加直达入口，不重新规划工作流管理页、SSO 协议或用户同步。

## 只读检索结果

| 已读取位置 | 当前事实及设计时需注意的问题 |
| --- | --- |
| `src/frontend/platform/src/routes/index.tsx`、`src/frontend/platform/src/pages/BuildPage/flow/index.tsx` | 已有 `/flow/:id/` 编辑器。普通入口先检查编辑权限；工作流管理来源调用独立的管理编辑读取入口。 |
| `src/frontend/platform/src/utils/workflowManagement.ts`、`src/backend/bisheng/api/services/flow.py` | 管理页编辑链接使用 `/flow/{id}?from=workflow-management`。该来源参数选择管理页返回及读取路径，服务端仍检查可信租户、查看与编辑权限，不能把来源参数当作授权。 |
| `src/frontend/client/src/routes/index.tsx`、`src/frontend/client/src/pages/appChat/AppChatEntry.tsx` | 已有 `/workspace/app/{id}/10` 入口及会话执行页面。入口优先打开最近会话，没有历史时生成新会话标识；不能据此宣称每次打开链接都会创建新执行。 |
| `src/frontend/client/src/pages/appChat/index.tsx`、`src/frontend/client/src/pages/appChat/useWebsocket.ts` | Workflow 使用页已有对象 `use` 检查、详情与历史读取，以及状态查询和交互消息机制。实际执行的当前上线版本选择及已有会话恢复需要后续定向验证，不能仅凭页面路由推断版本行为。 |
| `src/frontend/platform/src/pages/LoginPage/login.tsx`、`src/frontend/platform/src/contexts/userContext.tsx`、`src/frontend/platform/src/controllers/request.ts` | 工作流管理页有专用自动 SSO 与首次用户信息请求处理；当前识别主要基于管理页路径，不能直接认为编辑页已具备相同未登录直达行为。平台启动还保留历史 URL token 处理，外部入口必须避免落入该兼容路径。 |
| `src/frontend/client/src/utils/loginRedirect.ts`、`src/frontend/client/src/routes/RequireLogin.tsx` | 已有跨应用登录目标保存、同源校验、并发跳转去重和失败后手动重试机制。需要核对新入口与鉴权初始化的组合，避免多次授权或丢失目标。 |
| `src/frontend/packages/api-client/src/kunlianBrowser.ts`、商业网关 `KunlianLoginTransactionStore.java`、`KunlianSsoProperties.java` | 现有昆联浏览器协议支持安全 `return_to`；默认回跳前缀包含 `/flow`、`/build` 和 `/workspace`。部署配置和真实昆联回调仍需实际联验。 |

上述为源码事实，不是两个对外直达链接已经通过 SSO 联调的证据。具体 URL 合同、来源识别、两端改动位置及测试组织在 spec 确认后的 design 中确定。

## 验证边界

- 首轮可用现有 Mock 验证登录前后原目标保持、失败防循环、权限拒绝、上线版本切换，以及打开链接不自动产生业务执行。
- 真实昆联入口、真实 SSO、用户租户及授权差异、实际运行和静态部署后的深层路由需要独立验证，未执行前保持 `NOT_RUN`。
- 需求发现阶段仅新增规格文档。后续经用户授权的 W1 只实现共享包，不切换分支或修改部署配置；当前已有用户改动及其他会话的联调文档工作保持原状。
