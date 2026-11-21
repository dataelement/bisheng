# Tasks: 默认部署与可选客户端地址

| 文档 | 状态 |
| --- | --- |
| spec.md | ✅ 已评审，用户明确无地址完整使用 |
| design.md | ✅ 已评审，2026-11-17 用户确认继续 |
| test-cases.md | ✅ QA参考已生成并检查八列 |
| tasks.md | ✅ 已拆解，按 tasks-checklist 自审 LGTM |

## Wave 1：配置与请求地址

- [x] T001 配置实现与配对测试：`core/config/{settings,dsh}.py`、`common/services/config_service.py`、`test/dsh/test_config_contracts.py`、`test/common/test_yaml_settings_loading.py`；新旧键、空块、默认开启和地址可选。覆盖 AC: AC-04、AC-05、AC-06、AC-08。
- [x] T002 地址实现与配对测试（依赖T001）：新增 `dsh/request_origin.py`，修改 `domain/services/authorization.py`、`api/endpoints/{local_auth,identity,self_service}.py`、`work_mcp.py`；测试 `test/dsh/test_public_origin.py` 与新增无地址API/SDK回归。覆盖 AC: AC-04、AC-05、AC-07、AC-09。

## Wave 2：默认部署

- [x] T003 Compose/installer/默认YAML/来源实现与配对测试（依赖T001）：`docker/{install.sh,.env.example,docker-compose.yml,README.md}`、`docker/bisheng/config/config.yaml`、Gateway/Nginx配置、`scripts/tests/compose/verify-app-runtime-compose.sh`、既有 `runtime_manager/{config,egress}.py` 策略核对与对应安装/来源回归。覆盖 AC: AC-01、AC-02、AC-03、AC-08、AC-09、AC-10。
- [x] T004 Helm实现与配对测试（依赖T001）：Chart values/schema、configmap与Gateway模板、README、`scripts/tests/test_standard_helm.py`。覆盖 AC: AC-01、AC-02、AC-05、AC-06、AC-08、AC-10。

## Wave 3：验证与审查

- [x] T005（依赖T001–T004）task-review、arch-guard、ruff、安装/Compose/Helm、DSH API及真实SDK回归，按e2e-test技能输出分层覆盖与实机检查清单。覆盖 AC: AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10。
- [x] T006（依赖T005）sdd-code-review七维审查，更新design现状和交付记录。没有运行条件的实机验收明确列为待执行，不宣称线上生效。

## 实际偏差记录

- 开始实现前快进到远端最新 beta1 `0e975096fe`，保留主工作区及其他特性修改。

## 执行与审查记录

- T001/T002：新旧名称与空配置测试、实际API授权/撤销、两种地址模式PKCE/SQL/密码学换票与续期、真实SDK并发工具/技能调用均覆盖；task-review见task-review.md。
- T003/T004：默认镜像tag统一beta1、运行profile/独立密钥、npm下载源、活动YAML、Helm兼容归一化和代理接线完成；实际Compose解析与运行时接线全部通过。runtime-manager既有策略解析正确，复用而不改写，回归验证其来源/出站边界。
- T005：本地测试完成，e2e状态PARTIAL（尚未提供真实环境）。QA表保留待执行；真实Nginx/Gateway、Docker拉取与应用安装、DM8不计为通过。
- T006：按七维度自审并记录代码/验证边界；未合入发版线、未发布镜像、未部署线上。
- 细节同步：D2记录headless peers与Nginx边缘可信CIDR，属于已确认代理信任边界的接线；D3保留显式security_settings构造调用兼容。
