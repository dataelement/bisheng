# Tasks：F086 Vibe 开源托管与应用交付演进
**关联**：[spec.md](./spec.md) · [design.md](./design.md) · [验证](./validation.json)。基线4aa9ce69，分支codex/086-vibe-runtime-delivery。
## 状态
- spec、design已获确认；tasks已按实际文件重新核对。
- 92/94项完成实现及对应合同/原生验证；其余保留未完成。勾选不表示对应AC已取得部署证明。
- T055、T056仍保留未完成；T053已由2026-10-21测试发行实跑关闭。2026-10-21用户要求“提交推送代码先”，授权将当前阶段实现提交并推送到功能分支；完整验收与合并门继续保留。
## 开发及范围说明
测试与实现任务保留原ID，并以补充任务登记拆解时遗漏的协调器、句柄、临时数据helper、审计、CI脚本和安装文档；每项至多两个文件。基础设施依赖同域Repository/服务。新增表走model discovery；回退保留表/数据，先停控制写入。Celery复用原任务tenant headers→ContextVar，不引入第二Engine控制入口。
补充任务是本次增量接线，不改变已确认的Docker/开源/平台存储/单写SQLite边界。Python/Node用冻结argv，未增加无必要entrypoint；目录为CI真实生成JSON；专用runtime-images工作流不覆盖backend工作流。实际运行与未验证情况见task-reviews。
## Tasks

### Wave 1

- [x] **T001**：平台持久对象模型
  **类型**：基础设施；**文件**：`src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py`
  **逻辑/验收**：定义profile/default、artifact、delivery、operation、assignment、reservation、node、fact、route、policy和transfer。使用JsonType/共享时间默认/关系唯一键，应用对象保留原Owner；新表由model discovery建表，回退先停止新控制写入并保留表和资产，不破坏性drop。
  **覆盖 AC**：AC-06、AC-15、AC-19、AC-35、AC-36、AC-50、AC-61
  **依赖**：无

- [x] **T002**：模型发现注册
  **类型**：基础设施；**文件**：`src/backend/bisheng/core/database/tenant_filter.py`、`src/backend/bisheng/app_runtime/domain/models/__init__.py`
  **逻辑/验收**：通过领域包导入模型，租户表在过滤器初始化前注册；全局目录无tenant_id，明确超管入口，应用表保持自动隔离。
  **覆盖 AC**：AC-14、AC-30、AC-50、AC-61
  **依赖**：T001

- [x] **T003**：平台运行交付配置
  **类型**：基础设施；**文件**：`src/backend/bisheng/core/config/app_runtime.py`
  **逻辑/验收**：在已有app_runtime子键增加内部服务身份、文件限额/回收及协议设置，默认fail-closed；不新增YAML顶级键，保留旧配置可加载。
  **覆盖 AC**：AC-03、AC-05、AC-53、AC-58
  **依赖**：无

- [x] **T004**：manager执行配置
  **类型**：基础设施；**文件**：`src/runtime-manager/runtime_manager/config.py`
  **逻辑/验收**：加入固定node/platform身份、操作超时/回收设置、平台传输身份；旧存储参数在迁移前仅兼容解析，完成切换删除依赖。
  **覆盖 AC**：AC-04、AC-22、AC-53、AC-57、AC-58、AC-63
  **依赖**：无

### Wave 2

- [x] **T005**：平台操作/容量Repository合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_delivery_repository.py`、`src/backend/test/app_runtime/test_runtime_delivery_database.py`
  **逻辑/验收**：SQL事务约束幂等键/请求摘要、node预算锁/预占、app归属CAS、事实顺序和路由提交；隔离未知执行体，确认停止后释放；不在Service写ORM。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-06、AC-34、AC-35、AC-36、AC-37、AC-39、AC-50、AC-61、AC-63
  **依赖**：T001、T002

- [x] **T006**：平台操作/容量Repository
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`
  **逻辑/验收**：SQL事务约束幂等键/请求摘要、node预算锁/预占、app归属CAS、事实顺序和路由提交；隔离未知执行体，确认停止后释放；不在Service写ORM。
  **覆盖 AC**：AC-06、AC-34、AC-35、AC-36、AC-37、AC-39、AC-50、AC-61、AC-63
  **依赖**：T001、T002、T005

- [x] **T007**：版本2服务身份与重放保护合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_protocol_v2.py`
  **逻辑/验收**：签名绑定method/path/query/body摘要/时间/nonce/key_id；平台nonce持久端口fail-closed，不同服务动作隔离；上传用范围session，manager禁止任意URL。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-06、AC-07、AC-49、AC-52、AC-53
  **依赖**：T003、T004、T006

- [x] **T008**：版本2服务身份与重放保护
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_protocol.py`、`src/runtime-manager/runtime_manager/platform_protocol.py`
  **逻辑/验收**：签名绑定method/path/query/body摘要/时间/nonce/key_id；平台nonce持久端口fail-closed，不同服务动作隔离；上传用范围session，manager禁止任意URL。
  **覆盖 AC**：AC-06、AC-07、AC-49、AC-52、AC-53
  **依赖**：T003、T004、T006、T007

- [x] **T009**：平台产物传输合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_artifacts.py`
  **逻辑/验收**：streaming限额及hash、MinIO私有桶、upload/finalize/status幂等、代码/依赖/快照各独立上限；内容和元数据确认后verified；确认不明保护快照。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-05、AC-06、AC-07、AC-10、AC-19、AC-23、AC-28、AC-42、AC-43、AC-53
  **依赖**：T006、T008

- [x] **T010**：平台产物传输
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_artifact_service.py`、`src/backend/bisheng/app_runtime/domain/repositories/runtime_object_store.py`
  **逻辑/验收**：streaming限额及hash、MinIO私有桶、upload/finalize/status幂等、代码/依赖/快照各独立上限；内容和元数据确认后verified；确认不明保护快照。
  **覆盖 AC**：AC-05、AC-06、AC-07、AC-10、AC-19、AC-23、AC-28、AC-42、AC-43、AC-53
  **依赖**：T006、T008、T009

- [x] **T011**：环境目录和授权边界合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_profiles.py`
  **逻辑/验收**：不可变环境修订/平台镜像记录/默认CAS；超管管理全局、自然人owner管理私包，验证私包app/tenant；精确冻结平台和启动约定，拒绝可变tag假摘要。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-11、AC-12、AC-14、AC-15、AC-16、AC-17、AC-21、AC-24、AC-30、AC-31、AC-55、AC-56、AC-57、AC-59
  **依赖**：T006

- [x] **T012**：环境目录和授权边界
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_profile_service.py`、`src/backend/bisheng/app_runtime/domain/schemas/runtime_delivery.py`
  **逻辑/验收**：不可变环境修订/平台镜像记录/默认CAS；超管管理全局、自然人owner管理私包，验证私包app/tenant；精确冻结平台和启动约定，拒绝可变tag假摘要。
  **覆盖 AC**：AC-11、AC-12、AC-14、AC-15、AC-16、AC-17、AC-21、AC-24、AC-30、AC-31、AC-55、AC-56、AC-57、AC-59
  **依赖**：T006、T011

- [x] **T013**：内部操作与投影API合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_delivery_api.py`
  **逻辑/验收**：注册internal/app-runtime/v2操作/claim/facts/传输/路由/policy接口，endpoint依赖服务，按节点与scope过滤；日志status仍由F054包装；内部路由不依赖JWT租户header，验服务身份后建立scope。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-06、AC-34、AC-35、AC-36、AC-37、AC-48、AC-49、AC-50、AC-53
  **依赖**：T010、T012、T008

- [x] **T014**：内部操作与投影API
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/api/endpoints/runtime_delivery.py`、`src/backend/bisheng/app_runtime/api/router.py`
  **逻辑/验收**：注册internal/app-runtime/v2操作/claim/facts/传输/路由/policy接口，endpoint依赖服务，按节点与scope过滤；日志status仍由F054包装；内部路由不依赖JWT租户header，验服务身份后建立scope。
  **覆盖 AC**：AC-06、AC-34、AC-35、AC-36、AC-37、AC-48、AC-49、AC-50、AC-53
  **依赖**：T010、T012、T008、T013

- [x] **T015**：backend附件SDK兼容合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_storage_api.py`
  **逻辑/验收**：实现旧SDKobjects/meta/list/put/get/delete与错误信封，backend唯一MinIO访问；正式/preview独立作用域、大小、token撤销、跨app拒绝。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-05、AC-08、AC-09、AC-10、AC-38、AC-39、AC-51、AC-53、AC-60
  **依赖**：T010、T014

- [x] **T016**：backend附件SDK兼容
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/app_storage_service.py`、`src/backend/bisheng/app_runtime/api/endpoints/app_storage.py`
  **逻辑/验收**：实现旧SDKobjects/meta/list/put/get/delete与错误信封，backend唯一MinIO访问；正式/preview独立作用域、大小、token撤销、跨app拒绝。
  **覆盖 AC**：AC-05、AC-08、AC-09、AC-10、AC-38、AC-39、AC-51、AC-53、AC-60
  **依赖**：T010、T014、T015

### Wave 3

- [x] **T017**：新版清单与旧模式兼容合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_publish/test_manifest_delivery_v2.py`
  **逻辑/验收**：v2源码默认bundle、显式source-image、完整image判别，v1继续旧构建；image按运行契约不走源码模板过滤，未知字段/冲突启动拒绝。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-11、AC-12、AC-13、AC-17、AC-18、AC-25、AC-33、AC-60
  **依赖**：T012

- [x] **T018**：新版清单与旧模式兼容
  **类型**：实现；**文件**：`src/backend/bisheng/app_publish/domain/schemas/app_manifest.py`、`src/backend/bisheng/app_publish/domain/services/manifest_validator.py`
  **逻辑/验收**：v2源码默认bundle、显式source-image、完整image判别，v1继续旧构建；image按运行契约不走源码模板过滤，未知字段/冲突启动拒绝。
  **覆盖 AC**：AC-11、AC-12、AC-13、AC-17、AC-18、AC-25、AC-33、AC-60
  **依赖**：T012、T017

- [x] **T019**：CLI应用包交付合同与失败测试
  **类型**：测试；**文件**：`src/bisheng-cli/tests/test_delivery_v2.py`
  **逻辑/验收**：init默认v2，保留v1打包和状态轮询；包不带开发机venv/node_modules，锁/前端输入保留；清晰协议不兼容。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-07、AC-11、AC-13、AC-17、AC-25、AC-60
  **依赖**：T018

- [x] **T020**：CLI应用包交付
  **类型**：实现；**文件**：`src/bisheng-cli/bisheng_cli/project.py`、`src/bisheng-cli/bisheng_cli/packaging.py`
  **逻辑/验收**：init默认v2，保留v1打包和状态轮询；包不带开发机venv/node_modules，锁/前端输入保留；清晰协议不兼容。
  **覆盖 AC**：AC-07、AC-11、AC-13、AC-17、AC-25、AC-60
  **依赖**：T018、T019

### Wave 4

- [x] **T021**：manager平台内容客户端合同与失败测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_platform_client_v2.py`
  **逻辑/验收**：签名HTTP客户端、claim/query/facts/transfer接口，大小/hash校验、恢复上传、只接受平台ID；v2异步操作API输出可关联operation；所有外部响应显式检查。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-05、AC-06、AC-07、AC-23、AC-36、AC-42、AC-43、AC-53
  **依赖**：T014、T008

- [x] **T022**：manager平台内容客户端
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/platform_client.py`、`src/runtime-manager/runtime_manager/api/operations.py`
  **逻辑/验收**：签名HTTP客户端、claim/query/facts/transfer接口，大小/hash校验、恢复上传、只接受平台ID；v2异步操作API输出可关联operation；所有外部响应显式检查。
  **覆盖 AC**：AC-05、AC-06、AC-07、AC-23、AC-36、AC-42、AC-43、AC-53
  **依赖**：T014、T008、T021

- [x] **T023**：Python与Node准备和复用合同与失败测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_bundle_preparer.py`
  **逻辑/验收**：按scope/架构/ABI/镜像/锁/工具链/源码输入hash缓存；下载与无网安装编译隔离，固定wheelhouse/npm缓存，SDK入锁；只在成功后原子可见，缺包在审批前拒绝。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-59
  **依赖**：T022

- [x] **T024**：Python与Node准备和复用
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/bundle_preparer.py`、`src/runtime-manager/runtime_manager/bundle_inputs.py`
  **逻辑/验收**：按scope/架构/ABI/镜像/锁/工具链/源码输入hash缓存；下载与无网安装编译隔离，固定wheelhouse/npm缓存，SDK入锁；只在成功后原子可见，缺包在审批前拒绝。
  **覆盖 AC**：AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-59
  **依赖**：T022、T023

- [x] **T025**：bundle与完整镜像启动合同与失败测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_bundle_launch.py`
  **逻辑/验收**：实际host bind路径，代码和依赖ro/data rw，固定argv、端口与健康；无host端口/高权参数；离线image ID内容映射与完整镜像无pip/npm。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-11、AC-12、AC-17、AC-18、AC-22、AC-41、AC-46、AC-52、AC-56、AC-57、AC-58
  **依赖**：T024

- [x] **T026**：bundle与完整镜像启动
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/bundle_launch.py`、`src/runtime-manager/runtime_manager/docker_backend.py`
  **逻辑/验收**：实际host bind路径，代码和依赖ro/data rw，固定argv、端口与健康；无host端口/高权参数；离线image ID内容映射与完整镜像无pip/npm。
  **覆盖 AC**：AC-11、AC-12、AC-17、AC-18、AC-22、AC-41、AC-46、AC-52、AC-56、AC-57、AC-58
  **依赖**：T024、T025

- [x] **T027**：manager操作所有权和回收合同与失败测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_operations_v2.py`
  **逻辑/验收**：持久操作驱动、app串行、epoch/current claim、Engine标签查询幂等；无平台停止新破坏动作；终态/timeout/cancel/restart临时资源回收、未知保留容量、引用/DB/唯一备份保护。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-26、AC-34、AC-35、AC-36、AC-37、AC-39、AC-40、AC-50、AC-63
  **依赖**：T022、T026

- [x] **T028**：manager操作所有权和回收
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：持久操作驱动、app串行、epoch/current claim、Engine标签查询幂等；无平台停止新破坏动作；终态/timeout/cancel/restart临时资源回收、未知保留容量、引用/DB/唯一备份保护。
  **覆盖 AC**：AC-26、AC-34、AC-35、AC-36、AC-37、AC-39、AC-40、AC-50、AC-63
  **依赖**：T022、T026、T027

### Wave 5

- [x] **T029**：SQLite平台快照与owner恢复合同与失败测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_platform_appdb.py`
  **逻辑/验收**：Backup API一致副本/校验、backend confirmed后DDL、丢响应查询同snapshot；停写单写入者、恢复先保护当前数据、失败不自动覆盖生产；保留受控数据API。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-05、AC-35、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47
  **依赖**：T028、T010

- [x] **T030**：SQLite平台快照与owner恢复
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/appdb.py`、`src/runtime-manager/runtime_manager/platform_appdb.py`
  **逻辑/验收**：Backup API一致副本/校验、backend confirmed后DDL、丢响应查询同snapshot；停写单写入者、恢复先保护当前数据、失败不自动覆盖生产；保留受控数据API。
  **覆盖 AC**：AC-05、AC-35、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47
  **依赖**：T028、T010、T029

- [x] **T031**：F055交付准备接线合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_publish/test_delivery_pipeline_v2.py`
  **逻辑/验收**：源码下载只经backend；三交付模式统一prepare/probe/freeze；缺包/预检失败无审批，保留扫描、版本创建入口及原补偿。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-06、AC-11、AC-12、AC-13、AC-19、AC-29、AC-32、AC-33
  **依赖**：T018、T028、T030

- [x] **T032**：F055交付准备接线
  **类型**：实现；**文件**：`src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py`
  **逻辑/验收**：F055 的协议2 prepare/probe 接线放在 PublishPipelineService，经 RuntimeDeliveryCoordinator，不改协议1 precheck 的 URL 合同；Celery 仍使用原任务的 tenant headers→ContextVar。v1描述在协议2映射source-image；v2不在协议1静默发布。
  **覆盖 AC**：AC-06、AC-11、AC-12、AC-13、AC-19、AC-29、AC-32、AC-33
  **依赖**：T018、T028、T030、T031

- [x] **T033**：版本冻结与凭据代际合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_lifecycle_v2.py`
  **逻辑/验收**：delivery组合冻结，原四要素不变；候选只隔离凭据，切换生效/撤旧≤5秒，外部撤权不延迟；无重复签发/审批。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-15、AC-16、AC-19、AC-33、AC-36、AC-38、AC-51、AC-57、AC-60
  **依赖**：T032

- [x] **T034**：版本冻结与凭据代际
  **类型**：实现；**文件**：`src/backend/bisheng/app_publish/domain/services/version_service.py`、`src/backend/bisheng/app_publish/domain/services/app_credential_service.py`
  **逻辑/验收**：delivery组合冻结，原四要素不变；候选只隔离凭据，切换生效/撤旧≤5秒，外部撤权不延迟；无重复签发/审批。
  **覆盖 AC**：AC-15、AC-16、AC-19、AC-33、AC-36、AC-38、AC-51、AC-57、AC-60
  **依赖**：T032、T033

- [x] **T035**：F054/F055安全上线合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_lifecycle_v2.py`
  **逻辑/验收**：在停旧/DDL前原子预占，SQLite维护单写/快照确认，ready事实后事务切路由与原状态；失败/容量不足/停用恢复保持真实阶段；worker tenant_id随headers恢复。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-02、AC-09、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-46
  **依赖**：T034、T030、T006

- [x] **T036**：F054/F055安全上线
  **类型**：实现；**文件**：`src/backend/bisheng/app_publish/domain/services/publish_online_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_state_service.py`
  **逻辑/验收**：在停旧/DDL前原子预占，SQLite维护单写/快照确认，ready事实后事务切路由与原状态；失败/容量不足/停用恢复保持真实阶段；worker tenant_id随headers恢复。
  **覆盖 AC**：AC-02、AC-09、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-46
  **依赖**：T034、T030、T006、T035

- [x] **T037**：入口读取平台路由合同与失败测试
  **类型**：测试；**文件**：`src/app-proxy/tests/test_platform_route_v2.py`
  **逻辑/验收**：route读backend持久投影，无manager管理secret；manager短重启新HTTP/WS仍可取得目标，授权失败按TTL拒绝，保持身份清洗/OBO/预览。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-04、AC-18、AC-39、AC-48、AC-49、AC-50、AC-51、AC-53
  **依赖**：T014、T036

- [x] **T038**：入口读取平台路由
  **类型**：实现；**文件**：`src/app-proxy/app_proxy/clients.py`、`src/app-proxy/app_proxy/config.py`
  **逻辑/验收**：route读backend持久投影，无manager管理secret；manager短重启新HTTP/WS仍可取得目标，授权失败按TTL拒绝，保持身份清洗/OBO/预览。
  **覆盖 AC**：AC-04、AC-18、AC-39、AC-48、AC-49、AC-50、AC-51、AC-53
  **依赖**：T014、T036、T037

- [x] **T039**：出口读取平台策略合同与失败测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_platform_egress.py`
  **逻辑/验收**：平台policy只读身份/硬到期/撤销关CONNECT，本地只缓存，不挂应用卷不持管理密钥；保留L3/目标/DNS语义。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-04、AC-39、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53
  **依赖**：T014、T036

- [x] **T040**：出口读取平台策略
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/egress_proxy.py`
  **逻辑/验收**：平台policy只读身份/硬到期/撤销关CONNECT，本地只缓存，不挂应用卷不持管理密钥；保留L3/目标/DNS语义。
  **覆盖 AC**：AC-04、AC-39、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53
  **依赖**：T014、T036、T039

- [x] **T041**：环境导入及owner维护API合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_management_api.py`
  **逻辑/验收**：顶级profile/default/base-import路由，app私包和restore接口；owner自然人业务guard先于管理员短路、expected generation/恢复损失确认及审计，服务账号不能独立发起。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-14、AC-15、AC-24、AC-28、AC-30、AC-35、AC-45、AC-47、AC-53
  **依赖**：T016、T012、T036

- [x] **T042**：环境导入及owner维护API
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/api/endpoints/runtime_management.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_management_service.py`
  **逻辑/验收**：顶级profile/default/base-import路由，app私包和restore接口；owner自然人业务guard先于管理员短路、expected generation/恢复损失确认及审计，服务账号不能独立发起。
  **覆盖 AC**：AC-14、AC-15、AC-24、AC-28、AC-30、AC-35、AC-45、AC-47、AC-53
  **依赖**：T016、T012、T036、T041

### Wave 6

- [x] **T043**：离线制作与环境工具合同与失败测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_offline_materials.py`
  **逻辑/验收**：prepare/verify/import工具，manifest/hash/size/平台/ABI验证，制作机用Docker CLI、运行节点Engine API；双平台完整清单，默认配置导入SQL非共享文件。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-14、AC-15、AC-27、AC-28、AC-29、AC-30、AC-31、AC-55、AC-56、AC-58、AC-59
  **依赖**：T042、T024

- [x] **T044**：离线制作与环境工具
  **类型**：实现；**文件**：`src/runtime-manager/tools/runtime_materials.py`
  **逻辑/验收**：提供 catalog/export-profile/prepare-offline/pack/verify/import 工具；发行目录由CI真实inventory生成，不提交虚构digest。联网下载和禁网安装验证分离，临时副本不污染原源码；导入default用generation CAS，跳转不携会话。
  **覆盖 AC**：AC-14、AC-15、AC-27、AC-28、AC-29、AC-30、AC-31、AC-55、AC-56、AC-58、AC-59
  **依赖**：T042、T024、T043

- [x] **T045**：存量迁移与发布物兼容合同与失败测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_upgrade.py`
  **逻辑/验收**：只通过scope API盘点/干跑/幂等导入，核对app与Engine标签、旧状态和版本；逐app部署绑定换backend storage，无改历史版本/免审代码修改；备份/回退限制明确。；测试只调用真实模块，mock外部端口，不用占位模块替代实现。
  **覆盖 AC**：AC-03、AC-08、AC-10、AC-13、AC-46、AC-57、AC-60
  **依赖**：T042、T038、T040、T044

- [x] **T046**：存量迁移与发布物兼容
  **类型**：实现；**文件**：`src/backend/scripts/upgrade_vibe_runtime.py`、`src/backend/scripts/README.md`
  **逻辑/验收**：只通过scope API盘点/干跑/幂等导入，核对app与Engine标签、旧状态和版本；逐app部署绑定换backend storage，无改历史版本/免审代码修改；备份/回退限制明确。
  **覆盖 AC**：AC-03、AC-08、AC-10、AC-13、AC-46、AC-57、AC-60
  **依赖**：T042、T038、T040、T044、T045

- [x] **T047**：镜像和Compose发行合同测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_delivery_images.py`
  **逻辑/验收**：检查正式compose仅image、可选profile、代理权限/volume、双平台清单与预制运行/准备镜像合同；不以静态测试代替双架构运行。
  **覆盖 AC**：AC-01、AC-03、AC-04、AC-05、AC-54、AC-55、AC-56、AC-57、AC-58
  **依赖**：T046

- [x] **T048**：manager与入口预构建镜像
  **类型**：实现；**文件**：`src/runtime-manager/Dockerfile`、`src/app-proxy/Dockerfile`
  **逻辑/验收**：保留Python锁定依赖，删除manager MinIO并修正socket权限旧注释；egress同镜像独立command，非root和专用目录。
  **覆盖 AC**：AC-01、AC-04、AC-05、AC-54、AC-55、AC-57
  **依赖**：T047

- [x] **T049**：python3.11运行/准备镜像
  **类型**：实现；**文件**：`src/app-runtime/python3.11/Dockerfile`、`src/app-runtime/python3.11/requirements.txt`
  **逻辑/验收**：runtime/preparer分阶段镜像，固定SDK0.1.1及常用依赖/wheelhouse；纯argv启动不另造Python入口脚本。原生双架构与实际禁网物化为后续必需验收。
  **覆盖 AC**：AC-11、AC-17、AC-22、AC-25、AC-31、AC-54、AC-55、AC-59
  **依赖**：T048

- [x] **T050**：node20运行/准备镜像
  **类型**：实现；**文件**：`src/app-runtime/node20/Dockerfile`
  **逻辑/验收**：Node20 runtime/preparer分阶段镜像及固定npm；启动由冻结argv/Procfile/package.start控制，不增加重复入口脚本。真实npm安装钩子/编译与双架构待验收。
  **覆盖 AC**：AC-11、AC-17、AC-22、AC-25、AC-31、AC-54、AC-55、AC-59
  **依赖**：T048

- [x] **T051**：static运行/准备镜像
  **类型**：实现；**文件**：`src/app-runtime/static/Dockerfile`、`src/app-runtime/static/entrypoint.sh`
  **逻辑/验收**：非root静态HTTP服务与路径前缀；runtime/preparer多stage分别发行；双架构清单，现场不构建。
  **覆盖 AC**：AC-11、AC-17、AC-22、AC-25、AC-31、AC-54、AC-55、AC-59
  **依赖**：T048

- [x] **T052**：Compose与安装检查
  **类型**：实现；**文件**：`docker/docker-compose.yml`、`docker/verify_app_runtime_compose.py`
  **逻辑/验收**：正式使用Docker Hub image，保留optional profile；清除manager MinIO和egress应用卷，配置独立身份/平台API及宿主目录；自检镜像、依赖、运行接口分别报告。
  **覆盖 AC**：AC-01、AC-03、AC-04、AC-05、AC-18、AC-52、AC-54、AC-56、AC-58
  **依赖**：T049、T050、T051

- [x] **T053**：CI/Release双架构交付
  **类型**：实现；**文件**：`.github/workflows/runtime-images.yml`
  **逻辑/验收**：独立runtime-images工作流，amd64/arm64原生构建、真实容器级烟测、不可覆盖标签，双侧成功后发布目录与服务索引；不改backend已有CI。测试Tag v3.0.0-test-vibe已实跑成功，双原生构建/集成、架构标签、服务索引和目录已发布；见e2e-evidence/2026-10-21-ci-release。
  **覆盖 AC**：AC-54、AC-55、AC-56、AC-57
  **依赖**：T052

- [x] **T054**：CLI可分发wheel及锁定依赖
  **类型**：基础设施；**文件**：`src/backend/bisheng/dev_toolkit/artifacts/bisheng_cli-3.0.0-py3-none-any.whl`、`src/backend/bisheng/dev_toolkit/artifacts/manifest.json`
  **逻辑/验收**：重建并分发CLI wheel及manifest，保留SDK0.1.1工件；打包脚本干净环境安装/生产入口成功，不执行git add/commit/push。
  **覆盖 AC**：AC-05、AC-13、AC-54、AC-60
  **依赖**：T020、T053

### Wave 7

- [ ] **T055**：API E2E与故障证据
  **类型**：测试；**文件**：`src/backend/test/e2e/test_e2e_f086_runtime_delivery.py`、`features/v3.0.0/086-vibe-runtime-delivery/e2e-checklist.md`
  **逻辑/验收**：生成显式启用的部署级权限API用例及完整人工发布/故障/双架构清单；六项live权限已通过；真实平台关键旅程、MySQL和双原生架构已取得证据，剩余故障/离线/发行门保留。用户确认DM8本轮只做模型静态审查，实测留中央回归。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59、AC-60、AC-61、AC-62、AC-63
  **依赖**：T054、T038、T040

- [ ] **T056**：最终审查和证据汇总
  **类型**：实现；**文件**：`features/v3.0.0/086-vibe-runtime-delivery/task-reviews.md`、`features/v3.0.0/086-vibe-runtime-delivery/validation.json`
  **逻辑/验收**：按task-review记录真实L1、arch-guard/ruff/回归、七维code-review及差异基线证据；未通过的部署和质量门不改成已完成，无自动提交/推送/合并。
  **覆盖 AC**：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59、AC-60、AC-61、AC-62、AC-63
  **依赖**：T055

### Wave 8

- [x] **T057**：准备执行器与旧模板适配
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/container_runner.py`、`src/runtime-manager/runtime_manager/legacy_prepare.py`
  **逻辑/验收**：仅受限任务容器，资源限额与预占一致；宿主路径映射、非root、禁网/下载分离。source-image仅用平台模板、显式startup和操作范围出站。
  **覆盖 AC**：AC-11、AC-13、AC-19、AC-26、AC-53、AC-63
  **依赖**：T023、T027

- [x] **T058**：发布交付协调器
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py`
  **逻辑/验收**：准备/探活/预览/上线/恢复都登记持久操作；固定profile/源码/依赖，范围资产传输；原Owner提交状态，秘密先封装再允许执行。
  **覆盖 AC**：AC-05、AC-15、AC-33、AC-37、AC-39、AC-41、AC-63
  **依赖**：T031、T035

- [x] **T059**：凭据保护与执行代际读取
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_payload.py`、`src/backend/bisheng/app_runtime/domain/repositories/runtime_credential_repository.py`
  **逻辑/验收**：部署Fernet key封装可续跑的应用环境；正式和排队调用复用F049认证入口，绑定route operation，candidate/旧同版本/维护均拒绝。
  **覆盖 AC**：AC-39、AC-51、AC-53
  **依赖**：T033

- [x] **T060**：路由和出站投影业务
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_projection_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_egress_service.py`
  **逻辑/验收**：同UoW激活route/原凭据/附件句柄；失败撤销候选；出站稳定operation凭据、正式切换fencing、生成环境平台URL放行及显式UTC时间。
  **覆盖 AC**：AC-39、AC-48、AC-49、AC-50、AC-51、AC-53
  **依赖**：T033、T039

- [x] **T061**：存量与离线内容校验业务
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_upgrade_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_offline_package.py`
  **逻辑/验收**：校验有界tar/hash/ABI且拒绝登录文件；存量绑定用签名实时inventory复核，保持AppVersion不变，需确认维护及重新绑定。
  **覆盖 AC**：AC-07、AC-13、AC-27、AC-30、AC-46、AC-57、AC-60
  **依赖**：T041、T045

- [x] **T062**：控制客户端与范围回收
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_control_client.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_cleanup_service.py`
  **逻辑/验收**：平台独立control HMAC，只唤醒ID/读inventory；确认执行停止后清理该预览/删除动作的附件及指定快照，不改其他应用。
  **覆盖 AC**：AC-06、AC-09、AC-10、AC-26、AC-63
  **依赖**：T013、T015

- [x] **T063**：manager启动和旧协议拒绝
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/main.py`、`src/runtime-manager/runtime_manager/auth.py`
  **逻辑/验收**：协议2采用平台对账loop，旧写/存储入口拒绝；协议1保留迁移兼容。入站nonce后端持久化，身份与出站读身份分离。
  **覆盖 AC**：AC-04、AC-06、AC-48、AC-53、AC-58
  **依赖**：T027

- [x] **T064**：SQLite数据容器合同测试
  **类型**：测试；**文件**：`src/runtime-manager/tests/test_data_executor.py`
  **逻辑/验收**：验证只挂一个app数据、无控制secret、非root和network none，保留HTTP错误及清理容器/临时输出；真实Docker同镜像运行由CI验证。
  **覆盖 AC**：AC-47、AC-52、AC-53
  **依赖**：T029

- [x] **T065**：受控数据执行API
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/api/platform_data.py`、`src/runtime-manager/runtime_manager/data_executor.py`
  **逻辑/验收**：后台权限后经control签名到manager；当前node与维护互斥；相同manager镜像短命helper，128MiB/100mCPU、两并发、30秒与标签GC，导出一次性目录。
  **覆盖 AC**：AC-47、AC-52、AC-53
  **依赖**：T064

- [x] **T066**：单应用数据入口与只读观测
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/data_worker.py`、`src/runtime-manager/runtime_manager/api/platform_observe.py`
  **逻辑/验收**：worker只执行已有表/行/导出协议，无任意SQL；status/log由平台绑定定位容器并脱敏，runtime-status保留旧响应字段、SQL容量失联不回落本地状态。
  **覆盖 AC**：AC-47、AC-48、AC-50、AC-53
  **依赖**：T027、T064

- [x] **T067**：旧运行绑定只读inventory
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/api/upgrade.py`
  **逻辑/验收**：按旧state和实时Engine/镜像/标签导出范围，兼容模式可读取，排除容器env/密钥，记录旧bucket差异。
  **覆盖 AC**：AC-13、AC-46、AC-57、AC-60
  **依赖**：T045

- [x] **T068**：出口平台策略缓存适配
  **类型**：实现；**文件**：`src/runtime-manager/runtime_manager/platform_egress.py`
  **逻辑/验收**：独立只读身份取policy hash/epoch/硬期限，刷新离开事件循环，平台故障超过TTL就拒绝/关闭连接。
  **覆盖 AC**：AC-49、AC-50、AC-52
  **依赖**：T039

- [x] **T069**：入口协议与运行接线
  **类型**：实现；**文件**：`src/app-proxy/app_proxy/platform_protocol.py`、`src/app-proxy/app_proxy/main.py`
  **逻辑/验收**：独立镜像协议共享测试向量；入口不持有manager写权限，读取平台路由并保留原HTTP/WS授权。
  **覆盖 AC**：AC-48、AC-49、AC-53
  **依赖**：T007、T037

- [x] **T070**：审批预览与授权接线
  **类型**：实现；**文件**：`src/backend/bisheng/app_publish/domain/services/preview_instance_service.py`、`src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py`
  **逻辑/验收**：原预览session/owner能力例外不变，v2使用冻结delivery；正式维护路由不可被旧授权缓存长期放行。
  **覆盖 AC**：AC-09、AC-33、AC-48、AC-51
  **依赖**：T033、T035

- [x] **T071**：SDK中间件与创建入口约束
  **类型**：实现；**文件**：`src/backend/bisheng/utils/http_middleware.py`、`src/backend/test/app_runtime/test_runtime_layer_switch.py`
  **逻辑/验收**：仅SDK storage namespace走句柄认证；新增app-scoped材料/恢复维护POST不成为UI创建应用入口。
  **覆盖 AC**：AC-05、AC-07、AC-53、AC-60
  **依赖**：T015

- [x] **T072**：离线与owner业务测试
  **类型**：测试；**文件**：`src/backend/test/app_runtime/test_runtime_management.py`
  **逻辑/验收**：真实离线tar的内容及profile兼容元数据和自然人owner矩阵；不假造MinIO/权限核心模块。
  **覆盖 AC**：AC-07、AC-14、AC-15、AC-30、AC-45、AC-53
  **依赖**：T011

- [x] **T073**：数据恢复审计登记
  **类型**：基础设施；**文件**：`src/backend/bisheng/database/models/audit_log.py`、`src/backend/bisheng/app_runtime/domain/constants.py`
  **逻辑/验收**：登记app.data_restore到原审计枚举和UI可见白名单，使用原system audit流程；不增加新数字错误码。
  **覆盖 AC**：AC-45、AC-47
  **依赖**：T035

- [x] **T074**：Platform审计筛选接线
  **类型**：前端 Platform；**文件**：`src/frontend/platform/src/controllers/API/log.ts`
  **逻辑/验收**：原审计动作列表增加data_restore，保持既有请求封装；无组件/样式/新页面变更。
  **覆盖 AC**：AC-47
  **依赖**：T073

- [x] **T075**：审计三语文案第一组
  **类型**：前端 Platform；**文件**：`src/frontend/platform/public/locales/en-US/bs.json`、`src/frontend/platform/public/locales/zh-Hans/bs.json`
  **逻辑/验收**：仅已有bs审计字典新增同键；这不是api_errors生成文件。
  **覆盖 AC**：AC-47
  **依赖**：T073

- [x] **T076**：审计三语文案日语
  **类型**：前端 Platform；**文件**：`src/frontend/platform/public/locales/ja/bs.json`
  **逻辑/验收**：同键日语补齐，和前项在同一改动交付，check-i18n验证。
  **覆盖 AC**：AC-47
  **依赖**：T073

- [x] **T077**：原生镜像构建与容器烟测
  **类型**：实现；**文件**：`scripts/build_runtime_images.sh`、`scripts/smoke_runtime_delivery.py`
  **逻辑/验收**：构建服务及runtime/preparer、拒绝已有标签；真实Engine且全程应用包禁网、代码更新和复用、SQLite/helper，内存产物port；未运行不得等同整个平台E2E。
  **覆盖 AC**：AC-11、AC-19、AC-20、AC-31、AC-41、AC-54、AC-55、AC-56
  **依赖**：T047

- [x] **T078**：镜像内统一准备器
  **类型**：实现；**文件**：`src/app-runtime/common/prepare.py`
  **逻辑/验收**：联网只下载受限Python轮子和npm材料，禁网运行安装钩子/本地项目wheel/前端编译，保存锁/原生材料/源码overlay并拒绝逃逸或凭据文件。
  **覆盖 AC**：AC-19、AC-21、AC-24、AC-25、AC-27、AC-28、AC-29、AC-53
  **依赖**：T023、T043

- [x] **T079**：static无root入口配置
  **类型**：基础设施；**文件**：`src/app-runtime/static/nginx.conf`
  **逻辑/验收**：动态PORT配置由entrypoint渲染到tmp；静态编译复用Node preparer，不新建常驻服务。
  **覆盖 AC**：AC-11、AC-17、AC-25、AC-54
  **依赖**：T025

- [x] **T080**：独立开发构建覆盖
  **类型**：基础设施；**文件**：`docker/docker-compose.runtime-dev.yml`
  **逻辑/验收**：只有开发override含build；正式Compose全部使用镜像引用。
  **覆盖 AC**：AC-54、AC-58
  **依赖**：T047

- [x] **T081**：安装环境与校验脚本
  **类型**：基础设施；**文件**：`docker/.env.example`、`docker/verify-app-runtime-compose.sh`
  **逻辑/验收**：列明分离HMAC/Fernet/离线/镜像参数；Compose命令仅做config/权限/网络检查，不现场启动或构建。
  **覆盖 AC**：AC-03、AC-04、AC-53、AC-58
  **依赖**：T047

- [x] **T082**：manager冻结依赖合同
  **类型**：基础设施；**文件**：`src/runtime-manager/pyproject.toml`、`src/runtime-manager/uv.lock`
  **逻辑/验收**：默认不安装MinIO，legacy-storage显式optional；保留原固定依赖版本并用frozen锁检查，不做无关升级。
  **覆盖 AC**：AC-04、AC-05、AC-54、AC-57
  **依赖**：T047

- [x] **T083**：安装维护文档
  **类型**：文档；**文件**：`src/runtime-manager/OPERATIONS.md`、`docs/architecture/14-app-factory-deployment.md`
  **逻辑/验收**：说明具体profile/默认替换、离线制作导入/边界、SQLite/helper及维护升级；旧架构文档指向v2而不冒充已发布。
  **覆盖 AC**：AC-03、AC-27、AC-28、AC-45、AC-46、AC-54、AC-57、AC-58、AC-59、AC-62
  **依赖**：T044、T046

- [x] **T084**：CLI及版本交付登记
  **类型**：文档；**文件**：`src/bisheng-cli/README.md`、`features/v3.0.0/release-contract.md`
  **逻辑/验收**：同步owner绑定和SAK发布、F086设计已确认/代码与部署验收分层；原不变量及历史评审输入保持。
  **覆盖 AC**：AC-13、AC-30、AC-54、AC-58、AC-60、AC-62
  **依赖**：T054

### Wave 9

- [x] **T085**：离线补包入口流式代理
  **类型**：基础设施；**文件**：`docker/nginx/conf.d/default.conf`
  **逻辑/验收**：材料上传路径2GiB流式转发，保留鉴权/转发头；真实Nginx语法检查及2,218,132字节材料经nginx/后端校验已通过；未实传2GiB。
  **覆盖 AC**：AC-05、AC-07、AC-27、AC-28、AC-58
  **依赖**：T047

### Wave 10

- [x] **T086**：平台执行事实与旧RPC适配
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`、`src/backend/bisheng/app_runtime/domain/services/orchestrator_client.py`
  **逻辑/验收**：执行身份/阶段/事实/诊断/归属/预览/自愈的领域入口；原logs/status/data RPC通过v2control签名适配，不能旁路业务授权。
  **覆盖 AC**：AC-06、AC-29、AC-35、AC-36、AC-37、AC-48、AC-50、AC-53、AC-63
  **依赖**：T013、T033

- [x] **T087**：CLI既有入口回归适配
  **类型**：测试；**文件**：`src/bisheng-cli/tests/test_cli.py`
  **逻辑/验收**：显式新版init参数和旧项目兼容，保留CLI原有参数/分发行为；完整383项回归。
  **覆盖 AC**：AC-11、AC-13、AC-17、AC-60
  **依赖**：T017

- [x] **T088**：CLI命令分发接线
  **类型**：实现；**文件**：`src/bisheng-cli/bisheng_cli/cli.py`、`src/bisheng-cli/bisheng_cli/main.py`
  **逻辑/验收**：将init新版运行描述接入真实CLI入口；不重写已有manifest，不改变普通deploy鉴权。
  **覆盖 AC**：AC-11、AC-13、AC-17、AC-60
  **依赖**：T019、T087

- [x] **T089**：旧策略文件范围标识
  **类型**：文档；**文件**：`src/runtime-manager/runtime_manager/egress.py`
  **逻辑/验收**：仅明确本地policy文件属于protocol1兼容路径，protocol2采用平台只读缓存，不改变旧策略算法。
  **覆盖 AC**：AC-49、AC-50
  **依赖**：T039

## 交付门

未执行的真实运行不得用mock、skip或文档代替；DM8按用户确认的静态审查口径处理，实测留中央回归。前端lint和两项backend权限基线失败单独记录，不能宣称全仓绿灯。

真实 SQL 补充验收：T005 增加 opt-in 专用库用例；MySQL 同步竞争曾暴露重复键快照读与首次归属间隙锁两项缺陷，修复后通过。仅MySQL实测，DM8及平台完整 E2E 不因此勾选。

### Wave 2026-10-21：多租户启动验收修复

- [x] **T090**：后台租户上下文执行边界
  **类型**：实现；**文件**：`src/backend/bisheng/core/context/tenant.py`、`src/backend/test/tenant/test_tenant_execution_scope.py`
  **逻辑/验收**：绑定已验证目标租户，临时收窄visible set并清除继承的admin override/bypass，嵌套、异常和并发均恢复原上下文。组合回归56 passed；109全新multi_tenant.enabled=true启动与真实首管理员注册通过。
  **覆盖 AC**：AC-61、AC-62
  **依赖**：无

- [x] **T091**：系统资源启动投影租户绑定
  **类型**：实现；**文件**：`src/backend/bisheng/permission/application/system_resource_reconcile.py`、`src/backend/test/permission/test_f048_system_resource_reconcile.py`
  **逻辑/验收**：每个系统资源投影使用其可信tenant_id执行，保留原权限授权入口，不以全局bypass规避过滤。组合回归56 passed；109全新multi_tenant.enabled=true启动与真实首管理员注册通过。
  **覆盖 AC**：AC-61、AC-62
  **依赖**：T090

- [x] **T092**：首次管理员仪表盘投影上下文
  **类型**：实现；**文件**：`src/backend/bisheng/api/services/f048_preset_dashboard_bootstrap.py`、`src/backend/test/permission/test_f048_preset_dashboard_bootstrap.py`
  **逻辑/验收**：首次自然注册及启动对账的预置dashboard owner投影显式绑定Root租户；已有owner与投影的幂等逻辑保持。组合回归56 passed；109全新multi_tenant.enabled=true启动与真实首管理员注册通过。
  **覆盖 AC**：AC-61、AC-62
  **依赖**：T090

通用 F048 启动修复已按授权先进入 release line `9d156f261c`，F059 经 `98fbba032` 正常继承；本次只收回 F086 的历史文档/证据，不覆盖后续公共代码。spec/design 业务决策未偏离。

### Wave 2026-10-21：DM8静态审查与字节边界

- [x] **T093**：字节计数范围与模型规范检查
  **类型**：实现；**文件**：`src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py`、`src/backend/test/app_runtime/test_runtime_model_contracts.py`
  **逻辑/验收**：size_bytes和offset使用BigInteger，覆盖15表JsonType/时间默认/租户/唯一约束和索引静态检查，符合2GiB材料和10GiB快照合同；DM8不连接。
  **覆盖 AC**：AC-06、AC-35、AC-61
  **依赖**：T001

- [x] **T094**：已有运行时字节字段扩容迁移
  **类型**：基础设施；**文件**：`src/backend/bisheng/core/database/alembic/versions/f086_runtime_byte_counters.py`、`src/backend/test/app_runtime/test_runtime_model_contracts.py`
  **逻辑/验收**：挂接已核对single head merge_vibe_f077_heads，DDL-only INTEGER到BIGINT；新库/已扩容跳过，异常类型失败，降级保留宽列；组合28项回归通过。
  **覆盖 AC**：AC-06、AC-35、AC-61
  **依赖**：T093

2026-10-23 开发整合：F086 实现与证据已与 F059 汇合；92/94 不变，T055/T056 的完整离线/剩余故障/最终交付门仍 pending。当前七维开发合入审查已完成（code-review.md），旧审查归档为 code-review-2026-10-21.md。用户明确授权先合入 feat/3.0.0-vibe 并推送；此授权不表示全 AC 或当前版本正式镜像发行完成。
