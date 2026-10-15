# 任务：文件相似度两套规则

- Feature ID: `076-file-similarity-metadata-modes`
- Status: `implemented-local-verified`
- Created: `2026-10-15`
- 用户于2026-10-15确认实施；本地代码和验证完成，未提交、推送、部署或更新线上数据。

- [x] T001 配置模型、分组策略与保存校验
  - 增加两组规则和逐字段旧配置回退，保留false/0；提取元数据分组与公司资格策略；补配置及参数化分组测试、保存前拒绝非法配置测试。
  - 文件：`core/config/settings.py`、`api/v1/endpoints.py`、拟新增 `knowledge/domain/services/knowledge_file_similarity_policy.py`、`test/knowledge/`相关测试。
  - _Requirements: REQ-001, REQ-002, REQ-005_
  - _Acceptance: AC-01, AC-02, AC-03, AC-09_
  - _Verification: V-001 分组及配置；V-002 保存入口_
  - _Depends: none_
  - _Boundary: 本地代码及测试，不修改运行环境配置或数据库_

- [x] T002 统一库内、发布及共用相似校验
  - 将分组策略用于候选筛选；跨库正文按库批量读取；按各组开关/阈值复核；沿用排序、总数量及权限；共用版本校验与候选筛选一致。
  - 文件：`knowledge/domain/services/knowledge_version_service.py`；必要时最小适配 `approval/domain/services/shougang_approval_service.py`。
  - 补一个主要集成测试层，使用真实本地仓储、受控ES/Redis替身和发布权限回调；覆盖跨分类入选、不同组阈值、缺失字段、跨库正文、拒绝/降级及版本合并。
  - _Requirements: REQ-001, REQ-003, REQ-005_
  - _Acceptance: AC-01, AC-04, AC-05, AC-06, AC-09_
  - _Verification: V-003 服务集成及拒绝/降级回归_
  - _Depends: T001_
  - _Boundary: 不取消权限和租户/库过滤，不修改展示权重、数量、审批或force业务规则_

- [x] T003 缓存签名、补算筛选和配置示例
  - 源签名增加二级分类；补算使用统一资格，仍默认dry-run；初始化模板及运维说明列出分组参数、回退和存量刷新边界。
  - 文件：`knowledge_version_service.py`、`scripts/backfill_file_similarity_candidates.py`、`bisheng/initdb_config.yaml`及已存在的相关说明文件。
  - _Requirements: REQ-002, REQ-004_
  - _Acceptance: AC-02, AC-07, AC-08_
  - _Verification: V-003 状态/签名；V-004 脚本dry-run/apply替身_
  - _Depends: T002_
  - _Boundary: 不执行真实补算，不清空存量候选，不重开已处理文件_

- [x] T004 回归、界面验收与交付证据
  - 执行一次受影响后端回归、静态检查和现有页面必要浏览器验收；审查范围、权限与拒绝路径；记录真实命令、结果及环境限制。
  - 本地模拟与真实基础设施证据分别报告；没有运行的项目保留NOT_RUN或MANUAL_REQUIRED。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09_
  - _Verification: V-001至V-004有效证据复用；V-005 浏览器与最终回归_
  - _Depends: T001, T002, T003_
  - _Boundary: 不提交、推送、部署或写线上数据，除非用户另行要求_

## 覆盖与评审

| Task | Requirement | Acceptance |
|---|---|---|
| T001 | REQ-001、REQ-002、REQ-005 | AC-01、AC-02、AC-03、AC-09 |
| T002 | REQ-001、REQ-003、REQ-005 | AC-01、AC-04、AC-05、AC-06、AC-09 |
| T003 | REQ-002、REQ-004 | AC-02、AC-07、AC-08 |
| T004 | REQ-001至REQ-005 | AC-01至AC-09证据复用及缺口核对 |

## 实际偏差记录

- 用户确认后在现有 `feat/2.5.0-sg` 分支完成实现；未创建嵌套的同名前缀分支，未提交或推送。
- 仓库旧任务模板关于“没有测试框架”的描述与实际已有pytest/Jest测试不符，本规格复用现有测试，不新建测试基础设施。
- 后续只有范围、风险或实现路径发生实质变化才重新确认。
- 审批服务已有候选权限回调足以复用，未修改审批业务代码；新增复核分数沿用现有响应Schema。
- 界面源码未修改，使用实际SimilarDocumentDialog、本地API替身和后端实际计算快照验收；该证据不代表生产ES或浏览器完整联调。
- 2项旧多版本候选断言在修改前代码中同样失败，单独保留基线证据，不顺带改变其业务行为或测试预期。
- 已有超长配置/版本服务只做必要局部适配及局部格式化；新规则和新增测试独立成文件。
