# F106 验收测试用例（实现前矩阵）

输入：已确认 [`prd.md`](./prd.md)、[`spec.md`](./spec.md)、[`design.md`](./design.md)。  
**尚未写业务代码，本文件不是执行报告，不得把任何用例标成已通过。**

契约：`POST /api/v1/knowledge/space/{id}/sort`、`POST .../folders/{id}/sort`；列表 `can_reorder`、`can_reorder_folders`。  
落库：`knowledge.sort_weight`、`knowledgefile.sort_weight`。环境：171 MySQL；文件夹 `can_manage` 依赖 OpenFGA。SQLite 内存库不算写路径门。

---

## 需求追踪

| 方向 | 内容 |
|------|------|
| 新增 | 运营岗排公共/部门库；部门管理员按绑定表排团队/科室库；库/文件夹管理员排当前目录文件夹；列表下发可拖标志；TEAM+TEAM_KS 同一工作集 |
| 必须兼容 | 系统管理员现网能拖的全部；个人库 18041；midpoint 算法；置顶不改 |
| 删除 | 仅 `is_admin()` 才能调两个 sort 写接口 |
| 现有测试 | **无** `reorder_space` / `reorder_folder` 流转用例，全部新建 |

---

## 跨模块影响

| 改动点 | 模块 | 依赖 | 风险 | 优先级 | 覆盖 |
|--------|------|------|------|--------|------|
| sort 写鉴权 | knowledge | 本域 | 越权改全租户库序 | P0 | AT-01～AT-24 写路径 |
| `can_manage` | permission OpenFGA | 只 check | 文件夹误开放 | P0 | AT-14～AT-17, AT-25 |
| 运营岗 | `has_platform_operator_role` | 只读 | 写成 `is_admin()` 会升格超管 | P0 | AT-05～AT-08 |
| 绑定表 | `department_knowledge_space` | 只读 | 看见就能拖 | P0 | AT-09～AT-12, AT-23 |
| Client 拖拽 | 知识门户 iframe | 读新字段 | 有权无按钮 / 无权仍拖 | P0 | AT-20, AT-30～AT-32 |
| 门户 BFF | — | 无 | 无（iframe） | — | 不做 |
| 置顶/检索/积分/Celery | — | 不写 | 回归低 | P2 | 抽测不改语义即可 |

---

## 检查清单（适用性）

| 项 | 结论 |
|----|------|
| 业务主路径 | 适用：成功 midpoint |
| 状态机 | 不适用：无新状态 |
| 权限/越权 | 适用：矩阵核心 |
| 租户 | 适用：夹具固定 tenant=1，不测跨租户扩权 |
| 数据一致性 | 适用：拒绝无脏写；重铺不写出工作集 |
| 并发 | 适用：串行两次写（AT-24）；不升级行锁 |
| 异步/通知 | 不适用 |
| DDL/DM8 | 无 DDL；`sort_weight` 已有 CASE 排序 |
| 性能 | P2：列表禁止 N+1 OpenFGA，实现时用绑定 ID 集合，不做压测门槛 |

---

## 用例矩阵

写路径一步都不能少：调接口（身份明确）→ 断言 HTTP/180xx → SELECT 目标表 → 再打一枪（再读或再写/再拒绝）。

| ID | 追溯 | P | 层级 | 身份 | 初始 / 步骤 | 期望 HTTP | 落库 | 现状 |
|----|------|---|------|------|-------------|-----------|------|------|
| AT-01 | AC-01；`knowledge.sort_weight`；sort POST | P0 | 接口+落库 | 系统管理员 | 两条公共库，拖 A 到 B 前 | 200 `data=true` | A 的 weight 为中点；B 不变 | 缺口 |
| AT-02 | AC-02 | P0 | 接口+落库 | 系统管理员 | 两条部门库同样拖 | 200 | 同 AT-01 | 缺口 |
| AT-03 | AC-03, AC-22 | P0 | 接口+落库 | 系统管理员 | 团队库 prev/next 为科室库 | 200 | 只改被拖团队库 | 缺口 |
| AT-04 | AC-04 | P0 | 接口+落库 | 系统管理员 | 库根两个文件夹互拖 | 200 | `knowledgefile.sort_weight` 更新 | 缺口 |
| AT-05 | AC-05 | P0 | 接口+落库 | 运营岗 `role_names=平台管理员`，`is_admin=false` | 拖公共库 | 200 | 该库 weight 变 | 缺口 |
| AT-06 | AC-06 | P0 | 接口+落库 | 运营岗 | 拖部门库 | 200 | 该库 weight 变 | 缺口 |
| AT-07 | AC-07 | P0 | 接口+落库 | 运营岗 | 拖团队库或科室库 | **18040** | 该库及邻居 weight **不变**；再 GET 列表序不变 | 缺口 |
| AT-08 | AC-08 | P0 | 接口+落库 | 运营岗且非库/文件夹管理员 | 拖文件夹 | 18040 | 文件夹 weight 不变 | 缺口 |
| AT-09 | AC-09 | P0 | 接口+落库 | 部门管理员 | 拖「本部门+下级」已绑定且可见的团队/科室库 | 200 | 只改该行 | 缺口 |
| AT-10 | AC-10 | P0 | 接口+落库 | 部门管理员 | 拖未绑定团队库 | 18040 | 无脏写 | 缺口 |
| AT-11 | AC-11 | P0 | 接口+落库 | 部门管理员 | 拖其他部门已绑定团队/科室库 | 18040 | 无脏写 | 缺口 |
| AT-12 | AC-12 | P0 | 接口+落库 | 部门管理员 | 拖公共库、再拖部门库 | 皆 18040 | 无脏写 | 缺口 |
| AT-13 | AC-13 | P0 | 接口+落库 | 部门管理员且非该库管理员 | 拖文件夹 | 18040 | 无脏写 | 缺口 |
| AT-14 | AC-14 | P0 | 接口+落库 | 库 CREATOR/管理员，非系统管理员 | 库根拖文件夹 | 200 | 文件夹 weight 变 | 缺口 |
| AT-15 | AC-15 | P0 | 接口+落库 | 同上 | `POST .../sort` 拖该库 | 18040 | 库 weight 不变 | 缺口 |
| AT-16 | AC-16 | P0 | 接口+落库 | 仅父文件夹 `can_manage` | 在该文件夹内拖子文件夹 | 200 | 子文件夹 weight 变 | 缺口 |
| AT-17 | AC-17 | P0 | 接口+落库 | 仅子文件夹管理员 | 在库根拖文件夹 | 18040 | 无脏写 | 缺口 |
| AT-18 | AC-18 | P0 | 接口+落库 | 普通成员 | 调库 sort 与文件夹 sort | 皆 18040 | 两表目标行不变 | 缺口 |
| AT-19 | AC-19 | P0 | 接口+落库 | 系统管理员或普通用户 | 拖个人库 | **18041** | 不写 | 缺口 |
| AT-20 | AC-20 | P0 | 接口 | 运营岗 / 部门管理员 / 库管 / 成员 | GET `/level/{level}` 与详情 | `can_reorder` 与能否 200 写接口一致；无权 false | 不写 | 缺口 |
| AT-21 | AC-21 | P0 | 接口+落库 | 系统管理员 | 公共库的 next 设为部门库 ID | 18041 | 不写 | 缺口 |
| AT-22 | AC-22 | P0 | 接口+落库 | 合格部门管理员 | 工作集内团队↔科室互为邻居 | 200 | 只改被拖行 | 缺口 |
| AT-23 | AC-23 | P0 | 接口+落库 | 部门管理员，工作集外另有 NULL/已有 weight 的团队库 | 首次拖触发 respread | 200 | **工作集外**行 weight 与调用前逐列相同 | 缺口 |
| AT-24 | AC-24 | P0 | 接口+落库 | 系统管理员 | 同一库连续两次 sort | 两次 200 | 最终 weight=第二次中点；无半行 | 缺口 |
| AT-25 | AC-25 | P0 | 接口 | 库管 | GET `/children` 根目录 vs 无权子目录 | 根 `can_reorder_folders=true`，无权目录 false | 不写 | 缺口 |
| AT-30 | AC-20 | P0 | UI | Client | 侧栏 `canReorder=true` 才 draggable；投放仅同样 true 且同置顶组 | 不调错邻居 | — | 扩现有 `resolveReorderNeighbours` 测 | 缺口 |
| AT-31 | AC-20 | P1 | UI | Client | 工作台不再用单一 `isSystemAdmin` 作为 `canReorderSpaces` | 有标志的组可拖 | — | 缺口 |
| AT-32 | AC-20, AC-25 | P0 | UI | Client | 文件夹表：`can_reorder_folders` 且无列头排序才可拖 | — | — | 缺口 |
| AT-40 | 非目标 | P1 | 接口 | 运营岗 | 确认 `is_admin()` 仍为 false 时公共库可拖 | 200 | 防升格回归 | 可与 AT-05 同测 |

未登录沿用现网登录墙，不单列。跨租户本版不扩权，不单列 P0。

---

## 建议测试文件

| 文件 | 覆盖 AT |
|------|---------|
| `src/backend/test/knowledge/test_space_reorder_auth_flow.py` | AT-01～AT-03, AT-05～AT-07, AT-09～AT-12, AT-15, AT-18 库侧, AT-19, AT-21～AT-24, AT-40 |
| `src/backend/test/knowledge/test_folder_reorder_auth_flow.py` | AT-04, AT-08, AT-13, AT-14, AT-16～AT-18 文件夹侧 |
| `src/backend/test/knowledge/test_space_reorder_flags_api.py` | AT-20, AT-25 |
| Client `resolveReorderNeighbours.test.ts` 及工作台/FileTable 测 | AT-30～AT-32 |

命令（实现后才跑，现在禁止标绿）：

```bash
cd src/backend && uv run pytest test/knowledge/test_space_reorder_auth_flow.py test/knowledge/test_folder_reorder_auth_flow.py test/knowledge/test_space_reorder_flags_api.py -v
cd src/frontend/client && npx jest src/pages/knowledge/portal/components/resolveReorderNeighbours.test.ts --coverage=false --watchAll=false
```
