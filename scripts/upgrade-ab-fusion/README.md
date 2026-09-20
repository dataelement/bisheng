# 毕昇 B→A 升级与融合：运维执行包

**现场实施：** [`用户操作全流程手册.md`](./用户操作全流程手册.md)。开发对照 [`复制即跑.md`](./复制即跑.md)。
本轮演练结果：[`演练报告-20260917.md`](./演练报告-20260917.md).

## 方向 (已调整)

最终环境是 **A**. B 先升到与 A 一致的 2.5.0-sg, 再把 B 的业务 **INSERT** 进 A.

- A 原 `knowledge.type=3` 知识空间: 不导出、不 UPDATE、不重解析.
- B 的知识空间 (type=3, 含 hop 后由 type=2 转来的个人空间) **不迁**; 只迁传统库 type=0/1.
- 用户以 A 员工编码为准; B 资源改写到 A `user_id`.
- 禁止按姓名/用户名/部门名自动合并; 同名工作流/知识库加 `[B迁移]`.
- 默认 `APPLY=0` 只生成 SQL. `APPLY=1` 写入 A.
- 只针对 **MySQL 8**. 禁止整库 dump 合库.

## 阶段

| 序号 | 阶段 | 命令 |
|---:|---|---|
| 0-11 | P2 hop | 手册第 3 章. B 已升完可跳过 |
| 12 | 控制表 + A 基线 | `p4/00-install-control.sh` `p5/00-protect-a-baseline.sh` |
| 13 | 身份导出/映射 | `p4/01-export-identity.sh` `p4/02-propose-maps.sh` (无冲突自动写 p4 csv) |
| 14 | 身份写入 A | `APPLY=0` 再 `APPLY=1 p4/10-apply-identity.sh` |
| 15 | 业务导出/dry-run/SQL | `p5/10-export-b-business.sh` `p5/30-apply.sh` |
| 16 | MinIO | `p5/20-copy-minio.sh` 按 `minio-jobs.tsv` 拷对象, 禁止覆盖 A 键 |
| 16a | Milvus/ES | `p5/22-copy-vectors.sh` 兼容则物理迁入, 不兼容进 `vector-exceptions.tsv`, 不自动重解析 |
| 16b | OpenFGA | `p5/35-apply-openfga.sh` 写迁入资源 owner / 组 manager / 角色与部门授权 |
| 17 | 核对 | `p5/40-verify.sh` (A 空间不降 + B 基线条数) |
| 17a | 检索金标 | `p5/50-retrieve-gold.sh` 同向量对打, overlap@5 默认 ≥0.8 |
| 17b | 工作流上线 | `CONFIRM_PUBLISH_FLOWS=1 APPLY=1 p5/36-publish-flows.sh` (SQL 仍先下线) |
| 18 | 回滚本批 | `APPLY=0 p5/90-rollback.sh`（批次名脚本自取，会打印；含本批 MinIO dst） |
| — | B 升级前冻结 | `p2/01-freeze-and-backup.sh`（MySQL+MinIO+Milvus+ES；hop 无完整冻结则 FAIL） |
| — | B 版本回滚 | `APPLY=0 p2/90-rollback.sh`（完整冻结还原四件套；本轮不完整冻结要 ACCEPT_INCOMPLETE_STORAGE） |
| 19 | 切流量 | 冻结水位 + `p6/30-apply-incr.sh`, 见 `p6/cutover-runbook.md` |

编排: `bash full-migrate.sh` (默认 APPLY=0).

## 涉及数据表 (无业务 DDL)

控制表 (仅 A): `fusion_batch` `fusion_map` `fusion_exception` `fusion_a_baseline`.

读取 B / 写入 A: `user` `user_tenant` `department` `user_department` `group` `usergroup` `role` `userrole` `roleaccess` `tenant` `llm_server` `llm_model` `t_gpts_tools` `t_gpts_tools_type` `system_dictionary` `knowledge` `knowledgefile` `qaknowledge` `review_tag` `review_tag_link` `groupresource` `flow` `flowversion` `t_variable_value` `t_report` `assistant` `assistantlink` `message_session` `chatmessage` `message_citation` `message_citation_relation` `marktask` `markrecord` `markappuser` `user_link` `share_link` `auditlog`.

OpenFGA (A store `bisheng`): 迁入资源 `owner` / 组 `manager` / 角色 viewer|editor / 部门或 as_group 用户组授权. A 原 Tuple 不改. 工具/看板不扩权.

MinIO: `p5/20-copy-minio.sh` 按新键拷原文件/预览/BBox/缩略图/logo/对话附件/报表对象, 目标键已存在则失败. 回滚按 dst 名单 `mc rm`, 不递归删桶.

Milvus / ES: `p5/22-copy-vectors.sh` 只迁本批新建 type=0/1. 兼容则保留向量/正文并重写 ID/对象路径, 写入 `b{src}_` 新 Collection/Index. 不兼容进 `fusion_exception` / `vector-exceptions.tsv`, **不自动重解析**. A 原 type=3 的 Collection/Index 只读, 命中则拒绝.

A 原 `knowledge.type=3` 及相关文件/索引/OpenFGA: **只读核对, 不写**.

默认不迁: 积分/遥测/Redis/JWT/分享签名密钥. 模型/工具的 `config`/`api_key`/`extra` 随行拷到 A. 审计 `auditlog` 迁入 (方案 D16).

## 本包未做 (不要假装已迁完)

- 工作流/助手端到端运行 (脚本只做静态门禁 + 改 status; 须在 A UI 验收)
- 模型/工具冲突行须先消掉, 见 `logs/p4/*.conflicts.csv`; 无冲突会自动建行并拷密钥
- 不兼容知识库的重新解析 (须客户逐项批准, 见 `logs/p5/vector-exceptions.tsv`)

## 运行位置

在 **B 源机** 跑脚本: 本地 mysql 容器是 B, A 走 SSH (无脚本默认 IP).
`bash full-migrate.sh` 会自动生成 `env.sh`, 并问 A 的地址/账号/端口 (写入 `env.sh`) 和密码 (只留当前窗口, 不写文件); 已填则回显确认. 不必手工 `cp env.sh.example`. 分步跑第一次连 A 时同样会问.
本轮演练 A 曾用 `Oper1@10.171.0.50:52012`, `A_SSH_AUTH=password`. 有密钥后可改 `auto`/`key`.
密码登录才需要 `sshpass` (缺则脚本尝试安装). 开跑打印 `连接 A: user@host:port`.
无人值守: `SKIP_A_SSH_PROMPT=1` 且已有 `env.sh` + `SSHPASS`/密钥.
