# Tasks: 知识库文档纠错

**PRD**: [prd.md](./prd.md)  
**技术方案**: [design-technical-rfc.md](./design-technical-rfc.md)  
**实现契约**: [spec.md](./spec.md)  
**归属**: 积分系统 `features/v2.6.0/070-points-system/file-correction/`  
**版本**: v2.6.0  
**分支**: 当前已检出分支。未经允许不新建分支。

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| prd.md | 已落盘 | 2026-10-13 按对话确认稿写入 |
| design-technical-rfc.md | 使用中 | 取舍、失败停点和迁移 |
| spec.md | 已落盘 | 实现契约。不重复 RFC 的候选方案 |
| tasks.md | 已落盘 | 代码已在工作区，任务按完成补记 |
| 实现 | 工作区已完成 | 尚未提交。文档晚于代码 |

## 开发模式

后端写路径必须经过接口、服务、仓储到 171 MySQL。断言 HTTP 业务码、SELECT 点名的表，再用库里的事实再请求一次。测试放在 `test/knowledge/test_file_correction_flow.py`，不追加进知识库巨石测试。不对 `knowledge_space_service.py` 整文件格式化。

客户端用 `npx jest <文件> --coverage=false --watchAll=false`。门户只核对 G8 默认值。

## Tasks

- [x] **T001**: 三张纠错表、错误码、租户注入、G8 种子  
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge_file_correction.py`，`src/backend/bisheng/common/errcode/file_correction.py`，`src/backend/bisheng/core/database/tenant_filter.py`，`src/backend/bisheng/core/database/alembic/versions/v2_6_0_f110_knowledge_file_correction.py`，`src/backend/bisheng/points/domain/constants/seed_rules.py`  
  **逻辑**: 纠错单、待处理占位、发分行。G8 名称「文档纠错被采纳」，受益人反馈人，分值 1，每日上限空。纠错错误码用 184，不占用积分的 182。  
  **覆盖 AC**: AC-01 的落库前提  
  **依赖**: 无

- [x] **T002**: 提交资格  
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_file_correction_service.py`，`src/backend/bisheng/knowledge/api/endpoints/knowledge_file_correction.py`  
  **逻辑**: 可查看、四类库、非收藏、非上传人本人、上传人可用、500 字、一人一文档一条待处理。快照不存正文。  
  **覆盖 AC**: AC-01 至 AC-06、AC-17  
  **依赖**: T001

- [x] **T003**: 采纳、拒绝、撤回、删除取消、禁止代批  
  **文件**: 纠错服务，`src/backend/bisheng/approval/domain/services/approval_center_service.py`，`src/backend/bisheng/approval/api/endpoints/approval_user.py`，`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` 的删除调用点  
  **逻辑**: 纠错分支在管理员短路之前。拒绝要原因。撤回只在待处理。删除只取消待处理。  
  **覆盖 AC**: AC-07、AC-12 至 AC-16  
  **依赖**: T002

- [x] **T004**: 发分与采纳并更新  
  **文件**: 纠错服务，`src/backend/bisheng/core/database/alembic/versions/v2_6_0_f111_file_correction_award_kind.py`，`src/backend/bisheng/points/domain/services/points_award_facade.py`，`src/backend/bisheng/points/domain/services/points_award_hooks.py`，`src/backend/bisheng/worker/points/tasks.py`  
  **逻辑**: 采纳 1 分且上海自然日一次；采纳并更新每条 2 分且不设日上限。发分行按纠错单回写。新文件成为主版本后才发分。  
  **覆盖 AC**: AC-07 至 AC-11、AC-18  
  **依赖**: T003

- [x] **T005**: 客户端阅读页和待办  
  **文件**: `src/frontend/client/src/pages/knowledge/portal/fileCorrectionAccess.ts`，`src/frontend/client/src/pages/knowledge/portal/components/FileCorrectionDialog.tsx`，`src/frontend/client/src/components/approval/FileCorrectionNotice.tsx`，`src/frontend/client/src/components/approval/FileCorrectionDecision.tsx`，`src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx`，`src/frontend/client/src/api/approval.ts`  
  **逻辑**: 「纠错」按钮；待办显示采纳和采纳并更新；解析未完成可稍后再点。  
  **覆盖 AC**: AC-01、AC-09、AC-11 的页面侧  
  **依赖**: T002、T004

- [x] **T006**: 门户 G8 展示  
  **文件**: 门户仓 `frontend/src/pages/admin/pointsAdminUtils.ts`，`frontend/tests/pointsRuleAdminUtils.test.ts`  
  **逻辑**: 默认名称、受益人反馈人、分值 1、每日上限空。不改门户纠错页面。  
  **覆盖 AC**: 无新接口。与 AC-07 的金额展示一致  
  **依赖**: T001

## 实际偏差记录

- 代码先于这三份文档写入工作区。本文是补记。
- 纠错错误码曾误用 182，与积分调分、规则、公司根冲突。已改为 184。拒绝路径相关流转测试在改码后通过。
- 171 MySQL 上 `test/knowledge/test_file_correction_flow.py` 在改码前 6 条通过。改码后已重跑拒绝、代批和并发 3 条。采纳并更新那条没有改断言码，本次落盘没有重跑。
- 没有用已登录账号在页面上点过采纳并更新。达梦库没有跑。
- 采纳日切在非东八区服务器上可能偏差，见设计第 9 节。未改。
- `f111` 会删掉旧发分行再重建。本地 171 已执行。已有环境若已经有人用过旧结构，执行迁移会丢掉那些行。当前这条需求上线前若已有旧发分数据，必须先确认那些行可以丢。
