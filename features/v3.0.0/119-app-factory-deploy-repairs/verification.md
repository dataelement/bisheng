# F119 开发与验证记录

基线：编码前快进到 `463d6fc20`，原设计基线 `78ed282c2`。用户于2026-11-03分别确认规格与设计，授权任务拆解及开发。

## 已执行

- T001：新清单/历史兼容测试，修复前1失败、9通过；失败为新输入仍缺省1。
- T002：仅新提交入口补2；`test_manifest_intake_defaults.py` 与 `test_manifest_delivery_v2.py` 共17通过；ruff通过。
- 116 Node 镜像补齐与禁网启动烟测见 environment-verification.md；本功能代码尚未更新116，真实发布E2E未执行。

## L1 task-review

| 任务 | 分层 | 命名 | 序列化 | 数据库 | 前端 | 信息泄漏 | 设计同步 | 元数据 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T001 测试 | N/A | PASS | N/A | N/A | N/A | PASS | N/A | 文件/AC对应T002 | PASS |
| T002 新输入正规化 | PASS | PASS | N/A | N/A | N/A | PASS | D1/§4.3吻合 | 配对测试/依赖/范围PASS | PASS |

## 尚未完成

真实原生服务镜像构建/发行、116部署E2E及最终L2交付门仍未完成；本地代码/CLI制品/定向质量检查和预审已完成。开发完成时未提交、推送、合入或更新116；后续按下方用户明确指令整合推送。没有全量测试。

## 2026-11-03 续作：Wave 1

- 环境变量/适配器回归：`test_runtime_contract_environment.py test_bundle_launch.py test_k8s_delivery.py test_k8s_templates.py test_lifecycle.py`：152通过、2跳过。
- 静态/入口/准备/OCI/构建：`test_static_delivery_contract.py test_k8s_helper.py test_oci_assembler.py test_bundle_startup_contract.py test_bundle_preparer.py test_build.py`：175通过、4跳过；后追加Docker四目录/构建实际准备与restore用例，静态文件单独22通过。
- OCI权限位用例在受限沙箱中有13失败；放开沙箱后175通过，确认沙箱会剥离临时文件setuid/setgid位。未删改原安全断言。
- 后端组合：新增probe元数据、F114预览事务、清单/官方示例等35通过；已有协调器文件12失败。用`git show HEAD:...runtime_delivery_coordinator.py`替换进程内协调器模块、同一选择重新运行，12失败完全重现（旧fixture缺authorization_context/预览identity，或SQLite缺关联表）。不改原资格逻辑来迎合旧fixture。
- 环境/静态测试均先观察失败：环境13失败/11通过；静态12失败/2通过；后端probe缺runtime失败后修复。
- 纯函数不签发凭据；Docker完整镜像PATH/ENTRYPOINT不变；K8s凭据仍在Secret；预览数据挂载仍隔离。静态built来源固定于原始输入，不从安装overlay重新推断。

### L1 task-review：T003–T017

表中每行分别完成目标文件读取、七项适用检查、配对/前置依赖与范围核验；无新ORM/迁移/API/权限动作。设计§4.4/4.5未偏离。

| 任务 | 架构 | 命名 | 序列化 | DB | 前端 | 泄漏 | 设计 | 元数据/结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T003 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T004 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T005 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T006 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T007 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T008 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T009 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T010 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T011 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T012 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T013 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T014 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T015 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T016 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T017 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |

任务范围补记：T007增加真实Docker/K8s载荷与backend probe测试；T010将原K8s模板硬编码PATH改为引用公共常量，模板权限合同未改变。后续完成情况与交付限制以下方最终记录为准。

## 最终本地记录（2026-11-03）

**阶段：本地开发完成，41/43；真实部署验收未完成。** 目录由临时F118顺延F119，发版线已有118-project-new-chat；原42条AC不变。当前工作区HEAD `463d6fc20`，分支 `codex/app-factory-deploy-repairs-20261103`。核对时origin/feat/3.0.0为`10a816a9a`、领先7提交；这些后续提交未合入本工作区，合入交付前需保留其增强并重核受影响文件。本功能改动仍未提交。

| 最终运行选择 | 实际结果 | 限制 |
| --- | --- | --- |
| manager环境/载荷/入口/静态/helper/OCI/诊断/操作/K8s准入/镜像发行/策略，共21个相关测试文件 | **863 passed，20 failed，6 skipped** | 19个operations_v2失败在HEAD替换模块后77通过/19失败复现；另一个K8s observe字段集合测试在HEAD相同失败。均为原基线，不删除断言或放松原权限来制造全绿。 |
| backend新清单/官方示例/安全诊断/镜像policy/跨进程wire合同/F114动作与执行授权/预览事务/K8s服务，共12个相关文件 | **167 passed，3 skipped** | 3个skip为真实E2E安全门，未部署/未提供专用身份，不能写成E2E通过。 |
| CLI错误/实际wheel分发/同步发布/轮询发布，4个文件 | **100 passed** | 测的是源码与平台实际分发的post2 wheel，未更新116平台安装件。 |
| app-proxy原状态透传扩展418/500/502/503四种 | **4 passed** | 本地HTTP/WS回声端口；不代表真实入口已验收。 |
| 原生镜像发行脚本合同与镜像检查，单独组合 | **53 passed** | mock builder与本地SQLite真实HTTP；不是Linux原生镜像build或registry真实检查。 |
| locales生成检查 + check-i18n | PASS，无新增drift | 只改16227三语源与6个生成文件，无TS/UI组件改动。 |
| 受影响Python ruff format/check + arch-guard；git diff --check | PASS | 架构守卫无输出；最终文档更新后再核对。 |

补充已有失败比较：后端旧协调器文件12失败在HEAD同选择复现；旧publish_status_service文件在含新诊断测试的相同组合中28失败亦在HEAD复现（另一个新增日志防复制测试在旧代码预期失败）。单独跑该文件时为27失败/4通过，missing-app一项受旧测试导入顺序影响；不将单跑结果当作组合全绿。旧fixture尚未按当前F114资格/事务依赖更新，且部分调用试图连接未配置的中间件。这些文件不是本轮已通过的167项选择。

### 最终manager选择

`test_runtime_contract_environment.py test_bundle_launch.py test_k8s_delivery.py test_k8s_templates.py test_lifecycle.py test_static_delivery_contract.py test_k8s_helper.py test_oci_assembler.py test_bundle_startup_contract.py test_bundle_preparer.py test_build.py test_startup_failure_diagnostics.py test_operations_v2.py test_k8s_diagnostic_contract.py test_delivery_image_preflight.py test_k8s_image_preflight.py test_kubernetes_executor.py test_k8s_admission.py test_image_release.py test_secret_redaction.py test_delivery_policy_invariants.py`

均在`src/runtime-manager`用`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest ... -q -p no:cacheprovider`运行；需要setuid/setgid及临时127.0.0.1端口的本地测试在允许这些能力后执行，未访问运行环境。

### CLI实际制品

- `bisheng_cli-3.0.0.post2-py3-none-any.whl`，SHA256 `86c75828bc21436fcb273975acedde3e49438755344a774dca8f23aca8b48871`。
- `scripts/pack_cli_wheel.sh`通过build/内容/空venv安装/import/console/help/manifest与可纳管检查；另在空venv离线安装最终wheel后，fresh login shell输出 **bisheng 3.0.0.post2**，临时环境已清理。
- SDK仍为0.1.1，SHA256 `1c1e6cc3ca5a037dc91cfc8052ce63565a31f630f0981dd0fa2b8e06b2085950`，SDK清单条目与HEAD完全相同。

### 原生镜像与真实E2E限制

本机选中orbstack context，但Docker socket不存在，无法提供任何新Linux服务镜像构建或镜像ID证据。helper现在包含项目原已固定的crane v0.22.1及其license，assembler继承helper，原生脚本增加检查器导入/工具/许可证验证；须由原生CI/构建机实际构建验证。checker采用的全层验证语义已核对[固定版本源码](https://github.com/google/go-containerregistry/blob/v0.22.1/cmd/crane/cmd/validate.go)，不使用跳过层的fast参数；真实registry成本和时延未测。

116本轮没有更新服务、profile、现有应用、出网或数据库。此前Node镜像补齐仅为历史独立环境事实。部署清单见deployment-plan.md，真实发布/审批/数据停启/清理逐项见e2e-checklist.md；T042/T043保持待验。

### L1 task-review：T018–T041

逐项读取实际目标文件并核对适用七项、配对与前置依赖；任务范围已随必要接线同步。无新ORM/迁移/业务权限动作，backend不导入编排SDK；日志不越权或延长保留期。测试行AC追溯在tasks及测试docstring。

| 任务 | 架构 | 命名 | 序列化 | DB | 前端 | 泄漏 | 设计 | 元数据/结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T018 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T019 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T020 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T021 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T022 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T023 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T024 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T025 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T026 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T027 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T028 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T029 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T030 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T031 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T032 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T033 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T034 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T035 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T036 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T037 | PASS | PASS | N/A | N/A | PASS | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T038 | PASS | PASS | N/A | N/A | PASS | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T039 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |
| T040 | PASS | PASS | N/A | N/A | N/A | PASS | PASS | 范围/配对/依赖PASS；PASS |
| T041 | N/A | PASS | N/A | N/A | N/A | N/A | N/A | 范围/配对/依赖PASS；PASS |

T041完成的是验收清单/API测试入口的编写，不是116实际E2E。T042本地验证已执行，原生镜像与真实E2E待验；T043预审见code-review.md，最终交付门未关闭。

## 本轮提交与合并

用户已明确要求“合并到feat/3.0.0分支并推送远端”。已重新fetch，整合起点为origin/feat/3.0.0 `a65f130cf4`；核心app_publish/app_runtime/runtime-manager/CLI文件与开发基线后续提交无重叠，Feature索引需保留双方新增条目。主工作区有未提交配置和设计文件，整合在本独立worktree中执行。代码推送不代表原生镜像/真实116 E2E已完成，T042/T043保持待验。

### 合并后复核

- Feature提交：`4a91ec61d`（fix(app-factory): align delivery contracts and retained diagnostics）。
- 整合基线：最新远端feat/3.0.0 `a65f130cf4`；合并提交：`03d8d82c8`（Merge F119 delivery contract and diagnostic fixes into feat/3.0.0）。
- 唯一冲突为`features/v3.0.0/README.md`的并列新增条目，逐块保留F118项目内新建对话和F119本功能；没有覆盖上游整份文件。运行时代码无冲突，原SDK wheel/hash未变。
- 在整合工作区复核：backend原12文件 **167 passed / 3 E2E skipped**；CLI四文件 **100 passed**；manager本功能与环境/静态/K8s模板/准入11文件 **400 passed**；locales生成/check-i18n通过。旧20项基线失败已在前轮完整相关组合留证，本轮未为索引冲突重复全量组合。
- 合并后ruff/arch-guard和diff空白检查复核，代码发布仍不代表真实116/189部署或原生服务镜像已验收，T042/T043保持未勾。
- 推送目标为`origin`的`refs/heads/feat/3.0.0`，使用普通非强制push；以远端ref核验包含上述Feature与合并提交。主工作区未提交配置/文档须保持原内容。
