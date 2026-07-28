# 任务清单 Tasks: 系统字典路由启动修复

## 元信息 Metadata
- Feature ID: `049-dictionary-router-startup`
- Status: `completed`
- Related requirements: `specs/049-dictionary-router-startup/requirements.md`
- Related design: `specs/049-dictionary-router-startup/design.md`
- Created: `2026-07-28`
- Updated: `2026-07-28`

## 阶段 1：回归与修复

- [x] T001 建立 dictionary 路由注册失败回归
  - Done when: 测试在修复前因 `Prefix and path cannot be both empty` 失败。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02_
  - _Verification: V-AC-REQ-001-01_
  - _Depends: none_
  - _Boundary: `src/backend/test/dictionary/test_dictionary_router.py`_

- [x] T002 调整 dictionary 路由前缀挂载位置
  - Done when: dictionary 路由可注册，GET/POST 集合路径保持 `/api/v1/dictionaries`。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02_
  - _Verification: V-AC-REQ-001-01_
  - _Depends: T001_
  - _Boundary: `src/backend/bisheng/dictionary/api/router.py` 最小修改_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01, AC-REQ-001-02 | T001, T002 | V-AC-REQ-001-01 |

## 实现记录 Implementation Notes

- 修复前新增测试稳定复现 `FastAPIError: Prefix and path cannot be both empty`.
- `/dictionaries` 前缀移动到 `include_router()` 参数，集合接口路径未增加尾斜杠。
