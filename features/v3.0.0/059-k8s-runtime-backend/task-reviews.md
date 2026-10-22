# F059 L1 task reviews

## 基线

- 修改前 runtime-manager：437 passed、10 skipped（4.65s）；跳过项为既有需 Docker 的真实测试。本地回环端口在沙箱内受限，首次失败已按同一选择在授权的本地测试环境重跑，不能作为代码失败基线。
- 日志：`/private/tmp/f059-runtime-baseline.log`；本次尚未运行真实 K8s/平台验收。

## Task Review: T001

**任务**：K8s 配置及部署描述。**类型**：基础设施。
**文件**：`runtime_manager/k8s_config.py`、`runtime_manager/config.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 独立运行包，未读取平台配置/存储，无 backend 编排 SDK |
| 2 | 命名 | PASS | Config / KubernetesConfig 独立语义 |
| 3 | 序列化 | N/A | 没有 HTTP 输出 |
| 4 | 数据库 | N/A | 无数据库修改 |
| 5 | 前端 | N/A | 无前端修改 |
| 6 | 信息泄漏 | PASS | token 按文件读取，不存入 repr，错误不返回文件内容 |
| 7 | 设计同步 | PASS | design 4.1 登记配置实现但尚未接线 |

**验证**：默认Docker、K8s-v2门、namespace拒绝、descriptor范围/预算及token轮转断言通过；Ruff通过，逐文件arch-guard无违规。
**元数据验证**：文件范围 PASS；配对测试 N/A（配置基础设施）；依赖 PASS。
**结果**：PASS。

## Task Review: T006

**任务**：受限 K8s REST client 契约与失败用例。**类型**：测试。
**文件**：`tests/test_k8s_client.py`；覆盖 AC-03、AC-04、AC-13、AC-14、AC-48、AC-49、AC-52。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 测试子集 |
| 2 | 命名/AC | PASS | test_ 方法与完整AC；只定义合同和失败输入 |
| 3 | 序列化 | N/A | 测试子集 |
| 4 | 数据库 | N/A | 无数据库 |
| 5 | 前端 | N/A | 无前端 |
| 6 | 信息泄漏 | PASS | 测试假token，专门断言错误不泄漏响应详情 |
| 7 | 设计同步 | PASS | 与design 4.5、6.1的scope/UID/RV及410重列合同对应 |

**红阶段**：首轮12个配置用例通过、17个API用例因尚未实现k8s_client模块报错；补充有限重试、lease失效前取消和列表快照不一致场景。配对T007完成后必须绿阶段通过，当前不声称API可用。
**元数据验证**：文件范围 PASS；配对T007为后续实现；依赖T001 PASS。
**结果**：PASS。

## Task Review: T007

**任务**：受限 K8s REST client。**类型**：实现。
**文件**：`src/runtime-manager/runtime_manager/k8s_client.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 无平台存储依赖；只公开namespace资源和app日志；不把删除受理/404当停止事实。 |
| 2 | 命名/AC | PASS | 完整AC及明确输入输出 |
| 3 | 序列化 | PASS | 运行层固定资源文档；不涉及平台业务响应 |
| 4 | 数据库 | N/A | 无ORM/SQL修改 |
| 5 | 前端 | N/A | 无前端修改 |
| 6 | 信息泄漏 | PASS | 假凭据用于测试；错误不含响应/传输详情 |
| 7 | 设计同步 | PASS | design 4.1登记进展；D1–D8未变更 |

**验证**：32 passed；token轮转、UID/RV条件、重列及失败分类通过；逐文件arch-guard和Ruff通过。
**元数据验证**：文件范围 PASS；配对测试 PASS；依赖 PASS。
**结果**：PASS。

## Task Review: T008

**任务**：Pod/Service/PVC/Secret 模板：契约与失败用例。**类型**：测试。
**文件**：`src/runtime-manager/tests/test_k8s_templates.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 覆盖AC完整列示；用例断言可观察模板/拒绝结果，无平台写入。 |
| 2 | 命名/AC | PASS | 完整AC及明确输入输出 |
| 3 | 序列化 | N/A | 运行层固定资源文档；不涉及平台业务响应 |
| 4 | 数据库 | N/A | 无ORM/SQL修改 |
| 5 | 前端 | N/A | 无前端修改 |
| 6 | 信息泄漏 | PASS | 假凭据用于测试；错误不含响应/传输详情 |
| 7 | 设计同步 | PASS | design 4.1登记进展；D1–D8未变更 |

**验证**：红阶段29例因k8s_templates缺失报错；后续T009绿阶段29 passed。
**元数据验证**：文件范围 PASS；配对测试 N/A；依赖 PASS。
**结果**：PASS。

## Task Review: T009

**任务**：Pod/Service/PVC/Secret 模板。**类型**：实现。
**文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 输入为冻结PodPlan，无用户PodSpec；无SA token/hostPath/特权；helper命令将在后续T031接线。 |
| 2 | 命名/AC | PASS | 完整AC及明确输入输出 |
| 3 | 序列化 | PASS | 运行层固定资源文档；不涉及平台业务响应 |
| 4 | 数据库 | N/A | 无ORM/SQL修改 |
| 5 | 前端 | N/A | 无前端修改 |
| 6 | 信息泄漏 | PASS | 假凭据用于测试；错误不含响应/传输详情 |
| 7 | 设计同步 | PASS | design 4.1登记进展；D1–D8未变更 |

**验证**：29 passed；固定生产位置、临时期限、RO挂载、隔离卷、容器权限及ClusterIP通过；逐文件arch-guard和Ruff通过。
**元数据验证**：文件范围 PASS；配对测试 PASS；依赖 PASS。
**结果**：PASS。

## Task Review: T010

**任务**：停止证据三分类与同 UID 收尾（测试）。**文件**：`src/runtime-manager/tests/test_k8s_lifecycle.py`。

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 命名/AC | PASS | test_行为命名，完整列出9项AC |
| 前端/i18n | N/A | 运行层测试，无业务文案 |
| 元数据 | PASS | 文件范围明确；依赖T007已完成；配对T011 |

**红阶段**：22例因k8s_lifecycle尚未实现报错；Ruff通过。测试分别验证fresh API、UID、未调度/可信终态/unknown及先提交事实后移除finalizer。
**结果**：PASS。

## Task Review: T002

**任务**：资源账本、材料授权与控制器字段。**类型**：基础设施。
**文件**：`src/backend/bisheng/app_runtime/domain/models/runtime_kubernetes.py`、`src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 平台模型继承 ScopedRuntimeRecord，tenant_id索引/create_time/update_time、公钥而非私钥、JsonType与36位新UUID符合约束。旧RuntimeRecord ID不变。 |
| 2 | 命名/AC | PASS | 与任务领域及完整AC一致 |
| 3 | 序列化 | PASS | 继承SQLModelSerializable |
| 4 | 数据库 | PASS | 不在Service写SQL；迁移无数据读写 |
| 5 | 前端 | N/A | 无UI修改 |
| 6 | 信息泄漏 | PASS | 无真实私钥/宿主凭据；保留安全错误分类 |
| 7 | 设计同步 | PASS | design 4.1与6.2同步 |

**验证**：MySQL DDL编译及SQLite建表/legacy授权default/新旧传输唯一性smoke通过；账本正式用例随T014补齐。
**元数据验证**：文件范围 PASS；配对测试 N/A；依赖 PASS。
**结果**：PASS。

## Task Review: T003

**任务**：Schema 扩展与租户登记。**类型**：基础设施。
**文件**：`src/backend/bisheng/core/database/alembic/versions/f059_runtime_kubernetes.py`、`src/backend/bisheng/app_runtime/domain/models/__init__.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 真实旧head merge_vibe_f077_heads之后新增单head f059_runtime_kubernetes；revision仅DDL。models包已被tenant_filter预加载，因此在包__init__导入新表即可，不修改ContextVar。 |
| 2 | 命名/AC | PASS | 与任务领域及完整AC一致 |
| 3 | 序列化 | N/A | 无平台业务HTTP响应 |
| 4 | 数据库 | PASS | 不在Service写SQL；迁移无数据读写 |
| 5 | 前端 | N/A | 无UI修改 |
| 6 | 信息泄漏 | PASS | 无真实私钥/宿主凭据；保留安全错误分类 |
| 7 | 设计同步 | PASS | design 4.1与6.2同步 |

**验证**：alembic heads单head；test_alembic_single_head及既有ledger/artifact测试通过。DM8仍仅类型/约束静态检查，未连接真实DM8。
**元数据验证**：文件范围 PASS；配对测试 N/A；依赖 PASS。
**结果**：PASS。

## Task Review: T004

**任务**：密码依赖的可重复镜像供应。**类型**：基础设施。
**文件**：`src/runtime-manager/pyproject.toml`、`src/runtime-manager/uv.lock`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 新增cryptography==50.0.2，其他已锁定版本未变；官方Apache-2.0或BSD-3-Clause双许可。锁含Linux amd64/arm64轮子，镜像实构留到T063。 |
| 2 | 命名/AC | PASS | 与任务领域及完整AC一致 |
| 3 | 序列化 | N/A | 无平台业务HTTP响应 |
| 4 | 数据库 | N/A | 不在Service写SQL；迁移无数据读写 |
| 5 | 前端 | N/A | 无UI修改 |
| 6 | 信息泄漏 | PASS | 无真实私钥/宿主凭据；保留安全错误分类 |
| 7 | 设计同步 | PASS | design 4.1与6.2同步 |

**验证**：uv lock通过；临时独立目录安装50.0.2并执行Ed25519签名/验签/篡改拒绝通过；未修改共享backend环境。
**元数据验证**：文件范围 PASS；配对测试 N/A；依赖 PASS。
**结果**：PASS。

## Task Review: T011

**任务**：停止证据三分类与同 UID 收尾。**类型**：实现。
**文件**：`src/runtime-manager/runtime_manager/k8s_lifecycle.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 先fresh API核同UID/删除/status基线；先平台提交停止事实再CAS移除finalizer；unknown不释放。未接入业务执行器，不声称集群行为已验收。 |
| 2 | 命名/AC | PASS | 与任务领域及完整AC一致 |
| 3 | 序列化 | N/A | 无平台业务HTTP响应 |
| 4 | 数据库 | N/A | 不在Service写SQL；迁移无数据读写 |
| 5 | 前端 | N/A | 无UI修改 |
| 6 | 信息泄漏 | PASS | 无真实私钥/宿主凭据；保留安全错误分类 |
| 7 | 设计同步 | PASS | design 4.1与6.2同步 |

**验证**：配对T010已完成；22 passed；Ruff及逐文件arch-guard通过。
**元数据验证**：文件范围 PASS；配对测试 PASS；依赖 PASS。
**结果**：PASS。

## Task Review: T012

**任务**：独立准入和 status 来源约束：契约与失败用例。**类型**：测试。
**文件**：`src/runtime-manager/tests/test_k8s_admission.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 23项行为测试覆盖已批准模板、固定资源/凭据/权限、kubelet终态来源、收尾与无backend回调；完整AC列示，纯fake输入。 |
| 2 | 命名/AC | PASS | 与任务领域及完整AC一致 |
| 3 | 序列化 | N/A | 无平台业务HTTP响应 |
| 4 | 数据库 | N/A | 不在Service写SQL；迁移无数据读写 |
| 5 | 前端 | N/A | 无UI修改 |
| 6 | 信息泄漏 | PASS | 无真实私钥/宿主凭据；保留安全错误分类 |
| 7 | 设计同步 | PASS | design 4.1与6.2同步 |

**验证**：红阶段23 failed均因k8s_admission模块未实现；Ruff通过，依赖T009已完成。
**元数据验证**：文件范围 PASS；配对测试 N/A；依赖 PASS。
**结果**：PASS。

T004来源：[官方50.0.2变更记录](https://cryptography.io/en/latest/changelog/#v50-0-2)、[固定版本许可证](https://github.com/pyca/cryptography/blob/50.0.2/LICENSE)、[官方轮子安装说明](https://cryptography.io/en/latest/installation/)。直接PyPI TLS失败后用会话授权代理生成锁成功。

## Task Review: T014

**任务**：平台资源账本 Repository（测试）。**文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_repository.py`。

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 命名/AC | PASS | 完整AC；真实SQLite事务、无集群/外部依赖 |
| 前端/i18n | N/A | 无UI |
| 元数据 | PASS | 依赖T002/T003通过；配对T015；单文件范围 |

**红阶段**：14例均因runtime_kubernetes_repository尚未实现报错；Ruff通过。覆盖CAS/租约、UID不变、scope、未知写入者保留预占、cleanup计划不随操作终态消失。
**结果**：PASS。

## Task Review: T013

**任务**：独立准入和 status 来源约束（实现）。**文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 独立HTTPS准入进程无集群身份；资源计划由专用只读HMAC身份回读，status路径不回读、不写事实；CNI限制调用方是后续安装硬门。 |
| 2 | 命名 | PASS | 领域类名和可观察方法语义明确 |
| 3 | 序列化 | PASS | 固定AdmissionReview或ORM对象；平台API尚未接入 |
| 4 | 数据库 | N/A | 租户scope校验，非手写tenant WHERE；无SDK/外部存储 |
| 5 | 前端 | N/A | 无UI |
| 6 | 信息泄漏 | PASS | 安全错误；Secret计划仅摘要；不存workload私钥 |
| 7 | 设计同步 | PASS | design 4.1与6.2同步；D1–D8不变 |

**验证**：32 passed；增加HTTP入口、数量规范化、Secret摘要和只读身份轮转/重定向测试；修复初版HTTP入口422及quantity格式差异。 Ruff、逐文件arch-guard通过。
**元数据验证**：文件范围 PASS；配对测试 PASS；依赖 PASS。
**结果**：PASS。

## Task Review: T015

**任务**：平台资源账本 Repository（实现）。**文件**：`src/backend/bisheng/app_runtime/domain/repositories/runtime_kubernetes_repository.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | Repository继承既有事务UoW；租约行锁、资源UID/策略、生产writer互斥和容量释放均在数据库事务中；Service不写SQL。 |
| 2 | 命名 | PASS | 领域类名和可观察方法语义明确 |
| 3 | 序列化 | PASS | 固定AdmissionReview或ORM对象；平台API尚未接入 |
| 4 | 数据库 | PASS | 租户scope校验，非手写tenant WHERE；无SDK/外部存储 |
| 5 | 前端 | N/A | 无UI |
| 6 | 信息泄漏 | PASS | 安全错误；Secret计划仅摘要；不存workload私钥 |
| 7 | 设计同步 | PASS | design 4.1与6.2同步；D1–D8不变 |

**验证**：16 passed；新增容量释放后拒绝Pod创建及旧Pod不追认保护状态用例。SQLite证明业务控制，MySQL并发留到平台验收。 Ruff、逐文件arch-guard通过。
**元数据验证**：文件范围 PASS；配对测试 PASS；依赖 PASS。
**结果**：PASS。

阶段回归：runtime全套547 passed、10 skipped（后续新增5项准入边界用例单独通过）；backend既有账本/产物/单head共15 passed。尚未执行集群及真实平台验收。

## Task Review: T020

**任务**：material-v1编码与验签（测试）。**文件**：backend `test/app_runtime/test_runtime_material_protocol.py` 与 manager `tests/test_material_protocol.py`。

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 命名/AC | PASS | AC-15、AC-46、AC-47完整列举；固定414-byte/11行金样、真实Ed25519、重放与歧义拒绝 |
| 前端/i18n | N/A | 无UI |
| 元数据 | PASS | T004完成，两个独立部署包各自测试，不引入跨应用运行依赖 |

**红阶段**：两端模块均尚不存在；Ruff通过；完整红阶段日志见临时验证文件。
**结果**：PASS。

## Task Review: T021

**任务**：material-v1编码与验签（实现）。**文件**：backend `runtime_material_protocol.py` 与 manager `material_protocol.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 两端独立部署、不跨包import；只用cryptography，不自行实现密码算法 |
| 2 | 命名 | PASS | MaterialProof表示验签结果，不表示当前归属授权 |
| 3 | 序列化 | PASS | 固定11行wire、严格JSON/整数/UUID/头/query；API响应尚待接入 |
| 4 | 数据库 | N/A | 无SQL |
| 5 | 前端 | N/A | 无UI |
| 6 | 信息泄漏 | PASS | Proof不repr ticket；错误不含内容或私钥；nonce不可确认时拒绝 |
| 7 | 设计同步 | PASS | 精确保留design 6.2.1路径/414字节/hash；4.1同步阶段 |

**验证**：manager41 passed、backend40 passed；包含真实跨实现双向验签、原始头重复、JSON溢出/代理项、严格60秒边界和nonce失败。两实现当前内容一致且SHA核对通过。Ruff、逐文件arch-guard通过。
**元数据验证**：文件范围 PASS；配对T020 PASS；依赖T004 PASS。
**结果**：PASS。此结果不代表材料委托/票据/流式存储已接入。

T002/T021后续核对：材料 key_id 存储宽度修正为64，与已确认wire一致，并新增数据库列/最大长度验签守卫。T027注册文件改为main以保留固定根路径P；不是协议路径变更。

检查点：runtime 593 passed、10 skipped；backend 71 passed，随后新增key_id宽度守卫1 passed，uv frozen/offline锁检查通过。

## Task Review: T073

**任务**：F086字节计数器继承与迁移汇合。**类型**：基础设施。
**文件**：`f059_merge_f086_heads.py`、`test_runtime_model_contracts.py`；输入为F086本地来源提交`667546bb77`中的Vibe专有模型/迁移/静态测试。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 无SDK、外部接口或领域跨层调用 |
| 2 | 命名 | PASS | revision采用f059可读ID |
| 3 | 序列化 | N/A | 无HTTP |
| 4 | 数据库 | PASS | 显式merge两原parent；BIGINT只扩容不缩窄，无数据回填；历史authorization_id和待绑定uid的NULL是限定合同 |
| 5 | 前端 | N/A | 无UI |
| 6 | 信息泄漏 | PASS | 无敏感数据 |
| 7 | 设计同步 | PASS | design和prerequisites记录来源/约束及未交付边界 |

**验证**：27 passed（单head、模型类型/约束及K8s账本）；原F086同一来源21 passed。DM8使用通用编译器走shared helper的静态分支，未运行真实DM8。Ruff/逐文件arch-guard通过。
**元数据验证**：两个增量目标；依赖T003完成；模型/迁移基础设施无需配对业务测试。
**结果**：PASS。

T009/T013增量L1：应用凭据支持只给app容器的Secret引用，材料Secret不混用；backend审批投影仅接收/存放Secret内容与Pod环境值摘要。补测红阶段已记录，绿阶段模板+准入68 passed；禁止原始workload私钥进入backend，manager登记须先投影，准入对实际K8s请求独立投影比较。

最终本地检查点（源提交`ea3b1f6afb68da2b52ba4fd1fcf0bb5e060510ba`）：runtime **600 passed、10 skipped**；backend **82 passed**；公共启动补丁 **17 passed**。真实K8s/平台、镜像CI及新revision数据库升级均未执行。完整边界与本地日志见[validation.json](./validation.json)。公共发布线授权仍待用户答复。

## Task Review: T074

**任务**：发布线继承的迁移图汇合。**类型**：基础设施。
**文件**：`src/backend/bisheng/core/database/alembic/versions/f059_merge_release_heads.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 仅Alembic历史汇合，不引入领域依赖 |
| 2 | 命名 | PASS | f059明确可读revision |
| 3 | 序列化 | N/A | 无API |
| 4 | 数据库 | PASS | 实测三head的显式merge，无DDL/DML；保留原父链，降级只分叉 |
| 5 | 前端 | N/A | 无前端 |
| 6 | 信息泄漏 | PASS | 无凭据和运行数据 |
| 7 | 设计同步 | PASS | 维持现有单head和继承合同；当前进展回写，不改D1–D8 |

**验证**：合并提交98fbba032；`alembic heads`唯一f059_merge_release_heads；82项模型/协议/资源回归通过（`/private/tmp/f059-backend-inheritance-final.log`）；Ruff和逐文件arch-guard通过。
**元数据验证**：文件范围PASS；配对测试N/A（基础设施，使用既有单head门禁）；依赖T073 PASS。
**结果**：PASS。

## Task Review: T005

**任务**：F086公共修复继承核对。**类型**：基础设施。
**文件**：`prerequisites.md`、`prerequisites.json`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | 公共启动修复先发布线9d156f261c，再由F059普通合并98fbba032继承 |
| 2 | 命名 | PASS | 来源SHA、发布分支、继承提交明确 |
| 3 | 序列化 | PASS | JSON收据与Markdown一致 |
| 4 | 数据库 | PASS | BIGINT沿用单一来源；迁移单head；DM8仅静态 |
| 5 | 前端 | PASS | 继承适配保留审批与应用状态合同；98项交互通过，质量错误与发布线逐条比较无新增 |
| 6 | 信息泄漏 | PASS | 收据仅提交/验证事实，无集群或对象存储凭据 |
| 7 | 设计同步 | PASS | 记录已继承与尚未部署边界，不宣称E2E完成 |

**验证**：发布远端SHA一致；三个生产公共修复文件与发布线diff为空。公共修复17项通过，权限/审计197 passed、3 xfailed；运行层600 passed、10 skipped；资源/材料/模型82 passed。自动审批拒绝批量修改后采用逐文件验证。主工作区未改动。
**元数据验证**：文件范围PASS；配对测试N/A（继承核对）；依赖T074 PASS。
**结果**：PASS。

## Task Review: T016

**任务**：控制器/资源 Service 契约与失败用例。**类型**：测试。
**文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_service.py`；覆盖 AC-03、AC-07、AC-08、AC-13、AC-14、AC-48、AC-49、AC-52。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 测试子集 |
| 2 | 命名/AC | PASS | 完整AC编号；输入/输出与拒绝行为，不模拟核心账本事务 |
| 3 | 序列化 | N/A | 测试子集 |
| 4 | 数据库 | N/A | 复用真实SQLite资源账本fixture |
| 5 | 前端 | N/A | 无前端 |
| 6 | 信息泄漏 | PASS | 假镜像/UID；验证无明文Secret/环境值进入账本 |
| 7 | 设计同步 | N/A | 既有6.2控制合同 |

**红阶段**：27项因目标RuntimeKubernetesService尚未实现而报ModuleNotFoundError（`/private/tmp/f059-control-service-red.log`）；不是接口可用证据。Ruff与逐文件arch-guard通过。
**元数据验证**：文件范围PASS；配对T017后续实现；依赖T015 PASS。
**结果**：PASS。

## Task Review: T017

**任务**：控制器租约和资源事实Service。**类型**：实现。
**文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_kubernetes_service.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | Service→事务Repository；无FastAPI、集群SDK、MinIO或直接SQL |
| 2 | 命名 | PASS | 类/安全拒绝原因沿用运行层约定 |
| 3 | 序列化 | PASS | 既有内部运行协议的固定字段；只读准入不输出租户/holder/私钥 |
| 4 | 数据库 | PASS | 先验证可信node绑定，再tenant_execution_scope；Repository提交资源意图后才返回，不持SQL事务等待webhook |
| 5 | 前端 | N/A | 无新增前端 |
| 6 | 信息泄漏 | PASS | Secret仅摘要，env原值拒绝，错误只用稳定原因；投影深复制 |
| 7 | 设计同步 | PASS | design 4.3/6.2及修订历史已同步当前实现；HTTP及集群仍未交付 |

**验证**：27项首轮Service通过；新增边界测试先复现6项失败后修复；最终34项Service与16项真实SQLite账本共同通过（`/private/tmp/f059-control-service-final.log`），Ruff与逐文件arch-guard通过。操作终态仅保留同UID收尾，删除必须已记录stop；未知停止证据不释放。
**元数据验证**：文件范围PASS；配对T016已完成；依赖T015/T016 PASS。
**结果**：PASS。

## Task Review: T018

**任务**：内部控制API契约与失败用例。**类型**：测试。
**文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_api.py`；覆盖 AC-03、AC-04、AC-13、AC-14、AC-15、AC-48。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | N/A | 测试子集 |
| 2 | 命名/AC | PASS | 完整AC；真实HMAC和ASGI，核心Service/SQLite账本不mock |
| 3 | 序列化 | N/A | 测试子集 |
| 4 | 数据库 | N/A | 复用已验证事务fixture |
| 5 | 前端 | N/A | 无前端 |
| 6 | 信息泄漏 | PASS | 假服务密钥；未知nonce存储错误不应出现在HTTP响应 |
| 7 | 设计同步 | N/A | 既有控制/只读准入合同 |

**红阶段**：新端点模块未实现导致13 errors，生产聚合路由缺少目标路径导致1 failed（`/private/tmp/f059-control-api-red.log`）；非交付证据。Ruff与逐文件arch-guard通过。
**元数据验证**：文件范围PASS；依赖T017 PASS；配对T019后续实现。
**结果**：PASS。

## Task Review: T019

**任务**：内部控制API接入。**类型**：实现。
**文件**：`api/endpoints/runtime_kubernetes.py`、`api/router.py`。

| # | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS | Endpoint仅严格请求/鉴权/Service调用；生产聚合router已注册，无SQL或集群SDK |
| 2 | 命名 | PASS | controllers/resources/observations/admission plans对应既有合同 |
| 3 | 序列化 | PASS | 复用内部RuntimeRoute安全错误及扁平运行协议；不是前端业务响应 |
| 4 | 数据库 | PASS | 操作由Service/Repository执行；读取准入不修改资源记录 |
| 5 | 前端 | N/A | 无前端变更 |
| 6 | 信息泄漏 | PASS | HMAC/nonce沿用独立服务签名；混合角色配置拒绝；未知nonce存储失败关闭且不泄漏错误内容 |
| 7 | 设计同步 | PASS | design当前模块职责和修订记录已同步；材料根路径未改 |

**验证**：14项实际HMAC/ASGI+SQL API用例，加34项Service与16项账本合计64 passed；生产router路径亦由测试核对。Ruff与逐文件arch-guard通过。未执行真实K8s。
**元数据验证**：文件范围PASS；配对T018已完成；依赖T017/T018 PASS。
**结果**：PASS。
