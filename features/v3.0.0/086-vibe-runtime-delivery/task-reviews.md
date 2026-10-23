# F086 Task Review（L1）

同一代理按 task-review 检查，非独立评审。86/89项达到本地合同或原生容器验证；尚余T053、T055、T056。勾选不代表对应全部AC已取得平台部署证明。上述统计为2026-10-20验收快照，当时未暂存、提交、推送或合并。2026-10-21用户授权先提交并推送当前阶段成果，未完成验收项继续保留。

## 当前证据

- backend：1214 passed，2 failed，24 skipped。
- manager：437 passed，0 failed，10 skipped。
- app_proxy：256 passed，0 failed，0 skipped。
- cli：383 passed，0 failed，0 skipped。
- sdk：212 passed，0 failed，0 skipped。
- dev_toolkit（锁定依赖Docker）：129 passed。

backend 两项失败在未改基线复现；frontend lint 95错误/1警告的归一化输出与基线完全相同。frontend typecheck、i18n、变更Python Ruff/arch-guard、Compose合同与CLI干净安装通过。真实Engine、双原生架构、离线准备/补包、MySQL同步竞争和Docker主链路均已验证；DM8、新装多租户、完整故障/升级和正式发行仍待验证。详见[live-validation.md](./live-validation.md)。

## 按任务

### T001 平台持久对象模型

- 文件：[runtime_delivery.py](../../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-15、AC-19、AC-35、AC-36、AC-50、AC-61。

### T002 模型发现注册

- 文件：[tenant_filter.py](../../../src/backend/bisheng/core/database/tenant_filter.py)、[__init__.py](../../../src/backend/bisheng/app_runtime/domain/models/__init__.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-14、AC-30、AC-50、AC-61。

### T003 平台运行交付配置

- 文件：[app_runtime.py](../../../src/backend/bisheng/core/config/app_runtime.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-03、AC-05、AC-53、AC-58。

### T004 manager执行配置

- 文件：[config.py](../../../src/runtime-manager/runtime_manager/config.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-04、AC-22、AC-53、AC-57、AC-58、AC-63。

### T005 平台操作/容量Repository合同与失败测试

- 文件：[test_runtime_delivery_repository.py](../../../src/backend/test/app_runtime/test_runtime_delivery_repository.py)、[test_runtime_delivery_database.py](../../../src/backend/test/app_runtime/test_runtime_delivery_database.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：Repository本地21项回归、真实MySQL同步竞争5项通过；DM8原先待环境；用户2026-10-21确认本轮只做模型静态审查，已通过，实测留中央回归。
- AC：AC-06、AC-34、AC-35、AC-36、AC-37、AC-39、AC-50、AC-61、AC-63。

### T006 平台操作/容量Repository

- 文件：[runtime_delivery_repository.py](../../../src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：Repository本地21项回归、真实MySQL同步竞争5项通过；DM8原先待环境；用户2026-10-21确认本轮只做模型静态审查，已通过，实测留中央回归。
- AC：AC-06、AC-34、AC-35、AC-36、AC-37、AC-39、AC-50、AC-61、AC-63。

### T007 版本2服务身份与重放保护合同与失败测试

- 文件：[test_runtime_protocol_v2.py](../../../src/backend/test/app_runtime/test_runtime_protocol_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-07、AC-49、AC-52、AC-53。

### T008 版本2服务身份与重放保护

- 文件：[runtime_protocol.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_protocol.py)、[platform_protocol.py](../../../src/runtime-manager/runtime_manager/platform_protocol.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-07、AC-49、AC-52、AC-53。

### T009 平台产物传输合同与失败测试

- 文件：[test_runtime_artifacts.py](../../../src/backend/test/app_runtime/test_runtime_artifacts.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-05、AC-06、AC-07、AC-10、AC-19、AC-23、AC-28、AC-42、AC-43、AC-53。

### T010 平台产物传输

- 文件：[runtime_artifact_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_artifact_service.py)、[runtime_object_store.py](../../../src/backend/bisheng/app_runtime/domain/repositories/runtime_object_store.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-05、AC-06、AC-07、AC-10、AC-19、AC-23、AC-28、AC-42、AC-43、AC-53。

### T011 环境目录和授权边界合同与失败测试

- 文件：[test_runtime_profiles.py](../../../src/backend/test/app_runtime/test_runtime_profiles.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-11、AC-12、AC-14、AC-15、AC-16、AC-17、AC-21、AC-24、AC-30、AC-31、AC-55、AC-56、AC-57、AC-59。

### T012 环境目录和授权边界

- 文件：[runtime_profile_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_profile_service.py)、[runtime_delivery.py](../../../src/backend/bisheng/app_runtime/domain/schemas/runtime_delivery.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-11、AC-12、AC-14、AC-15、AC-16、AC-17、AC-21、AC-24、AC-30、AC-31、AC-55、AC-56、AC-57、AC-59。

### T013 内部操作与投影API合同与失败测试

- 文件：[test_runtime_delivery_api.py](../../../src/backend/test/app_runtime/test_runtime_delivery_api.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-34、AC-35、AC-36、AC-37、AC-48、AC-49、AC-50、AC-53。

### T014 内部操作与投影API

- 文件：[runtime_delivery.py](../../../src/backend/bisheng/app_runtime/api/endpoints/runtime_delivery.py)、[router.py](../../../src/backend/bisheng/app_runtime/api/router.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-34、AC-35、AC-36、AC-37、AC-48、AC-49、AC-50、AC-53。

### T015 backend附件SDK兼容合同与失败测试

- 文件：[test_runtime_storage_api.py](../../../src/backend/test/app_runtime/test_runtime_storage_api.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-05、AC-08、AC-09、AC-10、AC-38、AC-39、AC-51、AC-53、AC-60。

### T016 backend附件SDK兼容

- 文件：[app_storage_service.py](../../../src/backend/bisheng/app_runtime/domain/services/app_storage_service.py)、[app_storage.py](../../../src/backend/bisheng/app_runtime/api/endpoints/app_storage.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-05、AC-08、AC-09、AC-10、AC-38、AC-39、AC-51、AC-53、AC-60。

### T017 新版清单与旧模式兼容合同与失败测试

- 文件：[test_manifest_delivery_v2.py](../../../src/backend/test/app_publish/test_manifest_delivery_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-11、AC-12、AC-13、AC-17、AC-18、AC-25、AC-33、AC-60。

### T018 新版清单与旧模式兼容

- 文件：[app_manifest.py](../../../src/backend/bisheng/app_publish/domain/schemas/app_manifest.py)、[manifest_validator.py](../../../src/backend/bisheng/app_publish/domain/services/manifest_validator.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-11、AC-12、AC-13、AC-17、AC-18、AC-25、AC-33、AC-60。

### T019 CLI应用包交付合同与失败测试

- 文件：[test_delivery_v2.py](../../../src/bisheng-cli/tests/test_delivery_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-07、AC-11、AC-13、AC-17、AC-25、AC-60。

### T020 CLI应用包交付

- 文件：[project.py](../../../src/bisheng-cli/bisheng_cli/project.py)、[packaging.py](../../../src/bisheng-cli/bisheng_cli/packaging.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-07、AC-11、AC-13、AC-17、AC-25、AC-60。

### T021 manager平台内容客户端合同与失败测试

- 文件：[test_platform_client_v2.py](../../../src/runtime-manager/tests/test_platform_client_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-05、AC-06、AC-07、AC-23、AC-36、AC-42、AC-43、AC-53。

### T022 manager平台内容客户端

- 文件：[platform_client.py](../../../src/runtime-manager/runtime_manager/platform_client.py)、[operations.py](../../../src/runtime-manager/runtime_manager/api/operations.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-05、AC-06、AC-07、AC-23、AC-36、AC-42、AC-43、AC-53。

### T023 Python与Node准备和复用合同与失败测试

- 文件：[test_bundle_preparer.py](../../../src/runtime-manager/tests/test_bundle_preparer.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-59。

### T024 Python与Node准备和复用

- 文件：[bundle_preparer.py](../../../src/runtime-manager/runtime_manager/bundle_preparer.py)、[bundle_inputs.py](../../../src/runtime-manager/runtime_manager/bundle_inputs.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-59。

### T025 bundle与完整镜像启动合同与失败测试

- 文件：[test_bundle_launch.py](../../../src/runtime-manager/tests/test_bundle_launch.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-11、AC-12、AC-17、AC-18、AC-22、AC-41、AC-46、AC-52、AC-56、AC-57、AC-58。

### T026 bundle与完整镜像启动

- 文件：[bundle_launch.py](../../../src/runtime-manager/runtime_manager/bundle_launch.py)、[docker_backend.py](../../../src/runtime-manager/runtime_manager/docker_backend.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-11、AC-12、AC-17、AC-18、AC-22、AC-41、AC-46、AC-52、AC-56、AC-57、AC-58。

### T027 manager操作所有权和回收合同与失败测试

- 文件：[test_operations_v2.py](../../../src/runtime-manager/tests/test_operations_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-26、AC-34、AC-35、AC-36、AC-37、AC-39、AC-40、AC-50、AC-63。

### T028 manager操作所有权和回收

- 文件：[operations.py](../../../src/runtime-manager/runtime_manager/operations.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-26、AC-34、AC-35、AC-36、AC-37、AC-39、AC-40、AC-50、AC-63。

### T029 SQLite平台快照与owner恢复合同与失败测试

- 文件：[test_platform_appdb.py](../../../src/runtime-manager/tests/test_platform_appdb.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-05、AC-35、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47。

### T030 SQLite平台快照与owner恢复

- 文件：[appdb.py](../../../src/runtime-manager/runtime_manager/appdb.py)、[platform_appdb.py](../../../src/runtime-manager/runtime_manager/platform_appdb.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-05、AC-35、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47。

### T031 F055交付准备接线合同与失败测试

- 文件：[test_delivery_pipeline_v2.py](../../../src/backend/test/app_publish/test_delivery_pipeline_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-11、AC-12、AC-13、AC-19、AC-29、AC-32、AC-33。

### T032 F055交付准备接线

- 文件：[publish_pipeline_service.py](../../../src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-11、AC-12、AC-13、AC-19、AC-29、AC-32、AC-33。

### T033 版本冻结与凭据代际合同与失败测试

- 文件：[test_runtime_lifecycle_v2.py](../../../src/backend/test/app_runtime/test_runtime_lifecycle_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-15、AC-16、AC-19、AC-33、AC-36、AC-38、AC-51、AC-57、AC-60。

### T034 版本冻结与凭据代际

- 文件：[version_service.py](../../../src/backend/bisheng/app_publish/domain/services/version_service.py)、[app_credential_service.py](../../../src/backend/bisheng/app_publish/domain/services/app_credential_service.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-15、AC-16、AC-19、AC-33、AC-36、AC-38、AC-51、AC-57、AC-60。

### T035 F054/F055安全上线合同与失败测试

- 文件：[test_runtime_lifecycle_v2.py](../../../src/backend/test/app_runtime/test_runtime_lifecycle_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-02、AC-09、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-46。

### T036 F054/F055安全上线

- 文件：[publish_online_service.py](../../../src/backend/bisheng/app_publish/domain/services/publish_online_service.py)、[app_state_service.py](../../../src/backend/bisheng/app_runtime/domain/services/app_state_service.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-02、AC-09、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-46。

### T037 入口读取平台路由合同与失败测试

- 文件：[test_platform_route_v2.py](../../../src/app-proxy/tests/test_platform_route_v2.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-04、AC-18、AC-39、AC-48、AC-49、AC-50、AC-51、AC-53。

### T038 入口读取平台路由

- 文件：[clients.py](../../../src/app-proxy/app_proxy/clients.py)、[config.py](../../../src/app-proxy/app_proxy/config.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-04、AC-18、AC-39、AC-48、AC-49、AC-50、AC-51、AC-53。

### T039 出口读取平台策略合同与失败测试

- 文件：[test_platform_egress.py](../../../src/runtime-manager/tests/test_platform_egress.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-04、AC-39、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53。

### T040 出口读取平台策略

- 文件：[egress_proxy.py](../../../src/runtime-manager/runtime_manager/egress_proxy.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-04、AC-39、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53。

### T041 环境导入及owner维护API合同与失败测试

- 文件：[test_runtime_management_api.py](../../../src/backend/test/app_runtime/test_runtime_management_api.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-14、AC-15、AC-24、AC-28、AC-30、AC-35、AC-45、AC-47、AC-53。

### T042 环境导入及owner维护API

- 文件：[runtime_management.py](../../../src/backend/bisheng/app_runtime/api/endpoints/runtime_management.py)、[runtime_management_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_management_service.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-14、AC-15、AC-24、AC-28、AC-30、AC-35、AC-45、AC-47、AC-53。

### T043 离线制作与环境工具合同与失败测试

- 文件：[test_offline_materials.py](../../../src/runtime-manager/tests/test_offline_materials.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-14、AC-15、AC-27、AC-28、AC-29、AC-30、AC-31、AC-55、AC-56、AC-58、AC-59。

### T044 离线制作与环境工具

- 文件：[runtime_materials.py](../../../src/runtime-manager/tools/runtime_materials.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-14、AC-15、AC-27、AC-28、AC-29、AC-30、AC-31、AC-55、AC-56、AC-58、AC-59。

### T045 存量迁移与发布物兼容合同与失败测试

- 文件：[test_runtime_upgrade.py](../../../src/backend/test/app_runtime/test_runtime_upgrade.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-03、AC-08、AC-10、AC-13、AC-46、AC-57、AC-60。

### T046 存量迁移与发布物兼容

- 文件：[upgrade_vibe_runtime.py](../../../src/backend/scripts/upgrade_vibe_runtime.py)、[README.md](../../../src/backend/scripts/README.md)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-03、AC-08、AC-10、AC-13、AC-46、AC-57、AC-60。

### T047 镜像和Compose发行合同测试

- 文件：[test_delivery_images.py](../../../src/runtime-manager/tests/test_delivery_images.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-01、AC-03、AC-04、AC-05、AC-54、AC-55、AC-56、AC-57、AC-58。

### T048 manager与入口预构建镜像

- 文件：[Dockerfile](../../../src/runtime-manager/Dockerfile)、[Dockerfile](../../../src/app-proxy/Dockerfile)
- 结果：双架构原生构建/对应容器场景通过；正式CI发行独立受T053控制。
- 证据：[真实部署记录](./live-validation.md)，两侧各五项禁网容器场景；对应日志和镜像事实已归档。
- AC：AC-01、AC-04、AC-05、AC-54、AC-55、AC-57。

### T049 python3.11运行/准备镜像

- 文件：[Dockerfile](../../../src/app-runtime/python3.11/Dockerfile)、[requirements.txt](../../../src/app-runtime/python3.11/requirements.txt)
- 结果：双架构原生构建/对应容器场景通过；正式CI发行独立受T053控制。
- 证据：[真实部署记录](./live-validation.md)，两侧各五项禁网容器场景；对应日志和镜像事实已归档。
- AC：AC-11、AC-17、AC-22、AC-25、AC-31、AC-54、AC-55、AC-59。

### T050 node20运行/准备镜像

- 文件：[Dockerfile](../../../src/app-runtime/node20/Dockerfile)
- 结果：双架构原生构建/对应容器场景通过；正式CI发行独立受T053控制。
- 证据：[真实部署记录](./live-validation.md)，两侧各五项禁网容器场景；对应日志和镜像事实已归档。
- AC：AC-11、AC-17、AC-22、AC-25、AC-31、AC-54、AC-55、AC-59。

### T051 static运行/准备镜像

- 文件：[Dockerfile](../../../src/app-runtime/static/Dockerfile)、[entrypoint.sh](../../../src/app-runtime/static/entrypoint.sh)
- 结果：双架构原生构建/对应容器场景通过；正式CI发行独立受T053控制。
- 证据：[真实部署记录](./live-validation.md)，两侧各五项禁网容器场景；对应日志和镜像事实已归档。
- AC：AC-11、AC-17、AC-22、AC-25、AC-31、AC-54、AC-55、AC-59。

### T052 Compose与安装检查

- 文件：[docker-compose.yml](../../../docker/docker-compose.yml)、[verify_app_runtime_compose.py](../../../docker/verify_app_runtime_compose.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-01、AC-03、AC-04、AC-05、AC-18、AC-52、AC-54、AC-56、AC-58。

### T053 CI/Release双架构交付

- 文件：[runtime-images.yml](../../../.github/workflows/runtime-images.yml)
- 结果：未完成。本地双原生验证通过，GitHub工作流/不可覆盖发布/官方目录未实际发行。
- 证据：[真实部署记录及剩余门](./live-validation.md)、validation.json；未完成项不能用skip或本地测试替代。
- AC：AC-54、AC-55、AC-56、AC-57。

### T054 CLI可分发wheel及锁定依赖

- 文件：[bisheng_cli-3.0.0-py3-none-any.whl](../../../src/backend/bisheng/dev_toolkit/artifacts/bisheng_cli-3.0.0-py3-none-any.whl)、[manifest.json](../../../src/backend/bisheng/dev_toolkit/artifacts/manifest.json)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-05、AC-13、AC-54、AC-60。

### T055 API E2E与故障证据

- 文件：[test_e2e_f086_runtime_delivery.py](../../../src/backend/test/e2e/test_e2e_f086_runtime_delivery.py)、[e2e-checklist.md](../../../features/v3.0.0/086-vibe-runtime-delivery/e2e-checklist.md)
- 结果：未完成。Docker核心旅程通过；DM8、多租户和完整故障/升级验收未完成。
- 证据：[真实部署记录及剩余门](./live-validation.md)、validation.json；未完成项不能用skip或本地测试替代。
- AC：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59、AC-60、AC-61、AC-62、AC-63。

### T056 最终审查和证据汇总

- 文件：[task-reviews.md](../../../features/v3.0.0/086-vibe-runtime-delivery/task-reviews.md)、[validation.json](../../../features/v3.0.0/086-vibe-runtime-delivery/validation.json)
- 结果：未完成。运行及发行门未关闭，最终审查保持NEEDS_FIX。
- 证据：[真实部署记录及剩余门](./live-validation.md)、validation.json；未完成项不能用skip或本地测试替代。
- AC：AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59、AC-60、AC-61、AC-62、AC-63。

### T057 准备执行器与旧模板适配

- 文件：[container_runner.py](../../../src/runtime-manager/runtime_manager/container_runner.py)、[legacy_prepare.py](../../../src/runtime-manager/runtime_manager/legacy_prepare.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-11、AC-13、AC-19、AC-26、AC-53、AC-63。

### T058 发布交付协调器

- 文件：[runtime_delivery_coordinator.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-05、AC-15、AC-33、AC-37、AC-39、AC-41、AC-63。

### T059 凭据保护与执行代际读取

- 文件：[runtime_payload.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_payload.py)、[runtime_credential_repository.py](../../../src/backend/bisheng/app_runtime/domain/repositories/runtime_credential_repository.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-39、AC-51、AC-53。

### T060 路由和出站投影业务

- 文件：[runtime_projection_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_projection_service.py)、[runtime_egress_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_egress_service.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-39、AC-48、AC-49、AC-50、AC-51、AC-53。

### T061 存量与离线内容校验业务

- 文件：[runtime_upgrade_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_upgrade_service.py)、[runtime_offline_package.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_offline_package.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-07、AC-13、AC-27、AC-30、AC-46、AC-57、AC-60。

### T062 控制客户端与范围回收

- 文件：[runtime_control_client.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_control_client.py)、[runtime_cleanup_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_cleanup_service.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-09、AC-10、AC-26、AC-63。

### T063 manager启动和旧协议拒绝

- 文件：[main.py](../../../src/runtime-manager/runtime_manager/main.py)、[auth.py](../../../src/runtime-manager/runtime_manager/auth.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-04、AC-06、AC-48、AC-53、AC-58。

### T064 SQLite数据容器合同测试

- 文件：[test_data_executor.py](../../../src/runtime-manager/tests/test_data_executor.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-47、AC-52、AC-53。

### T065 受控数据执行API

- 文件：[platform_data.py](../../../src/runtime-manager/runtime_manager/api/platform_data.py)、[data_executor.py](../../../src/runtime-manager/runtime_manager/data_executor.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-47、AC-52、AC-53。

### T066 单应用数据入口与只读观测

- 文件：[data_worker.py](../../../src/runtime-manager/runtime_manager/data_worker.py)、[platform_observe.py](../../../src/runtime-manager/runtime_manager/api/platform_observe.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-47、AC-48、AC-50、AC-53。

### T067 旧运行绑定只读inventory

- 文件：[upgrade.py](../../../src/runtime-manager/runtime_manager/api/upgrade.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-13、AC-46、AC-57、AC-60。

### T068 出口平台策略缓存适配

- 文件：[platform_egress.py](../../../src/runtime-manager/runtime_manager/platform_egress.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-49、AC-50、AC-52。

### T069 入口协议与运行接线

- 文件：[platform_protocol.py](../../../src/app-proxy/app_proxy/platform_protocol.py)、[main.py](../../../src/app-proxy/app_proxy/main.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-48、AC-49、AC-53。

### T070 审批预览与授权接线

- 文件：[preview_instance_service.py](../../../src/backend/bisheng/app_publish/domain/services/preview_instance_service.py)、[entry_authz_service.py](../../../src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-09、AC-33、AC-48、AC-51。

### T071 SDK中间件与创建入口约束

- 文件：[http_middleware.py](../../../src/backend/bisheng/utils/http_middleware.py)、[test_runtime_layer_switch.py](../../../src/backend/test/app_runtime/test_runtime_layer_switch.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-05、AC-07、AC-53、AC-60。

### T072 离线与owner业务测试

- 文件：[test_runtime_management.py](../../../src/backend/test/app_runtime/test_runtime_management.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-07、AC-14、AC-15、AC-30、AC-45、AC-53。

### T073 数据恢复审计登记

- 文件：[audit_log.py](../../../src/backend/bisheng/database/models/audit_log.py)、[constants.py](../../../src/backend/bisheng/app_runtime/domain/constants.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-45、AC-47。

### T074 Platform审计筛选接线

- 文件：[log.ts](../../../src/frontend/platform/src/controllers/API/log.ts)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：冻结锁依赖typecheck及i18n；全量lint基线失败，动作字典与原审计白名单定向核对。
- AC：AC-47。

### T075 审计三语文案第一组

- 文件：[bs.json](../../../src/frontend/platform/public/locales/en-US/bs.json)、[bs.json](../../../src/frontend/platform/public/locales/zh-Hans/bs.json)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：冻结锁依赖typecheck及i18n；全量lint基线失败，动作字典与原审计白名单定向核对。
- AC：AC-47。

### T076 审计三语文案日语

- 文件：[bs.json](../../../src/frontend/platform/public/locales/ja/bs.json)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：冻结锁依赖typecheck及i18n；全量lint基线失败，动作字典与原审计白名单定向核对。
- AC：AC-47。

### T077 原生镜像构建与容器烟测

- 文件：[build_runtime_images.sh](../../../scripts/build_runtime_images.sh)、[smoke_runtime_delivery.py](../../../scripts/smoke_runtime_delivery.py)
- 结果：双架构原生构建/对应容器场景通过；正式CI发行独立受T053控制。
- 证据：[真实部署记录](./live-validation.md)，两侧各五项禁网容器场景；对应日志和镜像事实已归档。
- AC：AC-11、AC-19、AC-20、AC-31、AC-41、AC-54、AC-55、AC-56。

### T078 镜像内统一准备器

- 文件：[prepare.py](../../../src/app-runtime/common/prepare.py)
- 结果：双架构原生构建/对应容器场景通过；正式CI发行独立受T053控制。
- 证据：[真实部署记录](./live-validation.md)，两侧各五项禁网容器场景；对应日志和镜像事实已归档。
- AC：AC-19、AC-21、AC-24、AC-25、AC-27、AC-28、AC-29、AC-53。

### T079 static无root入口配置

- 文件：[nginx.conf](../../../src/app-runtime/static/nginx.conf)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-11、AC-17、AC-25、AC-54。

### T080 独立开发构建覆盖

- 文件：[docker-compose.runtime-dev.yml](../../../docker/docker-compose.runtime-dev.yml)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-54、AC-58。

### T081 安装环境与校验脚本

- 文件：[.env.example](../../../docker/.env.example)、[verify-app-runtime-compose.sh](../../../docker/verify-app-runtime-compose.sh)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-03、AC-04、AC-53、AC-58。

### T082 manager冻结依赖合同

- 文件：[pyproject.toml](../../../src/runtime-manager/pyproject.toml)、[uv.lock](../../../src/runtime-manager/uv.lock)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-04、AC-05、AC-54、AC-57。

### T083 安装维护文档

- 文件：[OPERATIONS.md](../../../src/runtime-manager/OPERATIONS.md)、[14-app-factory-deployment.md](../../../docs/architecture/14-app-factory-deployment.md)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：接口/字段/目录按工作树同步，输入评审文档哈希保持。
- AC：AC-03、AC-27、AC-28、AC-45、AC-46、AC-54、AC-57、AC-58、AC-59、AC-62。

### T084 CLI及版本交付登记

- 文件：[README.md](../../../src/bisheng-cli/README.md)、[release-contract.md](../../../features/v3.0.0/release-contract.md)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：接口/字段/目录按工作树同步，输入评审文档哈希保持。
- AC：AC-13、AC-30、AC-54、AC-58、AC-60、AC-62。

### T085 离线补包入口流式代理

- 文件：[default.conf](../../../docker/nginx/conf.d/default.conf)
- 结果：双架构原生构建/对应容器场景通过；正式CI发行独立受T053控制。
- 证据：[真实部署记录](./live-validation.md)，两侧各五项禁网容器场景；对应日志和镜像事实已归档。
- AC：AC-05、AC-07、AC-27、AC-28、AC-58。

### T086 平台执行事实与旧RPC适配

- 文件：[runtime_operation_service.py](../../../src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py)、[orchestrator_client.py](../../../src/backend/bisheng/app_runtime/domain/services/orchestrator_client.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：backend 真SQL/服务/ASGI合同与既有发布回归。
- AC：AC-06、AC-29、AC-35、AC-36、AC-37、AC-48、AC-50、AC-53、AC-63。

### T087 CLI既有入口回归适配

- 文件：[test_cli.py](../../../src/bisheng-cli/tests/test_cli.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-11、AC-13、AC-17、AC-60。

### T088 CLI命令分发接线

- 文件：[cli.py](../../../src/bisheng-cli/bisheng_cli/cli.py)、[main.py](../../../src/bisheng-cli/bisheng_cli/main.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：独立进程单元/合同或配置静态检查。
- AC：AC-11、AC-13、AC-17、AC-60。

### T089 旧策略文件范围标识

- 文件：[egress.py](../../../src/runtime-manager/runtime_manager/egress.py)
- 结果：本地任务合同完成；运行边界见验证汇总。
- 证据：接口/字段/目录按工作树同步，输入评审文档哈希保持。
- AC：AC-49、AC-50。

## 2026-10-21 多租户启动增量审查

### T090 后台租户上下文执行边界

- 范围：`src/backend/bisheng/core/context/tenant.py`、`src/backend/test/tenant/test_tenant_execution_scope.py`。
- AC：AC-61、AC-62。
- L1：PASS；绑定已验证目标租户，临时收窄visible set并清除继承的admin override/bypass，嵌套、异常和并发均恢复原上下文。
- 证据：修复前新增回归3 failed/7 passed，修复后包含租户过滤/owner投影的组合回归56 passed；六个Python文件Ruff与arch-guard通过。109真实新库多租户启动初始化18项系统资源，首管理员注册成功。

### T091 系统资源启动投影租户绑定

- 范围：`src/backend/bisheng/permission/application/system_resource_reconcile.py`、`src/backend/test/permission/test_f048_system_resource_reconcile.py`。
- AC：AC-61、AC-62。
- L1：PASS；每个系统资源投影使用其可信tenant_id执行，保留原权限授权入口，不以全局bypass规避过滤。
- 证据：修复前新增回归3 failed/7 passed，修复后包含租户过滤/owner投影的组合回归56 passed；六个Python文件Ruff与arch-guard通过。109真实新库多租户启动初始化18项系统资源，首管理员注册成功。

### T092 首次管理员仪表盘投影上下文

- 范围：`src/backend/bisheng/api/services/f048_preset_dashboard_bootstrap.py`、`src/backend/test/permission/test_f048_preset_dashboard_bootstrap.py`。
- AC：AC-61、AC-62。
- L1：PASS；首次自然注册及启动对账的预置dashboard owner投影显式绑定Root租户；已有owner与投影的幂等逻辑保持。
- 证据：修复前新增回归3 failed/7 passed，修复后包含租户过滤/owner投影的组合回归56 passed；六个Python文件Ruff与arch-guard通过。109真实新库多租户启动初始化18项系统资源，首管理员注册成功。

该次审查只覆盖新增修复；T053、T055、T056仍开放，不据此宣称全Feature可合并。

## 模型静态审查增量（用户确认DM8实测暂缓）

### T093 字节计数范围与模型规范检查

- L1：PASS；size_bytes和offset使用BigInteger，覆盖15表JsonType/时间默认/租户/唯一约束和索引静态检查，符合2GiB材料和10GiB快照合同；DM8不连接。
- 文件：`src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py`、`src/backend/test/app_runtime/test_runtime_model_contracts.py`。
- AC：AC-6、AC-35、AC-61。
- 证据：model-review.md / model-review.json / model-review-tests.txt；没有连接真实DM8或执行新revision的真实升级。

### T094 已有运行时字节字段扩容迁移

- L1：PASS；挂接已核对single head merge_vibe_f077_heads，DDL-only INTEGER到BIGINT；新库/已扩容跳过，异常类型失败，降级保留宽列；组合28项回归通过。
- 文件：`src/backend/bisheng/core/database/alembic/versions/f086_runtime_byte_counters.py`、`src/backend/test/app_runtime/test_runtime_model_contracts.py`。
- AC：AC-6、AC-35、AC-61。
- 证据：model-review.md / model-review.json / model-review-tests.txt；没有连接真实DM8或执行新revision的真实升级。

## 2026-10-21 测试发行增量审查：T053 / T077

- L1：PASS，同一代理复核，无独立代理评审。范围仅.github/workflows/runtime-images.yml与scripts/build_runtime_images.sh两处grep替换，commit 755d4456e5；无服务接口/权限/数据模型变更。分层、数据库、前端约定不适用；命名、无凭据泄露、设计同步通过，前置T052/T047已完成。
- shell与YAML语法通过；真实脚本guard的缺标签/已存在/认证失败三个隔离分支通过，现有镜像合同2 passed。已有标签拒绝为本地受控Registry结果验证，未额外重跑公开发行去覆盖既有标签。
- [GitHub原生发行](https://github.com/dataelement/bisheng/actions/runs/39567381522)三job成功；两架构各7镜像、应用包原生集成、多架构服务索引和catalog成功。109公开服务镜像隔离启动/访问检查通过，原27服务容器不变，测试资源已回收。
- T053关闭；当前92/94，T055/T056仍开放。正式生产版本、完整断网新装、所有故障组合、平台目录导入不据此声称完成。证据：e2e-evidence/2026-10-21-ci-release/。

## 2026-10-23 开发整合定向复核

用户明确授权先收尾开发、合入并推送 feat/3.0.0-vibe，避免全量回归。F059 T274（infra，两文件）CI同版本跨入口并发锁：新增现有契约断言先1失败，实际key修正后1通过；Ruff/format/架构门通过。两个模型/测试冲突逐hunk保留F059后续tenant/UID语义，与原实现相同，定向模型合同17通过（DM8仅静态）。新WT配置缺失的收集错误已用现有本地测试配置解决，不记作产品失败。三条独立L2分工代码无HIGH，设计D1定向复审关闭，开发合入PASS_WITH_WARNINGS。完整交付门保持pending；无全量或远端重验。详见code-review.md与整合报告。
