# 专家问答搜索筛选实施任务

Feature ID: F083-qa-search-filters
Status: VERIFIED_LOCAL
Related requirements: [requirements.md](./requirements.md)
Related design: [design.md](./design.md)

用户确认本规格后，按同一范围连续实施、修复和验证，不逐任务重复请求确认。

- [x] T001 扩展问题搜索与受邀专家组合查询
  - 完成条件：查询字段贯通接口、服务和仓储；全文关键词、同一受邀专家条件、日期、可见性和匿名兼容；分页与总数一致。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-006_
  - _Acceptance: AC-001, AC-002, AC-003, AC-004, AC-007_
  - _Verification: V-QUERY, V-FIELDS, V-API, V-ACCESS_
  - _Depends: none_
  - _Boundary: bisheng/qa_expert 与 test/qa_expert；无数据/Schema/权限策略变更_

- [x] T002 实现固定搜索筛选区并连接分页列表
  - 完成条件：所有核心条件可组合，关键词回车/按钮提交，清空、个人范围、错误重试和分页生效，旧请求不覆盖新结果，固定区域不遮挡三栏。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-003, AC-004, AC-005, AC-006_
  - _Verification: V-BROWSER；前端构建及定向静态检查_
  - _Depends: T001_
  - _Boundary: 专家问答页面、专用筛选组件、expertQa API 和浏览器回归；保留已有未提交修改_

## 覆盖矩阵

| Requirement | Acceptance | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-001 | T001 | V-QUERY |
| REQ-002 | AC-002, AC-003 | T001, T002 | V-QUERY, V-FIELDS, V-BROWSER |
| REQ-003 | AC-004 | T001, T002 | V-QUERY, V-API, V-BROWSER |
| REQ-004 | AC-004, AC-005 | T002 | V-API, V-BROWSER |
| REQ-005 | AC-006 | T002 | V-BROWSER |
| REQ-006 | AC-005, AC-007 | T001, T002 | V-ACCESS, V-BROWSER |

## 规格与任务审查

2026-10-14：范围限定于用户确认的核心项；已检查 REQ→AC→设计→任务映射，所有验收有验证目标。身份搜索、邀请交叉拼凑、历史停用专家、分页总数和固定区域空间均有明确处理；没有实现全站/智能搜索或常用筛选。

这是文档审查结论，生产代码与测试尚未实现，不能据此声明功能或测试通过。

## 实际偏差记录

- 2026-10-14 用户追加“先设计一下前端页面和相关组件”。已完成独立交互页面稿、组件说明与本地设计验证；本轮只推进设计，T001/T002 正式集成任务仍未开始。

- 沿用 F083 子目录管理增量规格，未新建独立版本或修改 release-contract。
- 用户已确认需求发现阶段；仓库要求的规格确认暂停点保留在本轮交付。确认前仅创建文档，未修改生产代码。
- 用户已明确确认开始实施；完成 T001/T002 并复用最终验证证据。沿用当前工作树，保留其他任务的未提交更改，未自行提交、切换分支、推送或部署。
