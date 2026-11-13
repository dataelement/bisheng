# 空间复制规则核对

日期：2026-11-13；基线 `feat/3.1.0-beta1` / `9041f3c263`，叠加本地已完成的设置样式修复。需求依据为用户提供的 PRD §1.3.4 截图及 F118 spec AC-25–AC-27、AC-84。只核对截图有关规则，不把截图中的其他文字当作新增实施指令。

## 结论

源码及本地定向测试支持 PRD 的核心复制规则。原普通树只有置顶菜单、复制说明与入口缺失；本轮补齐普通树的删除/权限管理，以及仅实际创建者可用的复制弹窗。未改后端复制算法或鉴权。

| PRD 要求 | 当前实现与证据 | 判断 |
| --- | --- | --- |
| 只有源创建者可复制，管理员不能豁免 | `space_copy.py:77` authorize 比较实际 PermissionActor 与源 user_id，预检/确认/执行都会复核；`test_super_admin_is_not_a_copy_creator_shortcut` 拒绝非创建者管理员 | 一致；UI 同样限制创建者 |
| 目录、文件及全部版本 | `SpaceCopyRepository.aload_scope/aallocate` 读取完整目录、文档和版本，分配新文件/文档/版本 ID 并重映射主版本与目录路径；原处理测试包含同一文档的两个物理版本 | 一致 |
| 标签、元数据和解析配置 | 复制 Tag/TagLink 并改成副本目标；文件元数据保留，root metadata_fields/processing_defaults 和各文件 split_rule 复制，规则里的空间 ID 改成副本 | 一致 |
| 独立资源、索引、任务 | root 使用新 index/collection；对象名按新文件 ID 生成，复制实际内容；新任务记在副本 root 上，原生复制 Worker 及最终 ACK 路径有定向回归 | 一致；本地端口替身不代表真实存储 E2E |
| 权限模式和普通授权沿既有复制规范 | `SpaceCopyOwner._pairs/aensure_logical` 交给 `KnowledgeCopyProjectionApplication`；CUSTOM/INHERIT 与有效普通授权按原规范处理 | 一致，未另写权限复制逻辑 |
| 副本创建者为所有者，不照搬旧受保护身份 | 仅创建者可复制，所以源/副本 user_id 可能相同；目标受保护 CREATOR 来源绑定新资源，普通授权对账排除 protected 来源，未重用旧受保护来源 | 一致 |
| 复制前说明授权范围 | 原普通树没有复制入口；新弹窗在任何预检/确认前展示完整范围、授权说明和排除项 | 本轮补齐 |
| 不发布广场、不复制订阅/置顶/聊天 | `_accept` 明确 is_released=False/is_shared=False；分配路径只处理空间、文件、文档/版本、标签/词库和权限，没有写成员订阅、用户置顶、聊天表 | 一致 |

## PRD 未明确的一点

源绑定的公共标签库也会在 `SpaceCopyRepository.aallocate` 中复制成副本私有词库（owner_knowledge_id=副本 ID），保留标签内容并使用独立词库 ID。`KnowledgeSpaceService._decorate_auto_tag_for_info` 会将这种绑定回显为“自定义标签”。因此内容被复制，但副本设置中公共库/自定义的模式名称可能与源不同。

PRD 要求标签复制和副本独立，没有明确要求公共库继续共用还是转私有，也没有规定该模式名称。本次记录这一行为并保留原后端实现，不将它说成已获产品确认的口径。

## 实施与验证

- 普通树保留置顶，并懒读取有效 delete/manage_permission/upload_file 动作。删除复用原引用预检/确认，权限管理复用现有组件，只有实际创建者再满足原创建资格及上传动作时才显示复制。管理列表未扩展额外入口。
- 新复制弹窗依次调用既有 copy/precheck、copy/confirm。检查不完整时阻断，确认 ACK 丢失时重用相同计划及幂等键；范围退役后不确认。有任务时读取副本 ID 的 space_copy 进度，空副本直接完成并刷新导航。
- 前端定向 8 文件 / 51 项通过：新菜单/复制交互、树导航、Workspace、原删除 hook/弹窗/API，以及上一轮设置交互。
- 后端现有 `test_kn_copy.py`、`test_kn_copy_index.py` 共 16 项通过。使用临时空配置、真实 SQLite 和原测试中的传输/外部端口替身；为避免 root conftest 的全链预 mock，以 AST 加载其中原 tenant_context fixture。首次隔离执行因缺该共享 fixture 报 1 个 setup error，补齐原 fixture 后完整通过，未修改产品或测试源码。
- 本地 Chromium（StrictMode，隔离 API fixture）实测：非创建者管理员菜单无复制；创建者菜单有复制/删除/权限，弹窗先展示范围，点击创建各调用一次预检和确认，完成后侧栏出现新副本。控制台无 error/warn；临时页面/源文件/服务已清理。
- 原生专用环境 E2E `test_ac25_copy_is_creator_only_and_survives_ordinary_source_delete` 在 F118_E2E=0 下执行为 1 skip，未跑真实 Worker/MinIO/Milvus/ES 验收；不能用本地通过替代它。

七维自查：空/缺失身份不推测创建者；权限及租户仍以原服务端为准；提交锁、scope 退役、预检与幂等重试覆盖；无新增引用披露；51 项前端和 16 项后端回归；共享 UI/原业务链复用；规格、设计和验证同步。无新增 HIGH/MEDIUM，PASS。修改留在 beta1 工作区，尚未提交推送或部署。
