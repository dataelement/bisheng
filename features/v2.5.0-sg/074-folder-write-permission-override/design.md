# 最小修复设计

## 后端

`permission_check.py` → `FineGrainedPermissionService.has_any_permission_async` → `get_effective_permission_ids_async`。
仅在 object_type 为 folder/knowledge_file 时启用 nearest_binding_wins，关闭关系档位回退，和 KnowledgeSpaceService 的现有子级写权限判断一致。
不改变底层解析器默认参数，避免改动显式要求累加的其他消费者。保留同一级多个匹配授权合并及隐式权限。

## 前端

新增 `hooks/useKnowledgeContainerWritePermissions.ts`，两处列表共用。状态带账号、空间、目录、管理员标记组成的作用域键；渲染时键不一致立即返回 false， effect 取消旧请求，加载/错误默认拒绝。
checkPermission 为这两处查询接受可选 cacheScope，隔离客户端短缓存及共享在途请求；不传递到 HTTP。其他调用保持原缓存行为。
知识库角色只能在根目录保留现有快捷授权；进入目录查询真实目录权限，防止知识库角色绕过子级覆盖。
PortalKnowledgeWorkbench 和 SpaceDetail/index 接入；删除旧的两个布尔状态和重复查询 effect。实际 HeaderActions 按权限条件渲染三个写入口。
保留现有手动上传/网页链接 guard 和拖放权限传递。无目录权限查询成功前不展示空列表上传。

## 文件计划

- backend/permission/domain/services/fine_grained_permission_service.py：最小参数修复。
- backend/test/permission/test_knowledge_child_permission_check.py：真实路由、绑定解析和上传拒绝。
- frontend/client/src/pages/knowledge/hooks/useKnowledgeContainerWritePermissions{,.test}.tsx/ts：状态隔离。
- frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.tsx、SpaceDetail/index.tsx：接入。
- frontend/client/src/pages/knowledge/portal/components/PortalHeaderActions{,.test}.tsx：操作入口。
- frontend/client/src/api/permission{,.test}.ts：可选缓存作用域隔离。
- frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.pageHistory.test.tsx：复用现有门户 fixture 验证真实操作栏和目录切换。

## 风险、验证及回退

影响仅为原先错误显示允许的子资源操作查询变为拒绝；后端写操作授权规则不变。前端加载阶段隐藏操作。
按 V3 覆盖允许/拒绝/降级/状态竞争，运行相关现有权限集及前端构建；本地浏览器验证入口。
回退仅还原本批代码，无数据迁移或补偿。线上真实授权数据/真实 FGA 未操作，需部署后验收。

REQ-1 → AC-1/AC-2；REQ-2 → AC-3；REQ-3 → AC-4。
