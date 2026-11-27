# Token Exchange 测试用例（测试工程师参考）

依据：spec及design均已用户明确确认；目标feat/3.1.0-alpha1/026-token-exchange，基线572d5ecf77，新增实现尚待集成提交。普通用户、tenant admin、global admin须分别造数；A为confidential且允许exchange，B独立注册，专用tenant/user和e2e-tokenexchange-前缀数据，测试后仅清理本套数据。自动化SQLite/FakeRedis与真实环境结果分别报告。

| ID | 功能点 | 优先级 | 前置条件 | 步骤 | 预期结果 | 测试结果 | 结果说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-TEX-001 | 同人跨系统 | P0 | A/B/策略有效，用户授权A | A授权码登录，再换B并验签 | aud=B，sub/tenant不变，无refresh/id_token | 待执行 | 自动化覆盖另见报告 |
| TC-TEX-002 | scope收敛 | P0 | 策略仅openid/profile | 申请含email范围 | 整体invalid_scope，不生成子会话 | 待执行 | — |
| TC-TEX-003 | 原凭证核验 | P0 | 有效签名样本 | 分别更换issuer/aud/tenant/sub/type或过期 | invalid_grant，未知详情不泄漏 | 待执行 | — |
| TC-TEX-004 | 可信调用方 | P0 | public/错误密钥/其他client | 请求交换 | invalid_client或unauthorized_client | 待执行 | — |
| TC-TEX-005 | 授权管理 | P0 | global/tenant管理员/普通用户 | 分别读写策略 | 仅global可用，分页准确 | 待执行 | — |
| TC-TEX-006 | 固定截止 | P0 | 原Token或父session短寿命 | 加入处理延迟后换证 | 不超过最早截止，过期拒绝 | 待执行 | — |
| TC-TEX-007 | 双向撤销区别 | P0 | 有A和B会话 | 撤销B，另换B后撤销A | 前者A有效，后者B在线无效 | 待执行 | — |
| TC-TEX-008 | 禁用/收窄 | P0 | 有B派生Token | 禁用策略/源/目标或缩scope | 新换证拒绝，B在线拒绝 | 待执行 | — |
| TC-TEX-009 | 错误输入 | P1 | 有效接口 | 重复字段/JSON键/超限/actor/resource/URLtoken | invalid_request和no-store | 待执行 | — |
| TC-TEX-010 | 故障与原子性 | P0 | 可注入身份/DB/提交故障 | 换证或在线查询 | 拒绝，无交付token，无半写会话和敏感日志 | 待执行 | — |
| TC-TEX-011 | 旧功能回归 | P0 | 原OAuth/DSH场景 | code/PKCE/refresh/revoke/DSH授权 | 行为兼容，无默认exchange授权 | 待执行 | — |
| TC-TEX-012 | B接收端 | P0 | 参考B配置issuer/aud/JWKS | 送正确/错aud/错issuer/过期Token | 只接受正确凭证，不继承A业务角色 | 待执行 | — |

映射：001→AC01/08/14；002→AC06/07；003→AC04/05；004→AC02/03；005→AC10/11；006→AC08/09；007→AC15；008→AC03/09/10；009→AC16；010→AC12/13；011→AC17；012→AC14。新入口与造数依据design §4–7，真实环境账号/地址不预填；执行后填写结果。
