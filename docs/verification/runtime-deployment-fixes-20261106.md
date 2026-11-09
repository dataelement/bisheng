# Runtime 部署缺陷代码修复与验证

日期：2026-11-06。分支：`codex/3.1.0-beta1/runtime-deployment-bugfixes`。
发布线基线：`feat/3.1.0-beta1@f20c9cd21c`；本轮代码修改前分支 HEAD 为 `8347e1ec1`。

## 交付范围

用户先确认修复 R1、R2、R3、R4、R6、R9、新增 R10，已提交 `541036331d`；随后继续确认在同一分支修复 R5、R7、R8。三项补修的代码基线为该提交，细节见[问题清单](runtime-deployment-bug-list-20261105.md)。

用户随后明确“先只修复代码”。本轮没有构建、推送或更新容器镜像，没有操作线上集群、数据库、配额或 cgroup 配置。CLI wheel 是后端下载工具包的仓库分发合同，随源码同步重建；不代表后端或 Runtime Manager 镜像已经更新。

## 实现

| 项目 | 最终行为 |
|---|---|
| R1 | `pod_template()` 省略空 `spec.initContainers`；准入只将该空列表与缺省等价，非空/异常字段继续严格比较。 |
| R2 | `image-check` 加入固定日志容器白名单，原 Pod 名、namespace、行数、时间、1MiB限制保留。 |
| R3 | 只有明确的HTTP403 Status/Forbidden与配额数量才产生 `k8s_quota_exceeded`；只传递固定资源键的 requested/used/limit。Manager事实、Backend持久化/发布失败、CLI保留原因，准备阶段16226、其它16125、CLI退出14。普通403不判配额，无Pod时不伪造构建日志。 |
| R4 | 签发/更新请求的 aware expires_at 转为服务器本地 naive 时间；数据库历史值、无时区输入、omit/None语义和PAT上限保持，不迁移数据。 |
| R5 | execution/services已有拉取Secret名分别渲染为descriptor的pull_secret/control_pull_secret，预检两域各自引用；不读取/创建/复制Secret，允许不同namespace与不同名称、空值及旧descriptor缺省。 |
| R6 | 对齐普通/init/ephemeral容器可信停止判据，补齐stop_confirmed，按UID/RV解除finalizer并确认执行/控制域对象真正消失。单个失败继续回收独立安全对象，但未知旧writer的冻结计划引用仍保护共享PVC，关联不明保守保留。 |
| R7 | 实际镜像CRI优先执行；短命helper提供CRI证据，各消费者前创建独立600秒listener并保持原UID跟踪和回收。冷镜像前置不消耗监听寿命，监听失败不复用旧Pod或继续消费。 |
| R8 | other-app前后用已有runtime-manager策略身份的NotReady控制域helper，前后均实测成功才可确认拒绝；DNS只对正对照3次/0.2秒有界重试，空/错名/非布尔结果拒绝，负例单次可达即失败。 |
| R9 | 删除Settings.admin及启动预置账户逻辑。旧YAML只固定告警后忽略admin，不打印值；其它未知键仍拒绝。首次正常注册仍走原超管路径，后续注册为普通角色。 |
| R10 | 有正内存上限继续按承诺额度，无上限才按Docker统计字段计算working set。按存在性选择v1/v2/旧Docker缓存字段，零值有效，异常缓存用总usage，非法usage阻断心跳预算发布；原80%、2048MiB、取整和资源预约保持。 |

R6 的 Unknown 不是已停止证明。新增标准[异常维护说明](../../deploy/kubernetes/app-runtime/README.md)规定精确UID、可信节点核验、临时窄维护条件及恢复审计；没有新增CRI证据自动授权接口，也没有普遍放行管理员删除或停用Webhook。其自动授权能力仍需另行设计。

R10 的字段口径依据[Docker官方说明](https://docs.docker.com/reference/cli/docker/container/stats/)。约2.7GiB来自用户提供的原生产快照预期；本轮只验证计算逻辑，不宣称这是实时生产预算。

## 验证记录

测试复用已有Python 3.11环境，但PYTHONPATH/cwd指向独立worktree。Backend的ignored配置仅通过 `config` 指向主工作区文件读取，未复制、修改或提交该文件；测试数据库使用SQLite和外部依赖替身，不连接生产。

| 范围 | 结果 |
|---|---|
| Backend R3/R4/R9与既有凭据、公开诊断、配置、首用户投影组合 | 83 passed |
| CLI quota/errors/deploy wait/deploy sync组合 | 101 passed |
| Manager 模板/准入/日志/Docker容量/配额/执行器组合 | 636 passed、2 Docker tests skipped、1既有失败（下述基线同样失败） |
| Manager 既有image-preflight与R1模板缺省合同 | 9 passed；原空列表断言已同步为字段缺省，不把本次导致的旧断言KeyError当作基线失败忽略 |
| 预检完整installation（含Helm渲染及本地API替身） | 199 passed；独立关键/新增选择另59 passed（与完整选择重叠，不累加） |
| CLI源码与post3 wheel/manifest一致性 | 通过；干净venv安装、入口/--version/deploy --help及新登录shell通过 |
| Ruff、格式、diff检查、架构守卫新增问题比较 | 27个变更Python文件check/format通过、diff通过；生产Backend文件相对发布线无新增守卫问题。预检脚本按路径默认格式化前后AST一致。 |

CLI：`3.0.0.post3`，SHA256 `6fac8457ad951ebdb3725ac9cc795eb074daad31209ddee286879b7e92bb221b`。SDK及其manifest未变。

### 既有失败与验证限制

扩展执行器/操作回归在同一选择、同一解释器下对比代码修改前HEAD的独立归档：基线255 passed / 26 failed，当前313 passed / 26 failed，失败名称集合相同、没有新增失败。主要是既有fixture缺preflight实现及启动快照断言陈旧；未修改这些无关业务实现来凑全绿。

上述636项组合中的唯一失败为 `tests/test_kubernetes_executor.py::test_completed_stage_at_exact_limit_advances_once_and_observe_shape_stays_same`：原断言未包含实现已有的 `probe_state` / `started_at`。该用例也在同基线26项失败中。Docker真实引擎测试两项默认跳过；本轮没有实际K8s/数据库双方言部署验收或线上镜像验证。

## 代码审查

按 `sdd-code-review` 七维度，以用户已确认的缺陷目标和现有F059合同为依据，独立交叉审查。R1/R2/R10与R4/R9分别由非作者复核；R3补有HTTP403→Manager事实→真实Backend repo持久化→发布失败五元组→CLI的跨层合同测试。

审查发现并修正的R6风险：API中旧Pod已404或替换时，不能仅看当前Pod列表便回收PVC。修复以冻结计划保留未证明停止writer的卷关联，覆盖恢复库存中未过期、缺UID、丢失/替换及关联不明的计划；头/模板身份不一致也保守保留，合法PVC计划不误持其它卷。控制域也要观察到删除完成。R4/R9/R6的非作者最终复审PASS，无未解决P1/P2。

| 七维度 | 结果 |
|---|---|
| 边界条件 | 零缓存、非法统计、空init、aware/naive、缺失/替换/坏计划有回归；PASS |
| 权限与认证 | Unknown、共享卷保护及现有注册/角色路径保留；无新增编排权限；PASS |
| 并发安全 | UID/RV与停止证明不放宽，事实重试保留原因，预约公式保持；PASS |
| 信息泄漏 | 配额仅固定资源数量，旧admin仅固定告警，不输出凭据；PASS |
| 测试覆盖 | 核心与负例、跨层合同、新旧基线比较完成；既有失败和跳过如实保留；PASS |
| 代码风格 | Ruff与diff检查完成；PASS |
| 文档同步 | F059 design、当前配置模板、fixture说明、问题清单与维护runbook同步；PASS |

最终R1/R2/R10非作者七维复核同样PASS，无未解决P1/P2。整体代码审查PASS；本报告不把代码验收当作生产部署验收。

## 同分支补修：R5、R7、R8

代码基线 `541036331d`。本段为用户追加确认后的验证记录，前述首批回归记录与既有失败限制保留。

- R5：实际Helm渲染→descriptor→执行/控制域Pod，验证不同namespace、不同Secret名、仅一域配置、均为空及旧descriptor缺省；只传引用，不创建Secret对象、不读取密码或挂载凭据。
- R7：模拟4个profile各175秒冷拉取，每项在默认180秒窗口内、总计700秒超过旧listener寿命；CRI证据仍来自真实观察对象，所有消费者的listener均在镜像阶段后新建，保持600秒、新UID、完整回收记录。失败不消费旧监听，不掩盖原探测/清理错误。
- R8：other-app前后用真实控制域runtime-manager角色canary，前置失败不创建负例、后置失败不返回成功；核对现有Chart策略身份、NotReady gate、Service隔离、日志后的UID和结果目标名。DNS正对照验证首次成功/瞬断恢复/持续失败、空结果/错名/非布尔值及参数错误；拒绝侧收到一次DNS响应即失败，不重试到通过。

独立审查进一步发现并修复R7的旧计划引用：准入负例不能复制最早helper的冻结计划，否则继承冷启动前的旧期限。现按当前listener UID唯一匹配并核对plan UID/kind/name/namespace；无匹配、重复或错配在计划写入和dry-run前拒绝。测试覆盖旧helper计划已过期但当前listener计划有效的两类负例，以及7个身份不明情形；不续期旧计划。

最终组合命令（cwd=`src/runtime-manager`，使用已有Python环境及本地Helm）：

```sh
HELM_BIN=/private/tmp/helm-3.14.3/darwin-arm64/helm PYTHONPATH=. python -m pytest \
  tests/test_k8s_installation.py tests/test_k8s_pull_secrets.py \
  tests/test_k8s_preflight_listener.py tests/test_k8s_preflight_network.py \
  tests/test_k8s_capabilities.py tests/test_k8s_canary.py \
  tests/test_k8s_templates.py tests/test_k8s_admission.py -q
```

结果：**579 passed**，包括本轮35项新回归；该选择无失败或跳过。原installation用例的本机临时HTTP API替身需要本地监听权限，只用于离线Helm lookup模拟，不访问线上。5个变更Python文件Ruff check/format、diff检查通过，格式化前后预检脚本AST一致。R7/R8的非作者七维最终复审均PASS，无未解决P1/P2；R5由主代理复核映射、权限边界及渲染测试。

本次补修未改NetworkPolicy/RBAC、业务API、资源预约、镜像标签或CLI分发包。没有访问线上集群、构建/推送镜像或执行部署；旧镜像中的工具行为需后续经授权交付后才改变。
