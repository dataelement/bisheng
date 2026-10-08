# 单模型授权记录修订（2026-09-10）

用户已批准：取消大 JSON，直接修改额度配置表为一行一条用户模型记录；功能未发版，不新增 Alembic，仅调整 109 独立 DSH 实例的数据结构，应用部署由用户处理。

## 数据与一致性

- 仍使用 dsh_user_policy，不增加用户主表或明细表。删除 model_configs，增加 model_id、monthly_token_limit、enabled。唯一键为 (tenant_id,user_id,model_id)，模型检索索引为 (tenant_id,model_id,enabled,user_id)。
- 每条记录独立 version、pending_operation_id 和 quota_sync_state。禁用仍保留记录及递增版本，防止删除重建导致旧请求重新授权；保留所有调用、月度用量及操作审计。
- 管理保存只提交一个模型：PUT /api/v1/dsh/admin/users/{user_id}/models/{model_id}/policy，正文 {operation_id,expected_version,enabled,monthly_token_limit}。同路径 GET 返回当前模型的版本、启用状态、额度、待处理操作。原整份用户策略 PUT 不再支持；原用户策略 GET 仅聚合只读用量信息。
- GET /api/v1/dsh/admin/models/{model_id}/users 默认列出有效毕昇用户，标注当前模型配置；authorized_only=true 走模型索引分页，再由用户模块检查有效性及用户名。无配置不是未登录，不查询席位、部门。
- Redis 保留用户槽内的真实用量账本；策略版本、所有者、同步阻塞按 model_id 分开。更新 A 只替换 A 的授权字段；不删除 B 的额度、计数或历史。SQL 与 Redis 单模型版本一致后结束操作；旧 worker/旧请求不能覆盖新配置。
- 模型列表和恢复需要的聚合对象仅在内存构造。恢复清单包括全部记录的 model_versions（含禁用及占位行），policy_version 是这些版本的和，仅用于用户用量账本的完整性校验，不作为管理写入版本。quota_epoch 仍表示同一用户用量账本的恢复代次，恢复时校验整份行快照后更新全部行。
- 公开客户端登录、换票、Token、模型调用和 usage 协议不变。仅管理前端配套接口调整；不恢复部门、用户组、限流、默认额度或缺用量冻结。

## 109 转换边界

只处理 /opt/server/dsh 对应独立 MySQL 的 bisheng.dsh_user_policy，先导出原表及配置备份并检查无未完成策略操作。当前检查结果为一条空策略、无模型授权、无调用明细。结构切换后旧应用镜像不能继续读取该表，需用户部署新版恢复 DSH 额度功能。不部署、不重启应用，不修改旧达梦实例。

## 验证

验证独立用户模型唯一性、不同模型并发修改、同模型 CAS/操作重试、取消授权后的在途结算、模型索引分页与跨租户隔离、恢复/跨月计数及前端单行请求。真实达梦验证按用户要求暂缓；业务查询仅 ORM，无 JSON 查询或新手写 SQL。


## 执行证据

- 2026-09-10 已在 109 独立库直接完成 ALTER TABLE；保留原表名，未增加 Alembic 或业务明细表。转换前一条空策略转换后为零条授权记录，无调用/月度用量、无处理中操作。仅把已证明为空的缓存策略修订计数从 1 对齐为 0；未清空用量账本或修改 Redis 拓扑审批。
- 原表 DDL、原行数据、缓存策略元数据及执行 DDL 备份：109 `/opt/server/dsh/private/dsh-policy-before-rows-20260910T075625Z.json`；另存于原 backend 的持久化 data 目录。备份 SHA256：`1857ac948a4f90450026056d3c0806d048c6f5aecd0992cf0c47c5ff5a095194`。应用容器未重启、镜像未变更。旧镜像与新表不兼容，用户需部署本次分支版本后恢复 DSH 额度读写。
- 本机临时 MySQL 8.0＋Redis 7.2：DSH 回归 362 项通过、19 项跳过；一项原有用户表 Alembic 测试因要求独立空 user 表而未纳入最终组合运行。本次未修改该迁移，也不需要执行该迁移。
- MySQL EXPLAIN 实测按模型分页命中 `ix_dsh_policy_model_users`，并显示 Using index；覆盖用户名候选与已授权两种查询、跨租户隔离、单模型并发、撤销后的在途结算与恢复。
- 前端 28 项组件及 API 测试通过，lint/typecheck 通过；变更 Python 文件 Ruff、架构守卫及 diff 检查通过。真实达梦和 109 新版应用联调未执行。
