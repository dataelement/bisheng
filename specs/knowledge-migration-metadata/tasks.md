# 任务

- [x] T1 复现普通迁移改变 ID/内容代次及重解析；实现原位迁移。_Requirements: REQ-1, REQ-4_ _Acceptance: AC-1, AC-4_ _Verification: E-001, E-002_ _Depends: none_ _Boundary: 本地代码_
- [x] T2 共享内容元数据迁移、保留链接与覆盖合并及失败恢复。_Requirements: REQ-1, REQ-2, REQ-4_ _Acceptance: AC-1, AC-2, AC-4_ _Verification: E-002, E-003_ _Depends: T1_ _Boundary: 不调用真实存储_
- [x] T3 有界批量领取、状态回写和查询复用。_Requirements: REQ-3_ _Acceptance: AC-3_ _Verification: E-002_ _Depends: T1, T2_ _Boundary: 保留单文档切换边界_
- [x] T4 相关回归、静态检查及验证记录。_Requirements: REQ-1, REQ-2, REQ-3, REQ-4_ _Acceptance: AC-1, AC-2, AC-3, AC-4_ _Verification: E-002, E-003, E-004；真实依赖人工验证未执行_ _Depends: T3_ _Boundary: 不部署_
