# 复盘 Retrospective

**Feature ID**: `057-domain-bindable-spaces-perf`  
**Status**: Completed  
**Updated**: 2026-07-16

## 已完成范围

- 新增业务域候选空间的 BiSheng 管理员专用查询。
- 门户 BFF 改用专用查询，并保持门户管理员校验和空列表降级。
- 新增两端回归测试与 SDD 验证记录。

## 关键决策

- 直接按 `knowledge_space_scope` 的 public/department 等级取空间 ID，再按 `knowledge.is_released` 过滤，避免通用可见范围、OpenFGA 和文件数统计。
- 未保留对通用 `/knowledge/space/grouped` 的回退，避免上游故障时重新引入慢路径。
- 前端缓存和并发去重维持范围外，后续如仍有体验问题可独立处理。

## 验证缺口

- 本地全文件 Ruff 有既有基线问题；真实 MySQL/DM8 测试需由 CI 完成。
