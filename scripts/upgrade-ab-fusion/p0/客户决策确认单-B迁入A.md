# 客户决策确认单 (B 迁入 A)

对照: `毕昇A-B环境升级融合方案-客户评审版(1).md` 第 18 节.

旧确认单 `客户决策确认单.md` 是 A 迁入 B, **作废**. 下表是脚本落地时采用的默认; 标「待你确认」的没有写死进 APPLY.

| 编号 | 决策 | 脚本默认 | 状态 |
|---|---|---|---|
| D01 | 最终环境 | A | 已按新方案落地 |
| D02 | A 空间 | 不迁移、不重解析、不 UPDATE type=3 | 已落地 |
| D03 | B 目标构建 | 与 hop 相同 `TARGET_ALEMBIC_HEAD` | 沿用 P2 |
| D04 | 用户权威 | 员工编码 `external_code`/`external_id`; 保留 A user_id | 已落地 |
| D05 | B 独有用户 | `create` 在 A 新建, 密码不迁 | 已落地 |
| D06 | 歧义用户 | 不按姓名合并; 无编码进 manual | 已落地 |
| D07 | 部门 | 编码 bind; 对不上 `as_group`, 不改 A 组织树 | 已落地 |
| D08 | B 个人库/空间 | 不迁 B 的 type=3 (`MIGRATE_B_SPACES=0`); 只迁传统库 type=0/1 | 已确认 |
| D09 | 解析产物 | MinIO 先拷; 兼容则迁 Milvus/ES 原向量 (不重 Embedding); 不兼容进例外清单, 不自动重解析 | 已落地 |
| D10 | 不兼容 B 文件 | 只记录 `need_reparse`, 须客户批准后才重解析 | 已按方案默认, 脚本不自动解析 |
| D19 | QA 问答对 | 迁 `qaknowledge` (仅已映射 type=0/1) | 已落地 |
| D20 | 传统库标签 | 新建 `review_tag` / `review_tag_link`, 不按同名合并 | 已落地 |
| D21 | 组可见性 | 迁 `groupresource` + OpenFGA manager; 不给 A 原工具扩权 | 已落地 |
| D22 | OpenFGA owner | 仅为迁入 knowledge_library/workflow/assistant 重建 owner | 已落地 |
| D25 | 消息引用 | 迁 `message_citation` / `message_citation_relation`, citation_id 换新 | 已落地 |
| D26 | 标注 | 迁 `marktask` / `markrecord` / `markappuser` | 已落地 |
| D27 | 报表 | 迁 `t_report`, version_key 冲突换新; 模板对象走 MinIO | 已落地 |
| D28 | 工具分类 | B 独有 `t_gpts_tools_type` 新建, 不拷 `api_key`, 不自动建子工具 | 已落地 |
| D29 | MinIO 附件 | 缩略图 / logo / 对话附件 / 报表对象写入 `minio-jobs.tsv` | 已落地 |
| D30 | 部门/角色授权 | roleaccess + userrole 重建; 部门授权重写 B OpenFGA dump. 禁止给 A 原资源/工具扩权 | 已落地 |
| D23 | 字典 | `system_dictionary` 同键 bind, 新键 create | 已落地 |
| D24 | 模型/工具缺口 | 不自动建, 出 `gaps-model-tool.tsv` | 已落地 |
| D11 | 会话 | 并集保留; chat_id 冲突则新 id | 已落地 |
| D12 | 迁入会话继续对话 | 依赖应用验证/上线后允许; 缺失应用只读 | 脚本不自动跑对话, 发布走 `p5/36-publish-flows.sh` |
| D13 | 同名 | `[B迁移]` 后缀 | 已落地 |
| D14 | Token | share_link 重新生成 UUID | 已落地 |
| D15 | 标注/报表 | 随核心业务迁移 | 已落地 |
| D16 | 积分/审计 | 不迁 (`CONFIRM_POINTS=0`) | 已确认 |
| D17 | 租户 | `p4/tenant-map.csv` 1->1 | 已确认 |
| D18 | 共享存储 | 默认不迁 B 空间, 此门禁不触发 | 已确认(随 D08) |
| 方案14.1 | RPO | 冻结水位 + `p6/30-apply-incr.sh`; 冻结后再写则作废 | 已落地 |
