# 模型 Token 配置升级

适用目标：已完成 3.0.0-beta2 表结构升级的环境。业务转换使用 `scripts/migrate_model_token_configs.py`，与 Alembic 结构变更独立。运行目录为 `src/backend/`，Python 和 `config` 环境变量与服务保持一致。

## 执行顺序

1. 备份数据库；确认本次作用于全部租户或明确的租户 ID。先部署目标代码和结构，保持 API、Worker 与 Linsight 停止写入，等待在途调用结束。
2. 在目标后端环境运行只读预检，核对扫描数、计划数、模型/租户/服务标识与错误列表。报告仅包含标识和计数。
3. 预检通过后，以全新私有备份路径执行正式转换。该文件包含前后完整模型配置，按凭据文件保护，保留在运维备份位置。
4. 再运行只读预检，确认计划数为 0、错误数为 0；核对模型 ID、状态、归属、服务商配额和高级参数继承情况。
5. 重启 API、Worker 和 Linsight，清理进程内模型信息缓存，恢复模型调用与配置写入。每日调用 Redis 计数保留。

```bash
export config=config.yaml
python scripts/migrate_model_token_configs.py --all-tenants
python scripts/migrate_model_token_configs.py --all-tenants --apply \
  --backup-file /secure-backups/model-token-upgrade-before.json
python scripts/migrate_model_token_configs.py --all-tenants
```

指定租户时使用 `--tenant-id 1`，可以重复传入。命令必须明确选择租户范围。原配置已转换时，重复执行保持原值；命中数为 0 时跳过备份与数据库写入。退出码 0 表示本次预检/转换成功，1 表示配置需人工处理并整批停止，2 表示参数、备份或基础环境错误。

JSON 在 Python 中解析和合并，SQL 使用 ORM，兼容 MySQL/DM8 的结构与 JSON 列；本地事务检查使用 SQLite，真实 MySQL/DM8 演练记录单独维护。

## 字段转换

只处理 `llm_model.model_type = llm` 且配置包含 `max_tokens` 的记录。按所属服务商识别 Ollama，将原有效值写入高级 `num_ctx`；其余服务商写入高级 `max_tokens`。原字段优先于同名高级值，保持升级前的生效值。其他参数保留。

旧高级参数支持 JSON 字符串和对象，转换后的有效 Token 配置保存为 JSON 字符串；异常 JSON、非对象 JSON、异常旧值、失效或跨租户服务关联会阻止整个批次写入。0、空字符串和 null 的旧值只清理独立字段，保留原高级值。

脚本仅更新模型 config；模型稳定 ID、状态、默认模型引用、所属服务、租户和权限关系及服务商 limit/limit_flag 保持原值。数据库写入在同一事务中完成，写入前独占创建 mode-0600 备份并刷新到磁盘。已有备份路径要求操作人员选择新路径，原备份保留。

## 恢复

继续保持维护窗口，先预检恢复范围；正式恢复前以新路径备份当前配置：

```bash
python scripts/migrate_model_token_configs.py --all-tenants \
  --restore-backup /secure-backups/model-token-upgrade-before.json
python scripts/migrate_model_token_configs.py --all-tenants --apply \
  --restore-backup /secure-backups/model-token-upgrade-before.json \
  --backup-file /secure-backups/model-token-restore-before.json
```

恢复核对模型 ID、租户及服务关联，并要求当前配置等于备份记录的升级后配置；已恢复记录跳过。后续编辑或模型丢失会阻止整个批次，先处理冲突再重试。新创建的模型保留。数据恢复后再回退代码并重启各业务进程；数据库结构按目标版本自身回滚方案处理。密钥或其他服务级配置的恢复沿用服务级备份，本脚本只负责模型 config。

## 执行证据

自动检查见 [verification.md](verification.md)。3006 已部署的界面包含旧字段兼容读取；本脚本的真实环境写入、MySQL/DM8 演练及数据恢复为独立发布步骤，当前记录为待执行。
