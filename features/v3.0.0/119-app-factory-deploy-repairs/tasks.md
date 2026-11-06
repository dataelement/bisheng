# F119 任务

2026-11-03：用户已分别确认 discovery、42 条 spec、整份 design，授权任务拆解与开发。本清单未完成项不表示已实施。仅必要定向验证，无全量测试。

| 文档 | 状态 |
| --- | --- |
| spec.md | ✅ 用户已确认 |
| design.md | ✅ 用户已确认 |
| tasks.md | ✅ 已按 sdd-review 21 项静态自审 |

## 路径和执行约定

表中路径均相对仓库：`BE=src/backend/bisheng`、`BT=src/backend/test/app_publish`、`RM=src/runtime-manager/runtime_manager`、`RT=src/runtime-manager/tests`、`CLI=src/bisheng-cli`。后端类型分 Domain/API/Worker；运行适配器归 Domain，官方材料/制品归基础设施；本次无前端业务组件。不新建 ORM/错误码/配置，故无数据库迁移或基础设施先置依赖。

每行是独立任务，`测试→实现` 必须先写并观察失败再编码，完成后执行 task-review 并记录证据。实现依赖的测试任务完成表示测试已写/已观察基线，不表示未实现前应当通过。所有测试行逐项标注 AC。共享文件只改本任务落点，保留上游后续增强。Worker 不新增调度入口，沿用 Celery headers→ContextVar，历史 deployment 恢复租户后读冻结清单。

## Wave 1：新清单与运行契约

| 状态 | ID/类型 | 文件与自包含任务 | 依赖/配对 |
| --- | --- | --- | --- |
| [x] | T001 测试/Domain | `BT/test_manifest_intake_defaults.py`：新提交缺版本→2/bundle，显式1→source-image，存储缺版本→1；null/未知版本拒绝。覆盖 AC: AC-02, AC-03, AC-04, AC-05 | 无；T002 |
| [x] | T002 Domain | `BE/app_publish/domain/services/manifest_validator.py`：仅新提交加载字典后 setdefault 2；不改 AppManifest 存储缺省，不改 worker 历史解析 | T001 |
| [x] | T003 测试/基础设施 | `BT/test_official_deploy_contract.py`：三份官方 YAML 为2/bundle、示例写库使用注入路径，技能包默认口径一致。覆盖 AC: AC-01, AC-06, AC-35 | T001；T004/T005/T006 |
| [x] | T004 基础设施 | `BE/dev_toolkit/skills/deploy-hosting/example/bisheng-app.yaml`、`example/main.py`：显式2/bundle，缺数据库配置明确失败而非源码写库 | T003 |
| [x] | T005 基础设施 | `BE/dev_toolkit/skills/platform-wiring/example/bisheng-app.yaml`、`example-sdk/bisheng-app.yaml`：显式2/bundle，保留原能力和数据库声明 | T003 |
| [x] | T006 基础设施 | `BE/dev_toolkit/skills/deploy-hosting/SKILL.md`、`platform-wiring/SKILL.md`：新默认/历史兼容、运行变量、入口、离线精确材料，保留身份和权限红线 | T004/T005 |
| [x] | T007 测试/Domain | `RT/test_runtime_contract_environment.py`、`RT/test_bundle_launch.py`、`RT/test_k8s_delivery.py`、`src/backend/test/app_runtime/test_runtime_k8s_delivery_coordinator.py`：DB两变量一致、真实标识/序号、预览隔离、Python/Node别名，完整镜像不替换PATH。覆盖 AC: AC-06, AC-07, AC-08, AC-09, AC-10, AC-11 | 无；T008/T009/T010 |
| [x] | T008 Domain | `RM/runtime_environment.py`：纯函数生成平台保留变量与语言别名；实际预检序号未知为空，不接触凭据签发/存储 | T007 |
| [x] | T009 Domain | `RM/bundle_launch.py`、`lifecycle.py`：消费纯默认块，保留平台密钥/挂载/身份，Node bundle本地bin，完整镜像PATH原样 | T008 |
| [x] | T010 Domain | `RM/executors/kubernetes.py`、`RM/k8s_templates.py`（复用同一PATH常量）、`BE/app_runtime/domain/services/runtime_delivery_coordinator.py`：K8s同函数，coordinator固定runtime/health，已有版本序号真实，未知不冒充1 | T008 |
| [x] | T011 Domain | `BE/app_runtime/application/preview_operations.py`：预览元数据取对应版本；不改变会话/凭据原子创建和临时数据边界 | T010 |
| [x] | T012 测试/Domain | `RT/test_bundle_startup_contract.py`：显式/Procfile/Python二入口/Node全部入口及优先级、本地bin和不运行npm隐式生命周期；逃逸/错误JSON明确拒绝。覆盖 AC: AC-12, AC-13, AC-14, AC-15, AC-16 | 无；T013 |
| [x] | T013 Domain | `RM/bundle_inputs.py`：按设计入口顺序读取包内文件，不在manager执行源代码；scripts.start直接sh，main安全相对路径 | T012 |
| [x] | T014 测试/Domain | `RT/test_static_delivery_contract.py`：四目录、构建前无index允许、build输出优先、无输出拒绝、包路径逃逸。覆盖 AC: AC-17, AC-18, AC-19, AC-20 | 无；T015/T016/T017 |
| [x] | T015 Domain | `RM/static_inputs.py`、`source_facts.py`：纯选择器含built参数；不复用会写stub的inspector，兼容构建根优先 | T014 |
| [x] | T016 Domain | `RM/bundle_preparer.py`：实际构建判定在输入固定，编译后选择/验证静态根，再上传compiled产物 | T015 |
| [x] | T017 Domain | `RM/k8s_helper.py`、`oci_assembler.py`：输入标记保留built，upload时规范产物根，assembler不再误选源码入口 | T015 |

## Wave 2：诊断与权限

| 状态 | ID/类型 | 文件与自包含任务 | 依赖/配对 |
| --- | --- | --- | --- |
| [x] | T018 测试/Domain | `RT/test_startup_failure_diagnostics.py`：取输出先于清理、已知BundleInputError原因保留、未知异常不泄漏、40行/16KiB脱敏、终态重试不覆盖。覆盖 AC: AC-21, AC-22, AC-23, AC-25 | T013；T019/T020 |
| [x] | T019 Domain | `RM/bundle_launch.py`、`container_runner.py`：启动退出/超时安全收集tail，日志异常不覆盖原错，复用有界脱敏 | T018 |
| [x] | T020 Domain | `RM/operations.py`、`executors/kubernetes.py`：失败原因归类、补抓在清理前、K8s最终40行，保留旧writer/终态清理围栏 | T019 |
| [x] | T021 测试/Domain | `BT/test_runtime_public_diagnostics.py`：准备首次/重试、启动/数据/取消分类，edit门禁、app/tenant关联、查询时过期、发布单不持久化tail。覆盖 AC: AC-21, AC-22, AC-24, AC-25, AC-26 | 无；T022/T023/T024 |
| [x] | T022 Domain | `BE/app_runtime/application/publish_diagnostics.py`、`domain/services/runtime_public_diagnostics.py`：已验证业务目标和edit资格后，仅经Repository读原operation，返回期限内白名单tail；不describe/unseal | T021 |
| [x] | T023 Domain | `BE/app_runtime/domain/services/runtime_delivery_coordinator.py`、`runtime_management_service.py`、`runtime_secret_diagnostics.py`、`runtime_operation_service.py`（同目录）：kind/stage分类/到期剔除/安全镜像上下文、具体reason/hints、安全元数据；新旧prepare恢复分支错误一致 | T021 |
| [x] | T024 Domain/API | `BE/app_publish/domain/services/publish_pipeline_service.py`、`publish_status_service.py`：存储去tail、合法读取补tail，基础轮询不扩大权限，不回填历史 | T022/T023 |
| [x] | T025 测试/基础设施 | `CLI/tests/test_errors.py`：原code/reason在终端和JSON一致，旧16124提示、无日志不谎称有日志。覆盖 AC: AC-24, AC-26, AC-27 | 无；T026 |
| [x] | T026 基础设施 | `CLI/bisheng_cli/errors.py`：旧码兼容、准备/启动按真实原因显示操作建议及tail，保持退出码 | T025 |

## Wave 3：镜像准入和网络不变量

| 状态 | ID/类型 | 文件与自包含任务 | 依赖/配对 |
| --- | --- | --- | --- |
| [x] | T027 测试/Domain | `RT/test_delivery_image_preflight.py`：缺runtime在下载/构建前拒绝、preparer不替runtime、ID/架构/标签漂移、never不pull、维护前拒绝保持旧路由。覆盖 AC: AC-28, AC-29, AC-30, AC-31, AC-32 | 无；T028/T029 |
| [x] | T028 Domain | `RM/bundle_preparer.py`、`legacy_prepare.py`：按固定profile检查两种镜像；base检查早于build并以实际ID渲染FROM，保持原拉取策略 | T027 |
| [x] | T029 Domain | `RM/executors/docker.py`、`operations.py`：提供镜像复核并在maintenance/停旧writer前调用；启动仍核验，不新增backend编排权 | T028 |
| [x] | T030 测试/Domain | `RT/test_k8s_image_preflight.py`、`RT/test_kubernetes_executor.py`、`src/backend/test/app_runtime/test_runtime_image_check_policy.py`：image-check计划/模板/准入、仅registry凭据、无源码/数据、全层和架构验证、同op幂等及清理，bundle不强依赖assembler。覆盖 AC: AC-28, AC-29, AC-30, AC-31, AC-32, AC-34 | T027；T031/T032/T033/T034 |
| [x] | T031 Domain | `RM/image_check.py`、`BE/app_runtime/domain/services/runtime_image_check_policy.py`（跨进程线协议policy）：固定引用与平台、crane受控只读核验、限时有界结果，已知失败reason；不推送、不执行应用 | T030 |
| [x] | T032 Domain | `RM/k8s_templates.py`、`k8s_admission.py`、`BE/app_runtime/domain/services/runtime_kubernetes_service.py`、`runtime_egress_service.py`（同目录）：image-check目的的命令/镜像/Secret/出网/资源和无生产挂载规则 | T031 |
| [x] | T033 Domain | `RM/executors/kubernetes.py`：准备前和维护前的短时image-check，原资源意图/阶段授权/终态清理，冻结所有实际角色 | T032 |
| [x] | T034 基础设施 | `src/runtime-manager/Dockerfile.helper`、`Dockerfile.assembler`、`RT/test_image_release.py`、`scripts/build_runtime_images.sh`：复用已固定crane工具来源与license，helper加入可信检查器；不依赖额外安装物 | T031 |
| [x] | T035 测试/Domain | `RT/test_delivery_policy_invariants.py`、`src/app-proxy/tests/test_proxy.py`（5xx透传）：offline不下载、显式联网仅download、材料作用域不变、5xx透传/容量理由保持，缺包不自动改版本。覆盖 AC: AC-33, AC-34, AC-35, AC-36, AC-37, AC-40, AC-41 | T006/T029/T033 |
| [x] | T036 基础设施 | `BE/common/errcode/app_publish.py`：仅已有16227通用文案与含义一致，不新分配码，不改恢复/取消错误 | T021 |
| [x] | T037 基础设施 | `src/frontend/packages/locales/src/api_errors/{en,ja,zh-Hans}.json`：每种语言单独一次小编辑，已有16227文案同义更新；生成任务为T038 | T036 |
| [x] | T038 基础设施 | 运行既有i18n生成器，更新仅16227对应Platform/Client派生产物；不手改生成文件，执行受影响i18n检查 | T037 |

T037 三个独立语言小编辑共享同一逻辑任务；T038 为不可拆的机械生成步骤（派生文件数可能大于2），不包含新的业务逻辑。此处明确制品生成范围，避免把三语/双端更新漏成后续债务。

## Wave 4：分发、必要 E2E 与合入前评审

| 状态 | ID/类型 | 文件与自包含任务 | 依赖/配对 |
| --- | --- | --- | --- |
| [x] | T039 测试/基础设施 | `CLI/tests/test_distribution_contract.py`：wheel源码版本/metadata/hash/平台manifest一致，不覆盖SDK，安装件包含新错误行为。覆盖 AC: AC-01, AC-27 | T026；T040 |
| [x] | T040 基础设施 | CLI `pyproject.toml`、`bisheng_cli/__init__.py`递增修订版；既有pack脚本生成并检查CLI wheel/manifest，SDK内容不变 | T039 |
| [x] | T041 测试/Domain | `features/v3.0.0/119-app-factory-deploy-repairs/e2e-checklist.md`、`src/backend/test/e2e/test_e2e_f119_deploy_contract.py`（只读真实API）：Python官方示例预检→审批→写库→临时应用停启数据保留、Node和static定向主流程，核对116原服务与策略，仅专用资源；镜像烟测不冒充发布。覆盖 AC: AC-01, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-17, AC-20, AC-23, AC-24, AC-25, AC-27, AC-28, AC-30, AC-33, AC-37, AC-38, AC-39, AC-42 | Wave 1–3完成 |
| [ ] | T042 基础设施 | 本Feature `verification.md`：依e2e-test运行本地定向验证/制品检查；真实116按实际授权更新，不越权操作其它环境；记录清理和未验限制 | T040/T041 |
| [ ] | T043 基础设施 | 本Feature `code-review.md`：sdd-code-review对照spec/design/tasks，复核原Owner/权限、无迁移/重建、无遗留TODO；必要arch-guard/ruff通过后交付 | T042 |

真实 E2E 不降级为单元测试；部署提交/镜像不就绪或授权不足时明确保留待验，不伪造完成。K8s本轮只做合同测试，不宣称189已部署或验收。未授权推送、合并、平台服务替换的操作在执行前按实际会话授权处理。

## 任务计划自审

21项检查：AC-01至AC-42均有测试任务；测试先于实现；依赖均为此前任务（Wave依赖在同表展开）；任务给出路径/输入输出/边界；无新增表、无迁移回滚；共享Owner不变；无前端业务；异步只沿用现有租户上下文；无全量测试或E2E降级。T037/T038/T040仅三语/制品的机械同步步骤，已显式解释生成范围，不混入多模块业务实现。

评审输出：LGTM。每批实施后继续执行L1，不以此计划审查代替代码审查。

## 实际偏差与完成记录

2026-11-03：T001 基线观察为1失败/9通过；T002修复后同新旧清单定向共17通过，ruff通过。未改AppManifest模型缺省。L1 T001/T002 PASS，证据见 verification.md。

2026-11-03 续作：Wave 1 T003–T017 已完成并逐项L1 PASS；补充Docker/K8s实际载荷和静态准备/恢复合同测试，范围同步于表；详情见 verification.md。原测试Node PATH断言改为本地bin位于系统路径之前，保留K8s原venv/bin优先顺序。

2026-11-03 收尾：T018–T041实现与适用L1完成，累计41/43；T042的本地定向检查完成，原生服务镜像构建/发行与真实116发布E2E未执行；T043已写L2预审，因交付门未通过保留未勾。所有未提交改动留在当前独立工作区。T030/T031/T032/T034范围补记为闭合原设计要求的服务端冻结文档/出网来源验证与实际镜像工具分发，不增加新业务范围、权限动作或数据库字段。

编号：原暂用F118，因远端同版本118-project-new-chat已占用，顺延F119；规格行为与42条AC未变。

本轮用户明确要求先合并feat/3.0.0并推送远端；允许提交、整合最新发版线并推送代码，保留T042/T043待验，不包含环境服务替换。结果与整合后验证追加至verification.md。

本轮整合复核：Feature提交4a91ec61d、合并提交03d8d82c8，最新远端基线a65f130cf4；backend 167通过/3 E2E跳过、CLI100通过、manager400通过。代码按用户指令进入feat/3.0.0；T042/T043待验状态不变。
