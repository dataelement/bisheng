# Tasks: 服务账号与应用操作租户一致性

**版本**：v3.0.0，发版线feat/3.0.0；开发分支codex/113-service-account-tenant-consistency。
**关联**：[spec.md](./spec.md) · [design.md](./design.md) · [任务审查](./tasks-review.md)。

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户确认38条AC，正文不变 |
| design.md | ✅ 已评审 | 用户2026-10-28明确“确认设计，进入任务拆解和开发”；确认摘要`d16fbbd1519c404fdcddeb20c5146bf8fba4dc891c72b7f2cd0ed433a1062ed4` |
| tasks.md | ✅ 已拆解 | 21项清单自审通过，见tasks-review.md |
| 开发与L1 | ✅ 已完成 | 51 / 53；所有实现任务已完成，见task-reviews.md |
| 真实验收与剩余审查 | 🔲 待执行 | T047、T048保留；用户已明确授权合入feat/3.0.0，不部署116 |

## 执行约定

- 顺序实现；本轮未派发子agent。基础设施先行，后端配对用例先行；前端请求包装先接线、随后补齐定向用例，未记为红绿测试；每个实现任务依据前驱测试，结果与命令记task-reviews.md。
- Wave依次为准入基础、复用连接、应用/发布、管理、前端、E2E/L2；每个任务以下列具体依赖为准。
- 不新增表/列、迁移器、编排进程；无数据迁移回滚需求。新代码回滚以版本回退为准；旧资源/凭据不迁移不修复。
- Worker沿现有tenant headers→ContextVar及持久deployment/operation，不新增队列或通用审批人解析。跨模块通过application；common不导入领域。
- 仅本功能定向测试，不跑全量；无测试降级，真实环境未验证项显式保留。前端仅Platform，Client只检查原审阅调用兼容，不新增Client页面。

## Tasks

- [x] **T001**：错误码与C5登记
  **类型**：基础设施
  **文件**：`src/backend/bisheng/common/errcode/open_api.py`、`docs/constitution.md`
  **逻辑**：重新扫描占用后登记26071–26073，分别表达失配、无法确认、管理范围变化；保留26030依赖错误，不改既有码。
  **覆盖 AC**：AC-02、AC-05、AC-06、AC-23、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：无

- [x] **T002**：统一错误三语源 zh-Hans
  **类型**：基础设施
  **文件**：`src/frontend/packages/locales/src/api_errors/zh-Hans.json`
  **逻辑**：新增本功能错误消息和处理指引，只修改源文件；三语源全部完成后统一生成产物。
  **覆盖 AC**：AC-02、AC-05、AC-06、AC-23、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T001

- [x] **T003**：统一错误三语源 en
  **类型**：基础设施
  **文件**：`src/frontend/packages/locales/src/api_errors/en.json`
  **逻辑**：新增本功能错误消息和处理指引，只修改源文件；三语源全部完成后统一生成产物。
  **覆盖 AC**：AC-02、AC-05、AC-06、AC-23、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T001

- [x] **T004**：统一错误三语源 ja
  **类型**：基础设施
  **文件**：`src/frontend/packages/locales/src/api_errors/ja.json`
  **逻辑**：新增本功能错误消息和处理指引，只修改源文件；三语源全部完成后统一生成产物。
  **覆盖 AC**：AC-02、AC-05、AC-06、AC-23、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T001

- [x] **T005**：实时资格允许/拒绝与热缓存测试
  **类型**：测试
  **文件**：`src/backend/test/open_api/test_service_account_tenancy.py`
  **逻辑**：用SQLite成员/账号或受控仓储测试热缓存后迁移、更换owner、0/1/多关系、删除标记、依赖失败；断言主体/授权独立，PAT/hosted_app不误伤，不写资源。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T001

- [x] **T006**：当前绑定仓储
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/domain/repositories/owner_repository.py`
  **逻辑**：新增唯一有效成员和账号/owner读取；精确受限bypass；不以User.delete为执行闸门、不first吞多关系；原PAT/候选语义保留。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T005

- [x] **T007**：实时资格服务和公开协议
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/domain/services/service_account_tenancy.py`、`src/backend/bisheng/open_api/application/service_account_tenancy.py`
  **逻辑**：提供revalidate_service_account及require_owner_tenant，依赖异常保留堆栈并转26030；只更新当次owner/name，不授予owner权限或改变凭据。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T006

- [x] **T008**：凭据缓存合流接线及受影响fixture
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/domain/services/credential_validator.py`、`src/backend/test/open_api/test_credential_validator.py`
  **逻辑**：热/冷合流均调用资格，保留原缓存上界；仅为真实受影响测试补成员事实，不能全局mock绕过新规则。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T007

- [x] **T009**：MCP复用请求资格测试
  **类型**：测试
  **文件**：`src/backend/test/open_api/test_mcp_tenant_revalidation.py`
  **逻辑**：真实请求上下文，工具延迟执行前迁租户/改owner，确保重新校验且工具体不调用；正常scope/mode配对。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-06、AC-09
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T008

- [x] **T010**：MCP工具准入接线
  **类型**：实现
  **文件**：`src/backend/bisheng/open_mcp/server.py`、`src/backend/bisheng/open_api/application/access_context.py`
  **逻辑**：工具marker加真实请求头重进公共准入，只绑定任务ContextVar，不改共享scope身份；保持错误/audit协议。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-06、AC-09
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T009

- [x] **T011**：WS新消息不可变身份测试
  **类型**：测试
  **文件**：`src/backend/test/open_api/test_websocket_tenant_revalidation.py`
  **逻辑**：消息间迁租户、owner变化、拒绝不派发，老消息快照不被新消息覆盖，默认无回调Web配对。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-06、AC-09
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T008

- [x] **T012**：中性WS消息回调与执行快照
  **类型**：实现
  **文件**：`src/backend/bisheng/common/chat/manager.py`、`src/backend/bisheng/common/chat/client.py`
  **逻辑**：common仅接中性callable；权限检查/投递前每消息准入，handle_message捕获不可变执行身份，不覆盖client.login_user；无回调行为不变。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-06、AC-09
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T011

- [x] **T013**：v2 WS准入端点接线
  **类型**：实现
  **文件**：`src/backend/bisheng/open_endpoints/api/endpoints/assistant.py`
  **逻辑**：构造每消息完整公共认证回调，重算委托/operator/permission及snapshot；保持watcher和ContextVar reset。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-06、AC-09
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T012

- [x] **T053**：MCP旧handler用例接入新请求准入
  **类型**：测试
  **文件**：`src/backend/test/open_mcp/test_server.py`
  **逻辑**：旧handler测试增加真实形状请求scope和明确credential端口桩；只对handler用例隔离本地SDK构造器差异，真实传输用例保持原状。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-32
  **验证/配对**：见task-reviews.md的本任务L1及定向证据。
  **依赖**：T010

- [x] **T014**：应用操作租户边界测试
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_app_tenant_access.py`
  **逻辑**：Root共享和actor同ID异租户，生命周期/元信息/数据/日志/配置/旧导出允许拒绝配对，ContextVar自证拒绝及原super差异；无副作用。
  **覆盖 AC**：AC-28、AC-29、AC-30、AC-31、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T001

- [x] **T015**：租户边界域策略与公开协议
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/application/tenant_access.py`、`src/backend/bisheng/app_runtime/domain/services/tenant_access.py`
  **逻辑**：只读认证来源边界，先租户后角色，原super策略显式；人工_start先校验，保留后台恢复，后续批准启动在T026接线。
  **覆盖 AC**：AC-29、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T014

- [x] **T016**：人工状态入口租户接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_state_service.py`
  **逻辑**：在operator/deleter的owner分支前采用认证租户策略，不用目标App上下文自证；批准启动后续独立接线。
  **覆盖 AC**：AC-29、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T015

- [x] **T017**：元信息与数据边界
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_meta_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_data_service.py`
  **逻辑**：人工metadata拒绝无来源actor；数据/导出保留owner-only，返回旧任务结果前重新授权；发布内部元信息在T028接可信来源。
  **覆盖 AC**：AC-29、AC-33、AC-34、AC-35、AC-36、AC-37
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T016

- [x] **T018**：日志与发布状态边界
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/app_query_service.py`、`src/backend/bisheng/app_publish/domain/services/publish_status_service.py`
  **逻辑**：真实entry租户闸门在owner分支和装配前；发布页manual入口保持owner-only；runtime_hint只沿已授权内部调用。
  **覆盖 AC**：AC-29、AC-33、AC-34、AC-35、AC-36、AC-37
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T016

- [x] **T019**：源码审阅与发布状态定向测试
  **类型**：测试
  **文件**：`src/backend/test/app_publish/test_review_tenant_access.py`
  **逻辑**：直接请求status/review-context/tree/file/diff，跨租户拒绝前不读存储；同租户审批任务与超管原例外配对，旧任务不豁免。
  **覆盖 AC**：AC-29、AC-35、AC-36、AC-37、AC-38
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T018

- [x] **T020**：共享ReviewAccess入口
  **类型**：实现
  **文件**：`src/backend/bisheng/app_publish/domain/services/snapshot_browse_service.py`
  **逻辑**：先认证租户再owner/admin/task；同租户diff任意侧审批任务原规则保留，预览消费者复用。
  **覆盖 AC**：AC-29、AC-35、AC-36、AC-37、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T019

- [x] **T021**：发布资格与批准来源测试
  **类型**：测试
  **文件**：`src/backend/test/app_publish/test_release_tenancy.py`
  **逻辑**：固定owner与app/deployment/version/approval引用真/假配对；接收/worker/审批前/上线前迁租户均拒绝；current/pending/route不变、失败清理继续。
  **覆盖 AC**：AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-28、AC-30、AC-31、AC-32、AC-38
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T007、T016

- [x] **T022**：审批来源只读应用投影
  **类型**：实现
  **文件**：`src/backend/bisheng/approval/application/execution_source.py`
  **逻辑**：包装现有审批repository，返回不可变实例状态/业务键/资源/快照，只读不改审批人解析、引擎、outbox签名。
  **覆盖 AC**：AC-14、AC-15、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T021

- [x] **T023**：发布来源仓储与内部值
  **类型**：实现
  **文件**：`src/backend/bisheng/app_publish/domain/repositories/release_tenancy_repository.py`、`src/backend/bisheng/app_publish/domain/schemas/release_tenancy.py`
  **逻辑**：精确读取唯一deployment及App/version，ApprovedReleaseSource只作本次内部值，不能HTTP构造或持久缓存；不得用审计兜底授权。
  **覆盖 AC**：AC-11、AC-12、AC-13、AC-14、AC-16、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T022

- [x] **T024**：发布资格服务及公开入口
  **类型**：实现
  **文件**：`src/backend/bisheng/app_publish/domain/services/release_tenancy_service.py`、`src/backend/bisheng/app_publish/application/release_tenancy.py`
  **逻辑**：实现require_release_eligible及qualify_approved_release，调用公开owner资格与审批投影；stage前完成，保留合法阶段与不自动重试边界。
  **覆盖 AC**：AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T023

- [x] **T025**：人工与批准启动定向测试
  **类型**：测试
  **文件**：`src/backend/test/app_publish/test_approved_start_tenancy.py`
  **逻辑**：批准source与人工actor互斥；真实批准允许、引用不符/跨租户拒绝，v1迁移/v2操作不调用；旧版本恢复配对。
  **覆盖 AC**：AC-14、AC-15、AC-33、AC-34、AC-35、AC-37、AC-38
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T024

- [x] **T026**：批准启动与共用状态实现
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/application/approved_release.py`、`src/backend/bisheng/app_runtime/domain/services/app_state_service.py`
  **逻辑**：共用已授权启动体，批准入口核对source与App/所选版本，不模拟owner、无skip参数或HTTP入口；保留原审计通知、CAS与容量结果。
  **覆盖 AC**：AC-14、AC-15、AC-33、AC-34、AC-35、AC-37、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T025

- [x] **T027**：发布接收/worker与上线接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py`、`src/backend/bisheng/app_publish/domain/services/publish_online_service.py`
  **逻辑**：接收留资源前、worker materialise前、生成版本前、stage前资格；_settle分人工/source，迁移前完成检查；失败记记录/清理并raise。worker沿原headers恢复tenant。
  **覆盖 AC**：AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-28、AC-30、AC-32、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T024、T026

- [x] **T028**：发布元信息公开入口
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/application/release_metadata.py`、`src/backend/bisheng/app_runtime/domain/services/app_meta_service.py`
  **逻辑**：update_meta_for_release(deployment_id)从可信deployment资格读owner/tenant，人工actorNone不能豁免；管道用application入口，保持原字段审计。
  **覆盖 AC**：AC-11、AC-13、AC-33、AC-34、AC-37、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T017、T027

- [x] **T051**：配置重建定向用例与真实来源fixture
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_secret_rebuild.py`、`src/backend/test/app_runtime/test_secret_runtime_snapshot.py`
  **逻辑**：fixture补真实User/UserTenant和AppDeployment；共享SQLite UoW读，避免单连接嵌套BEGIN。迁出owner拒绝重建且保留原运行；正常原确认仍可复用。
  **覆盖 AC**：AC-16、AC-34、AC-36
  **验证/配对**：见task-reviews.md的本任务L1及定向证据。
  **依赖**：T024

- [x] **T029**：预览与配置确认重建资格
  **类型**：实现
  **文件**：`src/backend/bisheng/app_publish/domain/services/preview_instance_service.py`、`src/backend/bisheng/app_runtime/domain/services/secret_rebuild_service.py`
  **逻辑**：原人工ReviewAccess/owner后、新session或部署维护前资格；后台终态/到期清理保留，不改保存不重启。
  **覆盖 AC**：AC-14、AC-15、AC-16、AC-31、AC-34、AC-35、AC-36、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T020、T024、T027

- [x] **T030**：管理范围与候选API测试
  **类型**：测试
  **文件**：`src/backend/test/open_api/test_service_account_management_scope.py`
  **逻辑**：super显式Root/子租户/未选/过期/Redis故障；全写动作范围头固定；普通admin伪造/disabled拒绝；owner候选分页与唯一成员；单租户保留。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T001

- [x] **T031**：可用租户查询与F019应用包装
  **类型**：实现
  **文件**：`src/backend/bisheng/admin/application/tenant_scope.py`、`src/backend/bisheng/admin/domain/repositories/tenant_scope_repository.py`
  **逻辑**：共享F019唯一真相，包装active查询及受控setter，不改其他页scope；异常不得fallbackRoot。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-23、AC-24、AC-25、AC-26
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T030

- [x] **T032**：账号管理范围服务与DTO
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/domain/services/service_account_scope_service.py`、`src/backend/bisheng/open_api/domain/schemas/service_account_scope.py`
  **逻辑**：预期X-Service-Account-Tenant不授权；验证后固定request ContextVar，收尾reset；超管写必选scope并匹配表单头，普通/单租户兼容。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T031

- [x] **T033**：管理依赖与静态scope端点
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/api/dependencies.py`、`src/backend/bisheng/open_api/api/endpoints/service_account_scope.py`
  **逻辑**：GET/PUT scope单独super依赖不陷入未选scope循环；owner-candidates原admin，先于动态ID路由注册；所有账号读写scope准入与业务方法清单。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T032

- [x] **T034**：账号/密钥路由范围接线
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/api/endpoints/service_account.py`、`src/backend/bisheng/open_api/api/endpoints/service_account_keys.py`
  **逻辑**：账号所有写及密钥/授权变更同一范围依赖；只读POST不误标写，GET按预期头防迟到；纯scopes目录保留范围无关读取。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T033

- [x] **T035**：归属人候选与创建范围约束
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/domain/repositories/owner_repository.py`、`src/backend/bisheng/open_api/domain/services/service_account_service.py`
  **逻辑**：同管理租户有界唯一自然人候选；显式super创建scope不随owner猜；改绑/创建最终重验，租户字段不可编辑。
  **覆盖 AC**：AC-18、AC-19、AC-20、AC-21、AC-24、AC-25、AC-26
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T034

- [x] **T036**：新静态router注册与管理API配对
  **类型**：实现
  **文件**：`src/backend/bisheng/open_api/api/router.py`
  **逻辑**：在动态ID前注册scope/owner路由；仅测试新增管理API和完整写动作清单，不扩大到PAT管理。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-23、AC-24、AC-25、AC-26
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T035

- [x] **T037**：Platform请求与范围hook测试
  **类型**：测试
  **文件**：`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/serviceAccountScope.test.tsx`、`src/frontend/platform/src/components/bs-ui/alertDialog/useConfirm.test.tsx`
  **逻辑**：表单打开scope固定到请求头、迟到请求丢弃、切换清空、普通admin及单租户不见切换，禁空SelectItem；无自动重试写。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-22、AC-23、AC-24、AC-26、AC-27
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T036

- [x] **T038**：Platform API范围协议
  **类型**：实现
  **文件**：`src/frontend/platform/src/controllers/API/serviceAccount.ts`、`src/frontend/platform/src/controllers/API/serviceAccountCandidates.ts`
  **逻辑**：包装现有request，新增scope/候选接口及每请求预期scope参数；禁止拦截器发送时读取全局scope。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-22、AC-23、AC-24、AC-25、AC-26
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T037

- [x] **T039**：Platform scope hook与选择栏
  **类型**：实现
  **文件**：`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/useServiceAccountManagementScope.tsx`、`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ServiceAccountScopeBar.tsx`
  **逻辑**：F019共享状态、不挂载默认覆写；完整active分页，过滤非法ID；切换/聚焦/范围错误刷新，取消旧请求与序号校验，三语文案。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-22、AC-23、AC-25、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T038

- [x] **T049**：用户候选数据源接入
  **类型**：实现
  **文件**：`src/frontend/platform/src/components/bs-comp/selectComponent/DepartmentUsersSelect.tsx`、`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/useServiceAccountOwnerCandidates.ts`
  **逻辑**：保留默认组织树；指定数据源时仅查询本租户候选，沿用分页/搜索/取消机制。
  **覆盖 AC**：AC-20、AC-23、AC-25、AC-26
  **验证/配对**：见task-reviews.md的本任务L1及定向证据。
  **依赖**：T038

- [x] **T040**：列表与创建弹窗范围
  **类型**：实现
  **文件**：`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/index.tsx`、`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/CreateServiceAccountDialog.tsx`
  **逻辑**：列表/详情query key固定scope；未选不查询创建，切换清表单；创建候选同scope；仿现有组件不加新样式。
  **覆盖 AC**：AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T039、T049

- [x] **T050**：确认框随所属范围失效关闭
  **类型**：实现
  **文件**：`src/frontend/platform/src/components/bs-ui/alertDialog/useConfirm.tsx`
  **逻辑**：既有确认框增加可选AbortSignal，仅取消拥有该signal的确认；未传参数的调用行为不变。
  **覆盖 AC**：AC-22、AC-23、AC-24
  **验证/配对**：见task-reviews.md的本任务L1及定向证据。
  **依赖**：T037、T040

- [x] **T041**：概览和密钥列表范围
  **类型**：实现
  **文件**：`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/OverviewTab.tsx`、`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ApiKeysTab.tsx`
  **逻辑**：编辑/改绑/启停删除及一键撤销固定打开时scope，新请求不读全局替换；scope错误清状态不自动重放。
  **覆盖 AC**：AC-18、AC-20、AC-21、AC-22、AC-23、AC-24、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T040、T050

- [x] **T042**：签发/授权弹窗范围
  **类型**：实现
  **文件**：`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/KeyIssueDialog.tsx`、`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ResourceGrantDialog.tsx`
  **逻辑**：密钥签发/更新及grant查询/变更与表单scope绑定；保留委托资格与主体权限规则。
  **覆盖 AC**：AC-18、AC-21、AC-22、AC-23、AC-24、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T041

- [x] **T043**：授权列表/撤销范围
  **类型**：实现
  **文件**：`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ResourceGrantsTab.tsx`、`src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ResourceGrantRevokeDialogs.tsx`
  **逻辑**：列表/单批撤销带固定scope，旧响应不覆盖，保留既有resource grant语义。
  **覆盖 AC**：AC-18、AC-21、AC-22、AC-23、AC-24、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T042

- [x] **T044**：Platform三语文案 zh-Hans
  **类型**：实现
  **文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`
  **逻辑**：本功能共享管理范围提示、空态、刷新错误和选择文案，无新组件样式；同时生成统一api_errors既有产物。
  **覆盖 AC**：AC-17、AC-19、AC-22、AC-23、AC-25、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T043、T002、T003、T004

- [x] **T045**：Platform三语文案 en-US
  **类型**：实现
  **文件**：`src/frontend/platform/public/locales/en-US/bs.json`
  **逻辑**：本功能共享管理范围提示、空态、刷新错误和选择文案，无新组件样式；同时生成统一api_errors既有产物。
  **覆盖 AC**：AC-17、AC-19、AC-22、AC-23、AC-25、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T043、T002、T003、T004

- [x] **T046**：Platform三语文案 ja
  **类型**：实现
  **文件**：`src/frontend/platform/public/locales/ja/bs.json`
  **逻辑**：本功能共享管理范围提示、空态、刷新错误和选择文案，无新组件样式；同时生成统一api_errors既有产物。
  **覆盖 AC**：AC-17、AC-19、AC-22、AC-23、AC-25、AC-26、AC-27
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T043、T002、T003、T004

- [x] **T052**：专用服务账号E2E准备与清理
  **类型**：测试
  **文件**：`src/backend/test/e2e/helpers/service_accounts.py`
  **逻辑**：共用认证及响应断言；按精确tenant/owner/前缀分页清理测试账号，失败显式报错；不碰存量应用或人员关系。
  **覆盖 AC**：AC-17、AC-20、AC-22、AC-24、AC-26、AC-28、AC-29、AC-30、AC-31
  **验证/配对**：见task-reviews.md的本任务L1及定向证据。
  **依赖**：T046

- [ ] **T047**：临时对象E2E用例与人工清单
  **类型**：测试
  **文件**：`src/backend/test/e2e/test_e2e_service_account_tenant_consistency.py`、`features/v3.0.0/113-service-account-tenant-consistency/verification.md`
  **逻辑**：按设计§7临时租户/owner/账号/app验证，拒绝与允许配对；不操作116旧资源；记录静态/模拟/真实界限及安全cleanup。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38
  **验证/配对**：允许/拒绝配对；前驱实现只mock外部资源，不mock被测租户闸门。
  **依赖**：T029、T036、T043、T044、T045、T046、T052

- [ ] **T048**：必要定向验证、L1及特性L2
  **类型**：验收
  **文件**：`features/v3.0.0/113-service-account-tenant-consistency/code-review.md`、`features/v3.0.0/113-service-account-tenant-consistency/task-reviews.md`
  **逻辑**：仅新/受影响测试及ruff/arch guard/i18n门，执行sdd-code-review；真实E2E在可用授权环境执行，未执行保留门，不宣称交付；DM8静态。不提交推送或部署未确认版本。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38
  **验证/配对**：运行前驱本功能测试，检查文件范围/架构/信息泄漏并记录L1。
  **依赖**：T047

## 实际偏差记录

- T008：直接受影响的旧凭据测试补真实User/UserTenant，不在全局conftest伪造所有owner。
- T010：增加公开access_context应用出口避免新跨域消费者导入内部service；当前本机MCP SDK不支持既有max_request_body_size构造参数，工具handler用构造器桩定向验证，不称为真实MCP传输验收。
- T012：消息使用独立ChatClient副本及不可变身份/快照，重建绑定身份的agent/callback；原连接身份和在途消息不变，见design §4.2。

以上为已确认方案下实现细节，无规格/关键设计偏离。

- 收尾拆分T049至T053：登记共享用户选择器可注入数据源、确认框生命周期、真实配置fixture、E2E安全清理、旧MCP handler fixture，均属已确认范围，无新增产品决策。
- 列表沿用useOpenApiList的generation及分页，不改为新ReactQuery列表。范围query key包含user，列表闭包包含scope/keyword，挂载key包含user/tenant/revision；旧scope取消与迟到结果拒绝不依赖全局拦截器。
- T043的ResourceGrantRevokeDialogs无需改动：它只调用父级已固定scope的回调，随Provider卸载清空。
- 51/53表示代码/定向用例及L1完成；T047仅脚本collection通过，真实E2E与人工项未执行；T048仍保留特性合入门。

- 用户最新指令：先完成开发并提交推送远端。本次只推开发分支，保留T047/T048验收门，不把未执行的真实E2E记为完成。

- 后续用户明确要求“合并到feat/3.0.0分支并推送远端”，本次执行该合入授权；不因此勾选未执行的T047/T048，不更改已确认AC。
