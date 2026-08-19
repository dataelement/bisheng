# F045 个人用户邀请确认 E2E 人工验证清单

## 1. 环境与证据

- [ ] 使用独立测试租户，确认 `resource_user_invite_confirmation` 场景存在、已启用，且只绑定一个“被邀请用户本人确认”节点。
- [ ] API、default Celery worker、Redis、OpenFGA、MySQL/DM8 均运行；记录 API 与 worker 的构建 SHA。
- [ ] 测试数据统一使用 `f045-e2e-` 前缀；开始前和结束后仅按该前缀清理资源与测试用户。
- [ ] 运行 `uv run pytest test/e2e/test_e2e_personal_user_invite_confirmation.py -q -s`；在独立租户可额外设置 `E2E_F045_ALLOW_SCENE_TOGGLE=1`。

## 2. 四个 F044 路由

### `/workspace/knowledge/create`

- [ ] 同时选择两个新个人用户、一个部门；创建成功后部门立即生效，两个用户分别提示“邀请已发送”，不出现“授权成功”。
- [ ] 权限列表中两个用户均为“待生效”，角色正确且不可修改、不可删除；资源只创建一次。
- [ ] 关闭邀请确认场景后重试：页面显示“个人用户邀请确认场景未启用，无法新增个人用户权限”，资源、部门授权、用户邀请均未创建。

### `/workspace/knowledge/space/:spaceId/settings`

- [ ] 新增个人用户产生 pending；已有 active 个人用户的改角色/移除仍直接生效，部门/用户组仍直接授权。
- [ ] 两位管理者对同一用户选择不同角色并发提交：只保留首次 instance/task/角色；第二次响应为 `invite_existing`。
- [ ] 用户确认前无法访问空间；本人同意且 default worker 执行成功后，pending 变 active，并按首次角色访问。

### `/workspace/channel/create`

- [ ] 同一批 mixed grants 的 direct/invite 计数与逐项结果正确；邀请结果只表示已发送。
- [ ] 模拟某一条邀请失败：频道只创建一次，恢复入口只重试 failed grant，不重放 direct 项、已创建邀请、订阅或知识同步。
- [ ] 场景关闭时返回 18106，频道及任何初始权限均不存在。

### `/workspace/channel/:channelId/settings`

- [ ] pending 行可见但不可编辑/删除；active 与 pending 用户都不能被再次选择。
- [ ] 本人拒绝后 pending 消失且无 OpenFGA tuple；再次邀请产生新 instance。
- [ ] 邀请人撤回后任务不可处理且无权限；同意/撤回并发只接受一个终态，重复终态返回 18102。

## 3. 权限、失败与幂等

- [ ] 管理员或其他用户代替被邀请用户 approve/reject 返回 18101；只有任务绑定用户本人可处理。
- [ ] 同意前分别验证邀请人失权、目标用户停用/跨租户、F033 部门范围变化、角色模型变化：均不得产生 active 权限，最终可追踪为执行失败。
- [ ] 模拟 OpenFGA 部分失败、binding 恢复失败：补偿未确认收敛时保持可重试，不写本邀请的 `failed_tuple`，不得发送“已生效”通知。
- [ ] 重复投递相同 outbox：只保留一个 relation binding 和一组有效 tuple；`outbox=success`、`instance=executed` 同时成立。
- [ ] worker 在 claim 后崩溃：TTL 前不并行重领，TTL 后可恢复；成功后重复投递不把终态降级为 failed/executing。

## 4. 通知与三语

- [ ] 建单后仅被邀请人收到 `resource_user_invite_pending`；已读、未读或删除消息不改变审批状态。
- [ ] outbox 成功后邀请人收到 `resource_user_invite_effective`；reject/withdraw/确定失败收到 `resource_user_invite_failed`，原因语义可区分。
- [ ] 站内信发送失败不影响 reject/withdraw API 或已成功 outbox 的终态。
- [ ] 切换中文、英文、日文：四路由 toast、待生效标签和三类通知均无 key 泄漏，pending/active 语义明确。

## 5. 最终数据核验

- [ ] 成功生效必须同时看到：`approval_instance.status=executed`、`approval_outbox.status=success`、目标 OpenFGA tuple、relation binding；HTTP 200 或 Celery task id 不能单独作为成功证据。
- [ ] reject/withdraw/execute_failed 均无目标有效 tuple，也不再投影 pending；结束后允许重新邀请。
- [ ] 不同租户无法邀请、查看或处理对方邀请；同一用户在不同资源上的邀请互不影响。
- [ ] 清理 `f045-e2e-` 资源和测试用户后，保留审批历史审计记录，不做宽范围删除。
