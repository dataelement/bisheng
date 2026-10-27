# 实施任务

- [x] T001 数据集、原始库名称批量读取和文件投影
  - _Requirements: REQ-1, REQ-2, REQ-3_
  - _Acceptance: AC-1, AC-2, AC-3_
  - _Verification: E-001 后端投影和数据集测试_
  - _Depends: none_
  - _Boundary: 不改上传、发布及组织事实源_
- [x] T002 后续事件维度传递及日记录身份兼容
  - _Requirements: REQ-4_
  - _Acceptance: AC-4_
  - _Verification: E-001 事件快照与ID兼容测试_
  - _Depends: T001_
  - _Boundary: 不重放或修改历史事件，不改变计数协议_
- [x] T003 回归、组件检查及交付说明
  - _Requirements: REQ-1, REQ-2, REQ-5_
  - _Acceptance: AC-1, AC-2, AC-5_
  - _Verification: E-001 后端相关回归，E-002 前端组件测试，E-003 浏览器检查_
  - _Depends: T001, T002_
  - _Boundary: 不提交、推送或部署_

- [x] T004 专用脚本、字段级保护与回退日志
  - _Requirements: REQ-6, REQ-7_
  - _Acceptance: AC-6, AC-7_
  - _Verification: 定向脚本测试、生产只读预览及写入后核验_
  - _Depends: T001_
  - _Boundary: 生产写入须先展示预览并确认；不改数据库或历史事件_
  - 实际结果：20项本地测试通过，最终版生产预览退出0；20,424条中候选0，无需写入。52条异常记录未修复，142条历史原始库ID回退已披露；真实ES更新/回退未执行。

## 实际偏差记录

- [ ] T005 按定向来源清单回填142条事实并刷新统计（等待用户确认生产写入）
  - _Requirements: 用户追加请求核实是否可以实际补齐；具体范围见verification.md E-010至E-013_
  - _Acceptance: 两个原始来源ID补齐142条，原始库名称142条、部门9条、科室139条按清单纠正；写后读回且重复检查无同一来源缺失_
  - _Verification: E-010至E-013为准备证据；生产写入与读回NOT_RUN_
  - _Depends: T004_
  - _Boundary: 必须先确认；只处理固定142组，不扩展到另80条或52条异常，不回写历史事件_

用户已确认字段口径并明确“直接执行”，本轮将规格与执行计划一起落盘后持续实施，不再次设置同范围确认点。不修改已有分支及用户的其他工作区变更。
