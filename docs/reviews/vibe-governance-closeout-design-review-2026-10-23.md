# Vibe 治理收尾 · 增量设计评审

> 2026-10-23 · 设计评审稿 · **等待用户单独确认**。规格已确认；此次增量未编码、未执行产品测试/远端变更。

## 1. 评审入口与阶段

| Feature | 设计 | 本轮范围 |
|---|---|---|
| F054 | [运行时与安全设计](../../features/v3.0.0/054-app-domain-runtime/design.md) | 宿主 INPUT/FORWARD 隔离、OBO 无效拒绝 |
| F055 | [应用密钥设计](../../features/v3.0.0/055-app-publish-pipeline/design.md) | 加密值资产、声明审批、同版本配置刷新 |
| F056 | [运行记录设计](../../features/v3.0.0/056-app-square-governance/design.md) | 三类查询、历史筛选、受权导出、操作事件关联 |

代码事实基线 `5f2541f4bc483c24624fede9031c88c4ec6f58f4`；规格获确认提交 `dda16a6502908ba8d58cff61dc350c0213b86c19`，用户原文“确认规格，进入设计”。确认内容 hash 保留在规格评审 JSON 的 approved_sha256。本次只改文档：更新三份 design、记录 spec 确认、限定旧 tasks 历史状态、登记实现资产，没有新增任务复选框或勾选历史待办。

按 AGENTS.md §6、SDD-Guide §3 与 sdd-review，**此次确认只针对设计**，确认后才做增量任务拆解、tasks 自审、逐任务实现/定向验证、E2E 和 L2。阶段门禁不是技术阻塞。

## 2. 需要重点评审的选择

| 选择 | 方案 | 取舍 |
|---|---|---|
| 密钥保存 | 平台 DB 加密当前值，版本只存名称；只接受自然人 owner 会话写入 | 不给管理员、审批人、SAK/PAT 开写值入口；部署 key 丢失需维护恢复 |
| 值生效 | 新 revision / 持久 intent；同版本 deploy 的 config_refresh 用途 | 不走同版本 shortcut、DDL、备份恢复或新审批；未知 writer 保持阻塞 |
| 预检/预览 | 名称对应空值，构建/preparer 无真实值 | 应用必须第三方 key 才能启动时仍可能探活失败；不伪造预检成功 |
| 记录读取 | 三现有专表只读适配，新“应用运行”页签 | 旧系统审计权限不直接继承到新管理员数据面 |
| 导出一致性 | ≤10,000 行固定 ID 选择集，90 天时间预算、10 分钟产物 | 超限要求缩小条件；不承诺无限数据集快照；文件经认证 backend 下载 |
| 宿主隔离 | root 安装侧维护 INPUT + FORWARD；独立短期报告驱动新部署准入 | 30 秒复核/60 秒过期；不增加 manager root/NET_ADMIN；暂不支持 IPv6/rootless |
| OBO | 配置无效拒绝新入口；启动脱敏诊断；allow 身份不缓存 | 增加授权 RPC，需定向量测；保留路由缓存；既有 WS 不逐帧重鉴权 |

没有新增商业化逻辑；runtime-manager、代理仍开源独立进程，架构边界不回到 Gateway 商业方案。

## 3. 自审结果

采用仓库 **sdd-review design 的 24 项清单**，由同一 agent 自审，非独立多 agent/L2 代码审查。三份设计各检查 24 项，复审结果：

```
LGTM
```

本轮先修正以下设计问题，再复审；不存在以“计划中”代替遗漏项通过的情况：

| 已修订项 | 修订后合同 |
|---|---|
| 旧 allow 缓存可跨过 OBO 配置失效 | 新 HTTP/WS 握手重新授权，route 缓存独立 |
| 只记 last_request_id 不足以长期识别重放 | 新 AppSecretMutation 持久唯一 request_id + HMAC，无值摘要泄漏 |
| 校验错误可能回显非法 secret input | 专属错误白名单过滤 input/ctx/raw body |
| DB 默认 collation 可能合并大小写不同 env 名 | 用公开 name_key 摘要查重，原名精确比较，不用单库 collation |
| 导出并发写入/全局任务租户不清 | 有限精确选择集；作业属于申请者工作租户，global 是授权过滤范围 |
| 新设计资产未登记归属 | release-contract 登记 F054/F055/F056 新资产；不复制原 owner |

### 3.1 逐项复审

| # | 检查 | F054 | F055 | F056 | 证据 |
|---|---|---|---|---|---|
| 1 | 目标简明 | PASS | PASS | PASS | §1 |
| 2 | 非目标明确 | PASS | PASS | PASS | §1 / §8 |
| 3 | 本功能约束 | PASS | PASS | PASS | §2 |
| 4 | Constitution Check 引用与门禁 | PASS | PASS | PASS | §2；release-contract 新资产登记 |
| 5 | 关键决策 | PASS | PASS | PASS | §3（D 编号保留） |
| 6 | 备选、选定与原因 | PASS | PASS | PASS | §3；F054 D6/D12、F055 D17–D20、F056 D12–D15 |
| 7 | 重新考虑触发条件 | PASS | PASS | PASS | 各决策末句 / §8 |
| 8 | 具体证据 | PASS | PASS | PASS | §4.1 / 下方源码证据表 |
| 9 | 主数据流 | PASS | PASS | PASS | §4.1 图与文字 |
| 10 | 字段与 JSON 契约 | PASS | PASS | PASS | §4.4 |
| 11 | 模块做什么 / 不做什么 | PASS | PASS | PASS | §4.3 |
| 12 | 现状与拟实现区分 | PASS | PASS | PASS | 页首 / §4.1 |
| 13 | 反直觉事实 | PASS | PASS | PASS | §5 |
| 14 | 坑的后果 | PASS | PASS | PASS | §5 表 |
| 15 | 处理文件或函数 | PASS | PASS | PASS | §4.3 / §5 |
| 16 | Outgoing HTTP/Python/数据 | PASS | PASS | PASS | §4.4 / §6.1 |
| 17 | Incoming 服务/配置/二进制 | PASS | PASS | PASS | §6.2 |
| 18 | 依赖破坏风险 | PASS | PASS | PASS | §6.1 / §6.2 |
| 19 | 测试层次与范围 | PASS | PASS | PASS | §7；只定向、不全量 |
| 20 | 可操作手验入口/命令/身份 | PASS | PASS | PASS | §7；真实环境尚未执行 |
| 21 | 后续边界与不做理由 | PASS | PASS | PASS | §8 |
| 22 | 修订历史 | PASS | PASS | PASS | 末节，保留旧基线引用 |
| 23 | 规格一致 / AC 追溯 | PASS | PASS | PASS | 下方 52 条映射（48 新增、4 修订） |
| 24 | tasks 偏差认知回写 | PASS | PASS | PASS | 当前基线覆盖历史过期叙述；旧任务状态限定为历史，增量尚未拆任务 |

## 4. 规格追溯（逐条）

下表每个 ID 均按 Feature 完整书写；规格条款原文不再改写。设计为拟实现 How，不代表 AC 已通过。Markdown 与 HTML 均从同一份设计源生成。

| Feature / AC | 确认条款摘要 | 设计落点 |
|---|---|---|
| F054 AC-66 | WHERE 使用受支持的 Docker 单机或 legacy systemd 托管形态, THE SYSTEM SHALL 阻止应用绕过受控出口新建到宿主平台服务的连接，包括经应用网络网关和宿主发布地址访问数据库、backend、对象存储及宿主管理端口；应用经受控出口使用已授权的 SDK、模型和附件能力应继续可用，不因附件业务在 backend 而放开该宿主服务的全部接口。 | D12 / §4.4③④ |
| F054 AC-67 | WHEN 宿主访问隔离生效, THE SYSTEM SHALL 保持统一入口的 HTTP、WebSocket、受控探活及其合法返回流量可用，且不得阻断平台其他业务网络；由应用主动建立的禁止连接不能冒充合法返回流量取得放行。 | D12 / §4.4③ |
| F054 AC-68 | WHEN 安装重复执行、运行服务重启或模块卸载, THE SYSTEM SHALL 分别保持隔离规则幂等有效，或只撤销本模块拥有的隔离规则；不得复制出重复放行规则、清空宿主全局策略或改变无关服务规则。 | §4.4③④ / §7 |
| F054 AC-69 | IF 必需的宿主隔离无法应用、无法确认，或已启用的网络地址族未获得同等保护, THEN THE SYSTEM SHALL 明确报告该运行环境隔离不可用并拒绝把它作为可发布环境；不得只告警后放行，亦不得把未知旧写入者的强制删除当作修复隔离的方法。 | §2 / §4.4④ |
| F054 AC-70 | IF 工场运行时已启用且 OBO 签发配置缺失、仅为空白或与平台会话签名配置相同, THEN THE SYSTEM SHALL 对原本有权进入的正式应用访问返回“本环境配置不完整，请联系平台管理员”状态，不转发到应用、不下发可用身份材料，也不留成功访问记录。 | D6 / §4.4① |
| F054 AC-71 | IF 预览访问发生相同 OBO 配置错误, THEN THE SYSTEM SHALL 同样拒绝进入预览；正式与预览入口都须保留既有登录、存在性、跨租户、访问权限及运行层未部署的判定顺序，不能借配置错误暴露调用者本来无权得知的应用信息。 | D6 / §4.4① |
| F054 AC-72 | WHEN backend 启动且工场运行时已启用, THE SYSTEM SHALL 对上述 OBO 配置错误记录不含任何密钥值的错误诊断；运行时层未部署时不制造已启用该层的假象，正常访问仍遵守原未部署提示。 | D6 / §4.3 |
| F054 AC-73 | WHERE OBO 使用正确且独立的签发配置, THE SYSTEM SHALL 保持现有正式/预览授权、身份注入、防伪头、短时凭据、撤权及 SDK/OBO 调用行为，并以允许与拒绝的配对验证证明本次收紧没有引入匿名降级。 | D6 / §6.1 / §7 |
| F055 AC-54 | THE SYSTEM SHALL 使平台模型、知识库的底层账号与连接配置继续只在原管理面维护；owner 可在应用详情页发布 tab 维护本应用调用第三方系统所需的应用密钥，但不能借此修改平台通道、服务身份或执行环境的安全配置。（2026-10-09 GOV-05 决议对 Discovery N4 的修订） | D3 / §4.4④ |
| F055 AC-56 | WHEN 能力声明只包含合法的应用密钥引用名, THE SYSTEM SHALL 接受该声明并按本节密钥规则处理；IF 引用尚未录入值, THEN THE SYSTEM SHALL 输出缺值警告而不以“本版不支持密钥引用”拒绝发布；发布产物含实际明文密钥时，原密钥扫描仍必须拦截。（GOV-05 验收 8、验收 10；替代旧 Discovery N4 排除项） | D3 / D5 |
| F055 AC-66 | WHEN 目标应用的自然人 owner 录入、修改或删除应用密钥值, THE SYSTEM SHALL 仅对该 owner 开放相应业务操作；租户管理员、非 owner 平台超管、审批人、普通成员、服务账号及个人访问令牌不得因管理身份、拥有 app:manage 或知道应用标识而取得该写权限。 | §2 / §4.4② |
| F055 AC-67 | WHEN 查看应用详情页发布 tab 的应用密钥区, THE SYSTEM SHALL 向 owner 展示引用名、固定掩码、已录入/缺少值状态及最近修改时间，并区分批准版本、待审批版本和未被当前版本引用的已存值；本租户管理员只能查看引用名和状态，审批人仅在其有权审阅的审批单内查看该版本的引用与缺值提示。 | D15 / §4.4②⑤ |
| F055 AC-68 | THE SYSTEM SHALL 加密保存应用密钥值；录入后不存在查询明文、导出明文或用界面掩码还原值的能力；应用管理、版本、审批、日志、错误和审计的任何平台输出均不含密钥值、其片段或可复用的访问凭据。 | D17 / D20 / §4.4①④ |
| F055 AC-69 | WHEN 新增或删除应用版本声明中的引用名, THE SYSTEM SHALL 将其作为能力声明变更随发布审批生效并在审批摘要中展示引用名；录入、替换或删除一个值不会擅自修改任何版本的声明，也不产生发布审批单。 | D6 / D7 / §4.4⑤ |
| F055 AC-70 | WHEN 已批准的正式版本启动、恢复或重建, THE SYSTEM SHALL 只把该版本明确声明的引用名注入为同名应用环境变量，使用当时已成功保存的值；未声明的值、其他应用的值与其他租户的值不得进入该实例，代码、依赖和运行环境的批准组合保持不变。 | D18 / §4.4③ |
| F055 AC-71 | WHEN 执行构建、依赖准备、静态扫描、预检启动或审批期预览, THE SYSTEM SHALL 不注入任何真实应用密钥值；预检启动和审批预览只获得该版本声明的变量名及空值，不能借复用已上线实例或材料取得生产值。（2026-10-23 用户明确确认） | D3 / D13 / §4.1 / §4.4③ |
| F055 AC-72 | IF 声明引用缺少已录入值, THEN THE SYSTEM SHALL 在 CLI deploy、发布 tab 和对应审批单显示引用名与缺值状态，且不因缺值本身拒绝提交或生成审批单；仍须执行原启动/探活检查，应用自身因空值无法启动时按原失败流程处理，不跳过真实健康校验。 | D4 / §7 |
| F055 AC-73 | WHEN 缺值的正式引用被启动或 owner 经影响确认删除仍被在线版本引用的值, THE SYSTEM SHALL 使该变量为空；删除值不等于删除版本引用名，界面仍可显示缺少值并允许 owner 补录，删除必须清楚提示对在线应用的影响。 | §4.4②③⑤ |
| F055 AC-74 | WHEN owner 保存在线正式版本正在使用的密钥值变更, THE SYSTEM SHALL 保存后刷新该应用实例使最新值生效，不创建新代码版本或审批单，不触发表结构迁移或覆盖 SQLite 数据，不改变其他应用的实例或密钥。 | D18 / §4.4③ |
| F055 AC-75 | WHEN owner 为已下线、草稿或尚未上线的版本保存值，或修改未被在线版本引用的值, THE SYSTEM SHALL 保持原应用状态且不擅自上线或无关重启；此后按原审批/上线动作启动时使用最新有效值。 | §4.4③ |
| F055 AC-76 | IF 值已保存但使其生效的实例更新失败, THEN THE SYSTEM SHALL 明确区分“值已保存”和“应用更新失败”，保持可诊断的执行结果并提供符合原生命周期约束的重试；不得谎报已生效、静默恢复旧值或回滚代码/业务数据。 | D19 / §4.4③⑤ |
| F055 AC-77 | WHEN 密钥保存并发发生，或与发布切换、停用、迁移、恢复、删除发生冲突, THE SYSTEM SHALL 明确成功顺序或拒绝冲突请求；已拒绝请求不得改变旧值，旧执行不得覆盖更新成功的配置，未知执行结果不得自动重复发起数据维护或绕过单写保护。 | D19 / §4.4③ |
| F055 AC-78 | IF 引用名无效、重复或企图覆盖平台身份、平台通道、应用启动、语言运行环境及代理隔离所需的保留变量, THEN THE SYSTEM SHALL 在提交声明或保存值时明确拒绝并指出相应字段，不截断或静默替换名称。 | §2 / §4.4④ |
| F055 AC-79 | WHEN owner 保存合法值, THE SYSTEM SHALL 保留其 Unicode、换行及特殊字符的原始语义，使应用读取到同一值而不执行其中内容；空字符串不能被标为已录入，超过已公布输入限制时明确拒绝，未编辑的掩码不能被当成新值提交。 | §2 / D20 / §4.4④ |
| F055 AC-80 | WHERE 不同应用或租户使用相同引用名, THE SYSTEM SHALL 分别维护各自的值与状态；对不存在或无权限的应用作查询/写入时，须遵守原应用存在性和租户拒绝语义，不通过状态、列表、错误或掩码泄漏另一作用域的信息。 | §2 / §4.4①② |
| F055 AC-81 | WHEN 应用密钥值成功录入、修改或删除, THE SYSTEM SHALL 由本业务写入应用、引用名、操作者、动作、时间和结果的审计，不记录值；应用运行期凭据的签发/回收仍由原凭据 Owner 留痕，并须携带受信的应用关联供治理面追溯。 | D12 / §4.4① / §4.3 |
| F055 AC-82 | THE SYSTEM SHALL 使真实应用密钥值不进入源码压缩包、版本快照、依赖缓存、构建产物、数据库快照、审批内容或应用附件；受限的正式执行交付可获得其必需的值，但普通查询者、预检执行体、代理和材料传输身份不得因此取得密钥管理能力。 | D6 / D17 / §4.4③④ |
| F055 AC-83 | WHEN 应用停用、进程重启、代码升级、移除某版本引用或准备环境缓存被回收, THE SYSTEM SHALL 保留仍在平台存储中的密钥资产而不再向未声明的版本注入；仅 owner 明确删除值或按原 owner 应用删除流程清理相应密钥，历史无值审计仍可追溯。 | D10 / §4.4① |
| F055 AC-84 | WHEN 查看能力声明和审批摘要, THE SYSTEM SHALL 展示该版本的引用名及对应缺值提示而不展示值；只有有效审批关系、owner 或原声明只读权限允许的访问者可见其授权范围内的信息，不能把审批人的有限审阅权限变成密钥管理权限。 | D7 / D14 / §4.4⑤ |
| F055 AC-85 | WHEN owner 通过密钥区保存一个未被正式版本引用的合法名值, THE SYSTEM SHALL 把它保持为未生效的应用私有配置；正式运行只以审批过的声明决定注入范围，不能靠预存一个新名字绕过引用新增的审批。 | §4.4②③⑤ |
| F055 AC-86 | WHERE 使用 Docker 或 K8s 执行后端, THE SYSTEM SHALL 对密钥权限、空值、预检/预览隔离、正式启动及保存后生效提供相同业务行为；实例重建、缓存恢复或执行器切换不得使旧值覆盖最新成功保存值。 | D18 / D19 / §4.4③ |
| F055 AC-87 | THE SYSTEM SHALL 保持 SDK 的原有公开能力边界，应用从标准环境读取业务密钥；不新增 SDK 密钥读取/管理入口，不将应用密钥变为可用于平台登录、平台管理或其他应用认证的凭据。 | D13 / §4.4⑤ |
| F055 AC-88 | WHEN 无应用密钥声明的既有应用升级或按原交付模式运行, THE SYSTEM SHALL 保持原发布、访问及依赖行为；声明使用应用密钥但目标执行形态不能兑现安全注入时，应明确拒绝所缺能力而不忽略声明或把真实值降级写入代码。 | D3 / §4.4③ / §8 |
| F055 AC-89 | WHEN 页面保存、缺值加载或实例更新请求失败, THE SYSTEM SHALL 结束相应等待并显示正确失败状态，保留用户尚未提交的本地编辑；不产生成功通知、不回填密钥明文，且不能通过重试误把掩码或过期页面状态覆盖已保存配置。 | D20 / §4.4⑤ / §7 |
| F056 AC-26 | THE SYSTEM SHALL 使任何审计记录、查询响应与导出内容不含密钥明文等敏感值；平台自签发凭据只显示既有前缀与末四位掩码，owner 录入的第三方应用密钥只显示引用名及无值动作信息，不借“掩码”暴露其字符片段。（NFR-2；应用密钥与 ApiCredential 的不同边界） | D15 / §4.4② |
| F056 AC-34 | THE SYSTEM SHALL 在既有管理后台审计页中以“应用运行记录”tab 承载模型调用、运行期能力调用及应用访问三个子视图，使高频记录可以查询和导出；操作类审计留在原 tab，不把高频事件混入原操作列表，也不另建独立管理页面；未部署工场运行时层时不显示该运行记录 tab。（2026-10-09 GOV-04 方案 A 替代原单列表筛选描述） | D11 / §7 |
| F056 AC-46 | WHEN 有权管理员进入已部署工场运行时层的既有审计页, THE SYSTEM SHALL 提供模型调用、应用能力调用、应用访问三个可独立选择的运行记录子视图，实际请求真实记录；原系统操作与原应用使用记录入口和既有筛选保持可用。 | D11 / D12 / §4.1 |
| F056 AC-47 | WHEN 管理员在任一运行记录子视图筛选, THE SYSTEM SHALL 支持时间范围、应用以及有意义的访问用户条件；模型调用还可按调用密钥筛选，并显示密钥掩码而非明文；无效时间范围、非法分页与跨租户筛选值须明确拒绝，不忽略后返回更宽范围。 | §2 / §4.4①④ |
| F056 AC-48 | WHEN 查询模型调用, THE SYSTEM SHALL 展示时间、调用归属（服务账号或应用）、模型、已记录 token 数及调用结果，并在有当前访问者信息时展示其身份；不以 app_id 非空为前提漏掉合法服务账号调用，也不把未记录 token 数伪造为零或把匿名/未知访问者替换为 owner。 | D12 / §4.4② |
| F056 AC-49 | WHEN 查询应用能力调用, THE SYSTEM SHALL 展示时间、应用、能力、以谁的名义调用、结果及已有的可用耗时/数量信息；调用归属与访问者归属分别展示，不把两种身份混成一个操作者。 | §4.4② |
| F056 AC-50 | WHEN 查询应用访问, THE SYSTEM SHALL 展示访问用户、应用与访问时间，并保持原“一次进入/合并窗口”的记录语义；不能把已有聚合访问记录宣称为每条 HTTP 请求或因查询重新生成访问事件。 | D7 / §4.4② |
| F056 AC-51 | WHEN 在相同筛选范围内分页、刷新或导出运行记录, THE SYSTEM SHALL 对相同时间的记录提供稳定顺序，不因并发新增导致同一次导出重复、漏掉已选历史记录或无限延长；分页与总数均只反映有权查看的筛选结果。 | D13 / §4.4①③④ |
| F056 AC-52 | WHERE 多租户开启, THE SYSTEM SHALL 使租户管理员只能查询本租户；平台超管全局视图可显式选择有权租户，切到目标租户视图后按该目标上下文呈现；前端隐藏筛选不是服务端授权，调用者自报其他租户、应用或密钥标识不能扩大查询或导出范围。 | §2 / §4.4④ |
| F056 AC-53 | IF owner、普通用户、审批人、服务账号或个人访问令牌不具有原治理面规定的管理员身份, THEN THE SYSTEM SHALL 拒绝其运行记录查询、筛选候选与导出；拥有应用使用、管理或审批权限不自动赋予审计访问权。 | §2 / D12 / §4.4④ |
| F056 AC-54 | WHEN 应用、密钥或访问用户已删除、吊销或重命名, THE SYSTEM SHALL 仍允许有权管理员按历史标识追溯已保存记录；优先使用已有名称快照，历史缺字段时显示标识或未知，不从另一租户或新同名对象补造历史身份。 | D10 / §4.4② |
| F056 AC-55 | WHEN 切换记录类别、租户视图或筛选条件, THE SYSTEM SHALL 同步复位不再适用的筛选和分页，不显示前一个租户/类别的过期返回内容；其后的导出必须使用当前明确选中的授权范围与筛选。 | §7 |
| F056 AC-56 | WHEN 管理员导出运行记录, THE SYSTEM SHALL 导出当前筛选条件下受授权的全部记录而非当前页，列含与该子视图对应的追溯信息；导出受理及交付遵守与查询相同的当前角色/租户约束，失权不能继续取得新内容。 | D13 / D14 / §4.4①④ |
| F056 AC-57 | IF 运行记录加载或导出失败, THEN THE SYSTEM SHALL 展示失败并结束等待，不能把失败表示为成功空列表、成功下载或沿用旧租户结果；合法无记录、历史字段缺失和服务失败须能被区分。 | D14 / §7 |
| F056 AC-58 | THE SYSTEM SHALL 使运行记录查询、导出、错误及筛选候选仅包含已获准的审计元数据，不包含密钥值、OBO/会话凭据、应用环境全文、模型请求正文或知识检索正文；密钥只显示既有掩码。 | §4.4② |
| F056 AC-59 | WHEN 按对象应用筛选操作审计, THE SYSTEM SHALL 能找到由 F055 及凭据 Owner 留下的应用密钥变更和应用运行期凭据签发/回收记录；应用关联须来自原业务目标，不能依靠审计查看者传入 app_id 伪造或补写历史事件。 | D15 / §4.3 / §6.1 |
| F056 AC-60 | WHEN 导出包含用户可控名称或其他文本字段的表格文件, THE SYSTEM SHALL 保留可读文本而不把其作为可执行公式；导出不得携带隐藏敏感列，历史空值不得使导出失败或被替换为其他租户内容。 | D14 / §4.4② / §7 |
| F056 AC-61 | WHERE 工场运行时层未部署, THE SYSTEM SHALL 不展示应用运行记录入口并对相应查询/导出遵循原层禁用语义，原操作审计继续可用；本次不新增聚合计费账单、owner 自助审计页或跨租户授权方式。 | D8 / §4.4① / §7 |

## 5. 固定基线源码核查

以下为已读代码证据，不等于新增设计已实现。链接固定在代码事实 SHA，避免后续行号漂移改变证据。

| 实现事实 | 路径 / 符号 |
|---|---|
| OBO 空返回后 formal/preview 仍可 allow | [src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py) · `_issue_obo_token / authorize_entry` |
| 现有防火墙只覆盖 FORWARD/DOCKER-USER | [src/runtime-manager/runtime_manager/egress.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/runtime-manager/runtime_manager/egress.py) · `firewall_rules / iptables_commands / _firewall_check` |
| 旧 secret 引用被广泛拒绝 | [src/backend/bisheng/app_publish/domain/services/manifest_validator.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/app_publish/domain/services/manifest_validator.py) · `_reject_secret_references` |
| capabilities 尚无 secret schema | [src/backend/bisheng/app_publish/domain/schemas/app_manifest.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/app_publish/domain/schemas/app_manifest.py) · `CapabilityDeclaration` |
| sealed_env 复用与同版本快速返回 | [src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py) · `inject_environment / deploy` |
| 操作的 generation/owner/claim 围栏 | [src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py) · `claim / commit_route` |
| K8s 已有执行专属 Secret 引用 | [src/runtime-manager/runtime_manager/k8s_templates.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/runtime-manager/runtime_manager/k8s_templates.py) · `secret_env / secretKeyRef` |
| 模型表已有查询/导出但不带新管理员入口 | [src/backend/bisheng/open_api/domain/repositories/model_call_record_repository.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/open_api/domain/repositories/model_call_record_repository.py) · `alist / aiter_export` |
| 能力记录写入表 | [src/backend/bisheng/app_publish/domain/models/capability_call_record.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/app_publish/domain/models/capability_call_record.py) · `AppCapabilityCallRecord` |
| 访问表缺历史 app 名称列 | [src/backend/bisheng/database/models/app_access_log.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/database/models/app_access_log.py) · `AppAccessLog` |
| 现有操作审计权限比新 runtime 查询更宽 | [src/backend/bisheng/api/services/audit_log.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/api/services/audit_log.py) · `_resolve_audit_groups / _get_audit_tenant_scope` |
| 凭据审计尚缺可信 app 关联 | [src/backend/bisheng/open_api/domain/services/credential_service.py](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/backend/bisheng/open_api/domain/services/credential_service.py) · `_audit` |
| 平台页当前只有两个日志页签 | [src/frontend/platform/src/pages/LogPage/index.tsx](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/frontend/platform/src/pages/LogPage/index.tsx) · `Tabs` |
| 应用发布页已有 settingsSlot | [src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/PublishTab.tsx](https://github.com/dataelement/bisheng/blob/5f2541f4bc483c24624fede9031c88c4ec6f58f4/src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/PublishTab.tsx) · `PublishTabProps` |

## 6. 验证范围与接下来

本轮已做：静态调用/字段核对、设计清单复审、完整 52 条 AC 映射、确认规格正文未变、链接/章节交叉引用/离线 HTML 静态一致性检查；页面视觉与布局检查结果另写 review JSON。没有运行 backend/runtime 全量测试，也没有远端部署、Docker/K8s E2E、DM8 实测或镜像发行。

设计确认后按依赖拆任务：先模型/迁移/契约和配对测试；再 secret 存储/正式用途/配置刷新，OBO 和宿主隔离；新管理员读面/导出/页面。只对实际修改路径执行必要 red→green、L1、定向 E2E，完成后再 L2；不重跑无关全量回归。ARM 和现有正式发行待办继续保留。

本 HTML 附三份设计全文，来自当前 canonical Markdown；所有图示/样式在本文件中，离线可读。旧章节编号与 D 编号保留；早期坑编号/细分契约历史引用明确转到 dda16a6 快照，不再以过期 MVP 状态作为当前事实。
