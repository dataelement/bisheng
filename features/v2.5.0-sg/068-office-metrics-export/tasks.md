# 科室指标导出任务

- Feature ID: `068-office-metrics-export`
- Status: `verified-with-warnings`
- Created: `2026-09-29`
- Updated: `2026-09-30`
- Related requirements: `requirements.md`
- Related design: `design.md`

用户已授权开始实施。T001—T003 已完成；2026-09-30 目标环境只读导出及明细独立复算通过。用户确认的历史兼容边界及实际证据见 verification.md。

- [x] T001 实现组织、库存、登录和问答只读查询边界。
  - 完成条件：严格租户和组织子树校验；固定科室唯一映射；库存排除条件正确；ES 全页读取及来源差异诊断；查询不创建索引。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-005_
  - _Acceptance: AC-001, AC-002, AC-004, AC-007, AC-008_
  - _Verification: V-001, V-002_
  - _Depends: none_
  - _Boundary: scripts/export_office_metrics.py 中的只读查询类与对应测试_

- [x] T002 实现去重集合、当前组织归属和两级比例计算。
  - 完成条件：贡献总数跨库去重；科室/部门/公司分母各自正确；其他组织不混入十科室使用占比分母；零分母和未知有明确状态。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-001, AC-002, AC-003, AC-004, AC-005, AC-008_
  - _Verification: V-001_
  - _Depends: T001_
  - _Boundary: scripts/export_office_metrics.py 中的计算类与对应测试_

- [x] T003 交付 CLI、CSV 汇总/明细和操作说明。
  - 完成条件：新目录输出全部 CSV，主表固定列和行顺序；导出有阶段日志、ES 页数和来源统计；失败只留诊断、不伪造完整主表；README 可独立指导使用。
  - _Requirements: REQ-001, REQ-004, REQ-005_
  - _Acceptance: AC-001, AC-006, AC-007, AC-008_
  - _Verification: V-003_
  - _Depends: T001, T002_
  - _Boundary: scripts/export_office_metrics.py、scripts/README.md 与对应测试_

## 验证检查点
- 同一代码状态完成一次新脚本定向测试，涵盖 V-001 至 V-003；若复用逻辑有改动，仅补跑受影响旧脚本测试。
- CLI --help、语法、针对新增文件的 lint 和 diff 检查；不得把未执行测试标为通过。
- V-004 在有目标环境连接与组织 ID 后只读执行，未执行时明确标注；不得借对账执行迁移或回填。
- 在 verification.md 记录命令、代码状态、结果和限制；成功证据复用，不逐任务重复跑全量测试。

## 覆盖矩阵
| Requirement | Acceptance | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-001 | T001, T002, T003 | V-001, V-003, V-004 |
| REQ-002 | AC-002, AC-003 | T001, T002 | V-001, V-004 |
| REQ-003 | AC-004, AC-005 | T001, T002 | V-001, V-002, V-004 |
| REQ-004 | AC-006 | T003 | V-003, V-004 |
| REQ-005 | AC-007, AC-008 | T001, T002, T003 | V-001, V-002, V-003, V-004 |

## 质量门与实施记录
- [x] 每项任务有稳定需求、验收、验证、依赖和边界。
- [x] 所有验收均有任务和验证覆盖，没有重复测试任务。
- [x] 实现严格限定新脚本、辅助模块、定向测试、README 和本规格，保留已有工作区改动。
- 用户已完成需求逐项确认并授权实施；本轮未提交、未推送、未迁移或写入远程数据。

## 实际偏差记录
- 2026-09-30 用户确认问答历史兼容策略，显式新增 `--qa-history-policy raw`，默认 strict 不变；原始来源计数、不叠加看板独有记录。新增旧事件重复/投影独有/双标识缺失测试；修复后 24 项测试及 lint 通过。
- 2026-09-30 生产复验发现历史组织路径与父链不一致。用户确认统计按 `parent_id` 重建内存组织树，保留原路径差异诊断；不修复或回写数据库。修复前新增三个用例均按预期失败；修复后新脚本 22 项测试及 lint 通过。真实导出结果另记 verification.md。
- 用户追加要求单文件交付：查询和计算收进 export_office_metrics.py，移除两个辅助模块，内置文档身份和 ES 节点日志函数，不再依赖其他运维脚本。内部类/函数和业务行为保留。
- 沿用当前分支实施独立脚本，未切换含已有改动的工作区，也未提交无关内容。
- 测试发现组织只出现在 JOIN 中时租户钩子未识别；新查询显式投影组织列解决，不修改共享租户过滤器。
- 用 CASE 包装成员关系 EXISTS，避免要求 DM8 支持直接 SELECT 布尔谓词；真实 DM8 执行仍待目标环境验证。
- 数据库保持现有隔离配置，因此文档明确只承诺同一读取事务，不宣称跨系统全局快照。
