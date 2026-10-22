# F059 E2E 验证清单与执行入口

## 1. 当前证据边界

此文件交付的是可执行的业务 API 行程和完整 AC 映射。**本次 C 线尚未连接 189 或 109；下表真实环境状态全部为“未执行”**。本地测试、模拟客户端和 Chart 静态检查不能证明部署验收通过。完成真实运行后，由主 agent 将脱敏事实写入 `e2e-evidence/installation.*`、`real-platform.*`、`fault-upgrade.*`，保留每条 AC 的部分覆盖与环境限制。

189 是单节点 amd64；不承诺或声称 arm64 原生、跨节点卷迁移、节点失联自动恢复通过。DM8 只做已确认的模型与迁移静态检查。

## 2. 运行前置与身份

- 已部署真实 backend、Celery、SQL、Redis、OpenFGA、MinIO 和 F059 运行时；不能把 manager API 或 mock transport 当平台 E2E。
- 已创建专用 **非根** `e2e-f059-` 租户，配置单节点、单审批人的应用发布审批场景，审批人必须是与 owner 不同的自然人；自动审批不覆盖预览/人工决定行程，脚本会拒绝它。
- owner、同租户普通 nonowner、另一专用租户 foreign、同租户 approver 是四个不同的 `e2e-f059-` 用户，不能为平台超管。nonowner 不能是租户管理员，也不能被授予应用权限；owner 保持 app 默认独占权限。
- 平台超级管理员仅创建/确认测试租户及读取全局运行诊断，不代替 owner 做数据或删除操作。CLI API key 必须是该 owner 的 mode-S、`app:manage` 凭据。
- 验收包的 name 和精确 slug 均以 `e2e-f059-` 开头，manifest 必须位于包根。预供离线 wheelhouse/npm材料、冻结profile、运行镜像和（仅source-image）内网仓库。
- 所有环境变量在专用进程中通过安全注入设置。禁止把密码、API key、kubeconfig、HMAC 或许可证写入脚本、JSON、Git、日志或命令行参数。

| 环境变量 | 内容 |
| --- | --- |
| `F059_E2E` | 显式 `1`，否则 pytest 跳过，CLI 拒绝 |
| `E2E_API_BASE` | 目标平台 `/api/v1` 地址，使用共享 auth helpers 的同一地址 |
| `F059_E2E_ENTRY_BASE` | app-proxy/nginx 统一入口 origin；脚本核对实际 entry_url origin |
| `E2E_ADMIN_USERNAME`、`E2E_ADMIN_PASSWORD` 或 `E2E_ADMIN_TOKEN` | 仅专用环境的平台超管认证；共享 helpers 完成 RSA 登录 |
| `F059_E2E_TENANT_CODE` | 已准备的专用 `e2e-f059-` 非根租户代码 |
| `F059_E2E_OWNER_USERNAME`、`F059_E2E_OWNER_PASSWORD` | 自然人 owner |
| `F059_E2E_NONOWNER_USERNAME`、`F059_E2E_NONOWNER_PASSWORD` | 同租户普通 nonowner |
| `F059_E2E_FOREIGN_USERNAME`、`F059_E2E_FOREIGN_PASSWORD` | 其他测试租户普通用户 |
| `F059_E2E_APPROVER_USERNAME`、`F059_E2E_APPROVER_PASSWORD` | 独立审批人 |
| `F059_E2E_OWNER_API_KEY` | 与 owner 相同资源所有者的 open API key |
| `F059_E2E_SCENARIOS` | 下述无凭据 scenario JSON 文件的绝对路径 |
| `F059_E2E_TIMEOUT` | 单阶段轮询上限，默认600秒，允许30–1800；恢复期限验收应设300 |
| `F059_E2E_EXECUTOR` | 默认kubernetes；同一行程在专用Docker可设docker |
| `F059_E2E_EVIDENCE` | pytest 可选私有证据文件位置；CLI 必须传 `--evidence` |

脚本逐用户访问 `/user/info` 与 `/user/current-tenant` 确认身份，API key 在任何发布前经 `/api/v2/auth/whoami` 核对 mode-S、app:manage、租户与自然 owner；发布后再用 session GET 核对 app。`ensure_test_tenant` 复用共享 helper；如果环境禁止创建或用户尚未归属该租户，必须先正确准备，不可改为 root 租户运行。

## 3. Scenario 文件与真实应用

```json
[
  {
    "slug": "e2e-f059-python-bundle",
    "package": "/opt/e2e-f059/packages/python-bundle.tar.gz",
    "update": "/opt/e2e-f059/packages/python-bundle-code-update.tar.gz",
    "mode": "bundle",
    "table": "items",
    "row_key": "1",
    "update_values": {"name": "e2e-f059-persisted"},
    "entry_path": "/",
    "expected_text": "e2e-f059-python",
    "application_checks": [
      {"path": "/e2e/sdk-storage-roundtrip", "expected_json": {"ok": true}},
      {"path": "/e2e/model-obo", "expected_json": {"ok": true}}
    ],
    "websocket_path": "/ws"
  },
  {
    "slug": "e2e-f059-missing-wheel",
    "package": "/opt/e2e-f059/packages/missing-wheel.tar.gz",
    "mode": "bundle",
    "expected_failure_code": 16227,
    "expected_failure_stage": "precheck_build"
  }
]
```

上例是参数形状，实际失败 stage 必须从已批准的部署合同与 fixture 确认，不能为让测试变绿而改期望。`update` 是同 runtime/交付模式的新版本包；脚本不代替 CLI 打包、锁依赖或生成轮子。完整验收须准备 Python/Node/static bundle、完整 image、显式 source-image、离线缺包/坏摘要/错架构/镜像拉取/健康失败等专用包。

`application_checks` 是应用实际执行 SDK/模型/OBO 的测试入口，不是 backend 绕过身份的管理接口：每个回调自行调用 SDK0.1.1 后返回无敏感信息的结果，需审查 fixture 实现并保留服务端调用证据。未配置、未执行、或只返回固定 `ok` 都不能算 SDK 验收。`websocket_path` 指向真实 echo 端点，脚本断言 owner 收发及 nonowner 在 upgrade 前被拒绝；连接撤权期限还须执行下述人工故障步骤。

## 4. 分阶段、可续跑命令

在仓库根使用 Python3.11 和 backend 测试依赖；不要运行多个验收进程并发修改同一套测试应用。

```bash
python scripts/e2e_k8s_runtime.py --stage installation --evidence /tmp/e2e-f059-api.json
python scripts/e2e_k8s_runtime.py --stage platform --evidence /tmp/e2e-f059-api.json
python scripts/e2e_k8s_runtime.py --stage observe --evidence /tmp/e2e-f059-api.json
python scripts/e2e_k8s_runtime.py --stage fault-upgrade --event manager-restart --checkpoint before --evidence /tmp/e2e-f059-api.json
# Operator serially restarts only the dedicated manager and records UID/time.
python scripts/e2e_k8s_runtime.py --stage fault-upgrade --event manager-restart --checkpoint after --evidence /tmp/e2e-f059-api.json
python scripts/e2e_k8s_runtime.py --stage cleanup --evidence /tmp/e2e-f059-api.json
```

- `installation`：真实平台诊断与权限；必须先有安装工具的实际集群探测，不能以此代替。
- `platform`：setup 精确清理上次同 slug 的测试应用，逐包 deploy→轮询→预览→审批→上线→GET→日志/权限/数据/CSV→停用恢复→可选版本更新。为后续故障验收保留本次应用与 journal；失败也保留可诊断现场，随后显式 cleanup。
- `observe`、`cycle`：续用 journal，再按当前后端事实与自然 owner 核验，分别只读行程或停用恢复。
- `fault-upgrade`：支持 manager-restart、runtime-upgrade、app-restart 的 before/after 观察。**不触发故障**，after不自动等待实例健康；操作者须在恢复期限内运行并附实际Pod/Deployment UID与时间。journal 标明 `injection_verified=false`，单凭这个结果不能声称注入已完成。
- `all`：完整业务行程，setup清理＋finally teardown清理；pytest 同样双重cleanup并共享 class 事件循环。仅使用 `--stage all` 时失败finally也可能删除诊断实例，先保存日志。
- `cleanup`：只遍历场景文件中的精确 slug；fresh GET 再核对同租户、同自然 owner、name前缀，online先停用再删除，最后GET精确16101。不删除租户/用户、全体前缀、非测试资源或未知writer；失败必须保留给主agent处理。

```bash
python -m pytest -q src/backend/test/e2e/test_e2e_vibe_k8s_runtime.py
```

测试代码复用 `helpers/auth.py`、`helpers/api.py`、`helpers/cleanup.py`；新增 `helpers/vibe_runtime.py` 为该 feature 的共享行程。禁用 opt-in 时4项测试跳过，不能计为真实通过。journal 原子保存为0600且拒绝凭据字段；API/SDK错误响应体不写CLI日志。完成后清理私有运行目录中的凭据、临时包和只含测试行的证据。

## 5. 55 条有效 AC 追溯

下表覆盖职责分类，不是“55条已通过”。API表示脚本能够覆盖其中业务部分；组合AC仍需补齐基础设施/人工证据。AC-38已退役且不复用。

| AC | 验证类型 | 实际入口与必留证据 | 真实状态 |
| --- | --- | --- | --- |
| AC-01 | API＋配置静态 | installation；确认 executor_kind=kubernetes、protocol_version=2；另核对部署开关不可运行期切换 | 未执行 |
| AC-02 | API＋人工 | platform；人工检查广场/详情/CLI/MCP、未部署入口及四类兜底页 | 未执行 |
| AC-03 | 基础设施真实 | 检查所有 Pod 实际 env/mount/SA；仅 manager 获得命名空间 token，其他进程实际 API 请求拒绝 | 未执行 |
| AC-04 | API | platform：真实 deploy、部署轮询、审批、日志、启停；销毁由 cleanup 验证 | 未执行 |
| AC-05 | API＋基础设施真实 | platform 审批预览/正式上线；比对 Pod UID、探活事实及路由提交顺序 | 未执行 |
| AC-06 | 故障注入＋API | app-restart before/after；人工记录真实退出、故障时刻及 ≤300 秒恢复；单节点本地卷不证明跨节点 | 未执行 |
| AC-07 | 故障注入＋API | manager-restart before/after；停止 manager 超过短缓存期，独立观察新入口与既有 HTTP/WS/CONNECT | 未执行 |
| AC-08 | API＋故障注入 | 负向 package 精确失败码/stage、无版本无审批；审批后制造容量不足，再原单 manual-publish 并核对审批ID不变 | 未执行 |
| AC-09 | API＋故障注入 | 负向 package 缺包/坏镜像/探活失败；核对有界结束及安全原因，恢复失败不能新增业务终态 | 未执行 |
| AC-10 | API＋人工 | observe：真实 instance/logs/versions 范围与权限；人工检验刷新、筛选和敏感信息脱敏 | 未执行 |
| AC-11 | 基础设施真实 | 并发/重试部署时按 app_id 列出所有实际 Pod/UID，任一时刻仅一个正式实例；区分预览与准备 | 未执行 |
| AC-12 | API＋基础设施真实 | observe HTTP与可选 websocket_path；实际非授权Pod直连应用必须拒绝，无逐应用NodePort/LB | 未执行 |
| AC-13 | 基础设施真实 | 安装工具按 manager 身份实际执行允许/拒绝：跨namespace、特权、hostPath、RBAC/exec/status均拒绝 | 未执行 |
| AC-14 | 静态＋基础设施真实 | 交付权限清单与实际RBAC矩阵一致；审计未启用明确标记，不能用普通日志伪造集群审计 | 未执行 |
| AC-15 | 基础设施真实 | 读取真实业务/准备/初始化/维护执行体环境、挂载及进程；不可取得manager、MinIO、SQL或集群身份 | 未执行 |
| AC-16 | 基础设施真实 | 实测非root、只读rootfs、代码/venv不可写、capabilities全部丢弃及资源限制；只允许明确工作目录 | 未执行 |
| AC-17 | API＋基础设施真实 | 通过既有档位API修改/禁用，现有Pod资源冻结不变，下次发布按新档位；拒绝停用档位 | 未执行 |
| AC-18 | 故障注入 | 在独占测试应用制造内存/CPU超限，旁路观测平台和第二个测试应用仍可用，不耗尽整个集群 | 未执行 |
| AC-19 | 基础设施真实 | 实际不可用RuntimeClass时记录默认档回退与告警；不声称已启用更强沙箱 | 未执行 |
| AC-20 | 基础设施真实 | 切换部署隔离档复跑身份、网络、资源和卷单写矩阵 | 未执行 |
| AC-21 | 基础设施真实＋应用API | 成对测试可达受控egress与不可达DNS/公网/平台/其他应用/API；已建立连接撤权须计时 | 未执行 |
| AC-22 | 基础设施真实 | 逐准备阶段实测允许端点与拒绝端点；offline安装不得访问公网fallback或生产数据库 | 未执行 |
| AC-23 | 故障注入 | 破坏专用namespace必需隔离并重探，准备/上线/维护实际拒绝；恢复并重新验证后才放行 | 未执行 |
| AC-24 | API＋基础设施真实 | platform 各bundle场景；观察代码变化无新OCI镜像构建/推送，记录冻结profile/artifact | 未执行 |
| AC-25 | API＋基础设施真实 | 至少Python3.11/Node20/static bundle、完整image、source-image五个scenario；无仓库只阻断source-image | 未执行 |
| AC-26 | API＋基础设施真实 | 真实应用包在执行Pod物化，分别检查backend持久产物、镜像可取得和无应用推送仓库bundle发布 | 未执行 |
| AC-27 | 基础设施真实 | 镜像pull/build Secret只在受控位置；业务env/mount/日志无仓库凭据 | 未执行 |
| AC-28 | API | 配置负向scenario的expected_failure_code和expected_failure_stage；缺包/错架构/坏摘要/拉取失败均精确断言 | 未执行 |
| AC-29 | API＋基础设施真实 | cycle 停用恢复；清理/缓存丢失后重建当前、待上线、停用引用仍可恢复 | 未执行 |
| AC-30 | 基础设施真实＋API | 安装工具真实逐项探测报告后，installation读取平台ready/preflight；后者不能代替真实探测 | 未执行 |
| AC-31 | 基础设施真实 | 动态SC缺失但合格静态PV允许；硬前置失败拒绝；node-local限制持续可见，可选沙箱回退不越过必需隔离 | 未执行 |
| AC-32 | API | installation 管理员允许、普通owner拒绝；检查真实逐项结果、时间、原因及回退信息 | 未执行 |
| AC-33 | API＋故障注入 | data_roundtrip/CSV、cycle与app-restart checkpoint提交行保持；隔离卷不误共享 | 未执行 |
| AC-34 | 基础设施真实 | 独立预检卷执行flock/SQLite/fsync；NFS/SMB配置拒绝；卷拓扑与节点绑定实际一致 | 未执行 |
| AC-35 | API＋基础设施真实 | cycle保留行；cleanup owner删除后GET16101；升级/卸载前后PV UID/卷内容比对；旧写入者未知不得purge | 未执行 |
| AC-36 | API＋人工＋基础设施真实 | 真实deploy/审批/预览/日志/数据/权限＋可选SDK回调/WS；复用F053/F057/F086既有用例，UI人工复核 | 未执行 |
| AC-37 | API＋人工 | 状态、审批审计、通知与CLI/MCP错误/文案逐项比对Docker；不把Pod内部名字暴露业务页面 | 未执行 |
| AC-39 | 静态＋真实安装 | 按Chart/README完成独立namespace安装、升级、卸载；保存脱敏helm/权限/卷/镜像供应证据 | 未执行 |
| AC-40 | 故障注入＋API | runtime-upgrade/manager-restart checkpoint；实际应用UID不变，行数据不变；代理按排空合同验证 | 未执行 |
| AC-41 | 真实卸载＋人工 | 仅回收安装拥有控制资源，保留PV/代码/依赖/快照/附件；平台其他功能和开关行为正常 | 未执行 |
| AC-42 | 基础设施真实＋API | 断公网使用预灌digest镜像与完整依赖发布/审批/重建；缺依赖必须失败，内网registry仅source-image依赖 | 未执行 |
| AC-43 | 故障注入 | 准备/probe/assemble/maintenance期限、并发与资源超限；实际取消/超时后回收，未知writer保持占用 | 未执行 |
| AC-44 | API＋基础设施真实 | 更新/重建实际Pod，代码与原生环境从backend产物重新构造；移走manager本机缓存后仍成立 | 未执行 |
| AC-45 | API＋基础设施真实 | 代码only update核对同依赖artifact；变更profile/架构/lock/offline材料/安装源码时artifact必须变更 | 未执行 |
| AC-46 | API＋基础设施真实 | data_roundtrip与application_checks触发实际SDK0.1.1附件/能力调用；核对只有backend访问MinIO，业务无MinIO/SQL配置 | 未执行 |
| AC-47 | 基础设施真实＋负向API | 隔离材料身份签发/续期/当前归属；过期、重放、篡改、跨app/tenant、撤销、未确认及坏摘要全部拒绝 | 未执行 |
| AC-48 | 故障注入 | 重复通知、manager重启及多进程竞争；持久事实/审批/正式UID数量与额度一致，无提前释放 | 未执行 |
| AC-49 | 故障注入 | 旧Pod正在删除但停止未知：观察资源与writer归属不释放，新writer不出现；404/NodeLost/超时不能作停止证明 | 未执行 |
| AC-50 | API＋基础设施真实 | 更新/迁移/恢复时记录旧writer停止证据；预览数据与生产隔离，整个窗口无双writer | 未执行 |
| AC-51 | 故障注入＋ownerAPI | 阻断快照确认禁止DDL；DDL后启动失败保留维护状态；owner显式restore保护当前数据并核对快照 | 未执行 |
| AC-52 | 故障注入 | 各阶段取消/超时/kill/响应丢失＋同名UID替换；有界清理，仅未知writer或唯一未确认备份继续占用 | 未执行 |
| AC-53 | API＋计时故障注入 | 可选WS allow/deny＋HTTP/CONNECT撤权/失联期限；manager停用后新访问依据backend投影 | 未执行 |
| AC-54 | 原生架构验收 | 189仅amd64；arm64原生与跨架构负向需独立环境，不能用QEMU/元数据/amd64代替；镜像/材料/API分别核验 | 未执行 |
| AC-55 | 证据治理 | 脚本journal记录实际API；installation/platform/fault evidence逐条记录类别与未验证；非测试资源前后清单相同 | 未执行 |
| AC-56 | 本地＋真实Docker | 相同本地runtime/backend测试与109专用Docker真实发布回归；DM8仅静态模型/DDL，保持发布线修复来源 | 未执行 |

## 6. 危险前置、失败和 UI 清单

- [ ] 安装/故障前后导出脱敏 cluster UID、命名空间与非测试工作负载清单；仅在指定 `e2e-f059-` namespace/路径/PV上操作。
- [ ] 禁止重启共享节点/kubelet/Docker daemon，禁止修改 kube-system、生产包源/网关/防火墙；故障限制到专用 manager、代理、应用与临时策略。
- [ ] RBAC/PSA/准入/网络每项记录一条允许和一条拒绝，包括真实服务端结果、Pod UID、target 与时刻，不只运行 `kubectl auth can-i`。
- [ ] 每个负向失败保留阶段、安全原因、operation ID、cleanup_status；未知writer未清理须显式保留，不能“清场”假装完成。
- [ ] SQLite迁移先记录旧writer停止证明，再确认backend快照已持久化，断上传确认时不得DDL；DDL后启动失败不得自动回滚数据库。
- [ ] 容量不足区分审批前预检失败与审批后pending_capacity；后者原单手动上线无第二审批，前者重新部署。
- [ ] HTTP/WS/CONNECT已建立连接撤权分别计时；manager不可用超过短缓存期仍从backend投影提供新访问判断。
- [ ] UI：应用广场、详情、状态/日志刷新、版本只读、审批预览、数据表/CSV、停用/恢复与删除提示；owner/nonowner/foreign三身份；四类兜底页；刷新后状态持久，控制台无新增错误。
- [ ] CLI/MCP：复跑F053/F052现有真实调用，精确exit/business code和文案；SDK复跑F057真实调用，不能只测harness回调固定值。
- [ ] 升级与卸载：应用Pod UID、PV UID、SQLite行、backend源码/产物/快照/附件引用前后比对；Helm卸载不级联清理数据。
- [ ] amd64本地卷测试明确不覆盖跨节点/arm64；DM8仅静态，不将通用SQLAlchemy DM分支编译写成真实驱动DDL通过。

## 7. L1 自审（交付准备，非真实验收结论）

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| 1 架构分层 | PASS | 测试/harness只调已有平台与app入口；无DAO/SQL/MinIO/集群客户/manager直连 |
| 2 命名与AC | PASS | pytest名称、完整AC docstring、55条有效AC映射；AC-38退役 |
| 3 序列化 | PASS | 真实平台envelope，接受restore等既有202；文件CSV、HTTP/WS按既有原始协议断言 |
| 4 数据库 | N/A | 未添加/改动生产模型或DDL；模型测试仅纠正已交付历史约束 |
| 5 前端 | N/A | 无前端源码；UI列为待人工执行 |
| 6 信息泄漏 | PASS | 凭据仅安全env内存；输出无响应体；600 journal；按自然owner/租户/精确slug重验后清理 |
| 7 设计同步 | PASS | 测试既有对外合同，无新增生产API/决策；实际验收与汇总由主agent完成 |

任务文件归属：T066两个原目标；新增pytest/helper/安全合同测试由主agent独立登记任务。T067文档完整记录本地/真实边界，真实Docker尚未执行，不能因此将整个验收任务标完成。
