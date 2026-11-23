# F118统一升级流程合入beta1核对

日期：2026-11-23。用户授权将`codex/f118-upgrade-flow-20261120`合入`feat/3.1.0-beta1`，并产出从3.0.0升级的操作文档。本报告审查合并接缝与文档，不声称重新逐行审查源分支全部实现。

## 固定输入与合并范围

- 发布线基线：`ec59c5a0faeab2ce84e4f0908d3caf29fa3a04ab`。
- 来源分支：`952165f85e92ffd371b5e82c448c0f9bc31c36e7`，包含实现`2530742181`及165验收记录。
- 合并提交：`56a461e2d7fdff84b7710a67a520402d95756c16`，父提交为上述发布线基线与来源分支；升级操作文档随后独立提交。
- 在隔离worktree进行非快进合并，142个文件进入合并，无冲突。主工作区及原分支未提交改动均不加入。
- 与来源分支逐文件比较，合并索引只多出发布线原有的6个路径：request_admission、gpts_tools、user服务及其3个测试；这些分别保留最新分享链接、工具归属和注册规则修复。来源分支的迁移实现未手工重写。
- 引用辅助化延期保持；标准迁移仍完整处理引用并签发原生Coverage，未新增后台迁移或跳过验证入口。

## 验证结果

使用主仓库Python3.11虚拟环境，配置仅为私有临时`{}`。迁移组合阻止真实socket连接；所有测试使用隔离数据/协议传输，不访问165或生产。

| 验证 | 结果 | 边界 |
| --- | --- | --- |
| 变更测试文件及结构/价格/Token运行时组合 | 685 passed、6 setup errors / 277.18秒 | 包含原生F118 CLI/E2E、历史规则、共享恢复、SQL/权限/引用批次、故障及规模；6个错误来自Token模块混入全局SQLModel metadata后的SQLite建表，不是业务断言失败 |
| Token配置模块按文件说明单独执行 | 22 passed / 0.22秒 | 使用`--confcutdir=test/llm`，覆盖上述6个需要隔离metadata的场景；与前组合有重叠，不机械相加 |
| 最新发布线3个修复的回归 | 31 passed / 0.53秒 | request_scope_admission、tool_key_lookup_prefers_own_tenant、account_login_rules |
| Ruff check | 124个Python文件通过；另1个文件38项与发布线完全相同 | knowledge_service.py的rule、行列和message逐项对比ec59基线一致，没有新增lint问题；未顺带改写既有大文件 |
| Ruff format / 架构守卫 | 125个Python文件通过 | 使用仓库相对路径，不修改guard规则 |
| Alembic图 | 唯一head正确，3.0.0 head是其祖先 | 官方v3.0.0与v3.0.2均127个revision、head=f114_app_authorization；3.0.0→3.0.1/3.0.2无迁移脚本/revision增量，目标head=v310b1_f016_dsh_call_pricing |
| 维护CLI帮助 | 4个入口全部通过 | unify_knowledge_spaces、migrate_model_token_configs、backfill_model_pricing、backfill_redis_processing_indexes的文档参数存在 |
| 升级文档 | 16个Bash代码块语法及相对文件链接通过 | 不运行有副作用的示例；镜像构建、真实首次迁移与开服验收另列 |

完整组合选择位于`/private/tmp/f118-merge-beta1-20261123/pytest-selection.json`，日志/JUnit为同目录`integration-tests.log/xml`。6项setup错误闭口使用：

```bash
config=/private/tmp/f118-merge-beta1-20261123/offline.yaml python -m pytest \
  --confcutdir=test/llm test/llm/test_model_token_config_upgrade.py -q
```

未更改Token测试或生产代码以绕过混合集合的metadata问题，没有把初次非零退出报告为全组全绿。

## 七维增量审查

| 维度 | 结论 | 依据 |
| --- | --- | --- |
| 边界条件 | PASS | 继承源分支R1～R11关闭证据；新/旧Run、坏材料、零写拒绝、终态复核及恢复原生用例通过，合并无逻辑改写 |
| 权限与认证 | PASS | C3执行范围、权限Owner原生写入及未知授权阻断保持；最新发布线身份/工具/分享读取回归保留 |
| 并发安全 | PASS（既有现场边界保留） | 原Run/checkpoint、控制代际、未知外部请求和批末事务协议不变；真实MySQL/DM8失锁/未知提交未在本轮触发 |
| 信息泄漏 | PASS | 受控日志/私有材料合同保持；没有引入凭据、业务dump或现场配置 |
| 测试覆盖 | PASS（本轮选择范围） | 原生入口/E2E及最新接缝通过；Token按既有隔离要求验证；不声称全仓回归通过 |
| 代码风格 | PASS（无新增问题） | 125文件格式/架构通过，38项旧lint与基线相同，未用忽略规则掩盖新问题 |
| 文档同步 | PASS | 升级指南改为3.0.0起点，明确累计结构链、统一入口与独立迁移边界，并纠正Worker同时启动Linsight及Redis ready不代表积压清零的操作描述 |

总体：**PASS（合并增量）**。源实现完整审查仍见[七维记录](./f118-upgrade-flow-code-review-20261120.md)，165既有Run后态实测见[验收记录](./165-f118-unified-flow-2530742181-20261121.md)。本次没有重新部署165、重放生产数据或发布镜像/tag；最终镜像digest和从3.0迁移前快照的实库演练仍是上线前工作。
