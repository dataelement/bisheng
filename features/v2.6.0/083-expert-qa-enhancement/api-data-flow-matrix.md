# F083 接口 + 落库流转验收矩阵

> 开发自验收门：测数据有没有按规则转完一圈。UI 不在本表。  
> 预言机：`prd.md` + `spec.md` AC + `design.md` 字段/183xx。  
> 实现：`src/backend/test/qa_expert/test_data_flow.py`（真仓储 + **171 MySQL**；禁止 mock Repository；SQLite 不算本门禁）。

## 涉及数据表（无 DDL / 无字段增删改 / 不做迁移）

| 表 | 角色 | 本矩阵关键已有字段 |
|---|---|---|
| `qa_question` | 写 | `question_type` `content_locked` `answer_count` `adopt_count` `related_docs` `resolved_at` `active_publish_request_id` `status` |
| `qa_question_invite` | 写 | `question_id` `expert_id` `user_id` |
| `qa_answer` | 写 | `question_id` `user_id` `status` `adopted` |
| `qa_answer_adopt` | 写 | `question_id` `answer_id` `expert_user_id` `adopted_by` |
| `qa_answer_eligibility` | 写 | `question_id` `user_id` `source` |
| `qa_comment` | 写 | `question_id` `answer_id` `user_id` |
| `qa_expert` | 写 | `user_id` `status` |
| `qa_publish_request` | 写 | `question_id` `status` `duration_days` |
| `qa_publish_approver` | 写 | `request_id` `user_id` `decision` |
| `qa_anonymous_alias` | 本轮 P1 | 同题别名稳定 |
| `inbox_message` | 旁路，本轮不测 | 通知 |

## P0（本轮必须绿）

| ID | AC | 接口动作 | HTTP | 落库 | 再打一枪 |
|---|---|---|---|---|---|
| DF-01 | AC-04 | POST 定向题邀 1 专家 | 200；`question_type=directed` | `qa_question` 一行 directed；`qa_question_invite` 正好 1 行且非提问者 | 提问者 GET 详情可见 |
| DF-02 | AC-05 | POST 公开题 | 200；`question_type=public` | `qa_question` public；invite 表 0 行 | 路人 GET 详情可见 |
| DF-03 | AC-06 | 无权用户 GET 定向详情 | `status_code=18301`；body 无标题/正文 | 问题行仍在，无新脏行 | 无权用户列表不含该题 |
| DF-04 | AC-08/47 | POST 带 `related_doc_ids=["3-8"]` | 200 | `qa_question.related_docs` 含 `3-8` | GET 详情 `unavailable_reason` 不得用无权限冒充 not_found 时见 DF 注 |
| DF-05 | AC-09 | 受邀专家首答 | 200 | `qa_answer` +1；`content_locked=1`；`answer_count=1` | 提问者改邀请应失败（锁） |
| DF-06 | AC-12 | 未受邀专家答定向 | 183xx | `qa_answer` 行数不变 | — |
| DF-07 | AC-11 | 删除唯一未采纳回答 | 200 | 该回答 `status=3`；`answer_count=0`；**`content_locked` 仍为 1** | 提问者仍不能改正文 |
| DF-08 | AC-14/16 | 公开题：A 受邀未答、B 答后删、C 答；采纳 C | 200；已解决 | `qa_answer_adopt` +1；`adopt_count=1`；eligibility 含 A/B/C | D 再答拒绝且无新回答行 |
| DF-09 | AC-17 | 连续采纳第 4 条 | 业务错误 | `qa_answer_adopt` 仍 3；`adopt_count=3` | — |
| DF-10 | AC-43 | 定向受邀专家未答就评论 | 183xx | `qa_comment` 无新行 | 先答后再评可写入 |
| DF-11 | AC-15/29/31 | 管理员停用专家 | 200 | `qa_expert.status=0`（行还在） | 该用户 POST 回答拒绝、无新行 |
| DF-12 | AC-30 | 非管理员 POST disable | 权限错误 | `qa_expert.status` 仍 1 | — |
| DF-13 | AC-23/24/28 | 已解决定向转公开：发起+全体同意 | 200 | 申请 `approved`；`question_type=public`；invite 行数不变 | 非原受邀专家回答拒绝 |
| DF-14 | AC-10 | 两专家并发 POST 首答 | 两路 200 | 两行 `qa_answer`；`content_locked=1`；`answer_count=2` | 锁不可逆 |
| DF-15 | AC-17 | 两路并发采纳不同回答 | 两路 200 | 两行 `qa_answer_adopt`；`adopt_count=2`；资格无重复脏行 | 不超 3 |

## P1（本轮不做，矩阵占位）

| ID | AC | 说明 |
|---|---|---|
| DF-16 | AC-19/20 | 匿名别名写入 `qa_anonymous_alias`，删除不重排 |
| DF-17 | AC-26 | 到期过期任务改 `qa_publish_request.status=expired` |
| DF-18 | AC-36 | `inbox_message` 旁路有行 |
| DF-19 | AC-07 | 存量迁移默认 public（Alembic，非接口） |
| DF-20 | AC-41 | 未登录 401（依赖网关，非本 SQLite 门禁） |
| DF-21 | AC-32/33 | 超管才能违规删除；管理员打 moderate-delete 拒绝且无删行 |

## 不算验收

mock Repository / 只断言 JSON 形状 / Playwright。
