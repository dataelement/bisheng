# 分享撤回、再次分享与审批历史闭环

- Feature ID: `075-share-revoke-closure`
- Mode: `Bug Fix`
- Status: `implemented-local-verified`
- Created: `2026-10-14`
- 用户已明确：保留后台清理；再次分享采用“直接覆盖”；待办保留历史记录并显示“已撤回”。

覆盖只适用于已撤回、处于 `deleting` 的旧分享引用。有效入口仍拦截重复分享，新分享仍走原审批。用新的审批实例与分享入口承载新一轮授权，旧任务仅清理旧入口。

需求见 [requirements.md](requirements.md)，设计见 [design.md](design.md)，任务见 [tasks.md](tasks.md)，验证见 [verification.md](verification.md)。

用户于 2026-10-14 确认按方案实施。本地实现与定向验证完成；未提交、部署或操作线上数据。实际证据和环境限制见 verification.md。
