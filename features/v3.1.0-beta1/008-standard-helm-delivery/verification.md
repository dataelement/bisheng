# F008 源码交付验证

日期：2026-11-10。分支 `codex/3.1.0-beta1/standard-helm-delivery`，现有 worktree `standard-helm-delivery`。基线 HEAD `19ba119e48fe4ffc08b84e8f093ae0fa14fd76ac`；本次验证对象是其上的工作区修改和新增文件，尚未提交/推送，不能把 HEAD 当成本次代码提交。

## 1. 第3项先验证

在修改保护配置接线前，使用原规则运行 `tests/test_k8s_admission.py`、`test_k8s_lifecycle.py`、`test_k8s_installation.py`：**437 passed**。覆盖来源、UID、删除、Unknown、CNI、PVC 绑定和原 Helm 升级保留。仅 loopback 模拟 API，未连接集群。没有发现需要改动原 Admission/UID 停止核心规则的缺陷；没有增加前代映射或旧安装接纳。

新增配置链路后发现并修复的是本期接线问题：image-check Helper 不能按 init 额度生成；阶段健康期限须同步 kubelet startupProbe；真实保护变化须持久失效旧路由，不能由下一次心跳追认；父子 Chart 共享引用不能依赖渲染顺序；ConfigMap/策略变化须通过 checksum 滚动 Pod。对应回归见下表。

## 2. 最终定向结果

| 范围 | 结果 | 实际覆盖 |
| --- | --- | --- |
| Backend，10个选定文件 | **207 passed** | 新策略独立校验、Manager→Backend 无/失败旧报告配对、持久路由保护、全部11种 Pod 阶段资源配对/拒绝、真实 SQLite 预约与重叠超额、签名 API/UID 保护、官方种子及公开 schema、配置装配、SQL/初始化顺序、Alembic 单 head |
| Runtime Manager，9个选定文件 | **579 passed** | 原 Admission/UID/生命周期、runtime Chart/模拟升级、namespace pull Secret、能力、模板、DNS/公钥命令、策略、资源/健康期限和 StorageClass 三态 |
| 父 Chart 和发行工具 | **39 passed** | 默认/外部/混合、开关、Gateway、双 release/namespace、探针端口、非 root 公钥 Job、Secret/公钥/TLS 保留及缺失拒绝、独立诊断、共享参数、配置滚动、NodePort、发行清单/Schema/来源/归档及忽略本地配置 |
| Helm 3.19 `lint --strict` | **通过** | 使用明确虚构 digest 和网络 fixture，非现场值 |
| Ruff / arch-guard / shell / whitespace | **通过** | 36个变更 Python 文件完整 Ruff 检查；逐文件 arch-guard 无违规；entrypoint bash语法；git diff --check |

合计最终定向 **825 passed**。没有依靠跳过失败用例把宽回归报绿。Chart/镜像均未发布；临时 fixture tgz 仅验证归档结构，不包含真实可执行发行镜像。

本地执行环境：共享现有 Backend Python3.11 venv，Helm3.19；Backend 使用 `/private/tmp/f008-test-settings.yaml` 的 localhost 测试配置，无生产凭据。需要模拟 apiserver 的测试仅允许本机 loopback 监听。脚本/测试未执行 ssh/kubectl/helm install/upgrade 到真实环境。

### 可复现选择

Backend cwd `src/backend`：

```bash
config=/path/to/test-settings.yaml python -m pytest \
  test/app_runtime/test_standard_helm_policy.py \
  test/app_runtime/test_system_profiles.py \
  test/core/test_deployment_renderer.py test/core/test_helm_initialization.py \
  test/database/test_alembic_single_head.py \
  test/app_runtime/test_runtime_image_check_policy.py \
  test/app_runtime/test_runtime_kubernetes_repository.py \
  test/app_runtime/test_runtime_kubernetes_service.py \
  test/app_runtime/test_runtime_kubernetes_api.py \
  test/app_runtime/test_runtime_protection_report.py -q
```

Runtime Manager cwd `src/runtime-manager`：

```bash
HELM_BIN=/path/to/helm python -m pytest \
  tests/test_k8s_admission.py tests/test_k8s_lifecycle.py \
  tests/test_k8s_installation.py tests/test_k8s_pull_secrets.py \
  tests/test_k8s_capabilities.py tests/test_k8s_templates.py \
  tests/test_standard_bootstrap.py tests/test_standard_execution.py \
  tests/test_standard_policy.py -q
```

仓库 cwd：

```bash
HELM_BIN=/path/to/helm python -m pytest \
  scripts/tests/test_standard_helm.py scripts/tests/test_helm_package.py -q
helm dependency build docker/helm/bisheng --skip-refresh
helm lint docker/helm/bisheng --strict -f /path/to/explicit-test-fixture.yaml
```

## 3. 宽回归与基线分开

- Runtime Manager 阶段性全量：**2014 passed / 90 skipped / 37 failed**。在 Git HEAD 的只读临时源码快照复跑：本轮这37个失败均在改动前存在，差集无新增失败；基线完整运行记录为1973 passed / 90 skipped / 62 failed，包含旧 Chart 测试/原环境差异。不能把次数变化当作本轮修复25个产品 Bug。37项主要是旧测试 fake 缺失现有 preflight、旧 purge/cleanup/host依赖等。后续参数/Chart修改再由上面的最终定向集合验证。
- Backend 邻近15文件宽回归：**243 passed / 18 failed**。同样18项在 HEAD 临时快照逐项复现失败，包括测试 schema 缺 host isolation 表、controller/fact 旧形状和 F114 之后的旧 owner 数据会话假设。本轮不恢复已退役权限语义来修测试。
- Backend `test/app_runtime` 整目录收集被原 `test_runtime_management.py` 导入已不存在的 `require_natural_owner` 阻断；该生产模块本轮未改。不能宣称整目录全绿。
- 本地没有 CI 执行结果，也没有 MySQL/DM8/OpenFGA/Gateway 实体集成、原生双架构和驱动运行证据。

## 4. SDD / E2E 边界

按仓库 e2e-test 的 AC 分类完成源码 API 配对、签名鉴权/真实 SQL 台账集成及手工清单。**没有运行真实部署 E2E**：用户本轮明确禁止构建/部署。`test-cases.md` 的集群用例保持待执行，具体清单见 [manual-verification.md](./manual-verification.md)。源码审查通过不等于允许上线或正式发行。

下一阶段还需要：同提交配套新镜像及真实 image-set/catalog；独立新集群安装；首次注册、DSH/Gateway许可证、沙箱会话、Python/Node/Static 外部依赖完整构建、卷容量/锁/持久化、在线阶段出网与禁止绕过、双 release/升级/卸载、恢复计时及 amd64/arm64 真实证据。未向旧v3.0.0镜像添加虚构 digest。

## 5. 交付入口

- 公开父 Chart：`docker/helm/bisheng`；唯一子源：`deploy/kubernetes/app-runtime`、`docker/helm/bisheng-sandbox`。
- 教程：`docker/helm/bisheng/README.md`；外部依赖/关闭功能示例在其 examples 下。
- 正式打包入口：`scripts/package_helm.py`。要求兼容清单、catalog/schema、匹配且干净的源码；只收录 Git 可见源文件，排除忽略的本地部署配置。无真实清单时拒绝正式交付。
- `.github/workflows/helm.yml` 只做源码检查，无构建、推镜像、部署或凭据写入步骤。
- 未读取/修改 `k8s-product`、122 集群、`bisheng-information` 或现有 `infra`。保留既有代码/部署，不迁入，不构建或更新线上镜像。

源码快照指纹（82个修改/新增代码、模板、Schema及锁文件，不含Markdown/忽略文件）：`2449141b0e6ed7dcff9899f296c24f6d63119d1a324711f6819406cf634c0b33`。
