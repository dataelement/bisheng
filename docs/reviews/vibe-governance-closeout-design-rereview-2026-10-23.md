> **历史复评快照**：本页的 NEEDS_FIX 针对 7b9027101；原问题已由用户授权修订并另行复审，当前结果见[修订后复审](vibe-governance-closeout-design-revision2-review-2026-10-23.md)。

# Vibe 治理收尾 · 设计复评

**结论：NEEDS_FIX / REVISE。2 项 high、3 项 medium；尚不适合进入任务拆解与编码。**

日期：2026-10-23。固定设计/源码提交：`7b90271017b74f8c43075dd28e40d895462d6783`。本轮为用户要求的“先评审设计”，不是设计确认或修订授权。仅只读静态核验；未运行测试、未操作远端、未改 spec/design/产品代码。

## 1. 复评方式与范围

按 sdd-review design 的 24 项清单复核 F054/F055/F056，并使用 architecture-critic 要求的一名独立、无编写历史的 agent 审查七个架构维度。独立报告原文保存在 [architecture-critique.md](vibe-governance-closeout-architecture-critique-round1-2026-10-23.md)。主 agent 复核其四项发现，再补一项运行状态完成协议问题；下表的严重度按 SDD 清单映射，不等同于独立报告 blocker/should-fix 的词面数量。

本轮结论**取代上次自审 LGTM 作为当前评审状态**；旧报告保留历史文本并加失效提示。已确认规格与未获确认设计保持原文，等用户决定修订。整体开源、独立进程、平台存储解耦和 formal-only 真实值边界没有被否定。

## 2. 发现项

### R1 · high · 10,000 行/90 天硬限制违背已确认的全部导出

ISSUE: 10,000 行/90 天硬限制违背已确认的全部导出 | SEVERITY: high | LOC: [F056 design.md:18](../../features/v3.0.0/056-app-square-governance/design.md)（固定提交行号）

F056 AC-56 及原 AC-32 要求导出当前筛选的全部受授权记录。设计 §2、D13 把 10,001 行及超过 90 天的合法筛选直接拒绝，属于需求收窄，不能仅称作实现预算。应将内部批次做成有界，持久任务完成全部冻结选择；若要用户总量限制，须先提规格变更。

关联规格：F056 AC-32、F056 AC-56。

### R2 · high · OBO 配置错误提示与已确认规格不一致

ISSUE: OBO 配置错误提示与已确认规格不一致 | SEVERITY: high | LOC: [F054 design.md:55](../../features/v3.0.0/054-app-domain-runtime/design.md)（固定提交行号）

F054 AC-70 已明确对原本有权者显示“本环境配置不完整，请联系平台管理员”；设计 D7 却要求通用“应用暂不可用”。应在原登录/租户/可见性判定之后，把 identity_config_incomplete 映射为确认过的配置提示，不暴露配置值。

关联规格：F054 AC-70、F054 AC-71。

### R3 · medium · 密钥敏感项缺少从注入到全部日志/诊断路径的明确传递合同

ISSUE: 密钥敏感项缺少从注入到全部日志/诊断路径的明确传递合同 | SEVERITY: medium | LOC: [F055 design.md:222](../../features/v3.0.0/055-app-publish-pipeline/design.md)（固定提交行号）

现有 container_runner.redact 仅替换名称含 TOKEN/SECRET/KEY 等且值长至少 6 的环境值。PIN=1234 或普通名称下的长值均可绕过旧规则。设计只写“已知值原文脱敏”，未明确批准声明如何生成 operation 绑定敏感项以及 Docker 正式日志、legacy 日志、K8s 日志/启动失败、diagnostic_tail 落库前各消费者如何取得并使用。应统一敏感清单，先脱敏再截断/分行，并覆盖短值、换行/跨块、重叠值；不宣称防住应用主动编码外传。

关联规格：F055 AC-68、F055 AC-79。

### R4 · medium · 部署密钥轮换后历史 request_id 的 HMAC 无法按现有合同验证

ISSUE: 部署密钥轮换后历史 request_id 的 HMAC 无法按现有合同验证 | SEVERITY: medium | LOC: [F055 design.md:94](../../features/v3.0.0/055-app-publish-pipeline/design.md)（固定提交行号）

幂等摘要由可轮换 runtime_payload_key 派生，但维护方案只重加密业务密文与运行 payload。历史 mutation 仅存 HMAC，旧值已改/删时无法重新生成；同参历史重试会成为错误冲突或失去幂等保障。应选择独立稳定验证 key 或持久 key version + 旧 key 验证/保留策略，明确轮换/清理步骤。

关联规格：F055 AC-77。

### R5 · medium · 路由生效与 applied_revision 的完成/恢复协议仍含未定选择

ISSUE: 路由生效与 applied_revision 的完成/恢复协议仍含未定选择 | SEVERITY: medium | LOC: [F055 design.md:213](../../features/v3.0.0/055-app-publish-pipeline/design.md)（固定提交行号）

设计写“尽量同事务”，没有选定唯一完成点或给出跨事务重放步骤。现有 AppStateService.commit_runtime_delivery 在 op.stage=serving 时立即返回（658–659 行），并由 RuntimeProjectionService.activate 提交路由；若路由已提交而 F055 结果回调失败，沿用旧幂等早退可能不再补写 applied_revision/释放配置 guard，导致实际运行新值却长期显示 pending/unknown。应明确同一 UoW 的公开结果适配协议，或以 version/revision/operation/exec_ref 冻结事实幂等补齐的恢复路径；覆盖该崩溃点及 completed/serving 重试。这里是设计遗漏，不是已复现的产品缺陷。

关联规格：F055 AC-76、F055 AC-77、F055 AC-86。

## 3. 证据与定向复验要求

| 证据 | 对应结论 | 修订后需验证什么 |
|---|---|---|
| F056 spec AC-56；design §2 / D13 | R1 | 大于 10,000 行仍完整导出且扫描有限，不靠缩小筛选规避规格 |
| F054 spec AC-70；design D7 | R2 | 已有权者得到配置提示；匿名/不存在/跨租户/无权限仍按原顺序拒绝 |
| container_runner.py:35；api/platform_observe.py:75；executors/kubernetes.py:954；api/readonly.py:128 | R3 | PIN 短值、普通名称、Unicode/换行、截断/跨块不泄漏到返回和持久诊断 |
| F055 D17 / AppSecretMutation / request_id 合同 | R4 | 轮换前历史请求在轮换后同参可识别、异参拒绝、无重复写入 |
| app_state_service.py:648 / runtime_projection_service.py:activate | R5 | 路由已提交但配置结果未提交时崩溃，重启只补结果，不重复启实例/DDL；旧 revision 不能确认新值 |

## 4. SDD 清单结论

24 项结构/追溯仍已覆盖；复评发现第 10 项（字段/完成协议）、第 17–18 项（日志敏感项与密钥轮换依赖）、第 23 项（spec 一致）不能维持 PASS，因此总体 NEEDS_FIX。追溯表“有一行映射”不等于设计兑现了该 AC。Constitution 的分层/租户/存储边界暂未发现新的实锤违反；这不是产品测试通过结论。

## 5. 后续边界

应先修订并复审以上合同，再由用户单独确认设计。保留已批准的规格，不把 R1/R2 的偏差直接改进规格当作已获授权。只需相应定向验证，不要求重新跑全部 Docker/K8s 回归、ARM、DM8 真测或镜像发行。

本轮保留原设计，不自动修订、不拆任务或编码。架构批评为评审建议；实施阶段仍遵守仓库 SDD 确认点。
