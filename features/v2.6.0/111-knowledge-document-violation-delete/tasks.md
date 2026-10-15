# Tasks: 知识文档违规删除

**技术方案**: [design.md](./design.md)  
**验收矩阵**: [acceptance.md](./acceptance.md)  
**版本**: v2.6.0  
**分支**: 毕昇当前分支 `feat-2.5.0-sg-lkk-1010`，门户当前分支 `feat-sg-1010`。未经允许不新建分支。

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| design.md | 已接受 | 2026-10-15 落盘 |
| acceptance.md | 已落盘 | 实现前矩阵，未执行 |
| tasks.md | 已拆解 | 尚未实现 |
| 实现 | 已完成 | T001–T007 |

## 开发模式

写路径的验收是接口流转：真实 Endpoint 到 Service、Repository、171 MySQL。断言 HTTP 业务码，SELECT 方案里的表，再用库里的事实再请求一次。流转测试写在 `src/backend/test/knowledge/test_knowledge_violation_delete_flow.py`，不追加进知识库巨石测试，也不整文件跑巨石测试。

新逻辑放小文件。不要对 `knowledge_space_service.py` 做整文件格式化。纯规则单测可以另放小文件，不能代替流转测试。

Client 局部 Jest：`npx jest <文件> --coverage=false --watchAll=false`。门户规则编辑同理，只跑碰到的测试文件。

达梦不在 macOS 上跑。迁移要能在 MySQL 执行；达梦留到 CI。

## Tasks

- [x] **T001**: 规则种子、补扣快照列、错误码和分值校验  
  **文件**: 新建 Alembic 版本（落笔前看 heads，当前可见最高号是 `v2_6_0_f115`）、`src/backend/bisheng/points/domain/constants/seed_rules.py`、`src/backend/bisheng/points/domain/services/points_rule_service.py`、`src/backend/bisheng/common/errcode/knowledge_space.py`、`src/backend/bisheng/core/config/settings.py`、`src/backend/bisheng/points/domain/models/points.py` 的 `PointPendingDeduct`、`src/backend/test/points/test_library_scope_rule_expr.py`  
  **逻辑**: 幂等插入 R4、R5、R6，类型 `deduct`，默认启用。展示名分别为「知识文档色情低俗/暴力违法」「知识文档不当言论」「知识文档其他违反规范」。`score_expr` 为 `{"mode":"library_scope","public":3,"department":2,"team":1}`。`point_pending_deduct` 增加可空列 `scope_tier`、`score_snapshot`，中文 comment 按 design.md。错误码 18052、18053、18054。R4–R6 只接受三个正整数的 `library_scope`，单分值、0、负数返回 18203。新增开关 `points.knowledge_violation_delete_enabled`，默认 true。不改 R1 的分值结构。  
  **覆盖 AC**: VD-21 的后端校验  
  **依赖**: 无

- [x] **T002**: 影响范围、豁免和被扣人  
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_violation_delete_policy.py`、`src/backend/test/knowledge/test_knowledge_violation_delete_policy.py`  
  **逻辑**: 纯函数。可见库等级取公共库、部门库、团队库或科室库的最高档；科室库使用 `team` 分值。个人库不进入档位，也不构成月奖豁免。月奖豁免只认删除当时、已启用且分值大于 0 的月奖身份，默认是公共库所有者、部门库管理者、科室库管理者。被扣人优先 `original_uploader_id`，否则管理入口的 `user_id`。操作者与被扣人相同则不扣。没有被扣人则不扣。  
  **覆盖 AC**: VD-02、VD-05、VD-07、VD-08、VD-09、VD-10、VD-27 的判定部分  
  **依赖**: T001

- [x] **T003**: 预览和确认接口  
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_violation_delete_service.py`、`src/backend/bisheng/knowledge/api/endpoints/knowledge_violation_delete.py`、知识空间路由注册处、`src/backend/test/knowledge/test_knowledge_violation_delete_flow.py`  
  **逻辑**: 预览 `POST /api/v1/knowledge/space/files/{file_id}/violation-delete/preview` 只读。确认 `POST /api/v1/knowledge/space/files/{file_id}/violation-delete`，`rule_code` 可空，空则只删不扣，`remark` 最长 200。服务端重查身份：平台超管，或该文档某个非个人可见库的所有者/管理者。只认 `is_platform_super_admin`，不把平台管理员算进来。从个人库发起、只有删除权限、开关关闭，返回 18052。没有 `reference_document_id` 返回 18053。存在 `preparing` 入口返回 18054。这三种拒绝都不写回收、不写流水。确认时锁定文档，调用 `KnowledgeDocumentRecycleService.recycle`，回收该 `reference_document_id` 下全部有效原件、发布和分享，含个人库原件。收藏行不删。回收提交后再扣分。幂等键 `deduct:knowledge_document:{document_id}`，不带规则编码。第一次不扣不写这个键。余额允许为负。错误响应不含文档正文。  
  **覆盖 AC**: VD-01 至 VD-12、VD-15 至 VD-18、VD-24 至 VD-27  
  **依赖**: T002

- [x] **T004**: 补扣使用确认时的金额  
  **文件**: `src/backend/bisheng/points/domain/services/points_pending_deduct_service.py`、`src/backend/bisheng/worker/points/tasks.py` 里现有 drain 的调用点、`src/backend/test/knowledge/test_knowledge_violation_delete_flow.py`  
  **逻辑**: 知识文档扣分失败时写入 `point_pending_deduct`，带上 `scope_tier` 和 `score_snapshot`。重试用快照金额，不再按删完后的可见库重算，也不改用后来保存的新分值。专家问答补扣仍读 R1–R3 的单一 `score`，`scope_tier` 和 `score_snapshot` 为空。扣分成功后的站内信继续用 `deduct_admin`。  
  **覆盖 AC**: VD-13、VD-20 的补扣不被快照带偏  
  **依赖**: T003

- [x] **T005**: Client 违规删除入口  
  **文件**: Client 知识库文件操作（门户工作台和空间详情里现有的删除入口）、对应 API 封装、局部 Jest  
  **逻辑**: 不另加「违规删除」菜单。非个人库且当前角色是创建者或管理者时，点单个文件的「删除」弹出选择，默认「不扣分」。不扣分走原来的删除，不调用违规删除接口。选「按规则扣分」才调用预览和确认，提交 R4、R5 或 R6。文件夹和批量删除仍走原来的删除。个人库和只有删除权限的成员点删除不出现这个选择。分值不在前端写死。按钮显隐不代替 T003 的查表测试。  
  **覆盖 AC**: VD-29  
  **依赖**: T003

- [x] **T006**: 门户规则编辑三档分值  
  **文件**: 门户仓 `frontend/src/pages/admin/PointsRuleEditModal.tsx`、`frontend/src/pages/admin/PointsManagementPanel.tsx`、`frontend/src/pages/admin/pointsAdminUtils.ts`，以及现有 `frontend/tests/pointsRuleAdminUtils.test.ts` 或同目录新测试  
  **逻辑**: R4、R5、R6 编辑公共库、部门库、团队库三个正整数，保存 `library_scope`。科室库不单列。R1–R3 和 G 规则的编辑不变。  
  **覆盖 AC**: VD-21 的页面提交体  
  **依赖**: T001

- [x] **T007**: 普通删除和专家问答回归  
  **文件**: 不改普通删除契约。点名跑现有专家问答扣分用例 `src/backend/test/qa_expert/test_moderate_delete_points_notify_flow.py` 中带 R1 的用例，以及一条普通删除不写 `biz_type=knowledge_document` 流水的断言，放在 T003 的流转文件里  
  **逻辑**: 普通删除不扣分。专家问答 R1 仍按单一 `score` 扣。  
  **覆盖 AC**: VD-19、VD-20  
  **依赖**: T004

## 实际偏差记录

- 2026-10-15: 171 MySQL 已执行 `f116_knowledge_violation_deduct`。`test_knowledge_violation_delete_flow.py` 共 9 条, 含个人库原件一起回收并扣 3 分、再确认不新增流水、无文档身份、公共库 1 分压过部门库 5 分、科室库月奖豁免。
- 2026-10-15 补齐查表: 只删不扣后再扣只记一条、发布准备中返回 18054 且不回收、补扣改分后仍扣确认时的 3 分、两人同时确认只扣一次。普通删除函数源码断言不调用违规扣分。专家问答 R1 回归已通过。
- Client 显隐单测和门户规则 helper 测试已通过。本地 4001/5173 知识库页面若未启动, 没有在浏览器里点违规删除。
- 2026-10-15 产品改为第一种: 沿用原来的「删除」。不扣分保持当前删除范围, 不调违规删除接口。只有选择按规则扣分才走违规删除, 各库原件和副本进回收站并扣分。个人库、普通成员、文件夹和批量删除不变。
