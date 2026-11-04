# Tasks: Vibe 全操作权限动作统一与具体租户管理视角

**关联**：[spec.md](./spec.md) · [design.md](./design.md) · [设计复审](./design-review.md)
**版本**：v3.0.0 · **分支**：codex/114-vibe-permission-actions · **基线**：bb62790ad22a3204493e7dce5878e0a4f7109599

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| discovery | ✅ 已确认 | 36 项动作盘点；具体租户单选 |
| spec.md | ✅ 已评审 | 71 条；v2及R3收窄由用户明确；AC正文保持 |
| design.md | ✅ 已评审 | 2026-10-30 用户“确认设计，进入任务拆解和开发”；R1–R6关闭 |
| tasks.md | ✅ 已拆解 | 104项；必要接线/消费者和合同同步均登记；同代理按21项清单复核 |
| 实现 | 🚧 代码收尾并获先合入授权 | 102 / 104；用户手动部署116后补T063真实E2E，T064最终L2/质量门禁仍未完成 |

## 执行约定

- 单人按依赖顺序实施；Wave 表示依赖，不自动授权派发子agent。
- 后端测试先写允许/拒绝配对再实施；测试任务可记录预期红灯，配对实现必须绿灯后L1打勾。已有fixture优先复用，不搭无关中间件。
- 每任务1–2个明确文件；新增接线文件或locale按实际必要内容追加小任务，不能用一个任务隐藏跨前后端改造。相同文件仅增量处理本任务声明的不同职责。
- 每任务内联交付接口/行为；设计理由只链接 design 章节。真实owner/tenant、F113/scopes、非创建人资格保护不变；只用六动作，不为共用助手接口添加Vibe管理门槛。
- UI每次编辑先读当前设计规范和对应应用AGENTS；用已落地组件，样式不改，三语同交付，Client/Platform分开。
- 测试只限本功能、直接受影响路径及必要质量门禁，不运行全量测试；无新增依赖/模拟arm验收，DM8仅静态。未执行真实E2E不宣称提测/交付完成。
- 既有dirty/untracked文档保留；禁止全树stash/reset/clean/restore。代码只在本工作树修改，推送/合并/部署不得扩到其它环境或版本线。

## 任务

### Wave 0：已确认合同与 additive 基础设施

- [x] **T001**：发布与预览 ORM 字段
  **类型**：基础设施
  **文件**：`src/backend/bisheng/app_publish/domain/models/app_deployment.py`、`src/backend/bisheng/app_publish/domain/models/app_preview_session.py`
  **逻辑/验证**：authorization_context 使用 nullable JsonType；预览增加 purpose、instance/task、credential、operation 及 starting 状态；新会话强制完整绑定，旧 NULL 不回填。
  **覆盖 AC**：AC-39、AC-50、AC-53、AC-69
  **依赖**：无

- [x] **T002**：已有表 DDL 与回退
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/database/alembic/versions/f114_app_authorization_context.py`
  **逻辑/验证**：读取 migration AGENTS，接当前唯一 head；仅 additive 字段和普通/唯一索引；降级只撤本 revision 的 DDL，运行前停止新写入并备份，绝不把 downgrade 当业务数据恢复。MySQL/DM8 静态核对，不做数据回填。
  **覆盖 AC**：AC-39、AC-50、AC-53、AC-69
  **依赖**：T001

- [x] **T003**：范围错误码与受信值对象
  **类型**：基础设施
  **文件**：`src/backend/bisheng/common/errcode/admin_scope.py`、`src/backend/bisheng/app_runtime/domain/schemas/app_authorization.py`
  **逻辑/验证**：复核 19704/19705 未占用；定义范围变化/无有效范围错误及六动作、内容层级、用户/系统来源、操作用途值对象，禁止原令牌或永久 allowed。
  **覆盖 AC**：AC-01、AC-04、AC-08、AC-13、AC-14、AC-40、AC-56、AC-60、AC-63
  **依赖**：无

### Wave 1：六动作授权与具体租户范围

- [x] **T004**：真实主体与动作组合配对
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_f114_action_authorization.py`
  **逻辑/验证**：mock F048 公开端口：use-only 不进管理；任一管理动作基础可见；组合缺一拒绝；先验证目标租户/删除态再鉴权；SA 与 owner 分开；不可判定无效果。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-62、AC-63、AC-65
  **依赖**：T003

- [x] **T005**：应用授权门面
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_authorization_service.py`、`src/backend/bisheng/app_runtime/application/authorization.py`
  **逻辑/验证**：D1/D8：AppAuthorizationService 先验证 app/tenant/state，复用 F048 adapter；提供 require/allowed_actions/management 基础信息与内容分级；公开端口不泄露 ORM。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-62、AC-63、AC-65
  **依赖**：T003、T004
  **配对测试**：T004

- [x] **T006**：具体租户解析与旧状态拒绝配对
  **类型**：测试
  **文件**：`src/backend/test/admin/test_f114_concrete_scope.py`、`src/backend/test/admin/test_f114_scope_middleware.py`
  **逻辑/验证**：覆盖超管具体 A/B、Root 非全平台、非超管伪造、无 key/过期/非法回所属租户、非法默认拒绝、null/global 切换不清旧值、实际范围审计。
  **覆盖 AC**：AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-17、AC-18、AC-64、AC-66
  **依赖**：T003

- [x] **T007**：范围真相与默认回退
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/admin/domain/services/tenant_scope.py`、`src/backend/bisheng/admin/domain/repositories/tenant_scope_repository.py`
  **逻辑/验证**：D3：沿 admin_scope 用户级 Redis key/TTL；选择只接受 active 具体租户；默认/过期回本人合法租户，失败不改旧选择；非超管忽略缓存。读取跨租户事实须窄范围受信端口。
  **覆盖 AC**：AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-17、AC-64
  **依赖**：T006
  **配对测试**：T006

- [x] **T008**：管理范围端口与切换 API
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/admin/application/tenant_scope.py`、`src/backend/bisheng/admin/api/endpoints/tenant_scope.py`
  **逻辑/验证**：返回正整数 scope_tenant_id 和 selected/own 来源；EffectiveManagementScope 公开值对象；新写保护端口核对 X-Management-Tenant，F113 单旧头继续合法。
  **覆盖 AC**：AC-09、AC-11、AC-12、AC-13、AC-14、AC-16、AC-17
  **依赖**：T007、T006
  **配对测试**：T006

- [x] **T009**：范围注入与任务隔离
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/common/middleware/admin_scope.py`、`src/backend/bisheng/core/context/tenant.py`
  **逻辑/验证**：读取同一有效范围并 pin 请求，具体租户过滤沿 ContextVar；仅明确管理路由接范围，开放 API/SDK/内部执行不继承页面选择；不为共用 GET/调用强制管理头。
  **覆盖 AC**：AC-10、AC-15、AC-16、AC-17、AC-18、AC-66
  **依赖**：T008、T006
  **配对测试**：T006

### Wave 2：应用基础信息、内容与生命周期

- [x] **T010**：应用管理内容和动作配对
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_f114_management_content.py`、`src/backend/test/app_publish/test_f114_secret_actions.py`
  **逻辑/验证**：对 edit/publish/unpublish/delete/manage_permission/use 分别查询和写入；断言基础详情不夹带源码/manifest/failure/env/grants，edit 可管理他人数据日志；保存环境变量不重启、确认重建组合检查。
  **覆盖 AC**：AC-07、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-42、AC-55、AC-61、AC-65
  **依赖**：T005、T009

- [x] **T011**：基础查询与版本安全投影
  **类型**：后端 API
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_query_service.py`、`src/backend/bisheng/app_runtime/api/endpoints/apps.py`
  **逻辑/验证**：列表/基础详情/实例/版本摘要用任一管理动作，返回 allowed_actions；详细日志 edit；保持不存在保密，版本只读和准确状态提示，不能无条件返回私有 manifest。
  **覆盖 AC**：AC-07、AC-08、AC-20、AC-21、AC-42、AC-55、AC-61、AC-63
  **依赖**：T005、T009、T010
  **配对测试**：T010

- [x] **T012**：元信息及生命周期动作
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_meta_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_state_service.py`
  **逻辑/验证**：元信息 edit；上线 publish、下线 unpublish、删除 delete；移除 owner/失效创建人资格分支，保留审批/容量/下线前置、确认、资源与 Grant 清理、实际 actor 审计。
  **覆盖 AC**：AC-05、AC-19、AC-29、AC-30、AC-31、AC-32、AC-54、AC-63、AC-64、AC-65
  **依赖**：T005、T009、T010
  **配对测试**：T010

- [x] **T013**：数据读取写入及恢复动作
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_data_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_data_session_service.py`
  **逻辑/验证**：所有表/行/导出/会话结果 edit；恢复按是否启动要求 edit 或 edit AND publish；保留确认、表范围、票据归属和 writer 停止证据，不增加任意 SQL。
  **覆盖 AC**：AC-22、AC-23、AC-28、AC-53、AC-65
  **依赖**：T005、T010
  **配对测试**：T010

- [x] **T014**：配置管理与确认重建动作
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/services/app_secret_service.py`、`src/backend/bisheng/app_runtime/domain/services/secret_rebuild_service.py`
  **逻辑/验证**：查看/保存配置 edit；确认重建 edit AND publish；沿原 revision/CAS、确认快照与幂等；保存无运行副作用，不改变 owner/密文规则。
  **覆盖 AC**：AC-24、AC-25、AC-26、AC-40、AC-56、AC-65
  **依赖**：T005、T010
  **配对测试**：T010

- [x] **T067**：有效审批审读与范围隔离测试
  **类型**：测试
  **文件**：`src/backend/test/app_publish/test_f114_review_access.py`
  **逻辑/验证**：edit允许长期审读；仅publish拒绝源码；任务与实例均pending才有临时资格；管理视角切到B后，A的有效个人任务仍按受信A读取且退出恢复原范围；SA不借归属人的任务；审批资格仅覆盖待审版本及其正式比较基线。
  **覆盖 AC**：AC-18、AC-20、AC-38、AC-49、AC-50、AC-51、AC-53、AC-69
  **依赖**：T005、T009

- [x] **T068**：审批拥有的审读资格公开端口
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/approval/domain/repositories/app_review_repository.py`、`src/backend/bisheng/approval/application/app_review.py`
  **逻辑/验证**：窄范围按已验证viewer、应用及pending实例/任务查询，Python解析冻结version，不暴露ORM；返回只读tenant/app/version/task/instance绑定；无新增状态或审批引擎行为。
  **覆盖 AC**：AC-18、AC-20、AC-49、AC-50、AC-53、AC-69
  **依赖**：T067
  **配对测试**：T067

- [x] **T069**：审批技能与跨域接口说明同步
  **类型**：文档
  **文件**：`.claude/skills/approval-module/SKILL.md`
  **逻辑/验证**：随新增公开端口同步代码锚点和实际pending审读规则；范围章节按已验证的具体租户middleware更新。后续候选/业务撤回实现后再增量同步其真实行为，不预写交付。
  **覆盖 AC**：AC-15、AC-49、AC-50、AC-52、AC-66
  **依赖**：T068

- [x] **T015**：快照与版本私有内容授权
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/services/snapshot_browse_service.py`、`src/backend/bisheng/app_publish/domain/services/version_diff_service.py`
  **逻辑/验证**：源码快照、文件、完整版本差异 edit；审批临时审读只走可信任务公开端口，不以长期 edit 替代审批，也不凭知晓版本 ID 放行。
  **覆盖 AC**：AC-20、AC-27、AC-42、AC-50、AC-53
  **依赖**：T005、T010、T068
  **配对测试**：T010、T067

- [x] **T016**：应用运行管理用途映射
  **类型**：后端 API
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_management_service.py`、`src/backend/bisheng/app_runtime/api/endpoints/runtime_management.py`
  **逻辑/验证**：移除 natural_owner_required；私有依赖/快照 edit，恢复组合取可信用途，取消按当前取消者原动作集合；公共 profile/依赖仍平台运维；旧 upgrade/rebind 不注册。
  **覆盖 AC**：AC-27、AC-28、AC-53、AC-55、AC-56、AC-57、AC-58、AC-70、AC-71
  **依赖**：T005、T010
  **配对测试**：T010

- [x] **T017**：按应用运行记录资格配对
  **类型**：测试
  **文件**：`src/backend/test/app_governance/test_f114_audit_actions.py`
  **逻辑/验证**：edit 可查看/导出非本人 app 的匹配记录，缺 edit 和跨具体租户拒绝；跨应用审计还需原菜单资格；导出结果取回再次检查。
  **覆盖 AC**：AC-15、AC-34、AC-62、AC-64
  **依赖**：T005、T009

- [x] **T018**：运行记录查询和导出范围
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_governance/domain/services/runtime_audit_scope.py`、`src/backend/bisheng/app_governance/domain/services/runtime_audit_export_service.py`
  **逻辑/验证**：F056 沿 source owner repository 与现有一致导出；单 app 资格改 edit，保留审计入口及具体租户，禁止凭旧导出 URL 继续越权。
  **覆盖 AC**：AC-15、AC-34、AC-62、AC-64
  **依赖**：T005、T009、T017
  **配对测试**：T017

### Wave 3：真实主体首发、代发布与审批

- [x] **T019**：开放通道真实主体与首发投影
  **类型**：测试
  **文件**：`src/backend/test/app_publish/test_f114_publish_actor.py`、`src/backend/test/app_runtime/test_f114_creation_actor.py`
  **逻辑/验证**：SA 首发归属自然人但 CREATOR_GRANT 归真实 SA；投影失败不排任务，未知保留围栏；已获授权可代发布他人 app，粗 scope 无动作拒绝，F113/mode/scopes 保留。
  **覆盖 AC**：AC-05、AC-35、AC-36、AC-39、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-64
  **依赖**：T005

- [x] **T020**：创建权限投影传递真实主体
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_provision_service.py`、`src/backend/bisheng/app_runtime/domain/services/f048_app_permission.py`
  **逻辑/验证**：owner/tenant 保持原事实，authorize_created 接真实 PermissionActor；复用 F048 CURRENT CREATOR_GRANT 并验证 edit AND publish；rollback_created 完成后才删孤立行，未知不盲删。
  **覆盖 AC**：AC-05、AC-43、AC-44、AC-48、AC-64
  **依赖**：T005、T019
  **配对测试**：T019

- [x] **T021**：发布受理冻结真实授权来源
  **类型**：后端 API
  **文件**：`src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py`、`src/backend/bisheng/app_publish/api/endpoints/deploy.py`
  **逻辑/验证**：已有 app 按真实 actor edit AND publish，首次沿 create；owner 不变，冻结用户来源与 self_review_user_id；scope/mode/F113 和密钥/扫描/预检规则保留，客户端不能传内部 context。
  **覆盖 AC**：AC-35、AC-36、AC-39、AC-40、AC-41、AC-43、AC-44、AC-45、AC-47、AC-48、AC-64
  **依赖**：T001、T020、T019
  **配对测试**：T019

- [x] **T022**：CLI/MCP 查询与管理真实授权
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/open_mcp/tools/apps.py`、`src/backend/bisheng/app_publish/domain/services/publish_status_service.py`
  **逻辑/验证**：列表与状态不按 SA owner 过滤替代资源动作；复用安全摘要/日志 edit，已有 supported scope/mode 原样；不新增 PAT 通道。
  **覆盖 AC**：AC-07、AC-21、AC-43、AC-45、AC-46、AC-47、AC-48
  **依赖**：T005、T011、T021、T019
  **配对测试**：T019

- [x] **T023**：自审排除及业务撤回配对
  **类型**：测试
  **文件**：`src/backend/test/app_publish/test_f114_review_actor.py`、`src/backend/test/approval/test_f114_business_withdraw.py`
  **逻辑/验证**：owner 与实际关联自然人双排除；SA 后改绑不改快照；单候选不等单管理员；后续节点/指定/重试不绕过；publish 用户可代撤回但其它场景 applicant 不变。
  **覆盖 AC**：AC-37、AC-39、AC-41、AC-49、AC-52、AC-54、AC-67、AC-68
  **依赖**：T021

- [x] **T024**：应用发布候选与异常重试
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/services/app_publish_scenario_handler.py`、`src/backend/bisheng/app_publish/domain/services/publish_approval_service.py`
  **逻辑/验证**：handler 消费冻结提交身份；增加仅应用场景候选校验，双重排除，可信租户管理员数量证明单人例外；无合格候选走既有异常，不自动通过。
  **覆盖 AC**：AC-39、AC-41、AC-49、AC-52、AC-67、AC-68
  **依赖**：T021、T023
  **配对测试**：T023

- [x] **T025**：审批引擎扩展点和公开业务撤回
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/approval/domain/services/approval_center_service.py`、`src/backend/bisheng/approval/application/app_publish.py`
  **逻辑/验证**：仅应用场景可选校验钩子默认不改其它场景；公开可信目标/事务撤回接口复用 withdrawn 引擎、终态与审计；不跨域直接写审批 ORM。
  **覆盖 AC**：AC-37、AC-49、AC-52、AC-54、AC-67、AC-68
  **依赖**：T024、T023
  **配对测试**：T023

- [x] **T026**：发布上线与主动撤回动作
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/services/publish_online_service.py`、`src/backend/bisheng/app_publish/domain/services/publish_terminal_service.py`
  **逻辑/验证**：上线 publish，不再 owner 特判；撤回当前 publish；保留冻结 app/tenant/version、审批结果、取消清理及真实 actor，异常管理当前具体范围和原任务资格。
  **覆盖 AC**：AC-29、AC-37、AC-40、AC-41、AC-49、AC-52、AC-54、AC-64
  **依赖**：T025、T005、T023
  **配对测试**：T023

### Wave 4：异步来源、首个效果与 v2 阶段许可

- [x] **T027**：阶段授权与系统恢复配对
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_f114_execution_authorization.py`、`src/backend/test/app_runtime/test_f114_system_recovery.py`
  **逻辑/验证**：用户凭据撤权、未知上下文拒绝新效果；验证 maintenance 前不影响原 writer，维护后仅安全收尾；recover 只认可信 serving 来源/精确转换，不依赖历史 actor，auto_commit 无豁免；取消组合和阶段限制。
  **覆盖 AC**：AC-04、AC-26、AC-28、AC-40、AC-53、AC-54、AC-56、AC-60、AC-62、AC-64、AC-65、AC-70
  **依赖**：T005、T021

- [x] **T028**：受信来源与一步授权服务
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_authorization_service.py`、`src/backend/bisheng/app_runtime/application/runtime_authorization.py`
  **逻辑/验证**：按 design §4.5/§6.2 实现 user_request/system_recovery 的生产/加载/验证值对象，复核 credential/current actor/用途动作或可信运行意图；不接受客户端自证，许可绑定完整执行围栏与短期限。
  **覆盖 AC**：AC-04、AC-40、AC-53、AC-56、AC-60、AC-62、AC-64、AC-70
  **依赖**：T005、T027
  **配对测试**：T027

- [x] **T029**：维护事实与恢复来源事务
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`
  **逻辑/验证**：recover 同一 UoW 冻结 route/op/version/delivery，保留 pending/幂等；fact 维护前复核并原子记录 maintenance_transition，commit 再复核；用户取消按用途，system 无通用 cancel，由 unpublish 终止意图。
  **覆盖 AC**：AC-26、AC-28、AC-40、AC-53、AC-54、AC-56、AC-60、AC-65、AC-70
  **依赖**：T028、T012、T027
  **配对测试**：T027

- [x] **T030**：内部阶段 API 与值对象
  **类型**：后端 API
  **文件**：`src/backend/bisheng/app_runtime/api/endpoints/runtime_delivery.py`、`src/backend/bisheng/app_runtime/domain/schemas/runtime_delivery.py`
  **逻辑/验证**：新增 manager HMAC/nonce authorize-step，校验 op/node/gen/owner_epoch/stage/lease/deadline；只返回短期 permit，不返回私有 env/用户 token；旧内部 handler 无任意授权写口。
  **覆盖 AC**：AC-40、AC-53、AC-60、AC-65
  **依赖**：T029、T027
  **配对测试**：T027

- [x] **T031**：Celery 与预检阶段重验
  **类型**：Worker
  **文件**：`src/backend/bisheng/worker/app_publish/tasks.py`、`src/backend/bisheng/app_publish/domain/services/precheck_service.py`
  **逻辑/验证**：tenant_id 由 Celery headers 恢复 ContextVar；准备、创建版本/审批前重载冻结来源；无效落可解释终态与清理，旧版本不被提前中断，预检不注入真密钥。
  **覆盖 AC**：AC-18、AC-35、AC-36、AC-40、AC-41、AC-51、AC-53、AC-54、AC-64
  **依赖**：T021、T030、T027
  **配对测试**：T027

- [x] **T032**：manager 维护首效果与许可重放
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_f114_stage_permits.py`
  **逻辑/验证**：mock 平台客户端验证请求/维护fact确认/停writer/备份迁移/starting/route顺序；失效/未知回复拒绝新效果，同sequence查询重放不双投影；Docker/K8s复用执行器。
  **覆盖 AC**：AC-40、AC-53、AC-54、AC-60、AC-65、AC-71
  **依赖**：T030

- [x] **T033**：manager 一步许可与首次副作用顺序
  **类型**：后端 Domain
  **文件**：`src/runtime-manager/runtime_manager/platform_client.py`、`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验证**：沿唯一 v2 客户端请求阶段许可；维护准入→fact确认→停writer→独占数据步骤新许可→启动新许可；结果未知不得自行当成功，必要清理保持原围栏。
  **覆盖 AC**：AC-40、AC-53、AC-54、AC-60、AC-65、AC-71
  **依赖**：T030、T032
  **配对测试**：T032

### Wave 5：双用途预览及平台能力

- [x] **T034**：预览事务、并发、资格与回收
  **类型**：测试
  **文件**：`src/backend/test/app_publish/test_f114_preview_lifecycle.py`、`src/backend/test/app_publish/test_f114_preview_access.py`
  **逻辑/验证**：Version 串行键含viewer/purpose/task；同 repo 事务登记 session/credential/op/sealed_env/audit；提交未知先查询，commit后wake；starting拒绝，ready激活；失败/过期只吊销该凭据，不动生产；双用途身份/任务/OBO混配拒绝。
  **覆盖 AC**：AC-38、AC-49、AC-50、AC-51、AC-53、AC-54、AC-59、AC-65、AC-69
  **依赖**：T001、T002、T005、T030、T025

- [x] **T035**：预览生命周期仓储
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/repositories/preview_runtime_repository.py`、`src/backend/bisheng/app_publish/application/preview_runtime.py`
  **逻辑/验证**：提供 caller-owned session 的 Version→operation→session/credential 锁序和 lifecycle值对象，完整绑定查询/ready激活/原子关闭；不独立commit，不跨域暴露ORM。
  **覆盖 AC**：AC-38、AC-50、AC-53、AC-54、AC-65、AC-69
  **依赖**：T001、T002、T034
  **配对测试**：T034

- [x] **T036**：预览独立凭据事务端口
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/open_api/application/runtime_credentials.py`、`src/backend/bisheng/app_publish/domain/services/app_credential_service.py`
  **逻辑/验证**：复用 issue_in_transaction 签发 per-preview凭据，同session单凭据吊销及审计；不使用正式stage_binding/reissue/revoke_subject；无明文返回浏览器。
  **覆盖 AC**：AC-50、AC-51、AC-53、AC-54、AC-59、AC-65、AC-69
  **依赖**：T035、T034
  **配对测试**：T034

- [x] **T037**：预览启动和用途 API
  **类型**：后端 API
  **文件**：`src/backend/bisheng/app_publish/domain/services/preview_instance_service.py`、`src/backend/bisheng/app_publish/api/endpoints/preview.py`
  **逻辑/验证**：edit管理预览与当前任务审批预览分型；显式用途或唯一资格推导；原子starting/凭据/op/env，提交后wake/wait；重试同键复用，数据库和附件命名空间隔离；过期终态同端口回收。
  **覆盖 AC**：AC-38、AC-49、AC-50、AC-51、AC-53、AC-54、AC-65、AC-69
  **依赖**：T036、T030、T025、T034
  **配对测试**：T034

- [x] **T038**：预览运行事实与清理接线
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_cleanup_service.py`、`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`
  **逻辑/验证**：preview fact/reclaim进入operation锁之前取得Version锁；ready与route事务激活，失败/取消/超时登记单会话清理；停止证据成立才释放容量；沿既有任务，不加驻留进程。
  **覆盖 AC**：AC-50、AC-53、AC-54、AC-60、AC-65、AC-69
  **依赖**：T037、T030、T034
  **配对测试**：T034

- [x] **T039**：运行身份、用途 OBO 与能力配对
  **类型**：测试
  **文件**：`src/backend/test/open_api/test_f114_preview_identity.py`、`src/backend/test/app_publish/test_f114_preview_capabilities.py`
  **逻辑/验证**：management使用viewer本人，approval用冻结owner能力且实际viewer审计；冻结version声明，不取current；同步/异步/排队重验，缺OBO或凭据会话混配拒绝，正式app_self不变。
  **覆盖 AC**：AC-38、AC-47、AC-50、AC-51、AC-59、AC-69
  **依赖**：T037

- [x] **T040**：可信预览访问上下文
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/application/preview_access.py`、`src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py`
  **逻辑/验证**：签名之后仍查完整running会话、viewer、tenant/app/version/purpose/credential/op以及当前资格；公开 CapabilityAccessContext，approval任务scope不随页面选择，management具体scope；缺端口拒绝。
  **覆盖 AC**：AC-38、AC-50、AC-51、AC-53、AC-59、AC-69
  **依赖**：T037、T005、T039
  **配对测试**：T039

- [x] **T041**：开放认证及模型范围消费
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/open_api/domain/services/access_context.py`、`src/backend/bisheng/open_api/domain/services/model_range_policy.py`
  **逻辑/验证**：正式凭据沿route；预览只认可信会话绑定/OBO；AccessSubject投影保留用途能力主体与冻结声明版本，模型沿原F051租户启用/声明，不能放宽底层授权。
  **覆盖 AC**：AC-38、AC-47、AC-50、AC-51、AC-59、AC-69
  **依赖**：T040、T039
  **配对测试**：T039

- [x] **T042**：能力总线与组合根注册
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`、`src/backend/bisheng/app_publish/composition.py`
  **逻辑/验证**：模型/检索/附件用可信上下文，分别实际viewer与能力主体审计；API/worker组合根均注册端口，异步任务仅传引用并执行时重验；SDK附件不是app.delete。
  **覆盖 AC**：AC-18、AC-38、AC-50、AC-51、AC-59、AC-64、AC-69
  **依赖**：T041、T039
  **配对测试**：T039

### Wave 6：运行协议唯一 v2 与公共能力保留

- [x] **T043**：旧协议拒绝与共用能力保留
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_f114_v2_only.py`、`src/runtime-manager/tests/test_f114_v2_only.py`
  **逻辑/验证**：默认2；显式1/未知进程启动前失败；旧manager RPC、inventory、backend upgrade/rebind不注册无副作用；bundle/image/source-image、SQLite/附件公共工具仍可调用；不运行v1成功链。
  **覆盖 AC**：AC-18、AC-27、AC-53、AC-57、AC-58、AC-59、AC-60、AC-65、AC-71
  **依赖**：T030、T016

- [x] **T044**：后端唯一控制协议
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_protocol.py`、`src/backend/bisheng/app_runtime/domain/services/orchestrator_client.py`
  **逻辑/验证**：固定v2且显式非2拒绝，调用沿v2持久operation；按调用者清理旧RPC分支，不改平台API版本/manifest格式；保留构建、数据、存储公共能力。
  **覆盖 AC**：AC-53、AC-57、AC-58、AC-59、AC-60、AC-65、AC-71
  **依赖**：T043
  **配对测试**：T043

- [x] **T045**：manager 旧路由/对账退役
  **类型**：后端 Domain
  **文件**：`src/runtime-manager/runtime_manager/config.py`、`src/runtime-manager/runtime_manager/main.py`
  **逻辑/验证**：默认2并拒绝非2；不注册旧router/inventory/desired-state对账，先提取v2复用builder/appdb工具；不删除资产，不恢复v1fallback。
  **覆盖 AC**：AC-53、AC-57、AC-58、AC-59、AC-60、AC-65、AC-71
  **依赖**：T044、T043
  **配对测试**：T043

- [x] **T046**：入口与出口代理仅用 v2
  **类型**：后端 Domain
  **文件**：`src/app-proxy/app_proxy/config.py`、`src/runtime-manager/runtime_manager/egress_proxy.py`
  **逻辑/验证**：代理默认v2并拒绝旧配置/回退；保留HTTP/WebSocket/OBO与egress公共策略，内部来源校验不放宽。
  **覆盖 AC**：AC-57、AC-59、AC-65、AC-71
  **依赖**：T045、T043
  **配对测试**：T043

- [x] **T047**：旧后端升级路由及配置引用清理
  **类型**：后端 API
  **文件**：`src/backend/bisheng/app_runtime/api/router.py`、`src/backend/bisheng/app_runtime/api/endpoints/runtime_management.py`
  **逻辑/验证**：不注册import/upgrade/rebind；审查同名公共工具的消费者，不顺带删除v2保留能力；源代码删除清单/运维前置记录到设计，不执行存量迁移。
  **覆盖 AC**：AC-57、AC-65、AC-71
  **依赖**：T045、T016、T043
  **配对测试**：T043

### Wave 7：前端动作、范围与用途一致性

- [x] **T048**：平台权限与租户视角组件配对
  **类型**：测试
  **文件**：`src/frontend/platform/src/test/f114AppActions.test.tsx`、`src/frontend/platform/src/test/f114ConcreteScope.test.tsx`
  **逻辑/验证**：分别用六动作render卡片/详情/tabs/按钮，use-only无管理；无owner特判、不预取私有tabs；switch清query/表单，跨标签刷新；空租户filter，无global项。
  **覆盖 AC**：AC-06、AC-07、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-24、AC-26、AC-29、AC-30、AC-31、AC-32、AC-33、AC-55、AC-61、AC-62、AC-63、AC-65、AC-66
  **依赖**：T011、T009、T014、T012

- [x] **T049**：平台 API 动作与租户快照
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/controllers/API/hostedApp.ts`、`src/frontend/platform/src/controllers/request.ts`
  **逻辑/验证**：按服务端allowed_actions，专用管理写携预期具体租户，F113旧单头兼容；共用GET/调用不强制头，范围变化导致可解释拒绝并刷新；不在store发HTTP。
  **覆盖 AC**：AC-07、AC-15、AC-16、AC-17、AC-18、AC-61、AC-62、AC-63、AC-66
  **依赖**：T009、T005、T048
  **配对测试**：T048
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T050**：顶部租户单选与范围失效
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/components/HeaderTenantScope.tsx`、`src/frontend/platform/src/controllers/API/tenant.ts`
  **逻辑/验证**：只列active具体租户，服务端生效值为准；移除全平台/null；切换/失效清旧scope query与可提交表单，监听跨标签变化；不变真实身份。
  **覆盖 AC**：AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17
  **依赖**：T049、T048
  **配对测试**：T048
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T051**：应用卡片动作一致性
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/pages/BuildPage/HostedAppCard.tsx`、`src/frontend/platform/src/pages/BuildPage/useHostedAppActions.ts`
  **逻辑/验证**：以allowed_actions和业务状态展示元信息/上下线/删除/授权；保留上线下线删除确认与禁止在线切版本；不因非owner隐藏有效动作。
  **覆盖 AC**：AC-07、AC-19、AC-29、AC-30、AC-31、AC-32、AC-33、AC-42、AC-61、AC-63、AC-65
  **依赖**：T050、T012、T048
  **配对测试**：T048
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T052**：详情内容分层与请求门控
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/pages/BuildPage/hostedApp/index.tsx`、`src/frontend/platform/src/pages/BuildPage/hostedApp/hooks/useHostedApp.ts`
  **逻辑/验证**：基础可见与edit内容分开；无edit不请求data/logs/env/private版本详情，不以is_owner授权；范围改变卸载表单与内容。
  **覆盖 AC**：AC-06、AC-07、AC-20、AC-21、AC-22、AC-24、AC-33、AC-42、AC-55、AC-61、AC-62
  **依赖**：T051、T011、T048
  **配对测试**：T048
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T053**：发布面板与配置确认资格
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/PublishTab.tsx`、`src/frontend/platform/src/pages/BuildPage/hostedApp/publish/AppSecretSettings.tsx`
  **逻辑/验证**：隐藏无作用提交发布；edit配置保存、edit AND publish确认重建；按动作展示管理预览/授权/运行按钮，保留确认/密文状态与准确拒绝。
  **覆盖 AC**：AC-24、AC-25、AC-26、AC-29、AC-30、AC-33、AC-38、AC-42、AC-61、AC-63、AC-65
  **依赖**：T052、T014、T048
  **配对测试**：T048
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T054**：管理预览用途与发布展示
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/controllers/API/hostedAppPreview.ts`、`src/frontend/platform/src/pages/BuildPage/hostedApp/publish/OwnerPreviewCard.tsx`
  **逻辑/验证**：显式purpose=management，文案用管理预览，按edit显示；不从角色推审批例外；展示真实提交者及自然人归属区别。
  **覆盖 AC**：AC-38、AC-39、AC-50、AC-51、AC-61、AC-64、AC-69
  **依赖**：T053、T037、T048
  **配对测试**：T048
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T055**：审批客户端用途兼容配对
  **类型**：测试
  **文件**：`src/frontend/client/src/api/hostedAppReview.test.ts`、`src/frontend/client/src/components/approval/AppPreviewPanel.test.tsx`
  **逻辑/验证**：审批预览显式approval，省略单一用途兼容由服务器决定；双用途隔离，失效任务拒绝；不改其它资源的调用动作。
  **覆盖 AC**：AC-49、AC-50、AC-51、AC-59、AC-66、AC-69
  **依赖**：T037、T041

- [x] **T056**：客户端审批预览参数与展示
  **类型**：前端 Client
  **文件**：`src/frontend/client/src/api/hostedAppPreview.ts`、`src/frontend/client/src/components/approval/AppPreviewPanel.tsx`
  **逻辑/验证**：仅审批客户端显式purpose=approval，沿既有Recoil/API包装/组件；展示实际审批者与提交主体不冒用owner；任务失效清旧预览。
  **覆盖 AC**：AC-39、AC-49、AC-50、AC-51、AC-64、AC-66、AC-69
  **依赖**：T037、T041、T055
  **配对测试**：T055
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T057**：错误源文案 zh-Hans
  **类型**：前端 Platform
  **文件**：`src/frontend/packages/locales/src/api_errors/zh-Hans.json`
  **逻辑/验证**：范围错误和动作拒绝的该语言源文案；三语同交付。使用locale生成命令更新派生件，不手改生成文件或baseline。
  **覆盖 AC**：AC-09、AC-13、AC-14、AC-16、AC-63
  **依赖**：T053
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T058**：错误源文案 en
  **类型**：前端 Platform
  **文件**：`src/frontend/packages/locales/src/api_errors/en.json`
  **逻辑/验证**：范围错误和动作拒绝的该语言源文案；三语同交付。使用locale生成命令更新派生件，不手改生成文件或baseline。
  **覆盖 AC**：AC-09、AC-13、AC-14、AC-16、AC-63
  **依赖**：T053
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T059**：错误源文案 ja
  **类型**：前端 Platform
  **文件**：`src/frontend/packages/locales/src/api_errors/ja.json`
  **逻辑/验证**：范围错误和动作拒绝的该语言源文案；三语同交付。使用locale生成命令更新派生件，不手改生成文件或baseline。
  **覆盖 AC**：AC-09、AC-13、AC-14、AC-16、AC-63
  **依赖**：T053
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T060**：平台业务文案 zh-Hans
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`
  **逻辑/验证**：本功能范围/管理预览/实际主体的该语言文案。触及冻结中文的源码文件同时用i18n-localizer清理，不新增库或修改组件视觉。
  **覆盖 AC**：AC-09、AC-13、AC-14、AC-16、AC-38、AC-39、AC-63
  **依赖**：T053
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T061**：平台业务文案 en-US
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/public/locales/en-US/bs.json`
  **逻辑/验证**：本功能范围/管理预览/实际主体的该语言文案。触及冻结中文的源码文件同时用i18n-localizer清理，不新增库或修改组件视觉。
  **覆盖 AC**：AC-09、AC-13、AC-14、AC-16、AC-38、AC-39、AC-63
  **依赖**：T053
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

- [x] **T062**：平台业务文案 ja
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/public/locales/ja/bs.json`
  **逻辑/验证**：本功能范围/管理预览/实际主体的该语言文案。触及冻结中文的源码文件同时用i18n-localizer清理，不新增库或修改组件视觉。
  **覆盖 AC**：AC-09、AC-13、AC-14、AC-16、AC-38、AC-39、AC-63
  **依赖**：T053
  **人工验证**：仅本功能页面，以有权/无权用户对比可见内容、按钮、直接请求与范围切换；设计 §7.3，执行证据写verification。

### Wave 8：专用验收与特性收尾

- [ ] **T063**：F114 专用 API E2E 与 AC 证据
  **类型**：测试
  **文件**：`src/backend/test/e2e/test_f114_permission_actions.py`、`features/v3.0.0/114-vibe-permission-actions/verification.md`
  **逻辑/验证**：按e2e-test生成仅本特性临时A/B租户、owner/授权管理者/use-only/SA/审批主体配对；Docker/K8s只验证v2主流程与本次边界；先只读盘点旧资产，未授权不覆盖；DM8仅静态，未执行项明确。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59、AC-60、AC-61、AC-62、AC-63、AC-64、AC-65、AC-66、AC-67、AC-68、AC-69、AC-70、AC-71
  **依赖**：T053、T041、T045、T030、T009

- [ ] **T064**：L1 汇总与 L2 审查提测
  **类型**：收尾
  **文件**：`features/v3.0.0/114-vibe-permission-actions/verification.md`、`features/v3.0.0/114-vibe-permission-actions/code-review.md`
  **逻辑/验证**：逐任务L1后执行sdd-code-review --base feat/3.0.0，核对实现接线和71AC，不以文档存在宣称交付；只跑必要定向测试/Ruff/arch-guard/单迁移head与前端必要质量门禁，真实E2E与CI/发行分别报告。合并/推送按现有授权，不擅自发tag。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59、AC-60、AC-61、AC-62、AC-63、AC-64、AC-65、AC-66、AC-67、AC-68、AC-69、AC-70、AC-71
  **依赖**：T063

### 必要接线增量（仍属已确认设计）

- [x] **T065**：运行数据短票据重验与真实主体
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_grant_service.py`
  **逻辑/验证**：T013接入后，同一数据会话在签发短票据前也复核当前edit；actor_ref采用受信PermissionActor.fga_subject，不能仍调用旧owner检查或借用归属人。共享签名与5秒期限不变。配对测试为T010中新增数据会话/签发拒绝场景。
  **覆盖 AC**：AC-22、AC-23、AC-43、AC-53、AC-62、AC-65
  **依赖**：T010、T013
  **配对测试**：T010

- [x] **T066**：范围上下文受影响回归
  **类型**：测试
  **文件**：`src/backend/test/tenant/test_tenant_execution_scope.py`
  **逻辑/验证**：既有上下文嵌套/并发/异常恢复保持；旧全平台旗标即使恢复也不再公开全平台数据视角。新增管理范围只改变视角、不改真实membership的断言。
  **覆盖 AC**：AC-09、AC-16、AC-17、AC-18
  **依赖**：T009

## 实际偏差记录

暂无。推翻已确认AC或设计决策时先按SDD-Guide §3重新确认；实现细节仅回写design并在此留单行指针。

## L1 任务审查索引

实现前无已通过记录；完成时在task-reviews.md逐项登记文件、配对测试、依赖及七项检查，不能以任务打勾代替运行证据。


### 必要接线补充（按已确认设计，不扩展产品范围）

- [x] **T070**：新 app 创建投影的逆向清理
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/permission/application/runtime.py`
  **逻辑/验证**：已确认D2要求确认 rollback_created 后才能删孤立行；现端口只接受 folder/knowledge_file，扩至新app且仍限制version=0与原创建ledger；未知结果保留行和围栏，不改变其它资源语义。
  **覆盖 AC**：AC-43、AC-44、AC-48
  **依赖**：T019
  **配对测试**：T019

- [x] **T071**：无令牌的延迟认证公开端口
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/open_api/application/runtime_authorization.py`、`src/backend/bisheng/user/domain/services/auth.py`
  **逻辑/验证**：公开credential-id实时重验并复用既有mode/S/F113/scopes上下文；Web凭据只冻结已验证JWT的exp和token_version，不存原文；缺失/不确定拒绝，保持原JWT和OpenAPI访问规则。
  **覆盖 AC**：AC-04、AC-18、AC-39、AC-40、AC-43、AC-47、AC-64
  **依赖**：T027
  **配对测试**：T027

- [x] **T072**：运行记录应用范围与查询接线
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_governance/domain/services/runtime_audit_query_service.py`、`src/backend/bisheng/app_governance/domain/schemas/runtime_audit.py`
  **逻辑/验证**：已确认AC-34需要将已授权app集合带入source查询/游标和导出；缺edit的app不贡献记录/候选，单app与跨app菜单资格分别保留；全部是具体租户，无全平台范围。
  **覆盖 AC**：AC-15、AC-34、AC-62、AC-64
  **依赖**：T017
  **配对测试**：T017


- [x] **T073**：用户会话当前身份的窄端口
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/user/application/runtime_identity.py`、`src/backend/bisheng/user/domain/repositories/runtime_identity.py`
  **逻辑/验证**：Web来源续办重读有效人员、唯一当前租户及token_version，返回当前UserPayload值对象；限定user_id，不受页面视角影响，过期或迁租户拒绝，跨域不返回ORM。
  **覆盖 AC**：AC-04、AC-40、AC-64
  **依赖**：T027
  **配对测试**：T027


- [x] **T074**：运行记录源仓储按已授权应用收窄
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_governance/domain/repositories/runtime_audit_repository.py`
  **逻辑/验证**：每类记录、候选及一致导出SELECT同样约束具体租户和服务器计算的edit应用集合；空集合返回空，应用范围进入快照和游标，不接受客户端自填。
  **覆盖 AC**：AC-15、AC-34、AC-62、AC-64
  **依赖**：T072
  **配对测试**：T017


- [x] **T075**：审批执行的冻结授权来源值对象
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/schemas/release_tenancy.py`、`src/backend/bisheng/app_publish/domain/services/release_tenancy_service.py`
  **逻辑/验证**：既有受信 ApprovedReleaseSource 携带发布记录冻结的 authorization_context；仅 qualify_approved_release 生成，人工上线仍捕获当前用户，审计不将SA伪装为归属人。
  **覆盖 AC**：AC-39、AC-40、AC-41、AC-64
  **依赖**：T028
  **配对测试**：T027


- [x] **T076**：可信审批候选资格及管理员总数
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/approval/application/app_candidates.py`、`src/backend/bisheng/approval/domain/repositories/app_candidate_repository.py`
  **逻辑/验证**：应用发布专用端口验证候选当前有效自然人与租户，可信完整管理员集合独立于节点候选，双重排除；Root沿原平台管理员来源，依赖未知不启用自审例外。
  **覆盖 AC**：AC-49、AC-67、AC-68
  **依赖**：T023
  **配对测试**：T023

- [x] **T077**：异常指定与实际任务审批的应用专用钩子
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/approval/domain/services/approval_exception_service.py`、`src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py`
  **逻辑/验证**：构造同一冻结gate request并仅对app场景调用候选钩子；指定/重新指定流程在首次写入之前校验全部指定人；其它场景空钩子保持原逻辑。
  **覆盖 AC**：AC-49、AC-67、AC-68
  **依赖**：T024、T023
  **配对测试**：T023


- [x] **T078**：应用业务撤回的原子审批仓储
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/approval/domain/repositories/app_publish_withdrawal_repository.py`
  **逻辑/验证**：实例行锁下校验tenant/app/deployment/version/scenario且pending，同事务更改实例、在途任务和withdrawn动作日志；不改其它场景公共applicant资格。
  **覆盖 AC**：AC-37、AC-49、AC-52、AC-54
  **依赖**：T025、T023
  **配对测试**：T023

- [x] **T079**：应用撤回管理入口
  **类型**：后端 API
  **文件**：`src/backend/bisheng/app_publish/api/endpoints/publish_status.py`
  **逻辑/验证**：新增appid绑定撤回入口，接expected_instance_id与reason，当前publish授权后从平台数据产生冻结审批目标；旧个人审批撤回入口保持applicant限制，前端只用业务入口。
  **覆盖 AC**：AC-16、AC-37、AC-49、AC-54、AC-63
  **依赖**：T026、T025
  **配对测试**：T023


- [x] **T080**：后端启动配置只接受协议2
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/config/app_runtime.py`
  **逻辑/验证**：默认2，显式非2或未知值在配置加载时拒绝，包括default_factory环境值校验；不更改manifest或平台API版本号。
  **覆盖 AC**：AC-57、AC-71
  **依赖**：T043
  **配对测试**：T043

- [x] **T081**：应用代理路由客户端移除旧回退
  **类型**：后端 Domain
  **文件**：`src/app-proxy/app_proxy/clients.py`、`src/app-proxy/app_proxy/main.py`
  **逻辑/验证**：ManagerRouteClient只从backend读取v2签名路由；旧manager路由不回退，保留backend访问授权HTTP/WebSocket/OBO既有协议。
  **覆盖 AC**：AC-57、AC-59、AC-71
  **依赖**：T046
  **配对测试**：T082

- [x] **T082**：应用代理旧配置拒绝测试
  **类型**：测试
  **文件**：`src/app-proxy/tests/test_f114_v2_only.py`
  **逻辑/验证**：默认2，显式1/未知配置与客户端构造均拒绝，不向旧manager发HTTP；保留访问授权独立HMAC，不混淆API路径里的v1。
  **覆盖 AC**：AC-57、AC-59、AC-71
  **依赖**：T043

- [x] **T083**：预览物料初始化与存储授权接线
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_material_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_storage_service.py`
  **逻辑/验证**：starting仅供围栏匹配的初始化物料；存储令牌仍逐次校验会话当前用途。
  **覆盖 AC**：AC-18、AC-50、AC-51、AC-53、AC-59、AC-69
  **依赖**：T034、T035
  **配对测试**：T034、T039

- [x] **T084**：预览执行公开事务门面
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/application/preview_operations.py`
  **逻辑/验证**：同一个repo/UoW内登记并封装环境；commit后wake/wait，不导出跨域ORM。
  **覆盖 AC**：AC-18、AC-50、AC-51、AC-53、AC-59、AC-69
  **依赖**：T034、T035
  **配对测试**：T034、T039

- [x] **T085**：预览当前自然人资格端口
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/user/application/runtime_identity.py`
  **逻辑/验证**：运行期重新读取真实自然人和有效租户，不借页面选择，不复用历史登录有效性。
  **覆盖 AC**：AC-18、AC-50、AC-51、AC-53、AC-59、AC-69
  **依赖**：T034、T035
  **配对测试**：T034、T039


- [x] **T086**：预览当前资格与用途领域策略
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/domain/services/preview_access_service.py`
  **逻辑/验证**：管理edit/审批有效任务分型，双资格不猜测；当前人/tenant/app/version/凭据/会话逐次一致，能力主体与实际viewer分开。
  **覆盖 AC**：AC-18、AC-38、AC-50、AC-51、AC-59、AC-69
  **依赖**：T034、T039
  **配对测试**：T034、T039


- [x] **T087**：发布拥有的预览交付投影端口
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_publish/application/runtime_delivery.py`
  **逻辑/验证**：预览空基线迁移计划及冻结声明的scope公开投影，不导出ORM或提交独立事务。
  **覆盖 AC**：AC-50、AC-51、AC-53、AC-69
  **依赖**：T034、T035
  **配对测试**：T034

- [x] **T088**：OpenAPI预览能力绑定端口
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/open_api/domain/services/preview_context.py`、`src/backend/bisheng/open_api/domain/context.py`
  **逻辑/验证**：缺端口默认拒绝，运行期重验完整绑定；排队仅传播引用和已验签OBO截止时间，正式app_self保持。
  **覆盖 AC**：AC-18、AC-38、AC-50、AC-51、AC-59、AC-69
  **依赖**：T039、T040
  **配对测试**：T039

- [x] **T089**：前端动作与管理范围值工具
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/pages/BuildPage/hostedApp/appActions.ts`、`src/frontend/platform/src/controllers/managementScope.ts`
  **逻辑/验证**：按已确认六动作/具体租户/用途接线，沿现有组件无视觉改动；覆盖定向允许/拒绝。
  **覆盖 AC**：AC-06、AC-07、AC-16、AC-17、AC-33、AC-37、AC-38、AC-50、AC-61、AC-63、AC-66
  **依赖**：T048、T049
  **配对测试**：T048、T055

- [x] **T090**：详情删除和业务撤回入口
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/pages/BuildPage/hostedApp/publish/DangerZoneCard.tsx`、`src/frontend/platform/src/pages/BuildPage/hostedApp/publish/ApprovalStatusCard.tsx`
  **逻辑/验证**：按已确认六动作/具体租户/用途接线，沿现有组件无视觉改动；覆盖定向允许/拒绝。
  **覆盖 AC**：AC-06、AC-07、AC-16、AC-17、AC-33、AC-37、AC-38、AC-50、AC-61、AC-63、AC-66
  **依赖**：T048、T049
  **配对测试**：T048、T055

- [x] **T091**：顶部范围hook与API合同
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/hooks/useAdminScope.ts`、`src/frontend/platform/src/controllers/API/admin.ts`
  **逻辑/验证**：按已确认六动作/具体租户/用途接线，沿现有组件无视觉改动；覆盖定向允许/拒绝。
  **覆盖 AC**：AC-06、AC-07、AC-16、AC-17、AC-33、AC-37、AC-38、AC-50、AC-61、AC-63、AC-66
  **依赖**：T048、T049
  **配对测试**：T048、T055

- [x] **T092**：审读角色editor类型
  **类型**：前端 Platform
  **文件**：`src/frontend/platform/src/controllers/API/hostedAppReview.ts`、`src/frontend/client/src/api/hostedAppReview.ts`
  **逻辑/验证**：按已确认六动作/具体租户/用途接线，沿现有组件无视觉改动；覆盖定向允许/拒绝。
  **覆盖 AC**：AC-06、AC-07、AC-16、AC-17、AC-33、AC-37、AC-38、AC-50、AC-61、AC-63、AC-66
  **依赖**：T048、T049
  **配对测试**：T048、T055


- [x] **T093**：顶部租户测试与派生文案生成
  **类型**：测试
  **文件**：`src/frontend/platform/src/test/headerTenantScope.test.tsx`
  **逻辑/验证**：旧全平台期望改为仅active具体租户，并拒绝空ID；错误源三语由既有生成器产出，不手改派生文件。
  **覆盖 AC**：AC-09、AC-10、AC-13、AC-16、AC-63
  **依赖**：T048、T050


- [x] **T094**：构建混合列表托管应用动作映射
  **类型**：后端 API
  **文件**：`src/backend/bisheng/api/services/workflow.py`、`src/backend/test/app_runtime/test_f114_build_list.py`
  **逻辑/验证**：分页前以托管应用五管理动作OR过滤并投影六动作，工作流助手原动作不变；卡片与详情使用同一资格。
  **覆盖 AC**：AC-06、AC-07、AC-15、AC-33、AC-55、AC-61、AC-62
  **依赖**：T005、T011
  **配对测试**：T048、T010

- [x] **T095**：旧控制测试入口退役与v2认证闭环
  **类型**：测试
  **文件**：`src/runtime-manager/tests/conftest.py`、`src/runtime-manager/runtime_manager/api/operations.py`
  **逻辑/验证**：旧HMAC v1 HTTP fixture显式retired skip，共用构建/SQLite/配置工具单测保留；v2仅独立HMAC，不保留upgrade绕过。
  **覆盖 AC**：AC-50、AC-53、AC-57、AC-58、AC-59、AC-65、AC-71
  **依赖**：T043、T045
  **配对测试**：T043、T082

- [x] **T096**：入口代理真实v2签名投影fixture
  **类型**：测试
  **文件**：`src/app-proxy/tests/fakes.py`、`src/app-proxy/tests/conftest.py`
  **逻辑/验证**：代理公共HTTP/WS测试fake改为平台v2路由投影，独立实现签名验证；不删除公共入口覆盖。
  **覆盖 AC**：AC-50、AC-53、AC-57、AC-58、AC-59、AC-65、AC-71
  **依赖**：T043、T045
  **配对测试**：T043、T082

- [x] **T097**：预览入口路径断言更新
  **类型**：测试
  **文件**：`src/app-proxy/tests/test_preview.py`
  **逻辑/验证**：改为平台v2预览/正式路由，仍验证身份与空间隔离，不再发送v1成功请求。
  **覆盖 AC**：AC-50、AC-53、AC-57、AC-58、AC-59、AC-65、AC-71
  **依赖**：T043、T045
  **配对测试**：T043、T082


- [x] **T098**：新增查询回收至所属仓储
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/open_api/domain/repositories/credential_repository.py`、`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`
  **逻辑/验证**：新预览凭据精确吊销/审计和可用性读取均由OpenAPI仓储承担；应用动作候选读取由runtime仓储承担，单批最多500个ID，继续调用方UoW/自动租户过滤；不新增DAO入口。
  **覆盖 AC**：AC-06、AC-07、AC-18、AC-50、AC-53、AC-59、AC-65、AC-69
  **依赖**：T004、T034、T039
  **配对测试**：T004、T034、T039


- [x] **T099**：私有依赖显式选择按edit授权
  **类型**：后端 Domain
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_profile_service.py`、`src/backend/test/app_runtime/test_f114_private_materials.py`
  **逻辑/验证**：清除唯一剩余自然人owner选择门槛和无调用者旧helper；实际SA或自然人持当前edit可选择同应用材料，跨应用/租户继续拒绝，不改变材料归属。
  **覆盖 AC**：AC-27、AC-35、AC-65
  **依赖**：T004、T010
  **配对测试**：T004


- [x] **T100**：离线补包工具对齐范围写入合同
  **类型**：基础设施
  **文件**：`src/runtime-manager/tools/runtime_materials.py`、`src/runtime-manager/tests/test_f114_material_tool_scope.py`
  **逻辑/验证**：单应用上传先读取server确认的具体范围，冻结请求头后才打开文件；缺失/非法范围不上传，范围冲突不自动重试；公开基础目录原超管入口不增加动作。
  **覆盖 AC**：AC-16、AC-17、AC-20、AC-65
  **依赖**：T099、T009
  **配对测试**：T009


- [x] **T101**：运行运维说明与F086当前目标
  **类型**：文档
  **文件**：`src/runtime-manager/OPERATIONS.md`、`features/v3.0.0/086-vibe-runtime-delivery/spec.md`
  **逻辑/验证**：当前运行仅v2，删除旧inventory/import/rebind操作指引；六动作、预览及停写恢复要求写清，历史验收原文保留。
  **覆盖 AC**：AC-19、AC-20、AC-57、AC-59、AC-71
  **依赖**：T099、T045
  **配对测试**：T043


- [x] **T102**：F054/F055当前合同覆盖说明
  **类型**：文档
  **文件**：`features/v3.0.0/054-app-domain-runtime/spec.md`、`features/v3.0.0/055-app-publish-pipeline/spec.md`
  **逻辑/验证**：顶部增加F114替代目标与未部署状态，保留原编号、原历史证据，不将F114本地代码冒充现场交付。
  **覆盖 AC**：AC-01、AC-02、AC-04、AC-50、AC-70
  **依赖**：T101
  **配对测试**：T004


- [x] **T103**：F056/F059当前合同覆盖说明
  **类型**：文档
  **文件**：`features/v3.0.0/056-app-square-governance/spec.md`、`features/v3.0.0/059-k8s-runtime-backend/spec.md`
  **逻辑/验证**：记录管理动作/审计及唯一v2阶段授权的后继合同，保留K8s既有存储围栏与验收限制，不改变历史AC。
  **覆盖 AC**：AC-18、AC-50、AC-60、AC-70、AC-71
  **依赖**：T101
  **配对测试**：T027


- [x] **T104**：F113具体租户范围后继合同
  **类型**：文档
  **文件**：`features/v3.0.0/113-service-account-tenant-consistency/spec.md`
  **逻辑/验证**：记录不含全平台的具体管理视角与F113旧请求头继续兼容，真实身份/资源归属/迁租户拒绝不变。
  **覆盖 AC**：AC-09、AC-16、AC-17、AC-64、AC-70
  **依赖**：T101
  **配对测试**：T006


## 集成记录（不改变104项功能任务完成口径）

2026-10-30用户明确要求先提交合入feat/3.0.0，再自行部署116并继续E2E。冲突处理仅落实已确认的权限动作与具体租户合同，未新增产品范围。对应T006–T009范围准入、T014/环境变量编辑接线及T050前端范围防护，补充允许/拒绝测试与L1见integration.md。原T063/T064保持未完成；不把合入或已有设计自审当作验收通过。
