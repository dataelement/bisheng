# Code Review Report

**Feature**: F023 子租户视图与文件元数据修复
**Review scope**: 本轮自审；对照已确认计划、spec/design/tasks 和全部变更，不代表独立第三方审查
**Base branch**: feat/3.1.0-beta1，起始 33bcadaa3e

## Summary

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## 审查要点

- 成员读取只接收已授权且有界分页。跨物理租户读取限制到确切用户/角色 ID；foreign-home 不返回角色，历史无效绑定不进入有效角色列表。异常数据仅可信全局超管且当前业务范围一致时返回，不写绑定、不作为授权结果。部门主属异常仍失败关闭。
- 提取 eligible/topology 函数保持严格登录解析语义。新增只读展示允许逐绑定诊断缺失定义，设计明确不能用于登录、额度、菜单或资源授权。
- 助手配置继续严格校验；候选同时受配置 ID、合法可见 provider、物理归属约束，不调用全量模型兜底。默认模型及 provider 置首保持，UI 过滤下线项并保留已有不可用选择。读取失败禁用候选并提供重试。
- 模型状态更新在缓存清理、provider 请求、数据库写入之前验证当前管理目标；子租户对合法共享 Root 模型返回已有只读错误，不能依全局超管身份穿透所选目标。
- 新建元数据复用原 schema revision、确认及幂等任务协议。未知请求结果冻结原操作同键重试；业务拒绝可修正草稿；任务成功且读到 schema 字段后才附加文件值。移除文件值不删定义。
- scope/space/file key 及组件存活标记阻止旧预检继续确认、旧保存关闭新弹窗；文件值保存单飞，失败保留草稿。时间值有日期范围保护及字段分组可访问标签。
- 无 DB 迁移、Worker 协议变更或现场修数。失败源任务保护沿用原规则；3547 不通过清标记或伪造成功解锁。
- 新文案三语覆盖；无新增架构违规、增量 Ruff 诊断或敏感信息。原范围检查、身份一致性及工具过滤不削弱。

## Findings

### MEDIUM

- [Test Coverage] 新构建尚未进入完整测试环境，真实 MySQL/DM8、OpenFGA、异步 worker 和浏览器联调未验收；5 个只读 opt-in E2E 默认跳过。依用户约定本轮不部署 116，后续按 e2e-checklist.md 验收。旧宽范围套件和 Ruff 的存量问题已与 HEAD 对照，详见 validation.md；不能宣称全仓回归通过。

## Overall: PASS_WITH_WARNINGS

本地实现和针对性验证完成；环境级验收保留为交付限制。spec/design/tasks 依据 sdd-review 清单复核 LGTM，报告在同目录。
