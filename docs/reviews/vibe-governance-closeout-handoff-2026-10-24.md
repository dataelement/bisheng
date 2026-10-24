# Vibe 应用治理收尾提测报告

日期：2026-10-24。分支：`codex/vibe-governance-closeout`。本轮起点：`818a12968`。实现提交见本报告的源码版本说明。

## 1. 当前结论

**F055 环境变量、F054 两项安全收尾、F056 运行记录查询和导出的主功能已编码，进入集中提测。** F055 简化设计及 F054/F056 修订设计均已获用户确认。按用户要求，本轮只做本功能定向验证，没有运行项目全量测试。

本报告区分本地验证和真实部署：本轮没有向 109/189 部署这些改动，没有执行宿主防火墙、真实 Docker/K8s 业务 E2E，也未完成最终 SDD L2 或合入。历史主流程验收不能代替本轮增量验收。没有公开推送、创建 tag 或发行镜像。

| 功能 | 实现内容 | 本地状态 | 提测重点 |
|---|---|---|---|
| F055 环境变量 | 单表加密保存；保存不重启；显示运行配置与最新配置的差异；owner 确认后复用部署流程重建；预检和审批预览不注入真实值 | 前序定向结果见 F055 验证记录 | 保存/确认重建/失败恢复，Docker 与 Pod 实际注入 |
| F054 OBO | 正式及预览入口检查专用非空签名密钥；保持登录、存在性、租户和权限检查顺序；校验与签发使用同一配置快照；代理不复用允许缓存 | 定向通过 | 无效配置拒绝，正常 HTTP/WebSocket 可用，三语提示 |
| F054 宿主隔离 | 独立 root 宿主 timer 维护规则并执行真实 canary；独立角色签名上报；证明过期/失效阻断新执行和路由提交；manager 保持非 root | 规则、适配器和报告模拟通过 | 真实 INPUT/FORWARD、iptables/nft、规则漂移和证明 TTL |
| F056 运行记录 | 审计页新增模型、能力、访问三类记录；管理员当前作用域校验；历史候选、冻结游标、异步完整 CSV、受权下载及取消/清理 | 定向通过 | 真实记录可见、分页完整、权限允许/拒绝配对、导出一致 |
| F056 凭据审计 | 从可信应用主体建立 app 关联；真实 binding 回收与审计同事务；旧实例回收/失败/停用/删除接线，重放不重复记回收 | 本地真实 SQLite 事务通过 | 部署/更新/停用的实际签发及回收事件可查 |

## 2. 交付位置与调用链

- [F054 设计](../../features/v3.0.0/054-app-domain-runtime/design.md)、[任务](../../features/v3.0.0/054-app-domain-runtime/tasks.md)、[验证与 AC 映射](../../features/v3.0.0/054-app-domain-runtime/closeout-validation.json)。
- [F055 验证](../../features/v3.0.0/055-app-publish-pipeline/manual-apply-validation.md)、[E2E 清单](../../features/v3.0.0/055-app-publish-pipeline/e2e-checklist.md)。部署加密密钥轮换仅是运维说明，没有新增轮换功能。
- [F056 设计](../../features/v3.0.0/056-app-square-governance/design.md)、[任务](../../features/v3.0.0/056-app-square-governance/tasks.md)、[验证与 AC 映射](../../features/v3.0.0/056-app-square-governance/closeout-validation.json)。
- [宿主隔离安装说明](../../deploy/runtime-manager/README.md)、[定向执行证据](./evidence/vibe-governance-closeout-2026-10-24/)。

```text
浏览器 → nginx → app-proxy → backend 入口授权/OBO 校验 → 应用
应用 → 既有 SDK/平台接口 → 三类事实记录
管理员 → backend 查询/导出任务 → Celery → 私有 MinIO 分块+manifest
管理员 → backend 再次校验作用域 → 流式下载 CSV

Docker 宿主 root timer → Engine 检查+自有防火墙+canary
                       → 独立 HMAC 上报 backend（60 秒证明）
manager → backend 读取证明 + 实际 Engine descriptor 比对 → 允许新执行
K8s → 延用 F059 能力证明，不读取 Docker 宿主证明
```

查询接口为 `/api/v1/app-runtime-audit/records/{kind}` 与 `/candidates/{dimension}`；导出为 `/exports`、状态、取消和 `/download`。只接受平台自然人会话，服务凭据不获得管理查询权。源记录只返回白名单元数据，不导出 prompt、响应正文、环境变量值、密钥或 OBO token。凭据只显示掩码。

## 3. 已执行的必要验证

下列是分批定向结果，跨命令用例存在重叠，**不能直接相加为独立总数**。原始输出保存在证据目录；机器可读验证文件记录源码和输出摘要。

| 范围 | 实际结果 | 证据边界 |
|---|---|---|
| 新查询、导出、凭据审计、报告等收尾批 | 30 passed；后续逐问题补测 | SQLite/替身资源，不是真实平台部署 |
| OBO 正式及预览 | 48 passed | 包括无效 key、配置快照、签发和拒绝顺序 |
| 代理页面和旧 allow 缓存 | 5 passed；HTTP 缓存回归另 4 passed | 渲染/MockTransport、loopback fake upstream |
| manager 隔离、门禁和 legacy 状态 | 9 passed | 未执行真实防火墙命令 |
| 宿主报告与导出租约交接 | 5 passed | 模拟证明和本地数据库 |
| 下载完整字节数 | 1 passed | 固定 CSV/manifest |
| 审计页 | 两文件 9 passed；候选分页修改后只重跑对应组件 4 passed | 组件测试，非浏览器业务部署 |
| 真实环境脚本 | 4 条 collected | **未执行，不计通过** |
| Python / 架构 / 打包配置 | Ruff 通过；逐文件架构守卫无 VIOLATION；单 Alembic head；Compose/角色配置、bash 语法和三语 keys 检查通过 | settings.py 一条既有 RULE7 warning 保留 |
| 前端 | 改动文件 ESLint 通过，无新增类型错误 | 全部类型检查仍被两条既有问题阻塞，见下 |

两条类型基线问题：`BuildPage/bench/OrgKbConfig.tsx` 缺 `@hello-pangea/dnd` 声明；`test/clientVoiceDraft.test.tsx` 参数签名不符。本轮未更改这两个文件，也没有新增豁免。F055 前序审批卡 Jest 用例因缺少 `canvas.node` 未执行，仍如实保留。

L1 七维度阶段结果为 **PASS_WITH_NOTES**，详见两个 feature 的 closeout-validation.md；任务拆解审查已完成。真实 E2E、最终 `/sdd-code-review` 和合入门禁仍待完成，不能据此宣称整个 Vibe 全部 AC 通过。

HTML 为离线文件，章节、链接和响应式/打印 CSS 已静态检查；浏览器安全策略拒绝 `file:` 协议，本轮未完成宽屏、窄屏与打印的视觉验收。

## 4. 部署前置条件

1. backend、默认 Celery worker、Beat、app-proxy、runtime-manager 和前端使用本轮源码构建。Compose 中既有公开镜像标签不会自动包含这些代码；本轮没有发行新镜像。
2. 对已有数据库执行 `alembic upgrade head`，新增 `app_access_log.app_name_snapshot` 可空列，无历史回填。新查询快照、导出任务、宿主证明表通过项目现有模型发现/create_all 路径创建。升级时确认实际 schema 齐备，不只检查进程健康。
3. backend/worker 使用一致的平台存储和加密配置，私有 `bisheng-apps` 桶允许创建、读写和按任务前缀清理。导出不依赖 API 主机本地目录；Beat 每 30 秒续办/清理，默认 worker 必须消费相应任务。
4. `BISHENG_RUNTIME_AUDIT_SOURCE_TIMEZONE` 应匹配现有三类记录的无时区数据库时间约定；未设置时使用进程 `TZ`，再回落 UTC。查询将请求 UTC 转为源时区，输出转回 UTC，快照冻结源时区；不做旧记录重写。
5. F055 部署加密密钥沿用运维配置，勿在聊天、仓库、日志或测试报告内写真实环境变量值。配置保存不触发重启，只有用户确认应用后进入既有重建流程。
6. **Docker 必须先按安装说明启用宿主隔离单元**：宿主 Python 包、可用 Engine API、明确的 iptables/nft 后端、IPv4 internal 应用/构建网络、受控 egress、固定 digest 的 Python canary 镜像，以及实际监听的管理探测目标。宿主工具可用宿主 socket；使用受限 API 代理时需明确允许检查和 canary 的 create/exec/start/stop 操作。不要求宿主 Docker CLI，不给 manager root/NET_ADMIN。
7. backend 独立配置 `host-isolation` 角色 HMAC 密钥和 node descriptor，manager 保留 `manager` 角色。先生成 descriptor、更新映射，再启动宿主 timer 和 manager。报告有效期 60 秒，每 30 秒真实重探；心跳不能代替宿主证明。每 Engine 一个宿主单元，覆盖该节点应用和构建网络。
8. K8s 不安装 Docker 宿主单元，保留 F059 的集群准入、CNI、PVC、镜像与权限前置条件。

## 5. 提测执行顺序

优先覆盖核心功能，不进行项目全量回归。所有测试使用专用应用和非生产资源，记录源码 SHA、镜像 digest、部署配置及脱敏请求结果。

| 顺序 | 场景 | 通过标准 |
|---|---|---|
| 1 | 109 Docker 宿主安装 | 证明 ready；实际 host/gateway 管理端口拒绝、egress 允许；HTTP 入站回包可用；明确记录采用的防火墙后端 |
| 2 | F055 保存与应用 | 修改后实例 ID 不变，界面显示差异；owner 确认后才重建，运行值更新；失败不错误显示已生效；缺值可见且不泄露值 |
| 3 | 正式发布与审批预览 | 正式批准实例注入真实值；未批准预检/预览只得到声明名与空值；正常 HTTP/WebSocket、升级、停用及恢复可用 |
| 4 | 三类真实记录 | 经应用 SDK 发起模型与能力调用、经入口访问，查询对应应用/访问者/凭据/时间，空值及历史名称正确 |
| 5 | 查询与完整导出 | 全部筛选记录跨页无重复遗漏；异步状态和取消可用；CSV 与冻结选择一致，包含全部行；下载无公开对象 URL |
| 6 | 权限配对 | 当前租户管理员允许；普通用户、跨租户、服务凭据拒绝；超管切换管理范围后不能继续读旧范围任务或下载 |
| 7 | 凭据审计 | 发布签发/旧实例回收/停用的事件从可信绑定归属到应用；回收重放不重复，失败事务不留下虚假审计 |
| 8 | 安全增量 | OBO 空/空白/共用会话 key 拒绝，不泄露身份；修复后下一请求恢复。宿主证明过期/规则漂移拒绝新执行及路由，清理入口仍可用 |
| 9 | 189 K8s 对应业务 | 复验上述环境变量、发布/预览、三源查询/导出、权限和回收；保持 F059 网络能力约束，记录 Pod/Secret 实际行为 |

真实 API 脚本：[test_e2e_vibe_governance_closeout.py](../../src/backend/test/e2e/test_e2e_vibe_governance_closeout.py)。它要求预先发布一个 `e2e-f056-` 开头的专用应用，并经真实入口/SDK 生成至少一条模型、能力和访问记录。它不负责部署、播种或修改宿主规则，不能作为全部场景的自动覆盖。

测试机安全注入 `F056_E2E=1`、`E2E_API_BASE`、`F056_E2E_APP_ID`、`F056_E2E_TENANT_ID`、`F056_E2E_TENANT_ADMIN_TOKEN`、`F056_E2E_USER_TOKEN`、`F056_E2E_FOREIGN_TENANT_ID`。管理员必须是租户管理员而非全局超管；执行期间专用应用的模型调用记录保持静止，便于核对冻结导出的完整 ID 集。

```bash
# From src/backend; credentials are already injected by the test environment.
uv run pytest -q test/e2e/test_e2e_vibe_governance_closeout.py
```

脚本只取消自己创建的导出任务；不删除应用、源记录、容器或 PVC。快照与导出产物由到期清理管理。

## 6. 暂缓和已知边界

- 按用户口径，DM8 只核对通用模型/DDL/约束，未实测驱动或流式导出；arm64 暂不测试；189 单节点不证明跨节点恢复。
- 真实 nft 版本兼容、INPUT/FORWARD 与 canary 必须在部署验收验证，本地生成规则通过不能替代。
- 低概率组合先列待验：超长暂停旧导出 worker 在 GC 后晚到上传、跨节点时钟偏差、历史混合/DST 时区、宿主网络单向分区和组合故障收敛。本轮不继续扩展状态机。
- F055 重建进入维护态后失败，使用既有下线/重新上线入口恢复；界面有提示，不新增自动重试/自动重启。
- 原 F056 AC-32 涉及的**既有系统操作审计导出仍有历史行数上限**；本轮批准设计保留旧审计实现，完整异步导出覆盖新增三类运行记录。该历史差异未修复，不标记整个 F056 所有旧 AC 完成。
- 尚未完成：真实部署 E2E、剩余任务验收勾选、最终 L2、分支合入及正式镜像发行。

## 源码版本说明

本报告与源码一并本地保存；实际实现提交将在提交后补记，机器可读验证文件的 `source_commit` 指向同一源码提交。它固定的是源码版本，不代表镜像已发行或环境已升级。
