# Vibe 合并 L2：发行、安装、SDK/CLI 与文档收口

## 结论

**限定交付代码范围：PASS_WITH_WARNINGS；未发现已确认的代码 HIGH。** F086/F059 代码可以按用户本次要求整合到 `feat/3.0.0-vibe`，但不能据此将完整 SDD、客户离线交付或 F059 正式 CI 发行标为完成。

原固定源码有一项发行 MEDIUM（同 release 跨 ref 并发）；root 已决定本轮修正，见下文。修订源码与静态合同测试固定前，本报告不将它写成旧提交已有的保护。

- 固定来源：`codex/059-k8s-runtime@cda8dccf26298af91a1df277dcd1a49787b6b444`。
- 固定目标：`feat/3.0.0-vibe@4aa9ce69b2830b81162fe631b9c801057c40ee8b`。
- 此范围包括 Compose/Helm/镜像构建与目录、installer、SDK/CLI 分发、F086 待收文档及四个旧子分支，不替代 backend 状态机、权限和前端的其他 L2 审查。
- 两提交的三点 diff 有 1640 文件，包含继承的发布线变更；该数字不代表全部都是本次 Vibe 独占实现或已由本报告逐文件审完。
- 仅本地只读代码/历史/归档内容核对及生成此报告。没有全量测试、网络、远端、构建、推送或产品文件/Git 写入。

## 七维度摘要

| 维度 | 本范围结果 |
|---|---|
| 边界条件 | 交付模式/平台/镜像摘要/库存完整性有明确检查；离线镜像、依赖和平台接口分别核验，不能互相替代 |
| 权限与认证 | manager 编排权限与入口/出站/准入身份分离；Docker socket 仅在 socket proxy，K8s token 仅 manager；installer 另需运维权限 |
| 并发安全 | profile 默认值 CAS、镜像版本冻结和只读运行材料合同保留；CI 跨 ref 同 release 并发为本轮唯一 MEDIUM，root 正在闭合 |
| 信息泄漏 | Helm 引用既有 Secret/公开 CA/公钥，值不写配置例；SDK/CLI 归档核对不读取客户凭据；全量 image Env 不作结论依据 |
| 测试覆盖 | 既有真实/模拟/静态结果按 SHA 分层；本次未重跑测试，F059 T070/T071/T072 不能因此关闭 |
| 风格与边界 | helper/assembler/runtime 分工一致，非业务代理不混入编排身份；旧子分支未发现待合入独占实现 |
| 文档同步 | F086 十份修改与 CI/模型附件应限定路径收录；历史 NEEDS_FIX/未验项保留，新整合结论另记，不覆盖为全通过 |

## MEDIUM M1：相同发行标识跨 ref 竞争（root 本轮修复）

固定 cda 源码 `.github/workflows/runtime-images.yml:14` 的组为 `runtime-images-${{ github.ref }}-${{ inputs.version }}`，但实际镜像 release 使用 `inputs.version || github.ref_name`。两个分支手动填同 version，或 tag 与手动填同 release，可能进入不同组。`scripts/build_runtime_images.sh:34–42` 的标签不存在性检查和 `:168–170` 的最终 push 之间不是原子占位，因此不能说客户端检查能绝对保证标签不可覆盖。

root 指定的新组：`runtime-images-${{ inputs.version || github.ref_name }}`，保留 `cancel-in-progress:false`。**该表达式与实际 RUNTIME_RELEASE 一致，能覆盖同仓库此 workflow 的同 version 跨 ref/tag+manual 竞争。** 架构矩阵仍发布不同 `-amd64/-arm64` 标签，catalog 继续等待两个 native job。

边界：其他 workflow、其他仓库、用户直接 CLI 写同一 DockerHub repository 不受这个 GitHub concurrency group 约束。正式发行仍须使用唯一新 release，控制发布权限，并按仓库能力采用不可变策略；已存在/不确定标签继续拒绝，不能重推未知结果。修复不授权本次公开 tag/push。

## 交付合同核对

### Docker Compose

- `docker/docker-compose.yml:305` 起的 `app-runtime` 可选 profile 保留 manager、app-proxy、egress-proxy、docker-socket-proxy 四进程。manager/egress 共用服务镜像，入口独立镜像；不 publish 每个应用的端口。
- 正式 Compose 使用预构建镜像；开发 build override 在独立文件。默认服务 tag `v3.0.0` 只是一条配置，不能证明它已按本次新源码发行；实际部署须通过 `BISHENG_RUNTIME_MANAGER_IMAGE`、`BISHENG_APP_PROXY_IMAGE` 选择已验证引用。
- `RTM_PROTOCOL_VERSION=2`、分离角色 HMAC、backend URL、原绝对 host data root 与容器 bind 对应；应用数据/helper 在 daemon 宿主解释路径。仅 socket-proxy 挂 docker.sock，manager 经 Engine HTTP API；无需安装 Docker CLI，但 API 权限仍然强。
- app/build 内网与独立 runtime-control 网络、socket API 白名单保留。backend/Celery 还须启用 app_runtime/open_platform、配置 payload/OBO/key IDs、节点和库存；只启动四容器不等于功能可用。
- 运行基础镜像由 backend 冻结 profile 和默认映射选择，不由更换 manager 镜像或 RTM_IMAGE_PREFIX 决定。

### Helm / installer / helper

- Chart 只装开源托管层，backend/worker、数据库、MinIO、OpenFGA 仍为外部平台。控制/执行 namespace 分离；manager SA 的范围化工作负载权限、显式轮换 token、无 token 的独立 admission 与默认拒绝网络保持。
- `values.yaml` 的空镜像/CA/网络/公钥/存储/报告并不是可直接使用的客户配置。必须提供精确 digest、独立角色 Secret、持久 material seed/admission CA、owner 公钥、可信 CNI/storage controller 身份、真实 CIDR/端口和合格容量存储。
- helper 来自同发行的 manager+Python preparer+Node 原生工具，安装受信任 site-packages，UID10001/isolated Python；assembler FROM helper 加固定 crane 及许可证。源码 COPY 的归属明确，不能用 manager-only 重建冒充 helper/assembler/profile 已更新。
- bundle 不构建 OCI：backend 提供冻结材料，Pod 内禁网物化，代码/依赖只读；完整 image 直接运行；source-image 另需可推内网仓库、assembler、相应 CA/策略/凭据。默认 bundle 不以应用推送仓库为前置。
- SQLite local PV 要实际有界 ext4/xfs、挂载 marker/UID 权限和节点绑定；PVC capacity 不是宿主目录配额。预览隔离，生产单写；Retain PV 的管理员回收不属于业务自动清理。
- installer 默认诊断，`--live --write-report` 才真测/写报告；外部运维需 kubectl、kubeconfig/impersonation、同版本 Python 依赖，source-image 可选检查另需 crane。它不向业务传递安装者身份。
- 能力报告与 descriptor 绑定、24 小时有效，外部运维按 6 小时刷新；Pod 健康、Helm wait、TCP canary、外部 crane 与真实 assembler push 是不同证据层。DNAT 后实际端口、真实 CNI 行为必须现场验证。客户环境须安排刷新监督，本 Chart 不偷偷部署高权限常驻 installer。
- 升级保留原 canary CM 归属/UID/RV，namespace/PV/公钥有 keep，独立业务 Pod/PVC 无控制 Deployment ownerReference。卸载不能在旧 unknown writer/保护未闭合时删除准入/网络；完整独立域卸载仍待 T070。

### CI / 镜像库存

- `runtime-images.yml` 触发为 `v*` tag 或显式 workflow_dispatch version。两个原生 runner 构建 **九镜像**：manager/proxy/helper/assembler 与五运行/准备镜像；原生 host/Engine/镜像执行架构必须一致，拒绝仿真证据。
- 使用当前 context 的 Docker driver 复用本机基础镜像，isolated helper/resolver、SDK wheel、许可证、SQLite 等检查在 push 前；真正的 Engine bundle integration 是其后的独立 step。架构镜像可能已推而后续 integration 失败，不能把它们当完整发行；服务索引/catalog 只有两个 job 全部通过才生成。
- `image_catalog.py` 检查九组件、同 release/source、架构、标签与 manifest digest，服务多架构索引只从冻结平台 digest 组合；本地 config ID、单平台 manifest digest、多架构 index 和 tag 不混用。
- 离线清单分镜像/依赖/平台 API 三层，并保留工具/许可证材料。正式 F059 CI 仍须在最终整合 SHA 重新跑，旧版本同名 artifact 或私有 R32 manager receipt 不代替它。

### SDK / CLI：实际分发包核对

使用固定 cda 提交的 Git blob 读取源码与 wheel，没有安装或执行 wheel。

| 项目 | 核对结果 |
|---|---|
| CLI3.0.0 | wheel SHA `739d58c34a4f9eb4833c21ecec60936ef78bf1a48ce0b050b0d86a810b0e3e39` 等 manifest；20 个包内 Python 模块逐字节等源码；实际分发 errors.py 包含16125容量处理 |
| SDK0.1.1 | wheel SHA `1c1e6cc3ca5a037dc91cfc8052ce63565a31f630f0981dd0fa2b8e06b2085950` 等 manifest；15 个包内模块逐字节等源码；与历史SDK轮子摘要保持 |
| 依赖/版本 | Python>=3.11；SDK仅httpx>=0.27,<1.0运行依赖；CLI另有PyYAML；dev依赖不作为应用运行闭包；metadata/project/manifest版本一致 |

SDK不持平台DB/MinIO/集群凭据，附件仍经backend既有合同。新增依赖时 wheelhouse/npm/系统库及目标ABI必须提前供应；不能把开发venv或一次SDK轮子存在误作所有依赖已离线可用。

## 四个旧子分支：实际文件与历史核对

四个工作树检查时均 clean。未执行 cherry-pick/merge，也未依赖 `git cherry` 单独判定。

| 旧分支固定 HEAD | 文件与历史结论 |
|---|---|
| `codex/f059-cli-capacity@01b58350e97d71e87c784d4ebc58fd039a94b80c` | `d156c88fe...` 测试和 `01b58350e...` 实现仍是独占 hash，但 source 有对应集成 `0ff595428`；两个测试文件、errors.py、已打包wheel、manifest与source字节完全相同。不得再摘取造成重复历史 |
| `codex/f059-image-release@f84415f2540b1b762dcfba2b7e8e521ca170f3bd` | 分支内容已在source历史；本组k8s_templates.py/test与source仅后续995c PATH修复1行/26测试行差异。CPU100m修改保留，无遗漏独占实现 |
| `codex/f059-installation@992905292418308b298d48a24d20cc9e19032c15` | 最后四个backend CPU预占/service/测试文件与source完全同字节，分支历史已包含；无遗漏独占代码 |
| `codex/f059-e2e@21250d32900c4c4ba893248aa5b8cc1d8d65182b` | 两个同步请求预算/E2E合同文件与source完全同字节，分支历史已包含；无遗漏独占代码 |

## F086 dirty 文档：限定收录，不碰旧公共草稿

允许整合的十份修改均在 `features/v3.0.0/086-vibe-runtime-delivery/`：`spec.md`、`design.md`、`tasks.md`、`tasks-index.json`、`task-reviews.md`、`code-review.md`、`e2e-checklist.md`、`implementation-files.sha256.json`、`live-validation.md`、`validation.json`。另有同目录未跟踪的 `e2e-evidence/2026-10-21-ci-release/`、`e2e-evidence/2026-10-21-docker/`、`model-review.{md,json}`、`model-review-tests.txt`，可按Vibe文档范围带入。

以下不是这批文档，必须留在原dirty WT：F048 preset-dashboard/bootstrap、tenant ContextVar、system_resource_reconcile 三生产文件，两权限测试，以及未跟踪 `test/tenant/test_tenant_execution_scope.py`。本审查未移动、提交或覆盖它们。

F086 dirty code-review仍写 `NEEDS_FIX/不进入merge`，其中H1/H2是完整离线新装/目录导入与剩余故障交付门，M1是记录的质量基线，不代表发现尚未修复的静态代码HIGH。用户本次要求代码整合与完成这些交付门是两个决定：新的整合L2应单列该范围和保留门，不能把旧历史报告直接替换成“全部完成”。

## 历史真实 CI 与后续发行边界

F086 T053的确有历史真实结果：tag `v3.0.0-test-vibe`，源码 `755d4456e50c015a3fa88da0c0c35ab53bbd1650`，runtime run `39567381522`，两原生job和catalog成功；**每架构七镜像**，并有109服务镜像启动记录。artifact ZIP当时未下载/未导入平台，新模型/tenant草稿不在tag里。这是保留原始证据，不在本次联网复核。

它不能证明新F059九镜像（新增helper/assembler）、最终整合源码的双原生CI、完整离线平台目录导入或新tag已经发行。R32的真实私仓manager digest `bc488d16...` 仅对应源码 `0f2db1f9a...` 的原生amd64 manager-only，与保留的旧helper/profile/代理来源分别记账；不能转标为 cda 或最终整合提交的全组件发行。

后续仍须明确保留：F059 T067后续Docker范围、T070剩余故障/独立域卸载与未实测AC子句、T071最终CI/模型发行证据、T072特性级总审查；F086完整离线新装/目录导入及尚未覆盖故障组合。DM8按用户确认仅静态检查，真实驱动/DDL/事务留中央环境；单节点不证明跨节点，ARM后续验证仍服从用户当前暂停范围。既有frontend/backend基线失败不可宣称被本范围消除。

**整合建议：可以合入已实现的F086/F059代码及限定Vibe文档，携带本轮CI串行修复和未验清单；不得以合并动作自动关闭上述验收/正式发行门，也不自动新建公开tag或推送镜像。**


## M1 关闭补充：整合工作树定向复核（2026-10-23）

**结论：MEDIUM M1 已关闭；本次已审交付代码范围可合并。** 本补充只复核 root 本轮两文件增量，不重写上文 cda 固定源码的历史发现，不代表剩余验收或正式镜像发行已完成。

- 复核工作树：`/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration`；检查时 HEAD 为 `575984069ff15e994caa53bda1785e769f6d80f5`，本轮修改尚在该工作树 diff 中。
- `.github/workflows/runtime-images.yml:14` 已改为 `group: runtime-images-${{ inputs.version || github.ref_name }}`，`:15` 保留 `cancel-in-progress: false`。该表达式与 `:37`、`:43` 的实际 `RUNTIME_RELEASE` 完全相同：不同 ref 手动指定同 version、同名 tag 与手动 version 均进入同一并发组；正在执行的同组发行不会被新请求主动取消。
- `src/runtime-manager/tests/test_image_release.py:138` 的既有契约测试新增精确 group 和 `cancel-in-progress: false` 两条断言；原原生 runner、无仿真、digest/index 门仍在。本轮定向红绿为 root 提供的 **1 failed → 1 passed**，本独立复核只读 diff/调用处，未再次运行测试或触发 CI。
- 两架构继续使用各自平台 tag，catalog 继续依赖两个 native job；本轮没有改变镜像构建、推送、索引或发行资料的验证顺序。

关闭范围是**同一仓库、采用该 group 的此工作流、相同有效 release 标识**的竞争。其他工作流采用不同 group、其他仓库或直接 registry/CLI 写入不受该锁约束；客户端“不存在”检查仍不是原子 registry 占位。唯一 release、受控发布权限和 registry 不可变策略的边界继续保留，不能宣称所有写入者已被序列化。

本轮未发现该定向增量的 HIGH/MEDIUM 阻断。用户已明确授权合入后推送 Git 分支，由 root 执行；这不等于新增公开 tag 或公开镜像发行授权。上文列出的 F086/F059 未验项、最终整合 SHA 的正式双架构 CI 和全量 SDD 交付门保持未关闭。
