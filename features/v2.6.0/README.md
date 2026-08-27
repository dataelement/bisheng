# v2.6.0 Feature 索引

**版本目标**：承载审批中心统一化等跨模块产品能力，作为 v2.5.x 之后的新一轮功能版本。

**版本契约**：[release-contract.md](./release-contract.md)

**开发主线分支**：`2.6.0-PM`

---

## Feature 列表

| # | Feature | 优先级 | 状态 | 依赖 |
|---|---------|--------|------|------|
| F025 | [approval-center-unification](./025-approval-center-unification/) | P0 | 🔲 规格已生成，待评审 | F005, F011, F012, F013 |
| F054 | [file-publish-submit-performance](./054-file-publish-submit-performance/) | P0 | ✅ 第一阶段已实现并完成自动化验证 | F025 |
| F079 | [tag-management-console](./079-tag-management-console/) | P1 | 🔲 规格已生成，待评审 | F013 |
| F082 | [department-short-name](./082-department-short-name/) | P1 | ⚠️ 主体实现完成，待环境验收 | F002, F009, F014/F015 |
| F083 | [portal-department-display-name](./083-portal-department-display-name/) | P0 | ✅ 已实现，人工 E2E 待执行 | F082, F025, F060, F064, F065 |
| F098 | [distribution-aware-container-delete](./098-distribution-aware-container-delete/) | P0 | 🔲 规格已评审，待实现 | F059, F071 |

---

## SDD 工作流

1. Spec Discovery → 对齐 PRD 不确定性
2. 编写 spec.md → `/sdd-review spec`
3. 编写 tasks.md → `/sdd-review tasks`
4. 创建 Feature 分支 `feat/v2.6.0/{NNN}-{name}`，基于 `2.6.0-PM`
5. 逐任务执行 → `/task-review` → 打勾
6. `/e2e-test`（强制）
7. `/code-review --base 2.6.0-PM`
8. 合并回 `2.6.0-PM`

---

## 变更历史

| 日期 | 变更 |
|------|------|
| 2026-05-18 | 初始化 v2.6.0 版本目录，并迁入 **F025-approval-center-unification** 规格与任务。 |
| 2026-08-26 | 新增 **F098-distribution-aware-container-delete**：容器删除不再被软链拦截，三条删除路径统一为一条分发规则。 |
| 2026-07-14 | 登记并完成 **F054-file-publish-submit-performance** 第一阶段：定向目标校验、发布通知异步化、审批任务批量写入与分段性能日志。 |
| 2026-08-07 | 登记 **F079-tag-management-console**：独立页面标签管理控制台（左右布局、统一分页、批量审核、审核留痕字段）。相似标签处理、正文高亮与上下切换、AI标签开关本期不做。 |
| 2026-08-10 | 登记 **F082-department-short-name**：创建部门与部门设置支持可选简称，简称本地维护且不改变组织树、搜索和同步名称契约。 |
| 2026-08-10 | 登记 **F083-portal-department-display-name**：首钢门户、嵌入式知识门户、成员管理、专家、审批和水印统一优先显示部门简称；保留正式名称字段及历史快照，首页硬编码积分榜与 Platform 组织架构不在范围内。 |
