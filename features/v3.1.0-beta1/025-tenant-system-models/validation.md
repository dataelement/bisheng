# F025 实施与交付验证

2026-11-18。独立分支 `codex/3.1.0-beta1/tenant-system-models-20261118`，基线 `c36ba672be0ff2f79d0e7358954e77973d2495f2`，工作区 `beta1-tenant-system-models-20261118`。用户授权评审通过后开发；本轮不合并、不推送、不部署、不恢复116存量。

## 结果

五栏目继承与模型授权分开；实际候选和运行移除继承授权捷径。slot执行保留完整来源校验与原身份/事务，只返回准入引用，保存现存模型验证类型/上线；原同源tombstone保留合同不改。共享意图/新接收receipt、新挂载/重新启用/新增模型生产者与默认可见初始化接通，历史未知不分发，重试不覆盖限制。图片owner基础与本地限制统一两模式，价格只读与积分独立。管理界面提供逐引用诊断、显式修复、继承覆盖/恢复、Root按需影响/覆盖检查，批量读取、保存刷新及租户切换隔离。

## 检查矩阵

| 检查 | 实际结果 | 说明 |
|---|---|---|
| 最终后端集中16文件 | 246 passed | 来源slot/原身份HTTP、保存、真实共享/恢复、图片/价格与Root诊断合并运行 |
| 新表登记后补充集中3文件 | 23 passed | 冷进程登记/填充/RootChild隔离、lifecycle与Root诊断；与246有重叠，不相加 |
| A运行/来源扩大19文件 | 375 passed | 选择清单与日志见下；与其它组有重叠 |
| A显式选模追加3文件 | 30 passed | Work显式hidden拒绝、Chat两入口前置拒绝、统一vision；与A扩大组有重叠 |
| B共享/删除/挂载/原DAO | 216 passed | validation-B.md含准确命令与额外C3/UI验证 |
| C能力/计费 | 87 passed | validation-C.md含准确命令和SQLite/HTTP边界 |
| 最终管理界面34文件 | 229 passed | `vitest run src/pages/ModelPage/manage --maxWorkers=1 --minWorkers=1` |
| 整个frontend lint/typecheck | 通过 | 平台、用户端及命令覆盖的各共享包，未扩大旧strict豁免 |
| i18n | 通过，无新增漂移 | 新界面文案三语言；错误码无新增 |
| 平台生产构建 | 通过 | 仅既有体积/动态导入/Tailwind提示，无新构建错误 |
| 格式、未定义符号、新Python文件lint | 通过 | 全修改Python已Ruff格式化；A的F821=0；新Python文件check通过 |
| 既有Python lint/架构基线 | 无新增；仍有遗留 | 详见下文，不宣称全后端Ruff或守卫零诊断 |
| 独立设计评审 | PROCEED | 首轮REVISE后补充来源/共享生产者及图片优先级设计 |
| 独立代码审查 | PASS | code-review-independent.md；实际独立执行后端62、前端31项，并复查最终AC06/C3增量 |
| 真实116、DM8、多进程/供应商E2E | 未执行 | 原环境只读，真实发布验收见e2e-checklist.md |

## 可重复的集中命令

后端使用主仓库Python3.11虚拟环境，config指向已存在开发配置，不复制凭据。以下运行均在隔离fixture SQL、权限传输/HTTP及身份环境中，不写真实业务数据。

```sh
python -m pytest \
  test/knowledge_unification/test_model_default_slot_admission.py \
  test/knowledge_unification/test_llm_default_read.py \
  test/knowledge_unification/test_llm_defaults.py \
  test/knowledge_unification/test_llm_default_consumers.py \
  test/knowledge_unification/test_model_sharing_lifecycle.py \
  test/knowledge_unification/test_model_provider_sharing_writers.py \
  test/knowledge_unification/test_model_sharing_projection.py \
  test/llm/test_model_actual_sharing_runtime.py \
  test/llm/test_llm_share_fallback.py \
  test/llm/test_system_model_settings.py \
  test/llm/test_model_pricing_edit.py \
  test/dsh/test_tenant_model_capabilities.py \
  test/dsh/test_model_display_catalog.py \
  test/dsh/test_credit_settings.py test/dsh/test_vision.py \
  test/dsh/test_pricing_hints.py -q -W ignore

python -m pytest test/database/test_model_registry.py \
  test/knowledge_unification/test_model_sharing_lifecycle.py \
  test/llm/test_system_model_settings.py -q -W ignore

python -m pytest test/llm/test_user_model_visibility_execution.py \
  test/linsight/test_model_vision_flag.py \
  test/llm/test_llm_system_config_consumers.py -q -W ignore
```

前端工作区：`pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`、`pnpm build:platform`；平台目录执行上述vitest命令。工作树依赖复用已安装包，并为本树工作区模块建立独立链接；最初knowledge包的bin包装路径问题经本地链接修复，最终正式全frontend命令通过，未以跳过包替代通过。

## 遗留基线与限制

- A修改文件集合Ruff原基线767条、当前726条，无新增诊断；详见quality-baseline.json。未将700余项旧中文标点/旧规则问题伪装为全量通过，也不为此次模型业务改动重写全部旧代码。
- 逐文件架构守卫保留3条与原基线相同诊断：common/chat/client.py原顶层领域/API依赖（RULE1两条），open_endpoints/api/endpoints/filelib.py原跨模块API依赖（RULE5一条）。此次仅接入slots，无新增违规；未把旧import藏进函数规避。
- C扩大回归有2项旧fixture失败，原始c36完整backend archive使用同环境独立复现，见validation-C.md。B另2个旧挂载测试mock已退役_creation_factory，原HEAD目标模块定向复现实证，见validation-B.md；这不是完整基线树的全量比较。集中主链回归没有排除任何新发现的本功能失败。
- 前端原有1项权限弹窗测试使用旧button角色，基线亦失败；本轮改为真实tab语义并更新“当前租户全员”断言，最终6项该文件及229项整组全部通过。
- HTTP测试保留真实业务/原身份与事务等核心边界，但替换登录传输或外部服务；不代表已验证生产登录、真实OpenFGA/数据库网络、DM8或供应商调用。

## 发布和116验收

新增两张独立SQLModel表由标准启动发现建表，模块显式登记租户过滤；没有既有表DDL和历史授权回填。部署应先确认模型发现/建表成功，再开放本功能。

旧提供商无持久意图时保持未知，不按旧tuple推断“以后给所有租户共享”；现有实际授权不变。若需补齐租户69，须在部署后盘点原计划/意图/实际关系/可见范围，再由有效管理员走原保护命令。原关闭计划必须按原actor/command/阶段恢复，不能删账本、清保护、重签摘要或直接提交相反开启操作。本轮没有执行这些现场动作。

最终提交可在本分支使用`git log -1`核对；主工作区未用于源码修改。QA参考用例保持待执行，真实环境清单不计为通过。
