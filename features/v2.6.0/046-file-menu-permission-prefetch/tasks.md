# Tasks: 知识空间文件菜单权限预取

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0（cofco 分支 feat/cofco-818）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认 2026-08-13 |
| design.md | ✅ 已评审 | 用户确认 2026-08-13（大白话对齐） |
| tasks.md | ✅ 已拆解 | |
| 实现 | 🟡 待 e2e | 5 / 5 代码完成;T004 手动项(Network 零请求走查)待 105 环境 |

---

## Tasks

- [x] **T001**: 后端 — children/search 响应条目附 `permission_ids`
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑**: `_filter_visible_child_items` 加可选收集参数:带 binding 条目→已算出的 per-item 有效权限;普通条目→链路继承结果(chain_perms,已缓存);上传者本人条目→链路 ∪ owner 默认权限(覆盖"自己的文件可改名/删除"的加成权)。`_scan_visible_child_items`/`_scan_visible_search_items` 透传;`list_space_children`/`search_space_children` 把收集结果写进条目 dict 的 `permission_ids`。bypassed(admin)分支不收集→字段为 null。oracle 参考路径不动。
  **覆盖 AC**: AC-01, AC-04 · **design**: 决策 1/2(简化为纯条目级,页级字段取消)

- [x] **T002**: 后端单测
  **文件**: `src/backend/test/knowledge/test_children_permission_prefetch.py`
  **测试**: 普通条目带链路 ids;binding 条目带自身 ids;本人条目含 owner 加成;bypassed 分支字段为 null;搜索路径同样填充。
  **覆盖 AC**: AC-01, AC-04 · **依赖**: T001

- [x] **T003**: 前端 — 列表数据到达即填权限 Set,懒查降级为兜底
  **文件**: `src/frontend/client/src/api/knowledge.ts`(模型+映射)、`src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx`
  **逻辑**: KnowledgeFile 加 `permission_ids`;files 变化时同步推导四个 Set(下载=download_file/folder,改名=rename_file/folder,删除=delete_file/folder,管理=manage_file_relation/folder_relation)并标记已解析;无该字段的条目保留 `ensureFilePermissions` 懒查(老后端/异常兜底,AC-05 语义);admin/owner 本地短路保留(AC-08)。
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-08 · **依赖**: T001

- [x] **T004**: 回归验证
  **逻辑**: 后端跑 test/knowledge 受影响套件与基线对比;前端 typecheck+lint;手动:普通成员开菜单 Network 零请求、滚动零请求、被单独授权文件菜单正确、admin 不回退。
  **覆盖 AC**: 全部 · **依赖**: T002, T003

- [x] **T005**: F040 design 修订历史加指针(懒查策略被本 feature 替换)
  **文件**: `features/v2.6.0/040-rebac-read-path-perf-rollout/design.md`
  **依赖**: T003 · **design**: 坑 4

---

## 实际偏差记录

- design 决策 2 简化 → 页级 `action_permission_ids` 字段取消,统一纯条目级(chain 结果本来就算好,逐条附带零成本);坑 3(搜索页页级不成立)随之消失,搜索路径同样即时
