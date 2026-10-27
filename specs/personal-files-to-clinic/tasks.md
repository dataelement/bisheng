# 执行任务

- [x] T1 实现路径选择、上传人组织路由、版本链过滤和逐文件跳过报告。
  _Requirements: REQ-1, REQ-2_ _Acceptance: AC-1, AC-2_ _Verification: 规划和查询集成测试_ _Depends: none_ _Boundary: 新脚本和测试_
- [x] T2 实现目录准备、原地迁移、权限/共享索引验证及报告恢复。
  _Requirements: REQ-3, REQ-4_ _Acceptance: AC-3, AC-4_ _Verification: 事务、失败和恢复测试_ _Depends: T1_ _Boundary: 不运行真实迁移_
- [x] T3 添加使用说明，完成相关回归、静态检查并记录限制。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_ _Acceptance: AC-1, AC-2, AC-3, AC-4_ _Verification: verification.md_ _Depends: T2_ _Boundary: 保留已有未提交改动_

## 实际偏差记录

- [x] T16 支持显式指定来源库及目录范围，自动仅接口同步文件；个人/科室/部门等来源共用原路由，复核及恢复固定范围并拒绝越界，原默认扫描保持不变。
  _Requirements: REQ-11_ _Acceptance: AC-11_ _Verification: 2026-10-20 相关脚本回归 342 项通过、只读 ORM 及迁移/恢复保护验证、静态检查_ _Depends: T14_ _Boundary: 用户确认包含非个人库，本地修改验证，不部署、不执行真实迁移_

- [x] T14 支持显式同内容覆盖，旧目标进入回收站，保留源文件 ID、原对象和内容；保护独立单版本/租约/审批/共享引用，验证两侧事务回滚、索引及全文清理中断恢复、稀疏向量报告往返。
  _Requirements: REQ-3, REQ-4, REQ-10_ _Acceptance: AC-3, AC-4, AC-10_ _Verification: 2026-10-14 脚本回归 286 项通过、静态检查及生产只读预检 19 项放行_ _Depends: T13_ _Boundary: 不执行生产迁移_

- [x] T13 显式允许同名不同内容主文件改名迁移，保留同内容/缺 MD5 冲突保护，覆盖规范文档及无版本链路径、事务回滚、报告恢复和全文名称刷新。
  _Requirements: REQ-3, REQ-4, REQ-9_ _Acceptance: AC-3, AC-4, AC-9_ _Verification: 2026-10-14 脚本回归 261 项通过及静态检查_ _Depends: T12_ _Boundary: 本地修改，不部署、不执行生产迁移_

- [x] T12 两人的科室库均不可用时，按原始/当前上传人顺序兜底最近部门绑定库，复用目录、权限、索引及恢复流程，验证四级优先级和目标类型/绑定保护。
  _Requirements: REQ-2_ _Acceptance: AC-2_ _Verification: 2026-10-13 脚本回归 235 项通过及静态检查_ _Depends: T11_ _Boundary: 本地修改、不部署或运行真实迁移_

- [x] T11 原始上传人无法匹配科室库时使用当前上传人兜底，同步预览与执行前批量查询，验证优先级、失败原因、上传人字段保留和路由变化拒绝。
  _Requirements: REQ-2_ _Acceptance: AC-2_ _Verification: 2026-10-13 脚本回归 205 项通过及静态检查_ _Boundary: 本地修改、不部署或运行真实迁移_

- [x] T10 准备固定范围后台执行，支持仅有管理入口的静止失败投影，验证默认拒绝、状态保留、恢复和范围/维护/审计边界。
  _Requirements: REQ-3, REQ-4, REQ-6_ _Verification: 2026-10-12 生产只读预检及 197 项本地回归_ _Boundary: 本地准备完成，实际部署和 apply 等待维护窗口确认_

- [x] T9 按用户修正，将接口同步模式目标改为文件直接所在目录名，来源筛选及报告保留完整路径，验证根目录、同名目录、冲突及新旧报告恢复。
  _Requirements: REQ-8_ _Acceptance: AC-8_ _Verification: 2026-10-12 目录映射及脚本回归_ _Depends: T8_ _Boundary: 普通模式保留完整路径、不运行真实迁移_

- [x] T8 增加接口同步来源筛选开关，支持所有个人库目录，复用原始上传人科室路由并验证锁内及恢复复核、混合来源版本链拒绝。
  _Requirements: REQ-8_ _Acceptance: AC-8_ _Verification: 2026-10-12 来源筛选及脚本回归_ _Depends: T7_ _Boundary: 保留普通模式、不运行真实迁移_

- [x] T7 支持已有版本链但无管理入口的静止未解析文件，保留版本及解析/投影状态，验证正常迁移、异常拒绝及提交前后恢复。
  _Requirements: REQ-7_ _Acceptance: AC-7_ _Verification: 2026-10-12 定向及脚本回归_ _Depends: T6_ _Boundary: 无共享内容、不补建管理入口、不运行真实迁移_

- [x] T6 支持未解析成功文件及未建立版本链的原始文件迁移，保留解析状态和已有内容，验证空/部分索引、并发拒绝与恢复。
  _Requirements: REQ-6_ _Acceptance: AC-6_ _Verification: 2026-09-30 定向及脚本回归_ _Depends: T5_ _Boundary: 不重解析、不补建分块、不运行真实迁移_

- [x] T5 增加显式权限所有者回退选项，保持上传人/库所有者不变，验证默认拒绝、有效所有者不替换、失效账号回退和中断恢复。
  _Requirements: REQ-5_ _Acceptance: AC-5_ _Verification: 所有者失效集成回归_ _Depends: T4_ _Boundary: 不运行真实迁移或修改库所有者_

- [x] T4 精简主报告为匹配但未迁移文件及原因，隔离最小恢复状态并验证预览、失败、中断和恢复。
  _Requirements: REQ-4_ _Acceptance: AC-4_ _Verification: 精简报告及恢复回归_ _Depends: T3_ _Boundary: 不修改迁移规则、不执行真实迁移_

用户已在会话确认迁移口径，按授权持续完成脚本和本地验证，不重复索要阶段确认；不执行 apply。
