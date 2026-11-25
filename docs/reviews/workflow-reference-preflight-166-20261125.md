# 工作流引用运行前预检修复及 166 验证

日期：2026-11-25（UTC+8）。实施方案经用户确认。需求与设计：features/v3.1.0-beta2/006-reference-hints/spec.md AC-15～18、design.md §4.12。

## 问题与修改

历史 dcf8f6122e2 移除了知识选择器的异步存在性校验，运行按钮虽仍等待 validateNodes，但该选择器返回空错误，导致先连接再报通用 18000。恢复为本地校验 → 只读 HTTP 预检当前未保存图 → 标红并拦截或传递已校验快照。完整工作流与单节点共用 gate；重复点击、请求失败、校验中修改图均不启动。

新增 POST /api/v1/workflow/references/validate。依赖原登录身份、来源编辑权限、租户、实际类型绑定权限和原资源事实读取，去重批量检查知识目标。错误明细包含节点、参数、目标 ID 和状态，返回所有位置；旧错误摘要默认五项保持。候选列表不判断删除。租户过滤的缺项统一 unavailable，避免把不可见判成删除。实际执行继续重校验，不信任预检结果。

## 本地验证

- 后端合并选择：279 passed、2 failed。两项失败在修复前 c5eff52b65 的相同扩展选择中也失败（236 passed、2 failed），失败名和栈一致，未新增失败：
  - test_wf_published_admission.py::test_only_admitted_graph_is_queued_and_override_is_not_applied_twice
  - test_wf_ws_admission.py::test_ordinary_real_adapter_injects_bound_identity_root_and_keeps_lease
  - 两者缺少真实数据库/进程运行时依赖，进入 SQLite 异步引擎初始化失败；未修改无关测试以隐去基线失败。
- 新增预检真实 SQLite/source/target 用例 9 项通过；包括八个节点重复引用、原身份、编辑拒绝、跨租户、目标权限失败、权限服务故障、QA 绑定以及预检后删除。
- 前端相关 36 项通过：useWorkflowPreflight、useNodeEvent、referenceCandidates、savedReferences、memorySwitchValidate。
- 前端全量 pnpm lint、pnpm typecheck、平台生产构建通过；i18n 检查无新增漂移；Python Ruff 与 git diff --check 通过。
- 架构守卫无新增 VIOLATION。legacy api/v1/workflow.py 直接导入数据库模型的 RULE-3 WARNING 为基线已有；新增 endpoint 只调用应用服务。
- SQLite 验证不等同于实际 MySQL/DM8 并发锁验收；新查询使用 ORM select/in_/with_for_update，无 DDL 或专用 SQL。

## 166 现场验证

- 用户提供工作流 b3844644404442bfa993fbf389f3153c 在实施期间已于 17:40:45 更新，原 ID 4 被替换为 ID 7，当前保存版本 v1 的知识引用均有效。实测点击运行先发预检，返回 valid=true 后才建立 WS。
- 使用现有“导入工作流”入口，仅在浏览器未保存图里把三个节点的 ID 7 替换为原 ID 4，名称“测试空间建立索引”。未点击保存、发布、下线或切版本。
- 实测点击运行后 agent_2b20c、rag_b5230、knowledge_retriever_fd212 三个节点均有 border-red-500，三个对应标签为 bg-danger-tint/text-danger，实际颜色 rgb(245,63,63)。通知包含节点名、空间名与 ID 4。
- 给 WebSocket 构造器增加只记录调用的观察探针，失败运行时新连接数为 0，预览面板没有打开。有效配置路径能建立连接，证明不是统一禁用运行。
- GET 回查确认 data 与 update_time 均未改变；已刷新丢弃临时图，页面回到用户最新保存版本。
- opt-in live E2E 三项通过：八个重复失效引用全部定位、未保存空图通过、匿名 HTTP 401。每项 teardown 回查保存图和更新时间保持不变。
- 额外以真实普通用户 gzx001 的 UserPayload、租户 1，初始化正常进程引用及 F048 权限上下文后调用预检应用服务，返回 403。此项为真实权限服务检查，不是普通用户 HTTP 登录 E2E。

## 部署及回退

备份目录：166 /opt/bisheng/ops-backups/workflow-reference-preflight-20261125，权限 700；含原 env、Compose、替换前源文件、构建日志与回退脚本。只修改两项镜像变量，不改模型、知识空间或业务数据。

- backend / backend_worker：bisheng-backend:3.1.0-beta2-reference-preflight-20261125
  - sha256:5bd65eaaa1ab27f5dbe3d4344b83c602812bba1cb9ddb5e41fa1a1045baff326
  - 派生自已含头像及引用提示修复的本地镜像，仅覆盖本次后端文件。覆盖前六个既有文件的 SHA256 与 c5eff52b65 一致。
- frontend：bisheng-frontend:3.1.0-beta2-reference-preflight-20261125
  - sha256:56875c1e04849fa453c5baf97f2db7f2023d396ed0e2307b368512a12cb4e7a1
  - 保留现有 Nginx 与客户端，仅替换 /usr/share/nginx/html/platform 的平台构建。
- API healthy 后 worker 启动；Nginx -t 成功并 reload。此为本次定向部署，不宣称整条分支所有新提交已部署。
- rollback.sh 只恢复两项原镜像变量及本次源文件，不覆盖整个 env，保留后续无关配置变更。原镜像不删除。
- v3.1.0-beta2 标签本次不移动。

## 七维度自审

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

Overall: PASS_WITH_WARNINGS。唯一验证限制为上述两项已复现的基线失败，以及未执行 DM8 的现场锁竞争测试。无新增阻断项。
