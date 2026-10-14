# 发布文件记住上次目标路径

- Status: `implemented-local-verified`
- Updated: `2026-10-14`

用户确认跟随账号跨设备同步，并指定“用 user_link，不用考虑租户”。实现当前账号的三类最近发布路径，保留实时权限校验。复用现有表，无 Schema 变更。

- [需求与验收](requirements.md)
- [设计与边界](design.md)
- [实施任务](tasks.md)
- [验证记录](verification.md)

规格自审：REQ-1–REQ-5 均有设计、任务及验证映射，指定字段容量足够，用户行锁保护更新，失败隔离与目录恢复有负向验证。当前获最终选择授权，进入实现。
