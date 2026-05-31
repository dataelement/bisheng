# E2E Verification Report — F026-knowledge-qa-permission-filter

> **状态**：模板（待人工执行 + 填写结果）
> **执行人**：_TBD_
> **执行日期**：_TBD_
> **目标分支**：`feat/2.6.0-beta3` @ commit `_TBD_`
> **运行环境**：_TBD（dev / staging / prod-mirror）_

本报告对应 [tasks.md](./tasks.md) **T012**。所有场景的成功与否需写入「结果」一栏；如某 AC 因环境限制未能验证，请在结果栏标注 `未验证：<原因>` 并在 [tasks.md](./tasks.md) §实际偏差记录 中登记。

---

## 0. 静态检查（已通过）

| 检查 | 命令 | 结果 |
|------|------|------|
| arch-guard 全量 | `bash scripts/arch-guard.sh <file>` 跨 6 个 F026 修改文件 | ✅ RULE-1 / RULE-2 / RULE-4 / RULE-5 / RULE-8 均无 VIOLATION；RULE-7 在 `settings.py` 的 `jwt_secret` 行为 WARNING（既有遗留，与 F026 无关）|
| Python 语法 | `python3 -m py_compile <files>` | ✅ 所有新增 / 修改文件语法干净 |
| JSON 语法 | `python3 -c "import json; json.load(...)"` 跨 6 个 i18n 文件 | ✅ 全部解析通过 |

---

## 1. 测试套件（CI 运行）

| 测试文件 | 测试数 | 覆盖 AC |
|---------|--------|---------|
| `test/knowledge/test_knowledge_file_visibility_service.py` | 12 | AC-11, AC-02, AC-06, AC-16, AC-17, AC-23, AC-24, AC-25 |
| `test/knowledge/test_knowledge_space_chat_service_visibility.py` | 7 | AC-02, AC-03, AC-06, AC-09, AC-26, AC-27 |
| `test/workstation/test_query_chunks_visibility.py` | 8 | AC-11, AC-12, AC-13, AC-14 |
| `test/citation/test_citation_resolve_visibility.py` | 9 | AC-15, AC-16, AC-17, AC-18, AC-19, AC-20 |

**运行命令**（在 CI 或本地环境配齐 `uv sync --frozen` 后）：

```bash
cd src/backend
uv run pytest test/knowledge/test_knowledge_file_visibility_service.py \
              test/knowledge/test_knowledge_space_chat_service_visibility.py \
              test/workstation/test_query_chunks_visibility.py \
              test/citation/test_citation_resolve_visibility.py -v
```

**CI 结果**：_TBD_

---

## 2. KB 下拉框回归（AC-10）

**前置**：
- 准备测试账号 `user_a`，对租户 `t1` 下空间 `S1` / `S2` 有 `view_space`，对 `S3` 无 `view_space`。

**执行步骤**：
1. 以 `user_a` 登录 Platform（http://<host>:3001）。
2. 调用 `GET /api/v1/knowledge/space/{mine,managed,joined,department}`，对比响应中是否仅含 `S1` / `S2`。
3. 进入工作台 / 客户端首页（`/workspace`），打开 KB 选择器；确认 `S3` 不出现。

**预期结果**：4 个端点均不返回 `S3`；KB 选择器仅显示 `S1` / `S2`。

**实际结果**：_TBD_ ✅/❌

---

## 3. 整空间问答 + 双层过滤（AC-02 / AC-06）

**前置**：
- 空间 `S1` 下有文件 `F1` / `F2` / `F3`，账号 `user_a` 对 `F1` / `F3` 有 `view_file`，对 `F2` 无。

**执行步骤**：
1. 以 `user_a` 触发整空间问答 `POST /api/v1/knowledge/space/S1/chat/folder` `folder_id=0`。
2. 截图响应中 `source_documents` 列表，提取 `file_id`。
3. 验证 `file_id` 均属于 `{F1, F3}`，无 `F2`。

**预期结果**：`source_documents[*].file_id ⊆ {F1, F3}`；不含 `F2`。

**实际结果**：_TBD_ ✅/❌

---

## 4. 工作台多 KB 检索（AC-11 / AC-12 / AC-13）

**前置**：
- 账号 `user_a`：
  - `KB_A`：无 `view_space`
  - `KB_B`：有 `view_space`，但 0 个 `view_file` 文件
  - `KB_C`：有 `view_space`，且有 ≥1 个 `view_file` 文件

**执行步骤**：
1. 以 `user_a` 通过 share-kb 工具触发问答，`knowledge_space_ids=[KB_A, KB_B, KB_C]`。
2. 抓取后端日志，确认：
   - `skipped_kb_id=KB_A reason=no_view_space` (AC-11)
   - `kb=KB_B post-filter-empty pre_filter_candidate_size=N post_filter_dropped_count=N`（AC-12 自然跳过）
   - `kb=KB_C ok docs=M pre_filter_candidate_size=N post_filter_dropped_count=(N-M)`（AC-13）

**预期结果**：响应 `finally_docs` 仅含 `KB_C` 的可见 chunks；`kb_succeed` = `[KB_C]`。

**实际结果**：_TBD_ ✅/❌

---

## 5. 角标溯源面板（AC-15 / AC-16 / AC-17）

**前置**：
- 已有会话 `chat_X`，其中引用了文件 `F1` / `F2` / `F3`（用户曾对全部有权）。
- 管理员调 `PermissionService.revoke` 撤回 `user_a` 对 `F2` 的 `view_file`。

**执行步骤**：
1. `user_a` 重新打开 `chat_X` 的历史 citation 面板，触发 `POST /api/v1/citations/resolve { citationIds: [F1_cit, F2_cit, F3_cit] }`。
2. 校验响应 `items` 数组：
   - 含 `F1_cit` 与 `F3_cit`（`previewUrl` / `downloadUrl` 已填充）；
   - 不含 `F2_cit` 任何字段（整条剔除）。
3. 再撤回 `F1` 与 `F3` 的 `view_file`，重新请求 → `items` 应为 `[]`（AC-17）。

**预期结果**：步骤 2 返回 2 条，步骤 3 返回空数组；HTTP 始终 200。

**实际结果**：_TBD_ ✅/❌

---

## 6. 单条 citation 无权（AC-18）

**执行步骤**：
1. `GET /api/v1/citations/{F2_cit_id}`（`user_a` 已无 `F2` view_file）。
2. 校验响应为 `NotFoundError`（HTTP 200 body 含业务错误码），不含任何 `documentName` / URL。

**预期结果**：等价于"该 citation 不存在"。

**实际结果**：_TBD_ ✅/❌

---

## 7. 匿名调用保持现状（AC-20）

**前置**：
- 创建 share link 公开访问某含 citation 的会话。

**执行步骤**：
1. 在未登录浏览器打开 share link 页面。
2. 触发 citation 解析（前端自动调用 `/api/v1/citations/resolve`，无 JWT）。
3. 校验返回 items 与 `view_file` 改造前等价（不引入新鉴权要求）。

**预期结果**：share link 公开访问行为不变。

**实际结果**：_TBD_ ✅/❌

---

## 8. 实时权限失效（AC-21 / AC-22）

**前置**：
- 账号 `user_a` 对空间 `S1` 下 `F1` 有 `view_file`。

**执行步骤**：
1. `user_a` 触发整空间问答 → 抓 source_documents 含 `F1` ✅。
2. 立即（< 10 s 内）以管理员身份调用 `PermissionService.revoke` 撤回 `F1`。
3. `user_a` 在 10 s 内追问同样的问题（同一 session）。
4. 校验 source_documents 不再含 `F1`（理想：`invalidate_user` 即时生效；最迟：10 s 内自动失效 = AC-22）。
5. 抓 log 行 `permission_filter | ... accessible_ids_size=A → A'`，确认 `A' = A - 1`。

**预期结果**：第二轮检索使用最新权限（缓存 invalidate 或 TTL 收敛）。

**实际结果**：_TBD_ ✅/❌

---

## 9. 性能 sanity（AC-23 / AC-24 / AC-25）

**前置**：
- 准备账号 `perf_user`：可见 ~5000 个文件 + 可见 ~10 万个文件 两种规模空间。

**执行步骤（每种规模）**：
1. 冷启动（清 Redis 缓存）触发整空间问答，记录权限过滤新增耗时 `t_cold`。
2. 立即再问一次（命中缓存），记录 `t_warm`。
3. 校验：
   - `t_warm ≤ 80 ms`（5000 规模）/ `≤ 200 ms`（10 万规模 NOT-IN）
   - `t_cold ≤ 500 ms`（5000 规模）
4. grep 后端日志，确认 `retrieval_attempts ≤ 2`（AC-24）。

**预期结果**：所有指标符合 AC-23/24/25 阈值；超出阈值需在 tasks.md §实际偏差记录登记。

**实际结果**：_TBD_

---

## 10. 结构化日志字段（AC-27）

**执行步骤**：
1. 触发任意一次整空间问答 / 工作台问答。
2. `grep -E 'permission_filter \\|' /path/to/backend.log | tail -1`。
3. 校验单行内含以下字段：`strategy=` / `accessible_ids_size=` / `prefilter_candidate_size=` / `retrieval_attempts=` / `post_filter_dropped_count=`。

**实际结果**：_TBD_ ✅/❌

---

## 11. 失败 & 偏差登记

如有 AC 验证失败 / 未达预期，分别处理：

1. **可修复**：在 tasks.md 表中将对应任务重新打开（`[x] → [ ]`）并立即修复，再次跑本报告该节。
2. **不可修复（架构 / 环境限制）**：在 tasks.md §实际偏差记录写明：
   - 偏差点
   - 已采取的补救
   - 后续 spec 是否需要回写

---

## 12. 总结

| 维度 | 结果 |
|------|------|
| AC 全量通过率 | _TBD_ |
| arch-guard 状态 | ✅ 静态通过 |
| 单元 / 集成测试 | _TBD（CI 跑完后回填）_ |
| 性能 SLO | _TBD_ |
| 是否可合并到主版本 | _TBD_ |
