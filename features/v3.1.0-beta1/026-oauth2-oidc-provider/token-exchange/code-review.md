# Token Exchange Code Review

范围：PR2821（目标origin/feat/3.1.0-alpha1，整合7f665b1704），含第一方扩展及旧A→B，F026同一用户换证；包含未提交新增文件的逐文件审阅，不仅检查git diff。用户规格与设计已明确确认。本次按sdd-code-review七维度及task-review清单执行。

| 维度 | High | Medium | 结果 |
| --- | --- | --- | --- |
| 边界 | 0 | 0 | PASS：重复字段、长度、类型、期限有测试 |
| 身份权限 | 0 | 0 | PASS：strict issuer/aud、同人租户、scope交集、global准入 |
| 并发事务 | 0 | 0 | PASS：child/link同事务，失败回滚；在途期限固定t0；policy复合主键 |
| 泄漏 | 0 | 0 | PASS：不记Token/密钥/异常值/源码行/locals，日志故障注入断言 |
| 测试 | 0 | 0 | PASS（本地范围）：217通过1skip，真实TCP本地集成；线上和实库限制显式记录 |
| 分层风格 | 0 | 0 | PASS：SQL在Repository、API不写ORM，Ruff/guard通过 |
| 文档同步 | 0 | 0 | PASS：已确认状态、数据/接口/默认不启用/升级/回滚/测试限制同步 |

独立安全审查exchange-review只读检查了exchange_service、exchange仓储、exchange API与auth/runtime/oidc相关diff，未发现可确认High/Medium；其结论不包含独立跑测试，本报告的测试由主代理实际执行。后续主代理加强了异常栈日志值脱敏及解析拒绝审计事件，已在最终合跑验证。

L1任务：T001的错误码28115–18及三语生成物、两新表/自动发现、管理envelope与platform scope核对通过；T002的独立session/link、反向撤销隔离、scope/期限/租户绑定核对通过；T003的配对测试、路由生成物、QA八列及清理/线程退出核对通过。旧task-checklist中“所有新表必须tenant”和“禁止显式tenant条件”的泛化表述不覆盖已确认平台级policy和当前constitution/AGENTS租户规则：policy是全局信任关系，link保存并校验tenant/user，窄范围bypass不接管业务资源授权。

第一方独立审查first-party-review发现1个Medium：旧待审批请求只绑定client_id，会批准到同ID新登记。主代理已修复request/code登记实例绑定，get-details/submit/exchange均检查，pending/code/existing-consent三相测试通过；48项源接缝与两条TCP链路覆盖父引用、CSRF、consent撤销。未发现待修复High/Medium，独立审查者随后只读复核确认该Medium已关闭，未重跑测试；执行证据由主代理提供。T004/T005分层/协议/无密存储核查通过；T006本地已验证，115发布待连接。

最终判定：PASS（本地实现；115部署验收尚未完成）。DM8方言和实库验证仍是已披露的环境覆盖限制，未计为通过。用户新授权开发完成后部署115且不额外备份，保留发布版本记录；当前尚未部署，不自动合并。
