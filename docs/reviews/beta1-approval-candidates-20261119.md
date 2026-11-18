# 应用发布历史审批与合格候选修复（2026-11-19）

用户要求：继续核对实例 436 与 gzx110 的租户归属及快照，确认原因后修复，并让异常指派列表只显示符合资格的人员。继续在 `codex/3.1.0-beta1/bugfixes-20261118` 修复并合回 `feat/3.1.0-beta1`。

## 现场证据与根因

先经现有登录会话读取审批和目录，随后经用户提供的既有 SSH 登录进入 116 的 `bisheng-test-backend`，使用容器实际数据库配置执行 READ ONLY 事务。未导出连接凭据。

| 对象 | 只读核实结果 |
| --- | --- |
| 实例 436 | tenant_id=60，applicant_user_id=868；当前 status=execute_failed |
| gzx110 | user_id=895，delete=0；唯一 user_tenant 为 tenant_id=60、status=active、is_active=1 |
| 主部门 | 314「测试子租户1」，上级 313「测试应用审批」挂载租户 60；314 自身不是另一个租户根 |
| 原发布记录 | `fbef6fc4a67e41f8941584bf1a17c1a5`，tenant_id=60，approval_instance_id=436，owner_user_id=868，submitted_by_user_id=0，authorization_context=NULL |
| 绑定版本 | app=`21cd17033eac4097bf8f0edcc5bc8741`，version=`b25e2f6912284dfb9f907c48fee53c59`，version_no=4；业务绑定由实际仓储读取再次验证 |
| 审批 payload | 有 tenant/app/deployment/version/owner/source=cli，完全没有 submission_actor、self_review_user_id 两个新增字段 |
| 异常 79 | approver_empty，已 resolved；原节点已由管理员跳过 |
| 异常 83 / outbox 194 | execute_failed / failed，错误摘要 Permission denied，仍待处理 |

**本次指定 gzx110 失败的直接原因是历史快照兼容缺口。** 原资格函数在 self_review_user_id 缺失时直接返回空候选；并不是 436 与 gzx110 的租户不同，也不是人员禁用。通用人员搜索并未执行场景资格校验，因此仍能显示该用户，保存却答 18101。

旧版 `6ac7704998^` 的发布接收链先读取凭据 resource_owner，再调用 `_assert_owned(app_id, owner_user_id, tenant_id=tenant)`；发布记录冻结该 owner，审批申请人也为该 owner。F114 引入代发布后才需要区分冻结 owner 与 self_review_user_id。两种提交格式的证据不能混用，也不能把所有缺项统一猜成当前 owner。

## 修复与边界

1. **仅恢复被原发布证据证明的旧排除身份。** `frozen_legacy_review_user` 只接受两个新增字段均不存在的旧 CLI 快照；精确绑定 app/deployment/version/instance/tenant、版本号及冻结 owner/applicant，要求原发布记录 authorization_context=NULL，submitted_by 为 0 或冻结 owner。任一不匹配、现代字段部分缺失或证据不可读都继续拒绝。读取不改写快照，不使用服务账号当前归属，不生成 runtime authorization。
2. **同一资格规则用于候选和保存。** `AppCandidatePolicy` 保留有效自然人、Home、双排除和真实单管理员例外。列表在 SQL 分页与 COUNT 前过滤停用/无效或不唯一 Home、外租户、被排除者；既有真实全局管理员资格保留。保存重新读取候选与管理员当前性，第二位管理员恢复启用后不能沿旧结果自审。
3. **新增只读候选入口。** `GET /api/v1/approval/admin/exceptions/{exception_id}/approver-candidates`，参数 keyword/page/limit（最多 50），返回 data/total 和每行 exclusive。操作者先过管理员检查，再验证异常及实例属于具体管理租户；仅 open 的 approver_empty 且实例为 exception 可指派。保存也拒绝已处理异常，重试/取消入口补齐同一显式租户围栏。没有更改通用 approver_resolver 的来源语义。
4. **前端按异常查询。** 异常指派不再用通用用户搜索，失败不回退到普通目录；保留原节点配置选人入口。单管理员自审例外只能单独选，双向选择都会清理冲突；换异常或管理租户时退休旧请求，切管理租户清空选择。后端仍为最终权限判据。

初次 GateRequest 不携带实例证据；持久请求的普通资格校验、异常重试与后续节点重建携带内部 instance_id。无 schema 迁移、无自动补授权、无数据修复任务。原多步异常写事务边界未改，未承诺并发重复指派的全事务幂等。

## 116 上的只读重放

在独立 `docker exec` Python 进程中以内存加载修复函数，使用实际仓储与实际 OpenFGA tuple 读取。禁止 bootstrap，SQL 白名单只允许 SELECT/SHOW/DESCRIBE，HTTP 白名单只允许 GET 和 tuple read；没有替换容器代码或启动应用服务。

```json
{"instance_id":436,"tenant_id":60,"legacy_review_exclusion_user_id":868,"before_candidates":[],"after_candidates":[895],"roster_user_ids":[895],"roster_total":1,"sql_statement_counts":{"SELECT":9},"business_writes":0,"snapshot_mutated":false}
```

这验证的是实际旧记录的身份恢复、场景资格和候选查询，不是当前已 resolved 异常 79 的 HTTP 再指派。原单据没有重开；83 的发布执行失败不由本次资格修复自动恢复。

## 本地验证

- 新增原生 SQLite 回归覆盖旧服务账号提交、同租户人员成功指派/创建任务、分页/搜索及总数、管理员 HTTP 准入和页参数、现代双排除、停用/外租户/无效主属、名单后资格变化、真实单管理员互斥与第二管理员重新启用、旧请求退休、业务绑定/现代半缺项拒绝。发布和审批快照不被修改。
- 新增前端回归覆盖按异常查询、数字用户 ID、失败不回退、旧响应退休、双向互斥、节点配置原入口及管理视角变化清空选择。
- 定向后端回归（新候选用例、F114 review actor、原异常服务）33 项通过；集成最新发布线后，前端候选/路由/来源 20 项通过。
- 完整 `test/approval` + `test/app_publish` 在独立 `e7960ce71d` 基线上为 740 通过、343 失败。最终以相同依赖再对照最新发布线 `6eb6a8ed09`：基线 738 通过/345 失败，修复并集成后 758 通过/345 失败；失败用例 ID 集合完全一致，20 项新增用例全通过，无新增失败。最新发布线比前一基线多出的两项频道订阅集成失败同样不由本次引入。旧失败涉及历史 fixtures/契约漂移、缺少数据库或运行上下文，不能描述为全量绿。
- 全量前端 lint 通过；全量 typecheck 仍止于原有 sidebarSpaceActions.test.tsx:175、180 两个 TS2349，无新增诊断。Python format/check --fix/F821 已执行，既有 schema UP042 保留；fixture-only 测试密码引起的 guard 警告不是真实凭据，业务源代码无 architecture VIOLATION。
- 较宽前端审批选择（含 approvalPage）在最新发布线独立基线为 23 通过/6 失败，最终修复版为 29 通过/6 失败，失败用例 ID 集合完全相同；六项旧失败在基线同样无法找到已移出页面正文的标题，未修改这些用例来隐藏失败。

## QA 与交付边界

部署后，用同租户管理员打开仍待处理的旧格式 approver_empty 异常，确认 gzx110 可搜索和保存；现代请求确认 owner/提交关联人排除；Root/另一子租户、停用人员、页面打开后资格变化、管理租户切换、无候选和重试失败都应保持拒绝或明确空/失败状态。单管理员例外应双向互斥，其他三类审批的节点配置及流转保持原规则。

**未部署、未改现场记录；未执行真实写入 E2E 或 DM8 验收。** 实例 436 已跳过节点并产生异常 83，继续恢复发布必须另核对执行身份与当前发布资格，不能从本次 reviewer 兼容证明推导出执行授权。

按 `.claude/skills/sdd-code-review/SKILL.md` 审查：边界、认证权限、只读候选与提交重校验、信息泄漏、原生/API/前端回归、分层风格及 F114/approval-module 文档同步均 PASS；既有完整套件与 typecheck/lint 限制如上，不以本次定向验证代替全量验收。

源码修复提交 `72b24217bf`；集成提交 `c394e44ccd` 保留了发布线 `6eb6a8ed09` 中的选人弹窗布局修复。交付仍使用同一 bugfix 分支与 beta1 发布线，无部署步骤或现场写入。
