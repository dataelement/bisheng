# 109 main 基线恢复与迁移范围修正

日期：2026-10-20。目标：先归档 109 原库，在新测试库建立 main 基线，再升级 feat/bisheng-work-110。本文的执行状态按实际进度更新。

## 原因与范围

109 原环境的审计功能来自 feat/3.0.0 版本线，而 work-110 来自 main。此前为识别原库 head `f062_dsh_audit_tree` 恢复 8 个旧迁移并增加 merge 的处理，将测试环境的特殊历史误当成目标版本必须支持的升级历史。
实际从 main 升级时，这会额外执行 `f068_knowledge_chat_entry`，给 `message_session` 增加与本功能无关的 `entry_flow_id` 及索引；同一批审计列/索引还会经过两套不同 revision 的 DDL。

修正保留 main 提交 `4218ba7c138a90764a304681c3d8a5875b2c9c1a` 的 83 个迁移文件原样，删除 8 个旧历史文件、1 个兼容 merge 以及 4 个冗余审计增量，最终只新增一条 revision：

`f065_dsh_install_policy_default_off → work110_dsh_local_sessions`

| 相对 main 的差异 | 处理方式 |
| --- | --- |
| dsh_model_call.seat_id、grant_version 从必填改为可空，版本检查允许无商业版本 | 唯一新增 Alembic revision，保留其他约束和既有数据 |
| 13 张审计表、2 张原生会话表 | 模型发现与 create_missing_model_tables 创建完整定义，无需迁入旧审计分支的逐列历史 |
| message_session.entry_flow_id 和外来 merge/审计 revision | 不属于目标差异，不进入本分支 |
| Gateway 的席位、Token 和会话数据 | 不导入新本地认证表 |

数据库回退和旧审计数据归档属于运维过程，不进入 revision；不能仅 stamp main 版本号，也不能靠本分支的非破坏性 downgrade 恢复 main。

## 已确认的恢复方案

用户选择：完整归档现有库，用新测试库建立 main 基线再升级。原业务库、Redis 旧逻辑库和原授权 Store 保留，不执行删库或伪造 seat_id。

归档前检查：原库 head 为 work110_merge_legacy_audit；模型调用 2132 条，其中 16 条无席位；审计请求 917 条；message_session 已包含 entry_flow_id。没有 RUNNING 调用，10 条 USAGE_UNKNOWN 记录保留为事实。

已归档目录：`/opt/server/dsh/backups/work110-main-baseline-20261020-183655`。
MySQL 全库备份 132234804 字节，SHA-256 `0181f1211b1afc501bbd499536db922ba3eaf79486aa046f7626246778fefb14`；同时保存 Compose、config、entrypoint、Nginx 和各相关容器 inspect，备份目录限 root 访问。

1. 以精确 main 提交源码建立并核验基线镜像；不能把不完全等同 main 的缓存 work-103 镜像作为基线。已核对该旧镜像有 3 个文件缺失、6 个文件内容不同。
2. 使用新的测试数据库、Redis 命名空间和 OpenFGA Store，运行 main 标准迁移和初始化，记录真实 head、表结构与 main 关键接口。
3. 使用修正后的 work-110 镜像升级同一新测试库，核验只有目标 DDL 及新增表，重复 upgrade 无额外变化。
4. 验证客户端原生登录、模型调用、个人优先/部门继承的独立额度计量以及模型审计；原库和归档保持可追溯。

## 当前验证

- 迁移历史/模型建表专项：14 passed、1 skipped。包括 83 个 main 文件的 SHA-256 不变、唯一 head、main 到目标只有一条 revision、MySQL/DM 大小写反射、15 张表完整建表及重复建表不改已有事实。
- 本地 DSH 回归：529 passed、107 skipped、54 deselected，不包含未提供前置条件的外部存储用例。
- 109 新 main 基线启动、实际 MySQL 升级和客户端复测：执行中，尚未作为通过项。
