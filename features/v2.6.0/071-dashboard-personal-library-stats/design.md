# 设计说明 Design: F071 看板个人知识库统计

## 元信息 Metadata

- Feature ID: `071-dashboard-personal-library-stats`
- Status: `approved`
- Related requirements: `features/v2.6.0/071-dashboard-personal-library-stats/requirements.md`
- Created: `2026-08-06`
- Updated: `2026-08-06`

## 设计摘要

- 在共享指标空间级别常量中加入 `personal`，四个指标使用同一允许集合。
- 在文件投影源查询、增量可见性和预览写入三个入口按 `is_favorite` 排除收藏库。
- 空间清理删除该 `space_id` 的全部记录类型，避免历史 `preview_daily` 残留。
- 全量投影结束时主动清理所有收藏空间的既有索引记录。

## 边界承诺 Boundary Commitments

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| 数据集指标 | 加入 personal 与统一预览级别过滤 | 修改聚合公式 | 指标定义变化 |
| 投影同步 | 排除收藏库并清理既有记录 | 修改其他空间可见性 | 空间类型规则变化 |
| 预览事件 | 收藏库短路 | 修改正常空间计数方式 | 预览事件契约变化 |

## 文件结构计划 File Structure Plan

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `bisheng/common/constants/telemetry.py` | modify | 统一允许空间级别 | REQ-001 |
| `bisheng/telemetry_search/domain/init_dataset.py` | modify | 四个指标采用个人库口径 | REQ-001 |
| `bisheng/worker/telemetry/mid_table.py` | modify | 投影排除及清理收藏空间 | REQ-001, REQ-002 |
| `bisheng/telemetry/domain/mid_table/knowledge_space_content.py` | modify | 收藏预览短路与空间记录清理 | REQ-001, REQ-002 |
| `test/test_realtime_dashboard.py`、`test/test_knowledge_space_content_telemetry.py` | modify | 口径回归 | REQ-001, REQ-002 |

## 测试策略 Testing Strategy

| Acceptance IDs | Risk / Level | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|
| AC-REQ-001-01..03 | medium/V2 | unit/service | EG-071-1 | 个人库出现在四指标口径和枚举中 |
| AC-REQ-002-01..03 | high/V3 | unit/service with fakes | EG-071-2 | 收藏库文件、预览和残留记录均被排除 |

## 设计决策 Decisions

### Decision: 使用 `is_favorite` 而不是空间名称

- Decision: 以结构化布尔字段识别“我的收藏”。
- Rationale: 名称可能变化或存在同名正常个人库，不能作为稳定判据。

### Decision: 不新增索引字段

- Decision: 在写入入口排除收藏库，并按空间删除既有索引记录。
- Rationale: 避免 Elasticsearch mapping 和历史预览回填迁移。
