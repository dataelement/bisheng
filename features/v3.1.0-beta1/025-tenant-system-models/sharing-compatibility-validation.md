# 共享兼容修复与116恢复验收

2026-11-18，Asia/Taipei。开发基线远端beta1 `6903f28c6f`，独立分支`codex/3.1.0-beta1/legacy-model-sharing-repair-20261118`。用户明确授权代码修复、116补授权、受限放弃未执行旧任务、验证后合并推送，并确认复制7份维护源码及3份配套文件到临时隔离目录。主工作区未参与开发。

## 修复与检查

旧Root开关依据实际接收者显示开启，新挂载/重启用却只消费新增intent表，导致旧提供商被遗漏。现在明确新状态优先，没有新记录时兼容canonical native共享关系；默认配置引用不授予权限，GET和启动不回填。legacy新增模型先零增量确认旧接收集合，产生真实完成计划，再初始化新模型策略。

存量恢复把预览intent/version/plan_id放入命令摘要，在provider锁内复核后创建原投影reservation；不能覆盖后来完成的关闭，只补缺失接收策略、不覆盖本地限制。

| 检查 | 结果 |
| --- | --- |
| 13个受影响测试文件组合执行 | 93 passed；SQL计划、真实投影流程、兼容/挂载、删除互斥、失败重试、时间精度、普通运行鉴权、取消及迟到journal |
| Ruff | 全部12个修改/新增Python格式通过；新增及共享链check、F821通过 |
| 架构守卫 | 逐一检查12文件，无诊断；git diff --check通过 |
| 脚本 | 本地--help通过；最终script角色启动及116只读覆盖复核通过，不导入或启动HTTP app |
| 独立设计评审 | 条件修复、零增量adoption、未执行任务取消均PROCEED；首轮两项blocker已补设计和交错测试 |
| 七维代码自审 | 边界、权限、并发、泄漏、测试、规范、文档均PASS |

无前端代码或数据库结构变化。未运行DM8实机和全仓回归；fixture测试不算供应商E2E。

回归命令，cwd `src/backend`，使用既有虚拟环境及config：

```sh
python -m pytest \
  test/knowledge_unification/test_model_sharing_preparation_cancellation.py \
  test/knowledge_unification/test_legacy_model_sharing_compatibility.py \
  test/knowledge_unification/test_model_sharing_lifecycle.py \
  test/knowledge_unification/test_model_provider_sharing_writers.py \
  test/knowledge_unification/test_model_mount_share_recovery.py \
  test/knowledge_unification/test_model_provider_operation_repository.py \
  test/knowledge_unification/test_model_deletion_application.py \
  test/knowledge_unification/test_model_deletion_prepared.py \
  test/knowledge_unification/test_model_sharing_projection.py \
  test/knowledge_unification/test_model_delete_plan_precision.py \
  test/permission/test_model_sharing_tuple_read.py \
  test/llm/test_model_actual_sharing_runtime.py \
  test/tenant/test_model_mount_fanout.py \
  --confcutdir=test -q --disable-warnings
```

## 116恢复及数据保持

在`bisheng-test-backend`内`/tmp/bisheng-sharing-repair-20261118`运行维护代码，使用原服务config及既有依赖。17提供商先恢复，通义千问处理旧准备任务后单独恢复。最终只读预览：18个均明确开启，对11个活跃子租户覆盖完整，无缺失接收者或活动任务错误。

| 检查项 | 实际结果 |
| --- | --- |
| 活跃子租户 | 19、20、25、26、28、60、65、67、68、69、70 |
| 授权 | 原114条，最终262条，新增148条；保留历史已有接收者 |
| 接收可见策略 | 原344行内容及版本均未改变，新增455行，最终799行 |
| 配置 | 全量提供商config、模型config（含价格）、租户系统默认配置的前后哈希一致 |
| 运行源码 | 最终9份涉及的既有服务源码哈希与运行镜像一致；未重启服务 |

旧任务`e8e882d2-fa74-49d2-b38a-388d350b791d`为11月13日PREPARING记录，请求hash完整，旧时间签名无法验证，没有共享冻结数据、接收receipt或权限journal。用户确认后，受限取消在provider锁内核对完整指纹，置原记录为ABANDONED，保留原actor、command/request hash、plan digest和operation ID，ack记录取消人与旧指纹。随后重新预览，创建独立正常共享命令。没有删除记录、改签旧摘要或执行旧命令。

复制新增依赖时曾因隔离目录父级软链误写两份服务源码。发现后立即从当前镜像恢复，两份哈希一致；随后建立实际父目录，逐项验证10份修复文件均解析到临时目录。最终9份涉及的既有服务源码均与镜像一致。未重启服务；后续操作均从修正的隔离目录执行。

## 真实HTTP与模型调用

用短时、仅内存的正式JWT请求当前服务，没有替换登录或业务依赖，没有改用户密码、角色或token_version。

| 用户 | 身份/租户 | /api/v1/llm | /api/v1/workstation/config |
| --- | --- | --- | --- |
| wangxinlei2 / 840 | 普通成员，69 | 200，18提供商、67模型 | 200，46个可选模型 |
| assa / 929 | 普通成员，69 | 200，18提供商、67模型 | 200，46个可选模型 |
| wangxinlei3 / 841 | 子租户管理员，69，非全局超管 | 200，18提供商、67模型 | 200，46个可选模型 |
| zgqTest1 / 199 | 子租户管理员，70，非全局超管 | 200，18提供商、67模型 | 200，46个可选模型 |

真实POST `/api/v1/workstation/chat/completions`：

- 普通成员840、租户69、模型936，SSE收到实际`OK`，会话`6e2b7ff3af6e4a50a264d835cafc02f6`。
- 用户841、租户69、模型933，SSE收到实际`OK`，会话`600849f3752c42e8958147ece949fe4e`。
- 模型935在子租户返回认证类失败，未计为通过；补充Root所有者上下文的供应商客户端直接诊断，同样得到`AuthenticationError / HTTP 401`，未修改凭据。一次Root浏览器HTTP探测因管理范围返回409，也未计为成功。子租户失败会话`356f7a0df3f84fc1b470e67221c77e15`保留证据。

这证明共享恢复后普通成员可选择并实际调用模型，不代表67个模型均通过供应商可用性验收，其中包含环境原有mock/假服务。

## 证据与发布边界

116主机`/tmp/bisheng-sharing-repair-20261118/`保留before-sharing、前后策略/配置摘要、两阶段apply、取消结果、最终覆盖、真实用户HTTP/调用及源码保持证据。没有复制config或模型密钥。运行镜像`sha256:941af66bb7cb9e2ec157d71226c280cc8e0e7b8a4040651b2dee9cb0c8494cb9`。本轮是实际授权恢复；代码合并推送不等于新镜像已部署，没有重启或重新部署116应用。
