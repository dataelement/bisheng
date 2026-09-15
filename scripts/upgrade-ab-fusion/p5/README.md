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
bash p5/50-retrieve-gold.sh
APPLY=0 bash p5/36-publish-flows.sh
```

生成 SQL 禁止 `UPDATE knowledge` (增量 UPDATE 只允许本批映射的 type=0/1, 且必须带 `type IN (0,1)`). 默认 `MIGRATE_B_SPACES=0`, 跳过 B 的 type=3. 回滚 `p5/90-rollback.sh` 按 `fusion_map` 删除本批 dst, 若映射撞上 A 原空间 id 会拒绝生成 DELETE. 向量回滚按 `vector-created.tsv` 删除本批新建 Collection/Index, 不会删 A 空间名. 检索金标 `p5/50-retrieve-gold.sh` 只读. 上线 `p5/36-publish-flows.sh` 要 `CONFIRM_PUBLISH_FLOWS=1`.

本阶段写入的业务表 (无 DDL): `system_dictionary` `knowledge` `knowledgefile` `qaknowledge` `review_tag` `review_tag_link` `flow` `flowversion` `t_variable_value` `t_report` `assistant` `assistantlink` `message_session` `chatmessage` `message_citation` `message_citation_relation` `marktask` `markrecord` `markappuser` `t_gpts_tools_type` `user_link` `share_link` `groupresource` `roleaccess`. 例外: `fusion_exception`. OpenFGA 写新增资源的 owner / 组 manager / 角色 / 部门授权. MinIO 只写新对象键. Milvus/ES 只写 `b{src}_` 新名.

大字段 (flow.data / chatmessage / qaknowledge.questions / message_citation.source_payload) 走 mysql JSONL. B 部门授权依赖 `logs/p5/b-openfga-tuples.jsonl`; OpenFGA 导出失败时只重建 roleaccess 角色授权.
