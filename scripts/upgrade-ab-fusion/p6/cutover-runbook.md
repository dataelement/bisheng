# P6 切换 (入口到 A)

B 业务已按批次 INSERT 进 A, 且 `p5/40-verify.sh` 通过之后.

1. 公告窗口. 停 B 的用户入口、API 写入、Worker、Beat.
2. `LABEL=freeze bash p6/10-capture-watermark.sh` 记录冻结水位.
3. `APPLY=0 bash p6/25-check-frozen.sh` 确认冻结后无新写入; 有漂移则水位作废, 重新冻结.
4. `APPLY=0 bash p6/30-apply-incr.sh` 看增量 DELETE/UPDATE 与补插 SQL. 确认后 `APPLY=1`.
   已映射行 skip INSERT; 新行补插; B 删除走本批 dst DELETE (不把整批标成 rolled_back);
   UPDATE 只打本批 type=0/1, 禁止碰 A 原空间.
5. `APPLY=1 bash p5/20-copy-minio.sh` 与 `p5/22-copy-vectors.sh` 补新对象/向量.
6. `VERIFY_STORAGE=1 bash p5/40-verify.sh`. A 原空间元数据不得变; 本批悬挂 FK=0; MinIO 抽样 + 金标不达标即停.
7. 金标已含在上一步. 若单独重跑: `bash p5/50-retrieve-gold.sh`.
8. `APPLY=0 bash p5/36-publish-flows.sh` 看上线门禁; `CONFIRM_PUBLISH_FLOWS=1 APPLY=1` 才改 status=2.
   端到端运行仍须人在 A UI 做.
9. 将域名 / Gateway / 回调切到 A.
10. 确认组织同步只在 A.
11. B 只读观察, 见 `p7/observe.md`.

回滚: 切换前可用 `p5/90-rollback.sh` 按批次删 B 来源对象. 切换后 A 已有新写入则不要整站切回 B.

水位表 (只读 B, 无业务 DDL): `knowledge`(type 0/1) `knowledgefile` `qaknowledge` `flow` `flowversion` `assistant` `message_session` `chatmessage` `review_tag` `review_tag_link` `groupresource` `t_report` `roleaccess` `auditlog`.
增量写 A 对应 dest (经 fusion_map), 以及 `fusion_exception`. 不写 A `knowledge.type=3`.
