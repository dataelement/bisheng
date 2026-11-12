# 后台知识空间展示适配

基线：`origin/feat/3.1.0-beta1` / `c9918ba14e`。旧 UI 参考：`3d4e167db1^` 的 client 知识空间侧栏、`FileListRow`、`FileCard`、`FileListToolbar`。

沿用旧前台的分组树、双行文件列表和卡片布局；展示适配在 platform 内完成。旧 client 的 Recoil、Auth、路由和上传/删除实现不跨应用移植，避免覆盖 F118 的 scope、权限、游标分页和确认生命周期。遵守 [constitution](../../../docs/constitution.md) C3、C4、C6、C7；无后端契约变更。

## 数据流与职责

- `/filelib` 与 `/filelib/:id?parent_id=...` 共用 `KnowledgePage`，普通页签挂载 `KnowledgeSpaceWorkspace`；目录切换保留侧栏。主页右侧保留现有普通授权列表和空间高级操作入口。
- `sidebar/` 通过已有 `/department`、`/mine`、`/joined` 取三组，按组排序；置顶使用现有 `set-pin`。查询 key 包含完整 `knowledgeQueryKeys.scope(scope)`。
- 文件夹树调用 `children(file_type=0)` 并消费游标，按需加载；深链通过已有 parent 路径接口展开。不能照搬旧实现固定取第一页的写法。
- `SpaceDetail` 复用当前服务端标题、父路径和 `Files` 数据/权限/生命周期。`Files` 的 workspace 呈现参考旧 UI，其他调用默认保持原表格模式。
- 列表/卡片偏好沿用旧版持久化行为，存储按身份、租户、管理域隔离；已解析文档优先显示缩略图，加载失败回到类型图标。目录与面包屑导航只变更 `parent_id`，保留状态筛选及其他 query。
- 问答库及管理员全量清单维持原独立页签。分组接口不能替代 F118 普通可见清单，后者仍保留仅子项授权的入口；管理员列表继续使用可信管理域。
- 广场沿用工作台 `/knowledge?square=1` 入口，不在后台重做订阅和加入审批。

## 已知约束

| 约束 | 处理 |
| --- | --- |
| 旧侧栏返回整页目录，现接口是游标分页 | 新树保留继续加载和错误重试，不能丢弃下一页。 |
| 只获文件/文件夹授权时根空间可能不可见 | 保留普通可见清单；深链目录不以 getSpaceInfo 成功作为文件浏览前置。 |
| 超管分组接口与管理员全量清单语义不同 | 保留独立管理清单；分组只是个人导航，不作为全量管理数据源。 |

## 修订历史

- 2026-11-12：根据用户确认恢复树与文件 UI，保留当前后台契约和操作实现。
