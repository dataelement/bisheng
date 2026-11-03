# Design: 应用工场交付契约与诊断修复

**关联**：[已确认 spec](./spec.md) · [需求发现](./discovery.md) · [设计自审](./design-review.md) · [116 环境记录](./environment-verification.md)。

**版本**：v3.0.0 / F119。**基线**：`78ed282c201e7b9fd8971094ef3031317c725ee8`。**更新**：2026-11-03。

**阶段**：正式规格 42 条 AC 已获用户单独确认；整份设计已获用户单独确认，进入逐任务实施。下文基线快照与目标行为分列；任务进度以 tasks.md、verification.md 为准。

## 1. 目标与非目标

修复官方材料到实际发布路径的契约差异，统一运行变量、语言入口、静态产物和失败诊断。镜像检查在运行层尽早完成，116 镜像补齐作为独立环境处置。

不恢复旧控制协议，不迁移资源或历史数据，不自动重建现存正式应用，不改变依赖/运行网络策略，不增加权限动作或编排后端。不把镜像烟测当成完整发布验收。

## 2. 关键约束

遵循 [constitution C1–C8](../../../docs/constitution.md)、[release-contract](../release-contract.md) 及 F114 后继合同；原领域 Owner 不变。

- 同一个 `AppManifest` 目前同时服务新提交解析和冻结历史读取；全局改默认值会改变历史缺版本记录。
- backend、runtime-manager、K8s helper 与 CLI 是不同分发单元。backend 不导入 manager 包或取得 Docker/K8s 编排访问；CLI 源码修改必须进入实际下载 wheel。
- 只使用现有运行操作、执行事实、产物及版本记录，不新增表或独立任务系统；新增查询在对应 Repository，沿用双 DB 类型与租户上下文。
- 预检没有正式版本序号，只有预分配的 `version_id`；已发布版本和审批预览才具有已分配序号。不能为了填充环境变量提前创建一个假版本。
- 镜像可用性仅代表当次检查事实，不能作为永久准入或全平台健康门禁。最终启动仍须按固定身份复核。
- 116 的 Node profile 镜像已补齐；现有平台、11 个正式应用和 `never` 策略未变。通用修复尚未部署。

## 3. 方案对比与选定

### D1：在新提交入口补默认版本，保留存储模型默认值

- **备选**：A. 全局把 `AppManifest` 默认值改成 2；B. 区分新输入与历史读取，在新输入边界补 2。
- **选定**：B。`manifest_validator.validate_manifest()` 在加载 YAML 后、版本门禁及 Pydantic 解析前，对“键不存在”的新提交补 `manifest_version=2`；显式值保持原校验，`null` 不当作缺省。冻结输出明确保存版本和交付模式。`AppManifest` 自身缺省仍为 1，worker 的历史读取不走新提交正规化。
- **原因**：`run_pipeline()` 直接解析 `deployment.manifest`，F086 AC-13 已承诺旧描述不能静默改为 bundle；只改一个字段会打破这个承诺。官方三个示例显式改为 2，CLI 脚手架维持现有 2。
- **重新考虑**：只有所有历史读取都已显式标记来源、且另行获准迁移历史合同后，才考虑删除模型的旧缺省；本次不做。

### D2：共用纯运行契约函数，入口和静态目录分别处理

- **备选**：A. Docker/K8s 各补几行变量并复制入口规则；B. manager 包内共用纯函数，由现有适配器调用。
- **选定**：B。在 manager 包增加小型纯函数模块 `runtime_environment.py`，集中生成平台保留变量与语言别名；不参与凭据签发、挂载、存储或授权。Docker `BundleLauncher`、K8s `_plan()` 与既有 `lifecycle.build_env()` 消费同一默认块。启动入口继续在 `bundle_inputs.startup_command()`；静态目录选择提取为无写入的公共函数，供 Docker/K8s 打包和现有兼容构建使用。
- **原因**：Docker bundle 当前缺变量，K8s 有 DB_PATH 但缺元数据；直接复制会再次漂移。`source_facts()` 会写 requirements/package stub，不能整体拿来做 bundle 入口检查。
- **重新考虑**：只有运行环境协议增加新的语言/挂载布局时再扩展参数；不引入运行环境注册框架或跨进程 Python 共享包。

### D3：保留既有错误五元组，修复两个丢失点

- **备选**：A. 把整个 `RuntimeOperation` 或异常字典返回公开 API；B. 在既有转换处构造安全白名单摘要，保留 `{stage, code, message, details, hints}`。
- **选定**：B。manager 保留具体已知原因并先取日志后清理；公开读取时从仍在保留期内的已脱敏运行失败补充 `details.tail` 行列表，不将日志复制进长期保存的发布失败。仅准备失败用 16227，真正启动失败用 16228；非启动、取消和维护语义保留原分类。CLI 同时识别原因和旧 16124。
- **原因**：运行操作保存的是 `diagnostic_tail` 字符串，而 CLI 只认 `details.tail` 列表；`failure_from_error()` 只复制 `kwargs.details`，并不复制顶层 `kwargs.failure`。直接返回整份 operation 会暴露解封环境、路径、控制上下文。
- **重新考虑**：只有公开诊断需要新增独立授权内容时再设计新 API；本轮不新增日志服务或改变状态轮询结构。

### D4：按请求在执行端检查镜像，不建立全局镜像库存

- **备选**：A. backend 访问 Docker/集群，或定时维护全局镜像可用性缓存；B. 使用已登记操作的固定输入，在运行适配器内检查。
- **选定**：B。Docker 在准备任何依赖前核对 runtime/preparer/适用 base image；正式维护开始前再次核对将启动的固定镜像，启动时继续原 `ensure_image()`。K8s 使用同一操作拥有的、短时、只读镜像检查 Job；不读取节点列表、不挂宿主路径、不增加集群权限，不启用新的 manager RPC。
- **原因**：116 只有 preparer 也能开始依赖构建，最后才发现 runtime 不存在。心跳只是一份过期快照；全局健康阻断会误伤其它语言和已运行应用。K8s 的镜像拉取身份和 Docker daemon 本地库存不同，不能用 Docker 的观测来承诺集群可用。
- **重新考虑**：若定向验证显示 K8s 镜像检查成本不可接受，可单独评审有有效期、绑定镜像身份及节点池的证明缓存；本轮先使用当次检查，不建立新的主数据或守护服务。

### D5：修复离线指引，复用现有材料机制

- **备选**：A. 关闭 offline 或把内置包清单做成唯一白名单；B. 保留现有配置，说明精确版本、锁定文件与公共/应用私有材料导入。
- **选定**：B。沿用 `runtime_offline`、`offline_artifacts`、现有材料导入与作用域校验；仅在允许的下载阶段使用已配置来源。安装/编译仍隔离，应用运行出网不随之开放。
- **原因**：文档中的“只能用 23 个包”忽略了现有材料导入；失败案例分别是精确版本缺失和 npm cache miss，放宽版本或网络不能作为通用修复。
- **重新考虑**：只有另行确认内网包仓治理或材料制作产品需求后，再扩展运维能力；不增加第二个依赖解析器。

### D6：源码和可安装 CLI 同批交付

- **备选**：A. 只修改 `errors.py`；B. 源码、版本、wheel、平台分发 manifest 同步。
- **选定**：B。以当前 `3.0.0.post1` 为基线递增 CLI 修订版本，使用 `scripts/pack_cli_wheel.sh` 重新构建，安装到空 venv 验证，再保留脚本生成的 CLI wheel 和 manifest；SDK 产物不动。实施时若上游已占用下一版本，使用大于上游的修订版本。
- **原因**：backend 镜像没有 `src/bisheng-cli/` 源码树，只分发 `dev_toolkit/artifacts`；不重打 wheel，用户安装后仍遇到旧行为。
- **重新考虑**：分发改成 CI 原生制品流水线时再移除仓库 wheel；本轮不改发行体系。

## 4. 系统现状与修改落点

### 4.1 当前数据流

`CLI deploy → 发布接收/清单验证 → AppDeployment 冻结 → Celery run_pipeline → prepare 操作 → runtime-manager → 依赖产物/RuntimeDelivery → probe 操作 → 审批 → deploy → 统一应用入口`

当前故障点：

| 当前代码 | 现状 | 拟修改 |
| --- | --- | --- |
| `app_publish/.../manifest_validator.py::validate_manifest`、`schemas/app_manifest.py::AppManifest` | 新提交和存储读取都缺省 1 | 仅新提交入口正规化为 2；历史模型默认不变 |
| `runtime_delivery_coordinator.py::probe/deploy/recover`、`application/preview_operations.py` | 正式/预览 payload 不完全一致，probe 没有序号 | 补真实 runtime/health 元数据；预检序号未知时不虚构 1 |
| `bundle_launch.py::payload`、`executors/kubernetes.py::_plan` | 同类变量分别拼装，Docker bundle 无 DB_PATH | 共用平台默认块，保留各自挂载、身份与 Secret 注入流程 |
| `bundle_inputs.py::startup_command` | Python 无默认入口；Node 只 scripts.start/npm start 或 server.js | 补合同顺序，脚本直接运行，不隐式运行 npm 前后置生命周期 |
| `bundle_preparer.py::prepare`、`k8s_helper.py::prepare_upload` | static 主要只认 dist 与根 | 区分上传现成产物与实际执行构建，支持四目录，缺入口明确失败 |
| `operations.py::_failure` | 先清理；未知 `BundleInputError` 被转 `execution_failed` | 保留已知输入原因、在清理前收集可用输出，维持终态清理守卫 |
| `runtime_delivery_coordinator.py::wait/prepare` | 非成功统一 16124；公开 details 不含日志 | 按操作和失败阶段分类，形成安全摘要 |
| `failure.py::failure_from_error`、`PublishStatusService` | 五元组保存/透传，后者不是日志丢失源头 | 保持结构；存储安全元数据，合法读取时追加仍有效的日志 |
| `bisheng_cli/errors.py`、平台 CLI wheel | 只读取 `details.tail`；旧 16124 未登记 | 原始错误不丢，原因和提示一致；安装件同步 |

### 4.2 模块职责

| 模块 | 做什么 | 不做什么 |
| --- | --- | --- |
| F053 官方技能包/CLI | 示范合同、显示诊断、分发可安装 CLI | 不解析平台权限，不静默改依赖版本 |
| F055 发布与错误转换 | 正规化新输入、冻结语义、映射公开失败 | 不调用 Docker/K8s，不创建镜像库存 |
| F086/F059 coordinator / Repository | 固定操作与所需运行元数据，沿用授权及事件事实 | 不复制运行适配器的镜像拉取/生命周期逻辑；新增 SQL 不放 Service |
| manager 纯函数 | 运行变量、源码入口与静态目录选择 | 不签发凭据、不执行宿主 shell、不写平台资产真相 |
| Docker/K8s 执行适配器 | 固定镜像检查、启动观测、受控日志与清理 | 不扩大租户资格、不以 preparer 充当 runtime |

### 4.3 新清单的冻结点

新输入版本缺省只在 `validate_manifest` 一处补齐；之后存储的 `deployment.manifest` 和版本快照明确包含 2。显式 1 仍不能包含 delivery；显式 2 无 delivery 缺省 bundle；未知、非法及 null 版本拒绝。worker 重试、历史版本、恢复、预览直接读取原冻结组合，不运行新输入正规化。

无需数据库迁移或历史 JSON 回填；新提交即使来自以前保存的包，也按“此次新提交”处理，要求旧方式时显式声明 1/source-image。source-image 由唯一 v2 操作链执行，与控制协议编号无关。

### 4.4 运行变量与启动路径

纯函数输入取自固定 operation/delivery，不从宿主环境推断应用身份：

| 变量 | 约定 |
| --- | --- |
| `BISHENG_APP_DB_URL` / `BISHENG_APP_DB_PATH` | `sqlite:////data/app.db` / `/data/app.db`；预检/预览挂载独立 `/data`，正式挂原持久数据 |
| `BISHENG_APP_ID` / `BISHENG_APP_SLUG` | 当前应用真实 ID / slug |
| `BISHENG_APP_VERSION_ID` / `BISHENG_APP_VERSION` | 固定版本 ID / 已存在的版本序号字符串；预检尚未分配序号时后者为空，不冒充 v1 |
| `PORT` / `BISHENG_APP_PORT` | 固定 port 的字符串 |
| `BISHENG_APP_BASE_PATH` / `BISHENG_APP_HEALTH_PATH` | 本次运行访问前缀 / 健康路径；预览使用其独立前缀 |
| Python 框架别名 | `UVICORN_ROOT_PATH`、`GRADIO_ROOT_PATH` 等于 base path；`STREAMLIT_SERVER_BASE_URL_PATH` 去掉前导 `/` |
| Node 别名 | `BASE_PATH` 等于 base path |

平台默认块覆盖上述保留键；已获授权的业务变量、存储/模型/预览凭据仍走原注入流程，函数不新增或返回明文控制凭据。Python bundle 的 PATH 保留 `/opt/venv/bin`；Node bundle 增加 `/workspace/app/node_modules/.bin`。完整镜像不强制替换其自定义 PATH、工作目录或 ENTRYPOINT。

backend 对新 operation 补固定 `runtime`、`health` 等已知值；preview/serve 从对应 AppVersion 取得序号。历史未提供序号的 operation 重试不猜号；历史读取不触发运行重建。

默认入口规则：显式 `delivery.startup.command` → 单个有效 Procfile `web:` → Python `main.py`/`app.py` 或 Node `scripts.start`/`main`/`server.js`/`index.js`/`app.js`/`main.js`。Node `scripts.start` 用 `/bin/sh -c` 直接执行已声明脚本，保留 shell 命令语义，避免 `npm start` 自动附带 prestart/poststart。

只检查相应源码文件是否存在、形态正确并在包内；不在 manager 进程导入或运行应用。包内入口只读、禁止路径逃逸/外链和非法 argv。显式完整镜像命令不强制解释为源码文件。原镜像健康判据 `<500` 本轮不改。

### 4.5 静态目录与构建产物

提取纯选择函数 `select_static_root(root, *, built)`，验证目标及 index 为包内正常文件：

- 现成上传包、没有实际构建：根 → dist → build → public。
- 实际执行并成功完成构建：dist → build → public → 根。

在构建前读取既有 `prepare.py::node_projects()` 相同范围的 package.json，记录是否将运行 `scripts.build`；成功编译后才按 `built=true` 选择。Docker 使用本次准备上下文；K8s 由既有输入标记/准备文档带到 upload 阶段；材料或安装 overlay 不得事后改写这个判定。无需为了选择目录而修改已注册 profile 的 preparer 镜像。

有构建步骤时不在输出生成前误判缺 index；没有构建步骤时尽早检查。两条路径在上传 compiled 产物前均做最终检查，将选定目录规范化成产物根；恢复后不再次在源码根选择，防止 Vite 根入口遮盖 dist。source-image 的既有预编译静态包沿用根优先；K8s source-image 已执行构建时采用同一 built 判定，OCI assembler 消费已选定产物。

不改变 CLI 默认排除 dist/build 的打包规则；技能包明确现成产物须通过 `.bishengignore` 的 `!dist/` 或 `!build/` 纳入。

### 4.6 具体失败原因、输出与权限

manager 仅保留安全已知异常的 reason：`ExecutionError`、`ExecutorError` 和 `BundleInputError` 等可枚举输入原因。未知异常仍为 `execution_failed`，不把原异常全文或堆栈公开；包 JSON/入口校验错误在输入边界转成已登记原因。

Docker `wait_ready()` 在确认退出/超时后、删除执行体前读取 40 行；通用失败处理中如需补抓，只枚举当前 node/app/operation/epoch 拥有的执行体。K8s 沿用真实 Pod UID/资源记录读取，将当前多容器合并诊断收敛为最终 40 行，保留必要 waiting reason。清理守卫仍有优先级：已提交 serving 操作不被回滚，终态重试不覆盖原失败或复活过期诊断，无法确认停止的 writer 不强删。

先使用现有两侧脱敏函数，再按 UTF-8 字节截断到 16 KiB，并限制 40 行；补盖控制凭据、下载源认证信息和业务密钥。无法读取/解封必要敏感值时不公开输出，主要 reason 保留；不能让日志读取失败覆盖原错误。

backend 在 F086 失败到 F055 公开失败的转换处形成白名单，不改 `failure_from_error` 的通用结构；以下为有 edit 资格且诊断仍有效时的响应，日志不作为发布单的持久快照：

```json
{
  "stage": "precheck_probe",
  "code": 16228,
  "message": "应用启动失败",
  "details": {
    "operation_id": "...",
    "reason": "startup_exited",
    "runtime_stage": "starting",
    "maintenance": false,
    "data_may_have_changed": false,
    "tail": ["<已脱敏的应用输出>"],
    "diagnostics_available": true
  },
  "hints": ["检查启动命令、监听地址和平台端口后重新提交"]
}
```

仅允许 operation 标识、已知 reason/stage、维护/数据变化标志、可公开缺失材料引用及脱敏 tail；不返回 `payload`、`runtime_env`、sealed_env、授权上下文或宿主目录。无输出使用空 tail、`diagnostics_available=false` 和对应提示。

`AppDeployment.failure` 只持久保存错误、提示及操作关联等安全元数据，不保存 tail 或 `diagnostic_tail`。即使某内部异常临时携带 tail，`PublishPipelineService._fail()` 的存储适配也须去除。`get_deployment_status()`、`PublishStatusService` 在已有 edit 授权之后，调用 app_runtime 导出的发布诊断读取适配器：通过 Repository 按 app/tenant/operation 关联读取，检查 `diagnostics_until` 和当前真实调用资格，才返回 tail。不得使用会解封 payload 的内部 `RuntimeOperationService.describe()` 作为公开读取器。

诊断以原 RuntimeOperation 为唯一保留来源；查询时已到期、被清理或无权读取时不提供输出，不依赖后台 purge 恰好执行，也不从长期发布记录恢复副本。这样不会把原 7 天日志延长成永久发布历史。基础进度可读资格不变。

| 条件 | 公开分类 |
| --- | --- |
| prepare 操作中的镜像、入口、材料、依赖/编译失败 | 16227，具体 reason 与对应 hints |
| probe/preview 或正式运行确实位于 starting/ready 的启动/探活失败 | 16228；维护与数据变化标志照实保留 |
| snapshot/migrate/restore 数据动作、取消、清理不明或其它非启动失败 | 现有对应分类；无专用分类仍用原 16124/操作错误，不统一包装成 16228 |
| 协调等待超时、执行端尚未确定清理结果 | 原操作超时类别与真实阶段，不伪造已完成失败 |

`wait()` 按操作/失败阶段选择，prepare 包装保持幂等：新操作和恢复既有 prepare operation 两条分支必须一致。16227 现有通用文案调整为“交付准备失败”，三语源及生成产物同步；不新增码段。16124 增加 CLI 兼容文案，原始 code 保持。

详细失败与 tail 继续遵守 F114 edit 门禁；publish-only 等调用者仍只拿到原有进度/操作摘要。`get_deployment_status`、`PublishStatusService`、runtime management 和 MCP/CLI 调用链逐处验证，不因新增 tail 扩大原有资格。

### 4.7 镜像检查与执行前复核

**Docker**：

1. bundle 在源码/依赖下载和构建前，对冻结 profile 的 preparer 与 runtime 分别调用 `ensure_image(reference, platform, expected_id)`；报告缺失角色及其无凭据引用。完整 image 模式保持原固定 image 检查。
2. source-image 在实际构建前检查对应已配置基础镜像和架构，将实际 Image ID 作为本次渲染的 `base_image`，避免标签在检查与 Docker build 间漂移。拉取行为仍按原策略；never/离线缺失只报错。
3. 新正式部署在 maintenance/停旧 writer 之前核对固定运行镜像；实际 `BundleLauncher.payload()` 仍执行原身份核验，防止 GC/替换造成过期准入。检查失败不影响旧 serving 路由。

**K8s**：

- 不照搬本地镜像库存。增加 operation-owned `image-check` purpose，复用现有 Job/资源登记/短期限时/清理与阶段授权；只读检查固定引用，不能运行应用安装脚本或挂生产数据。
- 检查器在现有 trusted helper 镜像中运行，复用项目已使用的固定版本 crane 工具。helper Dockerfile 复用固定 crane 构建来源；不依赖未配置的额外 assembler 镜像，不把 crane 或 registry secret 交给应用/preparer。
- 对目标平台本次需要的 helper/preparer/runtime、source-image 的 assembler 或完整 image 验证固定引用、config identity、架构及可读取的层；使用 `crane --platform … validate --remote …`，不使用跳过层下载的 `--fast` 冒充完整检查。工具语义已核对 [v0.22.1 validate 实现](https://github.com/google/go-containerregistry/blob/v0.22.1/cmd/crane/cmd/validate.go)。检查是只读 registry 访问，不生成/推送应用镜像。
- registry 认证只复用现有安装侧 registry Secret/pull Secret，在 trusted 检查 Pod 内挂载；网络来源仅允许本次固定镜像涉及的 registry 及现有显式认证端点，走既有受控出网。未配置所需来源/认证或不能验证时按该请求返回具体不可用，不自动增加授权或公网回退。
- 在任何材料准备前运行一次；正式 maintenance 前针对最终固定运行引用再次检查。Kubelet 实际拉取、Pod imageID、就绪与阶段围栏继续最终验证；在途变化不能借之前检查放行。已有 imagePullPolicy 保持，不引入 `Never→IfNotPresent` 隐式变更。
- `image-check` 目的、允许的容器命令、固定镜像引用、无源码/数据挂载、Secret 范围和资源上限同时进入 plan、资源意图与 admission 模板校验；manager 重启可从同一 operation 下资源记录恢复，终态回收，不新增节点池守护进程。

不改 profile 开关或全平台 health，不增加“节点有一个语言缺镜像则拒绝所有请求”的规则。镜像引用和架构来源均是已有固定交付，不能由错误上下文提供任意 URL。

### 4.8 离线材料、116 处置与交付边界

技能包分别解释：offline 只约束对应材料下载；runtime 镜像是否可拉取由节点策略决定；安装/编译与应用运行出网各有原有隔离。列出精确版本、锁文件、平台架构、私有材料导入及重试的现有步骤，保留 pip/npm 原始脱敏错误。

116 仅补齐了已启用 Node profile 指定的 digest，并做禁网非 root 启动验证。此前缺少的兼容构建基础镜像与应用私有依赖，不以这次结果标为解决；默认示例修复为 bundle 后不再依赖这三个 legacy tag。确需 source-image 验收时再从已批准来源固定具体镜像后补齐，不能把公网可变标签当作通用代码补丁。

本轮环境变更不写进产品默认配置或 compose，不批量更改现有 profile/应用。代码完成后再准备 backend/worker、manager/helper、CLI 及必要分发产物的同提交更新清单；没有另行环境更新授权前不替换平台服务。无需修改 runtime 镜像本体来实现变量/入口修复，不主动重建现有正式应用。

## 5. 已知坑与护栏

| 事实 | 忽略后果 | 处理位置 |
| --- | --- | --- |
| manifest 版本与 API/控制协议版本独立 | 误删有效源码兼容，或复活已退役 v1 RPC | `manifest_validator` / `AppManifest`；只保留 v2 operation |
| 默认模型同时读取存储 | 全局默认 2 会重解释历史缺版本 | D1 新输入正规化；worker 历史回归 |
| bundle 源码只读，DB_PATH 缺失使示例回落源码目录 | 发布失败或第二个错误数据库 | 运行默认块；官方 main.py 使用注入数据库，缺配置明确失败 |
| 预检尚无正式版本序号 | 默认 1 冒充真实版本 | operation 元数据及纯环境函数，空序号/真实版本 ID |
| Node `npm start` 自动执行生命周期 | 隐式运行未声明的 prestart/poststart | `startup_command` 直接执行 scripts.start |
| source_facts 会写 stub | 入口检查改变包内容和依赖缓存键 | 仅提取纯 static selector，不调用整个 inspector |
| Vite 根 index 可能是源码，dist 是成品 | 根优先会选择错误站点 | built 判定及 post-build selector |
| CLI 消费 tail 列表，而运行事实保存字符串 | 日志存在但终端仍为空 | D3 白名单适配；CLI 人类/JSON 两路 |
| 通用失败处理先清理执行体 | 日志无法补取 | 启动失败点先取日志；受控补抓再清理 |
| 发布失败长期保存，运行诊断有保留期 | 将 tail 复制到发布记录会绕过过期清理 | `_fail()` 不持久化日志；公开读取适配按原诊断到期时间补充 |
| 终态清理、取消或数据恢复不是启动失败 | 错误码误导，掩盖数据已变化 | 操作 kind/stage 组合分类，保留标志 |
| registry manifest 存在不证明层可读 | 轻量 HEAD 会把坏镜像报告为可用 | K8s 检查实际层；启动阶段继续核验 |
| backend 镜像不包含 CLI 源码目录 | 测试源码绿、实际安装仍旧 | wheel/manifest 同步及空 venv 安装验证 |

## 6. 对外契约与依赖

### 6.1 提供的合同

| 接口/格式 | 消费者 | 兼容与风险 |
| --- | --- | --- |
| `POST /api/v2/apps/deploy` 的新清单正规化 | CLI/开放发布调用 | 只影响此次新提交；显式 1 及历史固定组合保留 |
| `GET /api/v2/apps/deployments/{id}`、发布状态及现有 MCP 状态 | CLI/平台管理面 | 五元组不变，安全 details 增加 tail/可用性；旧客户端可忽略新增项 |
| `GET /api/v1/apps/{app_id}/runtime/operations/{operation_id}` 的合法摘要 | 有权限管理者 | 维持 edit 对详细失败/日志的限制，不公开内部 operation document |
| manager `runtime_environment` / `startup_command` / static selector | Docker/K8s/helper | 小型纯函数，输出固定，不签发凭据或操作存储 |
| CLI wheel + `artifacts/manifest.json` | 平台下载与 dev-toolkit versions | 源码版本、wheel METADATA 和 manifest hash 一致；SDK 条目保持 |

### 6.2 依赖的合同

| 依赖 | 风险点 |
| --- | --- |
| F048/F113/F114 真实主体、六动作和运行阶段授权 | 详细日志不能因为已有轮询权而泄漏；检查 Job 必须纳入原操作的阶段围栏 |
| F055 AppDeployment/AppVersion 固定语义 | 不重新解释历史清单，不在预检创建伪版本或放开必审 |
| F086 RuntimeProfile/Delivery/Operation/Artifact | image ID 与 digest 含义不同，材料必须绑定 app/tenant/profile/platform；SQL 仍为操作主数据 |
| F059 plan/resource/admission/egress | 新检查 purpose 的登记、模板、网络与清理同步，否则 fail closed；不增加 nodes 等集群读取权限 |
| 固定 Python/Node/nginx runtime、preparer、K8s helper/crane | 镜像身份与工具分发不可混用；trusted helper 增加工具后需新镜像并在部署清单核验 |
| 现有 Docker Engine/K8s/registry | 检查与启动间仍可能变化；当前检查不是未来可用性证明 |
| `scripts/pack_cli_wheel.sh` 与 backend artifacts 打包 | 构建或空环境安装失败则不能标记 CLI 已交付；不得删除 SDK wheel |

## 7. 测试、可观测与部署

### 7.1 定向验证策略

仅运行本次修改的测试和质量检查，不跑全量套件：

- backend：新输入缺省/显式 1/历史缺版本/非法版本；运行元数据；prepare 首次/重试同一失败；启动和非启动错误分类；tail 白名单、脱敏、edit 拒绝、未复制到发布记录、到期即时不可读；不新增数据库兼容性专用生产探针。
- manager：Python/Node 全部回落和优先级、路径逃逸、npm 生命周期；四种 static 位置及真正 build 输出；环境函数 Docker/K8s 一致、预览数据库独立；Docker 缺 runtime 在依赖前失败、ID/架构/标签漂移和 maintenance 前拒绝；启动取日志先于清理，40 行/16 KiB 与敏感片段不泄漏。
- K8s 合同：image-check plan/模板/admission/Secret/网络/资源回收、具体失败与超时；helper/preparer/runtime 校验分别覆盖，验证不取得生产挂载、不执行应用源代码、不推送 OCI。只做本地 fake-client/受控 registry 合同测试，不把它写成 189 实测。
- CLI/材料：终端和 JSON 的同一原始 code/reason/tail、旧 16124、无日志；官方三个示例合同；wheel 空 venv 安装及平台分发 manifest/hash。只运行受影响的 ruff、arch-guard、i18n 与构建检查。

### 7.2 真实环境验收

执行真实部署前，先核对待部署提交、不可变镜像和 116 当前平台服务；仅按实际授权更新。新建专用 `e2e-f119` 测试资源与服务账号，遵守实际权限和审批流程，会话/明文密钥只在进程内使用。

验收顺序：

1. 在临时目录建立空 venv，安装平台下载的 CLI wheel，核对 `bisheng --version` 及版本 manifest；`bisheng login http://192.168.106.116:3001 --api-key <内存中的专用密钥>`。
2. `bisheng skills sync`，复制官方 Python 示例，运行 `bisheng deploy <示例目录> --json`；通过真实审批后从返回的 `/apps/{slug}/` 访问，写入并读取一条数据库记录。只对该临时应用停止/上线一次，再读同一记录。
3. Node 用 `index.js` 或 package.main 的最小程序，依赖材料完整时发布一次；static 用 public/index.html 及一个有效 build 产物的定向验证。必要失败分支主要由本地测试覆盖；不得为制造失败删除共用 runtime 镜像或修改其它正式应用。
4. 核对部署失败的 CLI 与管理状态可读，publish-only 不能读取 tail；检查镜像/平台版本。删除临时资源，检查原应用和策略未变。

只有实际跑过的步骤才记通过；镜像版本、官方材料/CLI、运行服务升级、Docker 主流程与 K8s 合同证据分别记录。116 Node 的既有镜像烟测不重复冒充上述结果；不更新 189 或其它环境。

### 7.3 可观测与失败回退

沿用 operation_id/deployment_id、runtime stage/reason、cleanup_status、maintenance/data_may_have_changed 与现有诊断到期时间。记录缺失镜像角色/安全引用，禁止记录 registry 认证、业务密钥或解封 payload。

部署清单必须包含 backend/worker 对安全错误适配的版本、manager/helper 对运行合同的版本、CLI wheel/hash。滚回代码不重解释已固定的新版本或恢复旧 RPC；已发布版本继续固定原 RuntimeDelivery。若回滚会使新增默认合同不可读，应停止新提交并保留固定数据，另行受控处理，不自动迁移或重建。

### 7.4 AC 覆盖

| 规格 | 设计位置 |
| --- | --- |
| AC-01、AC-02、AC-03、AC-04、AC-05 | D1、§4.3、D6 |
| AC-06、AC-07、AC-08、AC-09、AC-10、AC-11 | D2、§4.4、§4.8、§7.2 |
| AC-12、AC-13、AC-14、AC-15、AC-16 | D2、§4.4 |
| AC-17、AC-18、AC-19、AC-20 | §4.5 |
| AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27 | D3、D6、§4.6、§6、§7.1 |
| AC-28、AC-29、AC-30、AC-31、AC-32 | D4、§4.7 |
| AC-33、AC-34、AC-35、AC-36、AC-37 | D5、§4.8 |
| AC-38、AC-39、AC-40、AC-41、AC-42 | §4.8、§7；代理 5xx 保持原样；容量只改善已有原因提示，不改预算或并发算法 |

## 8. 后续改进与当前不做

- 不引入常驻镜像库存、自动包仓或新依赖解析框架；当次固定输入检查及既有材料导入已覆盖本次根因。
- 不全面审计任意完整镜像的应用健康语义，不把 `<500` 改成统一必须 200；静态入口问题通过产物检查解决。
- 不补历史失败日志，不改变日志保留期限；没有原始输出不伪造。
- K8s 全层检查有网络与耗时成本，需在定向测试中记录；不能以 `--fast` 的层跳过或全平台放行掩盖不可用。若证据要求改变已确认规格的检查时点/能力，按偏差规则重新确认。
- 116 兼容构建基础镜像缺失仍是单独环境事项。新默认 bundle 与官方示例修复不以补齐所有 legacy tag 为前置，不以此次 Node 补齐声称所有依赖可用。

## 修订历史

| 日期 | 改动 | 触发原因 |
| --- | --- | --- |
| 2026-11-03 | 初版设计评审稿；明确尚未实施 | 用户确认 42 条规格，进入设计 |
| 2026-11-03 | Wave 1已实现：运行环境纯函数、固定metadata、入口与静态产物选择；K8s模板复用PATH常量 | 续作，定向验证见verification.md |

| 2026-11-03 | Wave 2/3实现：保留期内edit诊断、清理前脱敏输出、固定镜像检查和原生发行脚本合同；CLI post2及三语文案同步 | 续作，真实服务镜像/E2E待执行 |
| 2026-11-03 | 编号顺延F119，原42条AC及范围不变 | 最新发版线F118已登记118-project-new-chat |

### 实施落点补记

- 运行纯函数由`lifecycle.build_env()`、Docker `BundleLauncher`、K8s `_plan()`共同消费；K8s模板引用同一PATH常量。
- `image-check`复用已有Pod资源与原动作阶段授权，不增加业务阶段或权限动作。backend的`runtime_image_check_policy`/`RuntimeKubernetesService`核对固定目标文档的hash、可信helper、检查命令和无生产/源码挂载；admission对目的补基线限制。
- 沿用已有egress-bindings RPC增加仅用于检查的`image-check` phase。允许来源只由固定镜像registry及安装侧既有认证端点计算，不继承应用egress domains，也不在依赖安装/编译或应用运行期放开网络。仅安装侧已声明HTTP的目标registry使用`--insecure`，其它registry维持TLS。
- 该检查只读registry，实际运行Pod仍由原imagePullPolicy、Pod UID/imageID、就绪和停止围栏控制。成功检查Pod保留可信终态与finalizer供同操作重启采用，原操作cleanup再请求删除/确认停止；超过120秒的旧检查不继续放行。helper包含项目原有固定crane工具及license，assembler继承helper；不要求bundle配置assembler。
- 失败JSON仅增加经过格式检查的`image_role/image_ref`安全材料引用；终态清理重试保留原值，不复活到期日志。公开读不解封payload，发布记录与审计不复制tail；runtime management同样按查询时间剔除过期输出。
- 审查范围追加`runtime_secret_diagnostics`、`runtime_management_service`、`runtime_operation_service`以闭合后端保留期和安全上下文；不修改ORM、数据库或现存正式应用。
