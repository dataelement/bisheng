# 客户决策确认单 (B 迁入 A)

对照: `毕昇A-B环境升级融合方案-客户评审版(1).md` 第 18 节.

旧确认单 `客户决策确认单.md` 是 A 迁入 B, **作废**.

2026-09-16: 审计改为迁入 A `auditlog`; 方案第 18 节其余待确认项按建议锁定.
2026-09-17: D05 改为 `create` 拷贝 B `password` 哈希; JWT/Session 仍不迁.
D03 / D20 / D22 的生产 digest、窗口小时数、回滚截止时刻仍待演练回填, 规则已定.

下表「脚本扩展」编号 (D19 QA 等) **不是**方案第 18 节编号.

## 方案第 18 节 (已锁定)

| 编号 | 决策 | 锁定结论 | 状态 |
|---|---|---|---|
| D01 | 最终环境 | A | 已确认 |
| D02 | A 知识空间 | 原地保留; 不迁移、不重解析、不 UPDATE type=3 | 已确认 |
| D03 | B 目标构建 | 与 A 同镜像 digest / Git / Alembic; 演练沿用 hop `TARGET_*` | 规则已锁定; 生产钉死待演练 |
| D04 | 用户权威 | 员工编码 `external_code`/`external_id` 绑 A; 保留 A `user_id`. 无编码走 D05 新建. A 上 local+sg 双行绑权威 (sg) 那条 | 按建议锁定 |
| D05 | B 独有用户 | 在 A `create` 新建, 拷贝 B `password` 哈希; `bind` 不改 A 密码. JWT/Session 不迁 | 2026-09-17 改单 |
| D06 | 歧义用户 | 不按姓名合并; 无编码进 `manual.csv` 人工填 | 按建议锁定 |
| D07 | 部门 | 编码 bind; 对不上 `as_group` 成 B 用户组, 不改 A 组织树 | 按建议锁定 |
| D08 | B 个人库/空间 | 不迁 B 的 type=3 (`MIGRATE_B_SPACES=0`); 只迁传统库 type=0/1 | 已确认 |
| D09 | 解析产物 | MinIO 先拷; 兼容则迁 Milvus/ES 原向量 (不重 Embedding); 不兼容进例外清单 | 按建议锁定 |
| D10 | 不兼容 B 文件 | 只记录 `need_reparse`, 须逐项批准后才重解析 | 按建议锁定 |
| D11 | 会话和消息 | 两边并集进 A; `chat_id` 冲突则新 id | 按建议锁定 |
| D12 | 迁入会话继续对话 | 依赖应用验证/上线后允许; 缺失应用只读. 发布走 `p5/36-publish-flows.sh` | 按建议锁定 |
| D13 | 同名工作流/知识库 | 加 `[B迁移]` 后缀, 不自动合并 | 按建议锁定 |
| D14 | 分享链接和 Token | 密码/API Key 不拷; share_link 在 A 重签 UUID | 已确认 |
| D15 | 标注/报表/收藏 | 随核心业务迁移 (脚本已覆盖标注/报表/收藏分享) | 按建议锁定 |
| D16 | 审计/积分/遥测 | **审计** `auditlog` 迁入 A; **积分/遥测不迁** (`CONFIRM_POINTS=0`) | 已确认 (2026-09-16 改单) |
| D17 | 租户 | `p4/tenant-map.csv` 1->1 | 已确认 |
| D18 | 共享存储 | 默认不迁 B 空间, 此门禁不触发 | 已确认 (随 D08) |
| D19 | RPO | 冻结水位 + `p6/30-apply-incr.sh`; 冻结后再写则作废; 目标 RPO=0 | 按建议锁定 |
| D20 | 维护窗口 | 演练实测最大耗时 + 30%; 升级与融合拆两次; 小时数待演练回填 | 规则已锁定; 数字待演练 |
| D21 | B 只读观察期 | 不做独立 P7 观察期 | 已确认 |
| D22 | 快速回滚截止点 | 切入口前可按批次 `p5/90-rollback.sh`; 切入口后只允许前向修复. 时刻待演练钉死 | 规则已锁定; 时刻待演练 |
| D23 | 可接受例外 | P0=0; P1 原则上为 0; 其余例外逐项签字 | 按建议锁定 |

## 脚本扩展 (施工编号, 已落地)

| 编号 | 决策 | 脚本默认 | 状态 |
|---|---|---|---|
| X19 | QA 问答对 | 迁 `qaknowledge` (仅已映射 type=0/1) | 已落地 |
| X20 | 传统库标签 | 新建 `review_tag` / `review_tag_link`, 不按同名合并 | 已落地 |
| X21 | 组可见性 | 迁 `groupresource` + OpenFGA manager; 不给 A 原工具扩权 | 已落地 |
| X22 | OpenFGA owner | 仅为迁入 knowledge_library/workflow/assistant 重建 owner | 已落地 |
| X23 | 字典 | `system_dictionary` 同键 bind, 新键 create | 已落地 |
| X24 | 模型/工具缺口 | 不自动建, 出 `gaps-model-tool.tsv` | 已落地 |
| X25 | 消息引用 | 迁 `message_citation` / `message_citation_relation`, citation_id 换新 | 已落地 |
| X26 | 标注 | 迁 `marktask` / `markrecord` / `markappuser` | 已落地 |
| X27 | 报表 | 迁 `t_report`, version_key 冲突换新; 模板对象走 MinIO | 已落地 |
| X28 | 工具分类 | B 独有 `t_gpts_tools_type` 新建, 不拷 `api_key`, 不自动建子工具 | 已落地 |
| X29 | MinIO 附件 | 缩略图 / logo / 对话附件 / 报表对象写入 `minio-jobs.tsv` | 已落地 |
| X30 | 部门/角色授权 | roleaccess + userrole 重建; 部门授权重写 B OpenFGA dump. 禁止给 A 原资源/工具扩权 | 已落地 |
