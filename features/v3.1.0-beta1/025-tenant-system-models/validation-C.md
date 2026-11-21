# F025 C链路交付与验证

2026-11-18，工作区 `beta1-tenant-system-models-20261118`，基线 `c36ba672be0ff2f79d0e7358954e77973d2495f2`。仅本地源码与隔离测试，无SSH、部署、真实数据修复、提交或推送。

## 完成行为

- 图片权威采用owner `dsh_vision:{owner}:{model}`；子租户只能在其基础上收紧。历史dsh false或旧本地workbench visual false优先，不从继承payload推定本地限制。未知owner能力为false。
- 明确保存写内部 `authority_version=1`，新权威覆盖同租户旧visual证据；GET不迁移。设计第3节已同步真值表及显式修复语义。
- DSH和非DSH候选均使用同一`read_vision(model_id, *, snapshot=None)`；有snapshot的调用方必须已经验证实际模型/提供商授权。普通未带snapshot的读取再次经模型metadata入口核对。
- `POST /api/v1/dsh/admin/model-vision`：`{model_ids: number[]}`，上限200；去重，返回`ModelVisionRow[]`。已知无权返回该行unavailable，权限服务异常仍使整个请求失败。原GET/PUT vision兼容增加effective、source、can_edit/read_only等字段。
- 图片和价格管理依赖复用`authorize_admin`，不构造DSH access runtime，因此DSH关闭时仍能管理平台元数据。
- Root共享模型价格返回can_edit=false/read_only=true及source_tenant_id，子租户自有价格可编辑。原价格写入服务的Root共享只读保护经回归验证，未放宽直调权限。
- 倍率基准仅从默认元数据提取日常默认ID，再单独校验真实授权/上线及价格；不会执行整个工作台默认来源。失效返回base_reason和空ratio，不阻断其他模型价格。保存新基准要求有正数混合输入/输出价格；原公式、缺价免费策略、租户独立积分设置不变。
- `model_catalog`/`model_display`改为纯元数据默认读取，避免未使用的ASR等槽位使名称和候选展示失败；候选和调用授权仍走真实模型入口。

## C独占交付文件

后端：`dsh/domain/services/{vision,pricing,model_catalog,model_display}.py`、`dsh/infrastructure/model_capabilities.py`、`dsh/api/endpoints/{admin,credit_pricing}.py`。

前端契约：`platform/src/controllers/API/modelPricing.ts`新增ModelVisionRow/getModelVisionRows，ModelPricingRow增加只读来源及基准原因字段。UI由Root接线；实际调用消费者由A接统一read_vision。

测试：新增`test/dsh/test_tenant_model_capabilities.py`；适配`test/dsh/{test_vision,test_pricing_hints,test_model_display_catalog}.py`的metadata入口契约。

## 已执行检查

使用主仓库 `src/backend/.venv/bin/{pytest,ruff}`，`config`指向已存在主仓库配置文件；测试业务依赖均隔离，无真实数据库/权限写入。

```sh
pytest test/dsh/test_model_display_catalog.py test/dsh/test_credit_settings.py \
  test/dsh/test_tenant_model_capabilities.py test/dsh/test_vision.py \
  test/dsh/test_pricing_hints.py test/llm/test_model_pricing_edit.py -q -W ignore
```

结果：**87 passed**。包含owner/child真值表、显式保存冲突修复、跨owner关闭拒绝、batch已知拒绝/真实故障、HTTP管理scope、DSH关闭管理、两模式能力一致、SQLite仅本地旧visual读取且不写数据、共享价格只读、SQLite价格CAS及直接写入拒绝、失效基准和无关语音槽位隔离。

C修改的Python文件Ruff format/check通过；8个业务/前端文件逐文件架构守卫无输出；C范围`git diff --check`通过。

扩大到`test/dsh/{test_model_service,test_models_api,test_billing_scope}.py`后：**150 passed, 2 skipped, 2 failed**。两个失败均在原始基线隔离副本复现，未扩大修复范围。

## 原始基线对照

通过`git archive c36ba672be src/backend | tar -x -C /private/tmp/bisheng-system-models-c-baseline`生成独立原始源码副本，未改工作区或git索引。基线测试在该副本的`src/backend`目录运行，使用同一Python环境和同一已有配置路径。

```sh
pytest test/dsh/test_models_api.py::test_usage_selected_model_cannot_borrow_another_allowance \
  test/dsh/test_billing_scope.py::test_nothing_is_governed_when_the_enterprise_client_is_off \
  -q --tb=short -W ignore
```

原始基线结果：**2 failed in 0.40s**，与本轮工作区一致：

1. `test_models_api.py:265`调用usage后，`usage_projection.py:6`读取fixture未提供的`policy.monthly_token_limit`，抛`AttributeError`。
2. `test_billing_scope.py:46`期望修改`settings.__dict__["dsh"]`后关闭计费，实际`chat_credits.governed(...)`仍为True，断言失败。

相关业务文件与两个测试文件相对基线`git diff --numstat`为空。这里仅确认同环境下原基线亦失败，不把它们计作本功能回归通过。

## 尚需集成/现场验收

Root的UI/typecheck/build、A/B集成回归、独立审查和E2E由总任务推进。真实116、DM8、多进程权限撤销与生产调用未验证，不以单元/隔离HTTP测试代替。
