# P5 业务 B→A

在身份映射完成且 `p4/user-map.csv` 的 `a_user_id` 已填之后.

```bash
bash p5/00-protect-a-baseline.sh
bash p5/10-export-b-business.sh
APPLY=0 bash p5/30-apply.sh
APPLY=0 bash p5/20-copy-minio.sh
APPLY=0 bash p5/22-copy-vectors.sh
APPLY=0 bash p5/35-apply-openfga.sh
bash p5/40-verify.sh
# APPLY=1 拷完对象/向量后: VERIFY_STORAGE=1 bash p5/40-verify.sh
bash p5/50-retrieve-gold.sh
APPLY=0 bash p5/36-publish-flows.sh
```

生成 SQL 禁止 `UPDATE knowledge` (增量 UPDATE 只允许本批映射的 type=0/1, 且必须带 `type IN (0,1)`). 默认 `MIGRATE_B_SPACES=0`, 跳过 B 的 type=3. 回滚 `p5/90-rollback.sh` 按 `fusion_map` 删除本批 dst, 若映射撞上 A 原空间 id 会拒绝生成 DELETE. 向量回滚在删表前快照本批 `knowledge.collection_name`/`index_name`, 并合并 `vector-jobs` 里 skip 留下的旧 Collection/Index, 不单靠 `vector-created.tsv`; 不会删 A 空间名. MinIO 回滚按 `minio-jobs.tsv` 的 dst (缺则用 file-map / fusion_map note 还原) `mc rm` 本批对象, 不递归删桶, `src==dst` 不删. 检索金标 `p5/50-retrieve-gold.sh` 只读. 上线 `p5/36-publish-flows.sh` 要 `CONFIRM_PUBLISH_FLOWS=1`. 本阶段验收只看数据完整、引用一致、A 原 type=3/原会话未被改、迁入工作流能跑; 不含 Gateway/备份恢复. `40-verify` 把会话/消息 map 当硬门; `VERIFY_STORAGE=1` 再查 MinIO 抽样和检索金标.

本阶段写入的业务表 (无 DDL): `system_dictionary` `llm_server` `llm_model` `t_gpts_tools` `t_gpts_tools_type` `knowledge` `knowledgefile` `qaknowledge` `review_tag` `review_tag_link` `flow` `flowversion` `t_variable_value` `t_report` `assistant` `assistantlink` `message_session` `chatmessage` `message_citation` `message_citation_relation` `marktask` `markrecord` `markappuser` `user_link` `share_link` `groupresource` `roleaccess` `auditlog`. 例外: `fusion_exception`. OpenFGA 写新增资源的 owner / 组 manager / 角色 / 部门授权. MinIO 只写新对象键. Milvus/ES 只写 `b{src}_` 新名.

大字段 (flow.data / chatmessage / qaknowledge.questions / message_citation.source_payload / auditlog.metadata) 走 mysql JSONL. B 部门授权依赖 `logs/p5/b-openfga-tuples.jsonl`; OpenFGA 导出失败时只重建 roleaccess 角色授权.
