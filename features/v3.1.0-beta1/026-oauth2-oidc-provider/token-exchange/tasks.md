# Token Exchange 进度

| 文档/阶段 | 状态 | 说明 |
| --- | --- | --- |
| spec.md | ✅ 已评审并由用户确认 | 用户明确“规格接受，继续下一步” |
| design.md | ✅ 用户确认 | 用户明确“设计确认，开始编码”；不再重复请求确认 |
| test-cases.md | ✅ 已生成 | 八列QA参考用例，结果与自动化报告分开 |
| T001 接口和授权关系 | ✅ 完成 | 两新表、policy管理、标准grant、默认不启用；AC01–07/10–13/16 |
| T002 派生会话 | ✅ 完成 | B独立session、父关联、scope/expiry、userinfo；AC08–09/14–15 |
| T003 验证及交付 | ✅ 完成 | 最终合跑82 passed/1 skipped，真实TCP链路及路由回归通过；接入/验证/评审文档已补齐，不部署 |

## 任务核查

依赖顺序：T001定义policy/schema和接口，T002以独立会话补齐在线撤销，T003合跑旧新回归并做真实HTTP集成。目标文件分别为exchange模型/schema/repository/API/protocol/errors；exchange_service/auth_service/runtime；test_exchange、test_exchange_boundaries、test_e2e_token_exchange_local及locales/route metadata生成物。配对测试均在同一提交，已执行；L1/L2核查记录见code-review.md。两子代理异常退出且无改动，主代理接手全部实现，无并发文件覆盖。未知/失败状态拒绝，无环境部署授权扩展。

## 第一方增量（用户已确认）

| 任务 | 状态 | 范围 |
| --- | --- | --- |
| T004 权威平台接缝 | ✅ 完成 | user/application/oauth_exchange；web/mobile/CSRF/版本/撤销，独立58项联合测试通过 |
| T005 第一方换证与同意 | ✅ 本地验证完成 | 独立服务、两新表、token分派、consent记录/撤销、登记绑定；AC18–23 |
| T006 集成与交付 | 🔄 执行中 | 真实HTTP、全回归、独立审查、PR更新及115备份部署验收 |

## 实际偏差

暂无推翻已确认设计的偏差。测试使用SQLite/FakeRedis和真实签名；不把它当作MySQL/DM8或线上部署验收。
