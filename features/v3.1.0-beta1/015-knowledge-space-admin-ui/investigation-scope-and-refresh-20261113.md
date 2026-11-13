# 空间管理视图与后台刷新请求核对

2026-11-13，核对基线为原修复分支 `7aa739ce55`。本轮第 1、3 项为现状核对与调用来源排查，第 2 项修改菜单文案。116 的现场读取仅验证公开 browser-config 响应，未捕获已登录页面某个具体按钮的请求发起栈。

后续用户已授权统一管理详情：保留管理空间清单入口，详情复用普通界面并贯穿 admin scope；实现与验收见 design.md 的“管理详情统一”及 AC-17、AC-18。下表保留排查时的现状，两个接口的刷新行为按用户要求暂不调整。

## 两个页签

| 项目 | 当前实现 | 与用户描述的关系 |
| --- | --- | --- |
| 管理页签可见性 | `useKnowledgePageScope` 使用 is_global_super / is_child_admin。 | 与超管、租户管理员可见的口径一致。 |
| 管理列表范围 | `/knowledge/space/admin/list` 校验管理员身份、可信当前管理租户与完整数据范围；strict tenant filter 查询该租户的 SPACE，不执行普通可见性逐空间过滤。 | 与当前租户全部空间的口径一致；仍执行角色和租户校验。 |
| 普通页签 | 个人部门/创建/加入分组；分组为空用普通可见空间清单选择首条。服务端可见清单执行用户可见性过滤。 | 数据按用户身份和授权读取，不使用管理全量列表作为普通导航。 |
| 页面形态 | 普通页签是树形空间/文件目录，管理页签仍挂载 KnowledgeFile 空间表格。 | 尚未达到相同 UI、仅数据范围不同。 |
| 进入详情 | 管理行跳转 `/filelib/:id`；index.tsx 在有 id 时强制 file 页签，详情使用 ordinary scope。LibPage 仅记忆返回页签。 | 管理上下文尚未贯穿详情，不是独立的管理视图。 |
| 操作授权 | 菜单、目录、配置仍查询 my-permissions；服务端 get_my_permissions 对超管/目标租户管理员返回完整有效动作集，不要求其持有逐空间授权记录。实际业务动作继续走统一权限服务。 | 管理员免逐空间授权已在服务端实现；前端仍存在权限读取请求。不能把请求存在等同于要求管理员逐条授予权限。 |

代码锚点：`src/frontend/platform/src/pages/KnowledgePage/index.tsx:25`、`KnowledgeFile.tsx:188`、`src/frontend/platform/src/hooks/useKnowledgePageScope.ts:19`；服务端 `knowledge_space_service.py:2092`、`permission/application/resource_api.py:553`。

如按“完全相同 UI/操作，只替换数据范围”实施，需让管理页签也复用树形 Workspace 和文件详情，并在目录、文件、配置链保留 admin 视图上下文；当前代码仍是两种入口。此次核对没有修改权限或页签行为。

## 删除菜单

SpaceDirectoryRow 的共享菜单从 `deletion.delete_items` 改为现有 `delete` 键；文件/文件夹、列表/卡片均显示“删除”。引用检查、确认弹窗、授权和删除回调不变。

## browser-config

`useDshBrowserConfig` 在每次挂载立即读取，之后每 30 秒、window focus、dsh-settings-changed 事件读取。MainLayout 常驻使用，因此知识页也会持续读取 DSH 配置；DSH 页面、接入管理或工作台模型配置还会各自挂载订阅，每个实例有独立定时器，没有共享去重。

用途是同步 Desktop 业务开关、下载地址和启动地址。既有需求 `features/v3.0.0-beta2/062-dsh-desktop-model-access/self-service-revision.md:11` 明确要求每 30 秒或回到窗口刷新，以使开关变化影响菜单/弹窗。这不是知识空间操作所需的查询。

116 公开接口只读实测返回 HTTP 200、status_code=200、management_enabled=true、enabled=true、Cache-Control: no-store；不会通过浏览器 HTTP 缓存免掉这些请求。

Fake timer 复现：单实例挂载 1 次，30 秒后累计 2 次，focus 后 3 次，保存事件后 4 次；双实例挂载 2 次，普通按钮重渲染后仍 2 次，30 秒后累计 4 次。卸载取消当前请求、清除定时器和监听，后续 90 秒无新增请求，未发现定时器泄漏。

可以优化为共享订阅、合并重复请求、后台不可见时暂停；这是刷新策略优化，本轮不调整既有 30 秒热更新行为。

## user/info

- UserProvider 挂载时读取完整用户信息。
- `useCurrentIdentityRefresh` 有 initialData、staleTime=Infinity，不在普通重渲染时读取；但 refetchOnWindowFocus='always'，窗口重新获焦/恢复可见时会读取。无重连刷新，无周期定时器，无失败重试。
- 刷新回调只合并 user_name / external_id，用于昵称等身份显示同步，不是点击空间按钮时检查资源权限。
- 当前源码没有给普通空间按钮绑定 user/info 调用；从新窗口、文件选择器或开发者工具回到页面会触发焦点刷新，可能表现为“点某按钮后查询”。具体现场按钮还需请求 Initiator / 时间线才能定案。未发现生产代码全局 invalidateQueries() 主动刷新该身份 query 的调用。

锚点：`src/frontend/platform/src/hooks/useCurrentIdentityRefresh.ts:15`，`contexts/userContext.tsx:40`、`:163`。原昵称同步提交为 `fc5f8a3297`。

## 验证

4 文件 / 21 项测试通过：目录菜单 10、browser-config 刷新复现 3、身份焦点刷新 3、DSH 设置 API 5。全前端 lint、typecheck、check-i18n 通过。新增测试验证文件/文件夹的列表/卡片菜单、定时刷新与多订阅、普通按钮不触发读取、卸载清理；无真实写入、无部署。
