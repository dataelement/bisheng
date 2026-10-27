# 任务

- Status: `implemented-local-verified`

- [x] T001 候选入口和当前正文身份
  - _Requirements: REQ-001, REQ-003, REQ-004_
  - _Acceptance: AC-01, AC-03, AC-04_
  - _Verification: V-001 真实 ORM 复现；V-002 发布推荐和正文查询集成_
  - _Depends: none_
  - _Boundary: 不修改通用主版本查询语义，不绕过查看权限或目标库过滤_
- [x] T002 库内缓存和发布完成刷新
  - _Requirements: REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-02, AC-03, AC-04_
  - _Verification: V-003 发布完成持久意图、重复/失败/主版本变化回归_
  - _Depends: T001_
  - _Boundary: 不全量重算历史，不重开已处理提醒_
- [x] T003 前端入口预览与关联能力适配
  - _Requirements: REQ-003, REQ-005_
  - _Acceptance: AC-03, AC-05_
  - _Verification: V-002 接口契约；V-004 两个现有对话框组件验证_
  - _Depends: T001, T002_
  - _Boundary: 仅识别及必要交互，不新增合并/授权/审批流程_
- [x] T004 相关回归与规格验收
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05_
  - _Verification: V-001 至 V-004 有效证据、最终相关回归和静态检查_
  - _Depends: T001, T002, T003_
  - _Boundary: 未验证项保留 MANUAL_REQUIRED，不提交/推送/部署或修改线上数据_

## 实际偏差记录

- 发布就绪触发点落在仓储 `apply_projection_result` 的代次条件更新成功后，与就绪状态同事务登记持久任务；无需修改投影服务或 worker 的原有入口。
- 相似上下文与编排提取到独立 schema/service，避免继续扩大原版本服务；未新增表或依赖。
- 缓存签名使用现有 `user_metadata._similarity_snapshot`，锁行合并并在 RAG 元数据中排除此内部键。候选与签名分步提交期间，读端隐藏不匹配结果，后续重试可恢复。
- 发布入口只提供相似参考及目标入口预览；保留原有合法物理目标的发布版本关联能力，不新增入口版本链或自动合并。
- 本地使用真实 ORM、持久任务服务及实际前端组件完成验证，未进行部署后的浏览器端到端验收。MySQL、DM8、真实 ES/OpenFGA/Celery 仍需人工验收。
- 两项既有“多版本缓存候选必须隐藏”断言在修改前 HEAD 也失败，已记录基线并从最终相关回归中单独排除，未扩大范围修复。
