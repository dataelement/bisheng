# F111 E2E 执行清单

更新：2026-10-24。状态：**109单实例真实子集通过，完整特性仍PARTIAL**。

许可证已按用户追加授权由官方工具生成并实际有效至2026-11-23。真实协议35/35、身份/管理7/7、十二条审计记录的四模式只读复核4/4通过；实际Desktop两协议回复和read工具正反例通过。DM8、双租户、多副本、设施故障、无Gateway部署与容量/回退仍未执行，不能据此勾完整T121–T125或T132。以下AC包含多个观察点时仍保留PARTIAL，不把单个子集或本地测试当整条AC通过。

## 环境与安全边界

| 编号 | 必需环境 |
|---|---|
| E1 | 授权非生产backend、精确版本/迁移head、实际SQL及启动依赖、两个专用租户 |
| E2 | 一个或两个真实Gateway、合法现有License、相同backend/namespace/共享HMAC、Redis/词库/DDL/正有限既有HTTP响应预算 |
| E3 | backend通过真实模型准入与计量连接受控无费用provider；能够控制四协议模式、工具、推理、分片、坏帧与usage，记录物理调用数 |
| E4 | 两租户各管理员/普通用户及超管、正式平台登录和DSH原生PKCE会话、允许测试的模型 |
| E5 | 仅隔离实例的故障/重启/多副本控制及指标；不能在真实用户服务上断网、改时钟或停止worker |
| E6 | 当前Platform/Desktop真实登录与三语言界面、无副作用工具执行计数 |
| E7 | 实际MySQL和Linux DM8、明确schema/大数据资源配额/SQL与故障操作权限 |
| E8 | 公开入口/代理/防火墙实际拓扑及普通应用回归fixture；从客户端网络验证不可直连backend |

原始Token、密码、HMAC、License均不进入文档/命令参数/日志。使用已创建资源前缀`e2e-f111-<run>-`、精确tenant及ID；setup/teardown均GET核实，只清理本套件对象。已有cleanup helper吞错且非完整分页，其返回不能当清理成功。不得为清理测试数据而批量删除真实审计、计量或未ACK事件。

## 入口与已有helper

- M：`POST /api/v1/dsh/chat/completions`和`POST /api/v1/dsh/responses`，各流式/非流式；I：`GET /api/v1/dsh/profile`。
- P：Gateway `/api/sensitive/dsh/settings`读写、`/api/sensitive/dsh/capabilities`；A：backend `/api/v1/dsh/admin/model-audit`下requests/settings/users/models及事件查询。
- G：同A的conversation-groups/query-readiness；T：conversation-tree及children/location；U：DSH usage及管理员usage接口。
- E：`POST /api/v1/internal/dsh/content-safety-events`，精确路径、严格JSON、共享HMAC；只有HTTP200+同event_id+COMMITTED才是接收成功。
- UI：Platform `/dsh`；Desktop：真实Chat/Responses适配器与工具屏障；LEG：既有应用路由/词控；OPS：真实Outbox、索引worker和维护CLI。

复用`test/e2e/helpers/{auth,api,cleanup,dsh}.py`，原生登录用`native_desktop_session`正式PKCE。模型JSON/SSE、Gateway ResultData、内部Receipt和backend管理API的响应契约不同，不能统一套`assert_resp_200`。已有audit_diagnostics是合成组件，并非部署E2E；no_gateway示例会实际创建身份/调用配置模型，必须显式授权对应环境才运行。

T121/T122真实HTTP测试源已落盘，T123只读审计核心已实现并执行12条真实记录的四模式子集；源码存在不代表完整任务验收：

- `src/backend/test/dsh/test_content_safety_protocol_e2e.py`
- `src/backend/test/dsh/test_content_safety_identity_e2e.py`
- `src/backend/test/dsh/test_content_safety_recovery_e2e.py`

## 逐项验收

spec.md为AC原文唯一依据；下表只给执行观察点。每条应附真实环境、UTC时间、命令/用例、有限HTTP错误码、SQL持久读回及日志路径；界面/真实重启证据另附操作记录。涉及多个环境的AC必须全部满足，单方言结果只记PARTIAL。

| AC | 任务 | 入口 | 环境 | 必须观察的事实 | 执行结果 |
|---|---|---|---|---|---|
| AC-01 | T121、T125 | M | E1,E2,E3 | 四种协议模式，普通/内部用途/标题/compaction及完整历史均走检查；上游请求计数每轮至多一次。 | PARTIAL：四模式正常、历史/compaction/session-title语义已真实检查；独立无Gateway未验 |
| AC-02 | T121、T125 | M/P | E1,E2,E3 | 部署off、租户无策略、租户disabled三组分别对照；首装默认off；不能把policy不可用当disabled。 | PARTIAL：无租户策略默认DISABLED四模式与FINAL已验；部署off/开关切换未验 |
| AC-03 | T121、T125 | I/M/U | E1,E3 | 独立无Gateway部署执行原生PKCE登录→模型→用量；不改License/席位控制来制造通过。 | NOT_RUN |
| AC-04 | T124、T125 | M/UI | E1,E2,E6,E8 | 核对外部全部实际入口；受保护部署直接backend入口从客户端不可达；模型路径编码/matrix同入口检查，尾slash/邻近路径不扩匹配。 | NOT_RUN |
| AC-05 | T121、T125 | M/U | E1,E2,E3 | 四模式无命中对比直连受控基线原body/SSE顺序、工具/usage/error；固定JSON bytes不归一化。 | PARTIAL：四模式确定语义/usage80通过；原字节受控基线对照未验 |
| AC-06 | T122、T125 | P/M | E1,E2,E3,E4 | 同租户至少两模型验证一套启停/方向/内置+自定义规则和租户提示均生效；保存后GET确认。 | PARTIAL：同租户Chat8/Responses9真实规则及方向启用/命中；完整内置词/UI配置组合待验 |
| AC-07 | T122、T124、T125 | P/A/G/T/E | E1,E2,E4 | 租户A管理员允许A、拒B，普通用户均拒；超管允许有效可管租户、拒不存在/不可管目标。 | PARTIAL：实际admin允许/普通Gateway GET-PUT403且无变；跨tenant/超管范围未验 |
| AC-08 | T122、T124、T125 | P/I | E1,E2,E4 | 先用DSH成功profile填缓存，再用普通平台身份保存仍拒；撤管理权后保存拒绝，不能复用profile授权。 | PARTIAL：普通PKCE/profile/models不赋Gateway管理权，保存403；真实撤管理权未验 |
| AC-09 | T122、T125 | P/UI | E1,E2,E4,E6 | 无有效词、词/提示超限及非法值精确错误；内置+自定义都覆盖；GET未保存非法版本。 | PARTIAL：真实非法配置精确拒绝且GET原版本不变；全部上下限与UI未穷尽 |
| AC-10 | T122、T125 | P | E1,E2,E4 | 两个管理员基于同expected_version保存：一成功、一409冲突；GET最终唯一新版本。 | PARTIAL：真实旧expected_version精确409且GET保持唯一版本；双管理员并发未验 |
| AC-11 | T122、T125、T128 | P/M | E1,E2,E3,E5 | 长流在途保持旧快照；修改或关闭后新请求≤5s使用新版本，记录真实时钟和两副本版本。 | NOT_RUN |
| AC-12 | T122、T125 | P/M | E1,E2,E3,E5 | 两Gateway同版本规则/摘要一致；破坏可用词库或断policy读取时返回检查不可用，不透传。 | NOT_RUN |
| AC-13 | T122、T125、T127 | I/M | E1,E2,E3,E4 | 伪造tenant头/正文不影响profile身份；完整不同Token及不同backend namespace不串用。 | PARTIAL：两个真实PKCE凭据+refresh仍同user9/tenant1；namespace/跨身份缓存未验 |
| AC-14 | T122、T125、T127 | I/M | E1,E2,E3,E5 | 真实L1≤2s/Redis≤30s及token exp-5s；连续命中/跨副本读取不续期；检查cache不含原Token且日志无凭据。 | NOT_RUN |
| AC-15 | T122、T125、T127 | I/M | E1,E2,E3,E5 | 同凭据冷热多请求/多副本复用；profile次数与模型请求/流分片分开统计，分片增加不增加profile次数。 | NOT_RUN |
| AC-16 | T122、T125 | I/M/U | E1,E2,E3,E4 | 缓存命中后撤会话/模型权/额度；原始凭据仍转backend当前准入，不能用缓存绕过。 | PARTIAL：真实撤销已缓存会话后模型当前准入拒绝；撤模型权/额度组合未验 |
| AC-17 | T122、T125 | I/M | E1,E2,E3,E4,E5 | 真实注销/用户或租户失效使对应缓存失效且不重试模型；模型未授权/额度不足对照不删身份缓存。 | PARTIAL：旧refresh真实session_revoked；Gateway缓存/租户失效未验 |
| AC-18 | T122、T125、T127 | I/P/M | E1,E2,E3,E5 | profile/policy网络、格式、空结果及32在途/64队列满都503 check_unavailable，非账号错误/非关闭/非通过。 | NOT_RUN |
| AC-19 | T122、T125、T127、T128 | I/M | E1,E2,E3,E5 | 断Redis后仅有效L1或有界重新profile；过期失败不复用；统计有限等待/重试/日志，不持久凭据。 | NOT_RUN |
| AC-20 | T121、T125 | M | E1,E2,E3 | 输入/输出消息、reasoning、tool描述/参数/结果解码字符串命中；图像base64/加密reasoning/协议ID/audit_context不误扫。 | PARTIAL：真实完整历史/内部用途和两协议工具参数命中，图像/加密reasoning全部组合未验 |
| AC-21 | T121、T125 | M | E1,E2,E3 | 同消息连续块跨词命中；不同message/choice/tool独立域不拼词；大小写与既有字面规则一致。 | PARTIAL：真实相邻output_text/reasoning summary-content及空part/Unicode命中；全部域隔离未穷尽 |
| AC-22 | T121、T125 | M | E1,E2,E3 | 受控上游逐字节切UTF8/CRLF/multiline/data/escape/末尾残文，断言客户端从未收到完整命中词。 | PARTIAL：真实fragment与Unicode分片阻断，无完整词泄漏；CRLF/multiline/末尾残文全矩阵未验 |
| AC-23 | T121、T125 | M | E1,E2,E3 | Responses delta、done、completed及最终快照新增文本逐一检查，保持原SSE顺序/不把失败当completed。 | PARTIAL：真实Responses delta/done/final独立新增文本和reasoning均阻断；失败/异常全矩阵未验 |
| AC-24 | T121、T125 | M/Desktop | E1,E2,E3,E6 | 两个协议工具参数完整解码后才执行；命中/坏JSON/取消未完成时真实工具执行计数0；Desktop不能仅看HTTP状态。 | PARTIAL：两协议真实read各成功1且nonce匹配，敏感参数各零tool调度；坏JSON/取消现场未验 |
| AC-25 | T121、T125 | M/E | E1,E2,E3 | 请求/模型SSE/tool坏JSON、未知可交付结构、mixed error+choices均failclosed；审计ERROR不伪BLOCKED。 | NOT_RUN |
| AC-26 | T121、T125、T126、T128 | M/P/E/A | E1,E2,E3,E7 | 真实公布32MiB请求/累计响应、Responses8MiB事件、词库/并发等边界拒绝；无无限队列/未经检查透传。 | NOT_RUN |
| AC-27 | T121、T125 | M/A/U | E1,E2,E3 | 输入命中HTTP403；受控provider和backend模型调用计数0，用量前后不增；仍查独立安全记录。 | PARTIAL：真实四模式输入HTTP403、global/scenario0、无charge并有EXTERNAL_SAFETY；UI四模式未全验 |
| AC-28 | T121、T125 | M | E1,E2,E3 | Chat/Responses非流完整输出先检查；BLOCKED不交付原危险正文。 | PARTIAL：两非流协议真实完整输出先拦截、不泄漏敏感词；普通转发基线原bytes未对照 |
| AC-29 | T121、T125、T128 | M/Desktop | E1,E2,E3,E6 | 流式交付安全prefix后阻断；不交付完整命中词，无正常成功结束；Desktop停止该轮且零自动重试。 | PARTIAL：真实流式屏障与Desktop两协议CONTENT_FILTERED零调度/无重试；压力/所有取消场景未验 |
| AC-30 | T121、T125 | M/Desktop | E1,E2,E3,E6 | 输入/非流403 content_blocked+租户自定义原提示；Chat content_filter+[DONE]、Responses明确error；界面可见且不重试。 | PARTIAL：实际403/协议流错误保留合成租户提示，Desktop两协议可见；三语全UI仍未验 |
| AC-31 | T121、T125 | M/Desktop | E1,E2,E3,E5,E6 | 检查失败未开始503/已开始协议错误；backend鉴权、额度、供应商原错误原样区分；Gateway合成编号与backend编号口径正确。 | PARTIAL：真实公开/Backend两UUID口径已分离，普通管理拒绝403；供应商与检查失败现场全矩阵未验 |
| AC-32 | T121、T125、T128 | M/A/U | E1,E2,E3,E5 | 输出命中后backend确认真实usage继续结算；unknown永不改0；客户端停止交付/续读结束都不能当供应商停止。 | PARTIAL：实际输出命中仍raw30/50/80及SETTLED，流客户端结束可早于Provider排空；UNKNOWN/30s精确故障未验 |
| AC-33 | T123、T125 | M/A/E | E1,E2,E3 | 输入/输出实际终态逐一落审计；backend准入失败无模型输出为NOT_APPLICABLE；方向disabled不伪PASSED。 | PARTIAL：12条三场景原生/外部摘要及事件真实两读一致；ERROR/准入失败全组合未验 |
| AC-34 | T123、T124、T125 | A/G/T/UI | E1,E2,E3,E6 | 六阶段状态与请求汇总优先序；无事件/部分结果UNREPORTED；先BLOCKED后PASS不能清命中。 | PARTIAL：实际PASSED/BLOCKED/DISABLED独立模型执行和用量；完整六态UI/顺序未验 |
| AC-35 | T122、T123、T125 | M/E/A/OPS | E1,E2,E3,E4,E5 | 审计OFF/METADATA仍有最小安全事实；查Outbox/事件/日志字段无正文、匹配原词和凭据，原文仍受原审计权限。 | NOT_RUN |
| AC-36 | T123、T125 | M/A/UI | E1,E2,E3,E6 | 输入BLOCKED生成独立条目，模型调用/结果/交付/结算为N/A，无原文入口，不造零用量事实。 | PARTIAL：真实四模式输入BLOCKED独立条目/N_A且无usage；输入条目UI未全验 |
| AC-37 | T123、T124、T125 | M/A/E/UI | E1,E2,E3,E6 | 有效backend响应UUID关联其模型记录而非profileID；无/坏backendID保留未关联，不猜测。 | PARTIAL：真实四模式输出Backend UUID关联MODEL，输入Gateway UUID为EXTERNAL；坏Backend UUID/未关联现场未验 |
| AC-38 | T122、T123、T124、T125 | M/A/E/G/T | E1,E2,E3,E4,E5 | 事件先/原生先/并发合并一条；可信身份变更接受但不覆盖他人模型用量；未知模型执行仍UNKNOWN。 | PARTIAL：真实模型与事件关联、普通管理拒绝成立；跨tenant/可信身份变更并发未验 |
| AC-39 | T123、T125 | E/A/OPS | E1,E2,E5,E7 | 接收COMMITTED后真实backend进程重启仍可查询事件+摘要；纯易失排队不算ACK。 | NOT_RUN |
| AC-40 | T123、T125 | M/E/A/OPS | E1,E2,E3,E5 | 输出命中时先形成DECISION并可查询，不等30s续读/用量结束；DRAIN补充不能撤销命中。 | NOT_RUN |
| AC-41 | T123、T125 | E/A/G/T | E1,E2,E5,E7 | 重复/乱序/后到通过按request去重；同event异hash409；原生后到不重置命中；含exactduplicate保留期重放。 | NOT_RUN |
| AC-42 | T123、T125 | E/I/A | E1,E2,E4,E5 | 共享HMAC有效/坏签名/篡改/超来源租户范围及浏览器/DSH冒充拒绝；合法历史事件在用户退出后仍可补报。 | NOT_RUN |
| AC-43 | T123、T125、T128 | M/E/OPS | E1,E2,E3,E5 | Outbox写失败仍阻断并暴露固定告警/缺口；接收端断开产生积压后恢复；记录实际持久状态，不假完整回传。 | NOT_RUN |
| AC-44 | T124、T125 | A/UI | E1,E2,E3,E6 | 列表阶段/汇总可见；模型SUCCEEDED与输出BLOCKED可同时显示；UNREPORTED不是通过。 | NOT_RUN |
| AC-45 | T124、T125、T126 | A/G/T/E/UI | E1,E2,E4,E6,E7 | 命中/方向/状态+用户/模型/时间组合，在列表/详情/会话/目录均验证普通用户和跨租户拒绝。 | PARTIAL：实际会话日志含本轮HTTP及Desktop会话/命中0；完整树和筛选未验 |
| AC-46 | T124、T125 | A/E/UI | E1,E2,E3,E6 | 详情分别展示request/modelStart/occurredAt、版本/来源/方向/受限摘要/关联；外部only无原文入口，原文访问有权/无权配对。 | NOT_RUN |
| AC-47 | T124、T125 | G/T/A/UI | E1,E2,E3,E6 | 父子own/branch按命中请求去重，与异常数独立；external条目可增audit条目但模型调用/usage不增。 | NOT_RUN |
| AC-48 | T124、T125、T126 | G/T/OPS/UI | E1,E2,E3,E5,E6,E7 | 只改命中触发dirty重建；停worker/readiness、scan_limited明确；externalonly不误报stalled、不永久挡全租户ready。 | NOT_RUN |
| AC-49 | T124、T125、T126 | A/G/T/UI | E1,E2,E4,E6,E7 | 安全先到原生后到startedAt排序不动；跨tenant/改显式筛选cursor拒；默认相对7天不要求固定，补报刷新可见。 | NOT_RUN |
| AC-50 | T124、T125、T126 | A/G/T/UI | E1,E2,E6,E7 | 默认近7天、单次31天允许而超限拒绝并提示分段；多事件不增加主列表行数/命中请求数。 | NOT_RUN |
| AC-51 | T123、T124、T125 | E/A/OPS/UI | E1,E2,E5,E6,E7 | 隔离tenant执行purge-details保摘要且标PURGED；purge-audit水位后迟到新事件410、既有receipt仍COMMITTED且不得复活主行。 | NOT_RUN |
| AC-52 | T123、T125 | A/U/G/T | E1,E5,E7 | 真实旧schema/数据升级保存历史用量/未知结算与证据；无安全事件历史显示UNREPORTED而非PASSED。 | NOT_RUN |
| AC-53 | T123、T125、T126 | P/E/A/G/T/OPS | E1,E2,E5,E7 | 完整同套业务在真实MySQL和LinuxDM8各执行，记录方言/版本/迁移head/事务与查询结果；SQLite不可替代。 | PARTIAL：109 MySQL8.0.43四协议正常链路；LinuxDM8缺环境 |
| AC-54 | T124、T125 | LEG/UI | E1,E2,E4,E6 | 普通应用旧敏感词、原路由及响应与BlockRecord行为保持；DSH marker不进入旧词控，原非DSH不误用租户策略。 | NOT_RUN |
| AC-55 | T123、T125 | P/M/E/OPS | E1,E2,E3,E5 | 租户off/部署off/回滚新请求停止检查，在途快照不变，历史审计/usage/未ACK继续投递保留。 | NOT_RUN |
| AC-56 | T124、T125 | UI/Desktop/P/A | E1,E2,E3,E6 | 真实Platform+Desktop zh/en/ja设置/阻断/check_unavailable/N/A/UNREPORTED一致；租户autoReply不翻译，固定fallback按本机语言。 | PARTIAL：真实Desktop zh Chat/Responses与Platform审计可见；三语阻断/未知未验 |
| AC-57 | T121、T125、T128 | M/OPS | E1,E2,E3,E5 | hit起算独立≤30s；剩余响应bytes/8drain满/上游错误提前停，连接及buffer/额度归还；unknownusage保持unknown。 | NOT_RUN |
| AC-58 | T123、T125 | E/A/OPS | E1,E2,E5,E7 | 真实Gateway进程/实例重启后未ACK事实继续送；丢ACK重复只一份/计一次；永久拒绝隔离告警、未ACK不TTL删。 | NOT_RUN |
| AC-59 | T122、T125、T127 | I/M | E1,E2,E3,E5 | 同完整Token同backend冷/过期并发只一次物理profile；取消单等待者不取消共享请求；1s总预算与队列超限不重试模型。 | NOT_RUN |

## 结果与缺口

- 完整AC：PASS0 / PARTIAL30 / NOT_RUN29。已执行子集：协议35/35、身份策略7/7、十二条审计四模式4/4、输入边界7/7，另49本地边界断言；Desktop两协议普通回复及工具正负、Platform English命中筛选和事件详情实际通过。完整故障、跨租户/多副本、三语、网络封闭、容量与回退仍未验。
- MySQL持久事务与Gateway SQL恢复的独立结果见implementation-verification.md；它们不替代本清单。
- Linux DM8实测按用户决定待验；AC-53不得标PASS。小表EXPLAIN与组件负载准备不得替代百万/千万容量结果。
- AC-34按spec中优先表完整验证；任何已知命中先于失败/未知/关闭/通过，不把未知视为安全。检查结果独立于模型执行、交付和用量。
- 默认相对分页窗口不冻结、接受可信身份变更、复用同一共享HMAC，均沿已确认取舍。

完整私有只读核查矩阵保留于`/private/tmp/f111-e2e-ac-matrix.md`，含原文和源码位置；本文件仅保存待执行观察点。完成T121–T124后再由T125逐项链接实际证据，未执行项不得勾选。

## 109实际执行记录

BiSheng工作120修复3cc9de9298ad2c6346f17d180105d46d2d3e3324经Drone5624 SUCCESS，Backend digest8c001dcc8c921ebf32c8e5c468d5368216c56b698a3511e2421f860713ee4392，frontend digest与5623相同；Gateway64f602be经404 SUCCESS，当前digest63d7d9ed已部署。运行用户9、模型8/9仅该用户私有，server5为本轮独立合成Provider。既有默认模型和其他credit规则读回不变。

四协议请求：6fa33453-5e38-4b7a-9e01-ce0d6e4efd04（Chat非流）、ded3d432-70cf-4d70-9cdd-af1464fd4770（Chat流）、29e07447-9dc9-48b0-8d67-1aec5b9265d9（Responses非流）、ef086b78-4643-42ea-9aa1-4d20f28a46c6（Responses流）。均HTTP200/Provider delta1/原生MODEL SUCCEEDED/SETTLED/raw80，安全DISABLED；详情各AVAILABLE/一个FINAL，未把列表保守PENDING误判丢事件。

T122历史基础子集（后续最终全7通过）：`test_content_safety_identity_e2e.py -k 'not policy and not revoked_native'`，4PASS/3deselected，3.22s。旧access/profile/models与旧refresh均session_revoked；只撤销各case新建session。没有注销实际已登录Desktop或已提供平台会话。日志保留私有0600，文档不含凭据。


本轮执行日志均在/private/tmp/f111-release-109并0600保存：protocol-live-final、identity-live-final、recovery-twelve-live各log/XML；desktop-tools-live-results.json与四份持久事件、真实截图。记录不含原始凭据，错误首轮与修复单案日志保留。Gateway404更新后capabilities正常，测试策略按CAS恢复原关闭状态。

T204/T205最终56PASS/78.03s（49local+7live），boundary-live-final.log/XML；请求解析拒绝无Backend header/无Provider/无审计/额度不变。PlatformEnglish实际命中筛选+Conversation精确筛选唯一会话，展开唯一匹配请求与DECISION/DRAIN详情；最终策略恢复原disabled/version111，其他容器身份复核不变。
