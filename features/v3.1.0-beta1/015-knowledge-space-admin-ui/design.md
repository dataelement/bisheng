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

## Client 空间入口收敛

2026-11-12 用户明确要求移除前台四个独立按钮，引用来源在删除过程中按需展示。

- 移除 toolbar 的移动任务历史入口、主文件列表下的引用/清空按钮，删除无消费者的对应回调。无新增菜单入口。
- 删除普通处理任务管理面板及其专用查询 hook；以 `SpaceProcessingStatus` 保留 Root state=3/4 的重建中/失败提示。文件行状态与批量处理回执保持现有逻辑。
- 保留实际移动提交后自动打开的 `MoveJobProgress`、当前任务轮询、失败重试和丢失确认 ACK 的恢复；删除不再有入口的全空间移动历史查询和选择路径。无当前任务时不得手工 refetch 空 operation。
- 空间删除继续使用 `useSpaceActions → useKnowledgeDeletion`；文件/文件夹删除继续使用 `useKnowledgeFileActions → useKnowledgeDeletion`。不改只读范围捕获、服务端预检、不可变计划、二次确认、强制空间删除和批量跳过规则。
- `KnowledgeDeletionDialog` 只有预检返回引用计数、受限计数或来源页时展示引用区块；无引用不展示空来源/受限来源标题。来源名称/入口仍由服务端 disclosure 决定，检查失败保持原阻断。
- 原处理面板和专用 hook 的测试随退役功能删除，以状态反馈、四入口缺席、真实删除 hook 与弹窗的按需引用展示测试替代。

## 修订历史

- 2026-11-12：根据用户确认恢复树与文件 UI，保留当前后台契约和操作实现。
- 2026-11-12：按用户追加确认收敛 client 四个入口，保留简化状态和删除引用保护。
