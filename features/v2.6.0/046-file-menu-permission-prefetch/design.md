# Design: 知识空间文件菜单权限预取

> **本文档定位 — 现状快照（Why this How）**
> spec.md 回答做什么；本文回答为什么这么实现；tasks.md 是执行流水。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0（cofco 分支）
**最后更新**: 2026-08-13

---

## 1. 目标与非目标

- **目标**：文件「⋯」菜单的动作项(下载/改名/删除/管理)在菜单打开瞬间完整可用,且流式滚动零额外权限请求;替换 F040 定下的「菜单打开时逐文件 3-4 个 checkPermission」策略。
- **非目标**：不改权限模型/写路径;不动操作接口的服务端强制鉴权;platform 文件列表不动。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7。
- 列表首屏性能不得回退——F040 拆懒加载的初衷;任何新增计算必须搭现有请求的便车或证明可忽略。
- client 端 Recoil 冻结:新状态用 react-query v4 / useState,不加 atom。

---

## 3. 方案对比与选定

### 决策 1：权限数据怎么到前端

- **备选**：
  - A. **骑在 children 分页响应上**：每页响应附「文件夹链路级动作权限 ids」(整页一份)+ 例外条目各附自己的 `permission_ids`。
  - B. 独立聚合端点,进空间时单独预取一次。
  - C. 每页一个批量 check 请求。
- **选定**：A
- **原因**：F036 的可见性快路径(`_filter_visible_child_items`)在**同一个列表请求里已经算出了全部所需数据**——`binding_index` 标出哪些条目带细粒度授权(= 例外清单),带授权的条目为了可见性判定已做了整套 per-item 权限求值(`effective_permissions`,含 download_file/rename_file 等动作 ids),普通条目走链路继承(`_chain_effective_permission_ids`,按祖先链缓存、整页一次)。方案 A 只是把算完就扔的结果**暴露出来**,新增计算≈0、新增请求=0;B 要重建同一套 context(多一次全量求值),C 在无限滚动下每页多一个请求。spec AC-01 的「一次聚合请求」由列表请求本身承担,AC-03 自动成立。
- **何时该重新考虑**：若列表接口走了不做权限求值的旁路(如 admin bypass 分支)——该分支本来就短路,前端 admin 短路同样覆盖。

### 决策 2：响应契约形态（实现时简化:纯条目级,页级字段取消）

- **选定**：children/search 响应的**每个条目** dict 附 `permission_ids: list[str] | null`——带 binding 条目=自身逐条求值结果;普通条目=祖先链继承结果(chain_cache 已缓存,逐条附带零成本);上传者本人条目=链路 ∪ owner 默认(覆盖"自己的文件可改名/删除"加成权);admin/bypassed 分支=null。
- **原因**：调研时设想"页级一份+例外条目级"以省体积,落地发现普通条目的链路结果本来就在手上,直接逐条带上后:页级字段、页级/条目级语义区分、搜索页跨文件夹页级失效(原坑 3)全部消失,前后端都只剩一条规则「条目有 ids 用 ids,null 回退懒查」。响应体积增量 ~20 id×每页,可忽略。
- **null 语义**：null=未预取(回退懒查);`[]`/缺某 id=无该权限。老后端配新前端字段缺失→同一条回退路径(灰度即兜底)。

### 决策 3：前端改造方式

- **选定**：`SpaceDetail/index.tsx` 保留 `permissionEntryIds/renameEntryIds/downloadEntryIds/deleteEntryIds` 四个 Set 的对外形状(FileTable 无感知),但填充源改为:列表数据到达时同步从 `action_permission_ids`/条目 `permission_ids` 推导;admin/owner 本地短路保留(AC-08);当页级字段缺失(老后端/预取失败)时整体回退现行 `ensureFilePermissions` 懒查(AC-05/边界-2 的统一兜底)。
- **原因**：改动收敛在数据源一层,菜单/表格组件零改动。

### 决策 4：例外清单上限

- **选定**：不需要独立上限。例外识别按页进行(页大小 20-50),每页带授权条目的 per-item 求值本来就是可见性判定的既有成本;spec AC-05 的「退化」即决策 3 的字段缺失回退,不另设开关。
- **原因**：spec 写 AC-05 时假设独立预取端点要一次拉全空间例外;骑分页后该风险不存在。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**现状**：`GET /knowledge/space/{id}/children`(`knowledge_space.py:289`,F027 cursor 分页)→ `list_space_children`(service:2784)→ `_filter_visible_child_items`(:2589,F036 快路径)用 `binding_index` 区分「带 binding 条目→全量 per-item 求值」/「普通条目→祖先链继承求值(chain_cache)」→ **求值结果只用于可见性,即弃**。client 菜单打开时 `ensureFilePermissions`(`SpaceDetail/index.tsx:492`)逐文件发 3-4 个 `checkPermission`。

**目标态（已落地）**：同一请求内,每个可见条目的求值结果(普通=链路继承 / binding=per-item / 本人=链路∪owner 默认)写入该条目 dict 的 `permission_ids`;client 列表数据到达即填四个 Set(`SpaceDetail/index.tsx` 预取 effect),`ensureFilePermissions` 降级为兜底路径。

### 4.2 关键字段 / 契约

| 字段 | 含义 | 消费方 |
|---|---|---|
| children/search 条目 `permission_ids: list[str] \| null` | 该条目对当前用户的有效动作权限 ids;null=未预取(admin bypass/老后端)→前端回退懒查 | client SpaceDetail(映射为 `KnowledgeFile.permissionIds`) |
| 菜单项 ↔ 权限 id 映射 | 下载=download_file/download_folder;改名=rename_file/rename_folder;删除=delete_file/delete_folder;管理=manage_file_relation/manage_folder_relation | 前端判定,与服务端模板一致(`knowledge_space_permission_template.py`) |

### 4.3 关键模块职责

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `list_space_children` + `_filter_visible_child_items` | 顺带暴露已算出的权限 ids | 不为暴露而新增求值 |
| client `SpaceDetail/index.tsx` | 四个 Set 的推导与回退编排 | FileTable/菜单组件不动 |
| 操作接口(下载/改名/删除) | 强制鉴权,唯一真相 | 不依赖前端判定 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 可见性求值有 admin/owner/`read_permission_bypassed` 短路分支,短路时**没有**求值结果可暴露 | null 被误当"无权限",admin 菜单全灰 | null≠[]:null 走懒查回退,前端 admin/owner 短路保留(AC-08) |
| 2 | `permission_ids` 字段在部分列表响应里已被 F030 用于空间级(2052 行),语义是"空间的",别和条目级混淆 | 复用时页级/条目级语义打架 | 决策 2:页级用新字段名,条目级才用 permission_ids |
| 3 | ~~页级 ids 在搜索页不唯一~~（随决策 2 简化消失:纯条目级后搜索页与常规浏览同一条路径） | — | — |
| 4 | F040 设计文档记录了"懒查是刻意决策";本 feature 推翻它 | 后人以为懒查被误删又加回去 | F040 design 修订历史加一行指向本 feature |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的

| 契约 | 形式 | 谁在用 |
|---|---|---|
| children 响应新增页级/条目级权限 ids(向后兼容:老前端忽略,新前端对老后端回退) | HTTP API 扩展 | client |

### 6.2 我依赖别人的

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F036 不变量「非 owner 文件/文件夹授权必有 binding」 | 隐式数据契约 | 不变量破坏→例外识别漏,菜单显示与实际鉴权不一致(服务端兜底,不越权) |
| 权限模板动作 ids 命名 | 隐式契约 | 模板改 id 前端映射要联动 |

---

## 7. 测试与可观测

- 单测:children 响应字段填充(普通/例外/admin 短路/bypassed 四分支);前端 Set 推导 + 回退路径。
- e2e:普通成员开菜单零请求(Network 面板验证)、滚动零请求、被单独授权文件菜单正确、老后端字段缺失时回退。

## 8. 后续改进 / 不打算做的事

- platform 文件列表如有同样反馈,同一契约直接复用。
- 权限变更实时推送不做(AC-07 口径:重进/刷新生效)。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-13 | 初版(方案从独立预取端点改为骑 children 响应,spec 例外清单上限随之失效→AC-05 语义映射到字段缺失回退) | spec 确认后调研发现 F036 已算出全部所需数据 |
| 2026-08-13 | 实现落地:决策 2 简化为纯条目级(页级字段取消,原坑 3 消失);§4 更新为落地契约 | chain 结果逐条附带零成本,实现比设计稿更简 |
