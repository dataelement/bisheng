# 设计：复用细粒度上传权限

## 策略

1. 通过既有 Knowledge repository 按当前租户、已发布状态和公共/部门类型扫描候选空间；搜索条件也在仓储层应用。
2. 增加目录候选仓储查询，只读取上述空间中的目录，避免把文档或其他类型空间作为目标。
3. 在 KnowledgeSpaceService 内统一业务上传判断，复用 FineGrainedPermissionService 和单请求 PermissionReadContext。目录启用 `nearest_binding_wins=True`、`use_permission_level_fallback=False`，空间沿用既有细粒度规则；批量判断使用有界并发，取消/异常时回收任务和上下文。
4. 可上传空间 ID 与可上传目录所属空间 ID 取并集，再沿用既有游标查询。目录可见集仅包括可上传目录及其祖先，目录分页仅在目标空间内计算权限。
5. 最终目标验证复用同一权限判断，保留仓储的存在性、类型、状态和目录所属空间校验。DeveloperTokenService 在已有目录 ID 时传递该 ID，路径规则保持根预检。

## 文件边界

- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
- `src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_file_repository.py`
- `src/backend/bisheng/knowledge/domain/repositories/implementations/knowledge_file_repository_impl.py`
- `src/backend/bisheng/developer_token/domain/services/developer_token_service.py`
- `src/backend/test/developer_token/` 的相关回归
- `src/backend/test/open_endpoints/test_filelib_sync_folder_target.py` 的旧测试依赖隔离及既有响应字段断言
- 本 spec 目录

不修改已存在用户变更的 `fine_grained_permission_service.py`，不使用粗粒度 `can_edit` 预筛选，避免遗漏自定义上传授权或错误放行自定义只读授权。

## 验证与回退

先建立真实细粒度计算、模拟既有 FGA 关系模型的失败复现，再修复。覆盖允许、拒绝、自定义授权、目录覆盖、祖先导航、分页、目录保存和公共/部门过滤。最终运行开发者 Token 及共享同步目标相关回归；真实 MySQL/DM8 和生产验证不在本次授权范围内。

无需迁移或权限模型更新；回退仅恢复本次本地代码 diff。

模块回归发现两个旧同步测试已模拟上传权限判断, 但未模拟后来新增的目录显示和审计外部依赖, 且响应字段断言缺少既有 `tags`。仅补齐这些测试依赖及断言, 不修改同步生产代码或响应。
