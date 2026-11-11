# F009 实施任务

用户于2026-11-10授权按最新讨论继续。镜像构建/推送、线上部署、旧部署迁入和沙箱开启后关闭联动不在本期实施范围。

| 文档 | 状态 | 依据 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | 用户确认及后续范围收敛 |
| design.md | ✅ 已评审 | 用户授权按最新讨论更新并实施 |
| test-cases.md | ✅ 已生成 | 八列表、21个参考用例；源码部分完成，现场待执行 |
| tasks.md | ✅ 已拆解 | 源码任务完成；task-review及verification记录范围和基线失败 |

## 任务

- [x] **T001 保护基线**（基础设施）
  - 文件：src/runtime-manager/tests/test_k8s_admission.py、test_k8s_lifecycle.py。
  - 内容：使用原规则验证来源、原UID、未知状态、删除围栏；仅发现真实缺陷才改。
  - 覆盖 AC: AC-06。
  - 依赖：无。
- [x] **T002 策略配置测试**（测试）
  - 文件：src/runtime-manager/tests/test_standard_policy.py。
  - 内容：无报告、过期报告、非法策略、保护摘要不受普通资源改变、快照不可重置。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-06, AC-07, AC-16, AC-17。
  - 依赖：T001。
- [x] **T003 策略模块**（基础设施）
  - 文件：src/runtime-manager/runtime_manager/k8s_config.py、deployment_policy.py。
  - 内容：部署策略v2、诊断独立；不改Docker隔离。
  - 依赖：T002。
- [x] **T004 Manager接线**（实现）
  - 文件：src/runtime-manager/runtime_manager/executors/kubernetes.py。
  - 内容：消费合法配置、阶段参数和冻结策略，保持原UID保护。
  - 依赖：T003。
- [x] **T005 Backend信任测试**（测试）
  - 文件：src/backend/test/app_runtime/test_standard_helm_policy.py。
  - 内容：期望文件校验、报告解耦、保护历史不追认、既有入口保持。
  - 覆盖 AC: AC-01, AC-02, AC-06, AC-07, AC-17。
  - 依赖：T004。
- [x] **T006 Backend配置**（基础设施）
  - 文件：src/backend/bisheng/core/config/app_runtime.py。
  - 内容：部署期节点策略文件绑定，参数验证。
  - 依赖：T005。
- [x] **T007 Backend心跳**（实现）
  - 文件：src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py。
  - 内容：核对服务端期望策略、保护连续性与持久路由。
  - 依赖：T006。
- [x] **T008 执行规格测试**（测试）
  - 文件：src/runtime-manager/tests/test_standard_execution.py。
  - 内容：Helper额度、init有效需求、节点约束、阶段期限和存储三态。
  - 覆盖 AC: AC-16, AC-17, AC-19, AC-20, AC-23。
  - 依赖：T007。
- [x] **T009 Pod计划参数**（实现）
  - 文件：src/runtime-manager/runtime_manager/k8s_templates.py、executors/kubernetes.py。
  - 内容：Helper资源和合法placement参数；按原操作剩余deadline。
  - 依赖：T008。
- [x] **T010 资源意图对齐**（实现）
  - 文件：src/backend/bisheng/app_runtime/domain/services/runtime_kubernetes_service.py及repositories/runtime_kubernetes_repository.py。
  - 内容：预算与准入对齐冻结参数，不改应用ResourceTier权限。
  - 依赖：T009。
- [x] **T011 配置装配测试**（测试）
  - 文件：src/backend/test/core/test_deployment_renderer.py。
  - 内容：Secret投射装配、URL转义、false保留、非法输入失败且无明文日志。
  - 覆盖 AC: AC-12, AC-16, AC-18, AC-21。
  - 依赖：T010。
- [x] **T012 配置装配入口**（实现）
  - 文件：src/backend/bisheng/core/config/deployment_renderer.py。
  - 内容：正式镜像内命令读取Secret文件生成私有配置，禁止ConfigMap代码。
  - 依赖：T011。
- [x] **T013 可信种子测试**（测试）
  - 文件：src/backend/test/app_runtime/test_system_profiles.py。
  - 内容：仅可信正式catalog，system来源、缺项和冲突，默认不覆盖。
  - 覆盖 AC: AC-13, AC-14, AC-15。
  - 依赖：T012。
- [x] **T014 Profile来源迁移**（基础设施）
  - 文件：src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py、alembic迁移。
  - 内容：双DB、system无用户，不新增管理员；downgrade拒绝破坏系统引用。
  - 依赖：T013。
- [x] **T015 Profile种子**（实现）
  - 文件：src/backend/bisheng/app_runtime/domain/services/system_profile_service.py。
  - 内容：受信官方seed命令复用Repository，不开放人工API系统来源。
  - 依赖：T014。
- [x] **T016 初始化入口**（实现）
  - 文件：src/backend/scripts/standard_helm_bootstrap.py、wait_schema.py。
  - 内容：原迁移/权限初始化、实际状态等待；无总标记和claim表。
  - 依赖：T015。
- [x] **T017 密钥派生命令**（实现）
  - 文件：src/runtime-manager/runtime_manager/bootstrap_keys.py。
  - 内容：读取seed派生公钥，指定CM最小权限写入、无轮换。
  - 依赖：T016。
- [x] **T018 Chart矩阵测试**（测试）
  - 文件：scripts/tests/test_standard_helm.py。
  - 内容：默认/外部/混合、开关、双release、稳定Secret、未知组合拒绝。
  - 覆盖 AC: AC-08, AC-09, AC-10, AC-11, AC-12, AC-15, AC-16, AC-18, AC-19, AC-21, AC-22, AC-25。
  - 依赖：T017。
- [x] **T019 父Chart依赖**（基础设施）
  - 文件：docker/helm/bisheng/Chart.yaml、values.yaml。
  - 内容：固定本地子Chart、完整公开values与镜像锁定入口。
  - 依赖：T018。
- [x] **T020 平台模板**（基础设施）
  - 文件：docker/helm/bisheng/templates平台文件。
  - 内容：API/worker/linsight/beat/frontend资源、探针、调度和用途存储。
  - 依赖：T019。
- [x] **T021 依赖模板**（基础设施）
  - 文件：docker/helm/bisheng/templates基础组件文件。
  - 内容：各自可选内置/外部、专用库与有限初始化、Gateway可选。
  - 依赖：T020。
- [x] **T022 Secret模板**（基础设施）
  - 文件：docker/helm/bisheng/templates/secret.yaml。
  - 内容：owned lookup稳定保存、外部引用优先、独立随机根和TLS。
  - 依赖：T021。
- [x] **T023 Runtime命名**（基础设施）
  - 文件：deploy/kubernetes/app-runtime/templates命名与RBAC。
  - 内容：release隔离、共享控制namespace不创建/改PSA标签。
  - 依赖：T022。
- [x] **T024 Runtime配置**（基础设施）
  - 文件：deploy/kubernetes/app-runtime/templates/workloads.yaml。
  - 内容：策略/资源/timeout/probe/placement参数，诊断非启动依赖。
  - 依赖：T023。
- [x] **T025 Runtime网络存储**（基础设施）
  - 文件：deploy/kubernetes/app-runtime/templates/network.yaml、storage.yaml。
  - 内容：限定selector、稳定Service、动态CSI/静态池三态，禁止格式化。
  - 依赖：T024。
- [x] **T026 沙箱子Chart**（基础设施）
  - 文件：docker/helm/bisheng-sandbox/templates、values.yaml。
  - 内容：按release命名、逐副本DNS、默认2副本，token稳定、网络selector隔离。
  - 依赖：T025。
- [x] **T027 发行校验测试**（测试）
  - 文件：scripts/tests/test_helm_package.py。
  - 内容：无兼容digest/catalog拒绝正式打包、覆盖Job/Helper镜像、禁止假发行。
  - 覆盖 AC: AC-08, AC-14, AC-24, AC-26。
  - 依赖：T026。
- [x] **T028 发行脚本和CI**（基础设施）
  - 文件：scripts/package_helm.py、.github/workflows/helm.yml。
  - 内容：只校验源码模板与真实清单；不触发镜像build/push或部署。
  - 依赖：T027。
- [x] **T029 公开教程**（基础设施）
  - 文件：docker/helm/README.md、docker/helm/bisheng/README.md。
  - 内容：安装/外部依赖/开关/企业包源/Secret/手诊断/保留数据升级卸载；写明沙箱关闭延期。
  - 依赖：T028。
- [x] **T030 源码E2E及总复核**（测试）
  - 文件：features/v3.1.0-beta1/009-standard-helm-delivery/verification.md。
  - 内容：成对链路、全部定向回归及arch-guard，真实集群未执行明确列出。
  - 覆盖 AC: AC-05, AC-06, AC-07, AC-13, AC-20, AC-23, AC-24, AC-25, AC-26。
  - 依赖：T029。

## 实际偏差记录

- T001：现有保护/生命周期/Helm安装升级回归437通过；未修改保护逻辑。测试本机API模拟需允许loopback监听，非线上访问。
- 初始化去总完成标记/claim，旧接纳和额外代理地址冻结移除，沙箱热关闭延期：已同步design.md及用户确认记录。

- T002–T030：源码实施与定向复核见 task-review.md / code-review.md / verification.md。T030只完成本轮源码部分，未将模板或本地API回归算作真实集群E2E。
