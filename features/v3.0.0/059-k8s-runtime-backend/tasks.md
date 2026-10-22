# Tasks: F059 K8s 应用托管执行后端

**关联**：[spec.md](./spec.md) · [design.md](./design.md) · [任务评审](./tasks-review.md)

## SDD 状态

| 文档/阶段 | 状态 | 依据 |
| --- | --- | --- |
| Spec Discovery | ✅ 已确认 | 会话确认开源交付及 K8s 续办范围 |
| spec.md | ✅ 已评审、用户已确认 | 55 条有效 AC；规格确认不替代设计确认 |
| design.md | ✅ 已评审、用户已确认 | 用户明确回复“确认设计，进入任务拆解，继续推进 SDD 流程。”；确认正文摘要 b846e993909cda416502d33fdbf6b2174357068673840c2fc0f7d75fe9dc76a4 |
| tasks.md | ✅ 已拆解、评审通过 | tasks-review.txt 为 LGTM；251 项任务按依赖推进，无新增人审暂停点 |
| 实现/任务评审 | 🟡 实施中 | 246 / 251 完成；详见 task-reviews.md |
| E2E/L2审查 | 🟡 验收中/L2未开始 | 189 专用平台及四运行服务已部署；基线已读，真实隔离探测和业务验收进行中 |

## 开发模式

沿用已附加工作树 `codex/059-k8s-runtime@755d4456e5`。主 agent 与三个独立工作树并行开发，文件单一 owner、集成和189部署串行；各任务最多两个目标文件；测试先于对应实现，infra 配置/模型/锁/安装清单无需强行编写镜像实现的测试。独立验证已有批准的拒绝/故障合同。

任务编号用于追溯，不与 AC 编号混用。所有测试任务明确覆盖 AC，基础设施先于业务；新增 backend 测试位于 `src/backend/test/app_runtime/`。本次没有前端页面和 Celery 业务改动；若实际需新增 Worker，必须在任务登记 tenant_id headers→ContextVar 并遵守原 Owner。

### 基线及执行命令

- runtime 单测：在 `src/runtime-manager/` 使用共享 Python 3.11 环境运行 `python -m pytest -q tests`；修改前基线 437 passed / 10 skipped，详见 task-reviews。
- backend 定向测试：在 `src/backend/` 运行同一环境 `python -m pytest -q test/app_runtime/<task-file>`；依赖隔离按现有 conftest，数据库类另验真实平台。
- Ruff：各子项目对本任务文件运行 `ruff format`、`ruff check`；架构门 `bash scripts/arch-guard.sh <file>` 逐文件执行。
- 集群验收：仅专用 e2e-f059 资源，使用主机既有配置/安全环境，不把密码写入测试、任务或证据。

## 任务清单

### Wave 1

- [x] **T001** — K8s 配置及部署描述
  **类型**：基础设施
  **文件**：`src/runtime-manager/runtime_manager/k8s_config.py`、`src/runtime-manager/runtime_manager/config.py`
  **逻辑/验收**：新增 RTM_EXECUTOR 与 K8s namespace/cluster/descriptor/token/CA 配置；默认 Docker，K8s 强制 v2，非法形态/namespace/descriptor 拒绝；敏感 token 仅按文件读取，不输出。
  **覆盖 AC:** AC-01、AC-03、AC-13、AC-39
  **依赖:** 无

- [x] **T002** — 资源账本、材料授权与控制器字段
  **类型**：基础设施
  **文件**：`src/backend/bisheng/app_runtime/domain/models/runtime_kubernetes.py`、`src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py`
  **逻辑/验收**：按 design 6.2 定义资源 UID/停止证据、委托公钥/范围及 Node controller 租约字段、Transfer 授权字段；继承已有租户记录，使用 JsonType/跨库类型；新 36-char 标识仅用于新增路径，保留旧 ID。
  **覆盖 AC:** AC-13、AC-15、AC-47、AC-48
  **依赖:** 无

- [x] **T003** — Schema 扩展与租户登记
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/database/alembic/versions/f059_runtime_kubernetes.py`、`src/backend/bisheng/app_runtime/domain/models/__init__.py`
  **逻辑/验收**：在真实单 head 后追加扩展 DDL；在已注册的 models 包导入新表以进入租户发现。旧数据回填另列运维前置，不在 revision 做读写变换。降级前由独立运维前置检查停用 K8s/无新引用，未满足则拒绝；revision 只撤列等 DDL，不执行数据回填/清理；保留原 Docker 字段。
  **覆盖 AC:** AC-15、AC-39、AC-40、AC-48、AC-56
  **依赖:** T002

- [x] **T004** — 密码依赖的可重复镜像供应
  **类型**：基础设施
  **文件**：`src/runtime-manager/pyproject.toml`、`src/runtime-manager/uv.lock`
  **逻辑/验收**：manager/helper 显式锁定维护中的 cryptography 依赖；Apache/BSD 许可证检查；无现场下载、无自研密码算法，双架构安装与镜像供应由发行任务验收。
  **覆盖 AC:** AC-15、AC-39、AC-42、AC-54
  **依赖:** 无

- [x] **T073** — F086 字节计数器继承与迁移汇合
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/database/alembic/versions/f059_merge_f086_heads.py`、`src/backend/test/app_runtime/test_runtime_model_contracts.py`
  **逻辑/验收**：继承F086 667546bb77的Vibe专有BIGINT修复；模型在通用发布线上不存在。显式merge revision保留两个原parent，恢复单head；静态守卫明确历史授权NULL/待绑定UID NULL，其他约束不放宽；DM8仅静态。
  **覆盖 AC:** AC-15、AC-39、AC-48、AC-56
  **依赖:** T003

- [x] **T074** — 发布线继承的迁移图汇合
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/database/alembic/versions/f059_merge_release_heads.py`
  **逻辑/验收**：合并已授权发布线9d156f261c后，实际出现f059_merge_f086_heads、asr_rt_model_type、merge_skill_center_heads三条head；新增空merge revision保留三条原父链，不改表/数据、不重写历史；以已有单head门禁和模型/账本回归验证。降级只回到原分叉。
  **覆盖 AC:** AC-39、AC-48、AC-56
  **依赖:** T073

- [x] **T005** — F086 公共修复继承核对
  **类型**：基础设施
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/prerequisites.md`、`features/v3.0.0/059-k8s-runtime-backend/prerequisites.json`
  **逻辑/验收**：逐文件比对原 F086 的多租户启动、BIGINT 和测试修复与 release-line；记录已有同内容提交或发布线继承方式。禁止直接复制权限分叉；真实平台验收以前必须有来源 SHA/内容证据。
  **覆盖 AC:** AC-36、AC-55、AC-56
  **依赖:** T074

### Wave 2

- [x] **T006** — 受限 K8s REST client：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_client.py`
  **逻辑/验收**：以 httpx MockTransport 验 namespace 白名单、token 文件轮转、CA/TLS、固定 Core/Discovery 路由；UID/RV 删除条件、分页、410 relist、限时退避与取消；403/404 不当作停止证明；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-03、AC-04、AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T001
  **配对:** T007

- [x] **T007** — 受限 K8s REST client
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_client.py`
  **逻辑/验收**：以 httpx MockTransport 验 namespace 白名单、token 文件轮转、CA/TLS、固定 Core/Discovery 路由；UID/RV 删除条件、分页、410 relist、限时退避与取消；403/404 不当作停止证明；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-03、AC-04、AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T001、T006
  **配对:** T006

- [x] **T008** — Pod/Service/PVC/Secret 模板：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_templates.py`
  **逻辑/验收**：冻结 profile/架构、UID/GID、命令/资源/RO 挂载、单生产位置及按用途卷；不使用 hostPath/特权/SA token，不由应用提供 PodSpec。临时/预览 deadline 不延长，正式 Pod 无总寿命；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-05、AC-11、AC-12、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-24、AC-27、AC-33、AC-34、AC-43、AC-44、AC-54
  **依赖:** T001
  **配对:** T009

- [x] **T009** — Pod/Service/PVC/Secret 模板
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：冻结 profile/架构、UID/GID、命令/资源/RO 挂载、单生产位置及按用途卷；不使用 hostPath/特权/SA token，不由应用提供 PodSpec。临时/预览 deadline 不延长，正式 Pod 无总寿命；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-05、AC-11、AC-12、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-24、AC-27、AC-33、AC-34、AC-43、AC-44、AC-54
  **依赖:** T001、T008
  **配对:** T008

- [x] **T010** — 停止证据三分类与同 UID 收尾：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_lifecycle.py`
  **逻辑/验收**：覆盖未调度删除、init 从未启动、可信 kubelet 终态、NodeLost/404/同名异 UID、陈旧 cache、finalizer 重试；fresh API 证据入账后才释放，未知保留写入占用和唯一备份；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-08、AC-09、AC-11、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T007
  **配对:** T011

- [x] **T011** — 停止证据三分类与同 UID 收尾
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_lifecycle.py`
  **逻辑/验收**：覆盖未调度删除、init 从未启动、可信 kubelet 终态、NodeLost/404/同名异 UID、陈旧 cache、finalizer 重试；fresh API 证据入账后才释放，未知保留写入占用和唯一备份；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-08、AC-09、AC-11、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T007、T010
  **配对:** T010

- [x] **T012** — 独立准入和 status 来源约束：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：验证 AdmissionReview CREATE/UPDATE/DELETE 的批准模板、角色/范围/UID、过期操作收尾计划；status 规则无副作用/不调用 backend，仅绑定 kubelet 可引入终态。拒绝提权、越界 PVC/Secret、强删及基线变更；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-03、AC-13、AC-14、AC-15、AC-16、AC-21、AC-23、AC-30、AC-31、AC-32、AC-49
  **依赖:** T009
  **配对:** T013

- [x] **T013** — 独立准入和 status 来源约束
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：验证 AdmissionReview CREATE/UPDATE/DELETE 的批准模板、角色/范围/UID、过期操作收尾计划；status 规则无副作用/不调用 backend，仅绑定 kubelet 可引入终态。拒绝提权、越界 PVC/Secret、强删及基线变更；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-03、AC-13、AC-14、AC-15、AC-16、AC-21、AC-23、AC-30、AC-31、AC-32、AC-49
  **依赖:** T009、T012
  **配对:** T012

### Wave 3

- [x] **T014** — 平台资源账本 Repository：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_repository.py`
  **逻辑/验收**：以现有内存/SQLite fixture 验租户范围、资源意图幂等/UID绑定、CAS epoch、容量预占和 cleanup 生命周期；Repository 事务内完成并发控制，业务 Service 不拼 ORM SQL；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-08、AC-13、AC-15、AC-35、AC-48、AC-49、AC-52
  **依赖:** T002、T003
  **配对:** T015

- [x] **T015** — 平台资源账本 Repository
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/repositories/runtime_kubernetes_repository.py`
  **逻辑/验收**：以现有内存/SQLite fixture 验租户范围、资源意图幂等/UID绑定、CAS epoch、容量预占和 cleanup 生命周期；Repository 事务内完成并发控制，业务 Service 不拼 ORM SQL；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-08、AC-13、AC-15、AC-35、AC-48、AC-49、AC-52
  **依赖:** T002、T003、T014
  **配对:** T014

- [x] **T016** — 控制器租约和资源事实 Service：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_service.py`
  **逻辑/验收**：claim/renew holder/expected_epoch，验证固定执行域与有效操作、Service提交资源意图并结束SQL事务，manager随后调用 K8s；错 UID、过期控制器、越界、提前释放拒绝，终态后的只读收尾计划可续办；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-03、AC-07、AC-08、AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T015
  **配对:** T017

- [x] **T017** — 控制器租约和资源事实 Service
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_kubernetes_service.py`
  **逻辑/验收**：claim/renew holder/expected_epoch，验证固定执行域与有效操作、Service提交资源意图并结束SQL事务，manager随后调用 K8s；错 UID、过期控制器、越界、提前释放拒绝，终态后的只读收尾计划可续办；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-03、AC-07、AC-08、AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T015、T016
  **配对:** T016

- [x] **T018** — 内部控制 API 接入：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_api.py`
  **逻辑/验收**：注册 controllers/resources/observations/admission plans；沿用独立服务 HMAC/角色和序列化，API→Service→Repository；admission 只读，非角色/重放/跨域拒绝；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-03、AC-04、AC-13、AC-14、AC-15、AC-48
  **依赖:** T017
  **配对:** T019

- [x] **T019** — 内部控制 API 接入
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/api/endpoints/runtime_kubernetes.py`、`src/backend/bisheng/app_runtime/api/router.py`
  **逻辑/验收**：注册 controllers/resources/observations/admission plans；沿用独立服务 HMAC/角色和序列化，API→Service→Repository；admission 只读，非角色/重放/跨域拒绝；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-03、AC-04、AC-13、AC-14、AC-15、AC-48
  **依赖:** T017、T018
  **配对:** T018

- [x] **T020** — material-v1 编码与验签：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_protocol.py`、`src/runtime-manager/tests/test_material_protocol.py`
  **逻辑/验收**：对同一 414-byte 固定向量验 11 行编码与真实 Ed25519 互验；覆盖原始 body/ticket/method/path/offset、重复头/query、nonce 与时钟界限。双方实现固定 wire contract，不从 backend import manager；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-46、AC-47
  **依赖:** T004
  **配对:** T021

- [x] **T021** — material-v1 编码与验签
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_material_protocol.py`、`src/runtime-manager/runtime_manager/material_protocol.py`
  **逻辑/验收**：对同一 414-byte 固定向量验 11 行编码与真实 Ed25519 互验；覆盖原始 body/ticket/method/path/offset、重复头/query、nonce 与时钟界限。双方实现固定 wire contract，不从 backend import manager；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-46、AC-47
  **依赖:** T004、T020
  **配对:** T020

- [x] **T022** — 材料委托和续期 Service：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_service.py`
  **逻辑/验收**：从操作/部署/预览推导范围并绑定 UID/公钥；operation 终态失效，deployment-init 按当前 serving/候选冻结引用续取；旧 ticket 不独立续期，撤销/跨租户/错材料/Redis未知拒绝；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-27、AC-46、AC-47、AC-48
  **依赖:** T015、T021
  **配对:** T023

- [x] **T023** — 材料委托和续期 Service
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_material_service.py`、`src/backend/bisheng/app_runtime/domain/models/runtime_kubernetes.py`
  **逻辑/验收**：从操作/部署/预览推导范围并绑定 UID/公钥；operation 终态失效，deployment-init 按当前 serving/候选冻结引用续取；旧 ticket 不独立续期，撤销/跨租户/错材料/Redis未知拒绝；正式部署的expires_at允许NULL，含义为逐次检查当前归属；operation/预览分别保留操作/会话期限。仅调整未发布新表声明，无数据或已发布父链变更；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-27、AC-46、AC-47、AC-48
  **依赖:** T015、T021、T022
  **配对:** T022

- [x] **T024** — 范围化分块材料传输：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_transfers.py`
  **逻辑/验收**：复用对象存储和持久 offset；exchange 同范围轮换票据，单块 16MiB，重复同字节幂等/错摘要拒绝，分块下载与 finalize 内容/SQL确认；接口到期和响应丢失可查，无 MinIO 直链；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-26、AC-28、AC-29、AC-42、AC-46、AC-47、AC-51
  **依赖:** T023
  **配对:** T025

- [x] **T025** — 范围化分块材料传输
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_material_transfer_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_artifact_service.py`
  **逻辑/验收**：复用对象存储和持久 offset；exchange 同范围轮换票据，单块 16MiB，重复同字节幂等/错摘要拒绝，分块下载与 finalize 内容/SQL确认；接口到期和响应丢失可查，无 MinIO 直链；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-26、AC-28、AC-29、AC-42、AC-46、AC-47、AC-51
  **依赖:** T023、T024
  **配对:** T024

- [x] **T075** — 材料根路径多租户中间件：合同与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_middleware.py`
  **逻辑/验收**：固定材料根路径独立于浏览器JWT，租户由公钥授权决定；精确前缀免浏览器租户检查，相似路径不豁免；真实CustomMiddleware验证；测试不加入生产实现。
  **覆盖 AC:** AC-15、AC-47、AC-48
  **依赖:** T025
  **配对:** T076

- [x] **T076** — 材料根路径多租户中间件接线
  **类型**：实现
  **文件**：`src/backend/bisheng/utils/http_middleware.py`
  **逻辑/验收**：仅新增材料根路径到可信内部请求前缀，并排除浏览器凭据解析；授权Service逐次清除ambient bypass/admin后验证租户/UID，不扩大其他路径。保持平台已有JWT/DSH语义；配对测试及L1后完成。
  **覆盖 AC:** AC-15、AC-47、AC-48
  **依赖:** T025、T075
  **配对:** T075

- [x] **T026** — 材料 workload HTTP API：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_api.py`
  **逻辑/验收**：按 design 6.2.1 完整方法/头/响应/错误注册 exchange、status、content、finalize；使用 workload 身份依赖，拒绝 manager/app/OBO 身份互换，流式阶段重新检查期限/撤销；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-28、AC-46、AC-47、AC-51
  **依赖:** T025、T019、T076
  **配对:** T027

- [x] **T027** — 材料 workload HTTP API
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/api/endpoints/runtime_material.py`、`src/backend/bisheng/main.py`
  **逻辑/验收**：material-v1固定P直接注册为main根路由，不继承/api/v1前缀；按 design 6.2.1 完整方法/头/响应/错误注册 exchange、status、content、finalize；使用 workload 身份依赖，拒绝 manager/app/OBO 身份互换，流式阶段重新检查期限/撤销；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-28、AC-46、AC-47、AC-51
  **依赖:** T025、T019、T026
  **配对:** T026

### Wave 4

- [x] **T028** — 材料 client 与平台控制 client：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_material_client.py`
  **逻辑/验收**：下载/上传按 frozen SHA、受限票据及新 nonce 签名；部分块丢弃、响应丢失查 offset、重交换不延长操作；控制 client 支持资源、租约、材料绑定接口且不记录私钥；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-07、AC-15、AC-26、AC-28、AC-42、AC-44、AC-46、AC-47、AC-52
  **依赖:** T007、T027
  **配对:** T029

- [x] **T029** — 材料 client 与平台控制 client
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/material_client.py`、`src/runtime-manager/runtime_manager/platform_client.py`
  **逻辑/验收**：下载/上传按 frozen SHA、受限票据及新 nonce 签名；部分块丢弃、响应丢失查 offset、重交换不延长操作；控制 client 支持资源、租约、材料绑定接口且不记录私钥；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-07、AC-15、AC-26、AC-28、AC-42、AC-44、AC-46、AC-47、AC-52
  **依赖:** T007、T027、T028
  **配对:** T028

- [x] **T077** — 准备操作依赖缓存选择：合同与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_dependency_materials.py`
  **逻辑/验收**：缓存选择须持久化当前准备操作；同应用/profile/platform/verified、输入键不可变；材料授权从真实选择/SQL计划推导，伪造引用不扩权；测试不混入实现。
  **覆盖 AC:** AC-15、AC-25、AC-28、AC-29、AC-46、AC-47
  **依赖:** T023、T029
  **配对:** T078

- [x] **T078** — 依赖缓存选择与材料授权接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_profile_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_material_service.py`
  **逻辑/验收**：resolve/confirm在操作行锁下持久选中结果，授权复查同范围SQL计划和材料；禁止任意引用扩大授权、终态写入或更换输入键。保持旧Docker内容确认合同。配对测试及L1后完成。
  **覆盖 AC:** AC-15、AC-25、AC-28、AC-29、AC-46、AC-47
  **依赖:** T023、T029、T077
  **配对:** T077

- [x] **T030** — 受信材料 helper 与离线环境物化：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_helper.py`
  **逻辑/验收**：material-fetch 只安全取冻结材料；无凭据 environment 阶段在固定 /opt/venv/Node/static 路径物化；prepare 分下载/安装编译/上传独立 Pod，代码不会借传输身份执行；环境键包含 profile/ABI/架构/锁/安装输入；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-16、AC-24、AC-25、AC-26、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T009、T029、T078
  **配对:** T031

- [x] **T031** — 受信材料 helper 与离线环境物化
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_helper.py`、`src/runtime-manager/runtime_manager/k8s_prepare.py`
  **逻辑/验收**：material-fetch 只安全取冻结材料；无凭据 environment 阶段在固定 /opt/venv/Node/static 路径物化；prepare 分下载/安装编译/上传独立 Pod，代码不会借传输身份执行；环境键包含 profile/ABI/架构/锁/安装输入；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-16、AC-24、AC-25、AC-26、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T009、T029、T030
  **配对:** T030

- [x] **T079** — K8s节点报告和控制事实：合同与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_coordination.py`
  **逻辑/验收**：心跳持久执行形态/探测，失败阻断新建但可清理；事实必须当前租约/代次，停止声明须资源证据，ready须已绑定Service/Pod；未知异常不被全局错误处理泄漏。测试只定义合同。
  **覆盖 AC:** AC-03、AC-07、AC-08、AC-13、AC-14、AC-30、AC-31、AC-48、AC-49、AC-52
  **依赖:** T019、T031
  **配对:** T080

- [x] **T080** — K8s节点与控制事实接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`、`src/backend/bisheng/app_runtime/api/endpoints/runtime_delivery.py`
  **逻辑/验收**：扩展兼容心跳/node plan、K8s控制器事实闸口、停止与ready事实校验；保留Docker合同。探测失效阻断新建，清理不被同一状态锁死；内部未知异常安全503。配对测试和L1后完成。
  **覆盖 AC:** AC-03、AC-07、AC-08、AC-13、AC-14、AC-30、AC-31、AC-48、AC-49、AC-52
  **依赖:** T019、T031、T079
  **配对:** T079

- [x] **T032** — K8s 执行能力与资源操作：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`
  **逻辑/验收**：实现 prepare/launch/observe/request_stop/confirm_stopped/cleanup/logs/data 能力，只有 adapter 拼 Core API；固定名称/UID 账本、Service就绪端点、bounded wait、平台资源事实及数据/维护前后 stop 闸口；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-04、AC-05、AC-07、AC-08、AC-09、AC-11、AC-18、AC-33、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T031、T011、T019、T080
  **配对:** T033

- [x] **T033** — K8s 执行能力与资源操作
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`、`src/runtime-manager/runtime_manager/executors/protocol.py`
  **逻辑/验收**：实现 prepare/launch/observe/request_stop/confirm_stopped/cleanup/logs/data 能力，只有 adapter 拼 Core API；固定名称/UID 账本、Service就绪端点、bounded wait、平台资源事实及数据/维护前后 stop 闸口；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-04、AC-05、AC-07、AC-08、AC-09、AC-11、AC-18、AC-33、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T031、T011、T019、T032
  **配对:** T032

- [x] **T034** — Docker 能力适配且保留旧合同：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_docker_executor.py`
  **逻辑/验收**：抽离既有 Docker/本机路径算法到适配器，通用 checkpoint/facts/操作归属保留；基于现有三路径/生命周期测试比较原输入输出，不用假 K8s API 模拟 Docker；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-01、AC-04、AC-10、AC-36、AC-37、AC-56
  **依赖:** T033
  **配对:** T035

- [x] **T035** — Docker 能力适配且保留旧合同
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/docker.py`、`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：抽离既有 Docker/本机路径算法到适配器，通用 checkpoint/facts/操作归属保留；基于现有三路径/生命周期测试比较原输入输出，不用假 K8s API 模拟 Docker；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-01、AC-04、AC-10、AC-36、AC-37、AC-56
  **依赖:** T033、T034
  **配对:** T034

- [x] **T036** — 通用操作状态机和 composition root：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_executor_selection.py`
  **逻辑/验收**：按配置选唯一执行器并共用操作状态/事实编排；K8s 不初始化 Docker 或 v1本地循环；不接受调用方执行路径/PodSpec，重复唤醒、manager关闭/恢复、待上线前后容量语义保持；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-01、AC-02、AC-04、AC-05、AC-07、AC-08、AC-09、AC-36、AC-37、AC-39、AC-48、AC-56
  **依赖:** T035
  **配对:** T037

- [x] **T037** — 通用操作状态机和 composition root
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/operations.py`、`src/runtime-manager/runtime_manager/api/operations.py`
  **逻辑/验收**：按配置选唯一执行器并共用操作状态/事实编排；K8s 不初始化 Docker 或 v1本地循环；不接受调用方执行路径/PodSpec，重复唤醒、manager关闭/恢复、待上线前后容量语义保持；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-01、AC-02、AC-04、AC-05、AC-07、AC-08、AC-09、AC-36、AC-37、AC-39、AC-48、AC-56
  **依赖:** T035、T036
  **配对:** T036

- [x] **T038** — 状态、日志和能力 API：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_observe.py`
  **逻辑/验收**：保留业务 API 范围、since/tail/脱敏，仅读取 app/previous 和删除前有界诊断；新增认证 capabilities，前置 blocked 原因清楚；健康存活不冒充已就绪，K8s禁用v1编排注册；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-02、AC-07、AC-10、AC-30、AC-31、AC-32、AC-36、AC-37、AC-40、AC-53
  **依赖:** T037
  **配对:** T039

- [x] **T039** — 状态、日志和能力 API
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/api/platform_observe.py`、`src/runtime-manager/runtime_manager/main.py`
  **逻辑/验收**：保留业务 API 范围、since/tail/脱敏，仅读取 app/previous 和删除前有界诊断；新增认证 capabilities，前置 blocked 原因清楚；健康存活不冒充已就绪，K8s禁用v1编排注册；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-02、AC-07、AC-10、AC-30、AC-31、AC-32、AC-36、AC-37、AC-40、AC-53
  **依赖:** T037、T038
  **配对:** T038

### Wave 5

- [x] **T040** — 数据 helper 动作票据与 journal：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_data_helper.py`
  **逻辑/验收**：只持 backend 公钥；5秒受理票据绑定 app/UID/action/body/nonce，有界60秒执行和串行；platform目录持久started/done，未知不重做；owner数据白名单SQL和流式导出，结果查询新只读ID指向原ID；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-16、AC-33、AC-34、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T021、T009
  **配对:** T041

- [x] **T041** — 数据 helper 动作票据与 journal
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_data_helper.py`、`src/runtime-manager/runtime_manager/data_grant.py`
  **逻辑/验收**：只持 backend 公钥；5秒受理票据绑定 app/UID/action/body/nonce，有界60秒执行和串行；platform目录持久started/done，未知不重做；owner数据白名单SQL和流式导出，结果查询新只读ID指向原ID；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-16、AC-33、AC-34、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T021、T009、T040
  **配对:** T040

- [x] **T081** — 数据会话互斥与开销预占合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_repository.py`
  **逻辑/验收**：真实SQL验证data_operation_id不改变serving代次/归属，数据会话与生命周期提交/claim互斥；期限到期或未知结果不释放，只有终态且清理完成释放；K8s正式Pod的128MiB/25m sidecar计入预占，Docker原额度不变。先验证SQL原子性，再接Service；不加入实现。
  **覆盖 AC:** AC-04、AC-05、AC-33、AC-34、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T041、T080
  **配对:** T082

- [x] **T082** — 数据会话账本及部署资源开销接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`
  **逻辑/验收**：Repository在node/assignment锁下登记内部数据操作及helper预占，不改active_operation_id/generation；生命周期新提交及claim检查未清理data归属，数据claim校验原范围；unknown保留互斥。终态且清理确认后释放。OperationService按K8s实际sidecar计入正式Pod资源、保留Docker预算；不做集群I/O。
  **覆盖 AC:** AC-04、AC-05、AC-33、AC-34、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T041、T080、T081
  **配对:** T081

- [x] **T042** — owner 数据会话业务协调：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_sessions.py`
  **逻辑/验收**：在原权限/确认/审计后创建内部 kind=data；不改 serving代次/App态，数据/迁移/停用/部署互斥；事务先提交再唤醒，在线复用helper，停用冷启动也计入60秒，超时不等于cleanup；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-35、AC-36、AC-37、AC-43、AC-48、AC-49、AC-50
  **依赖:** T017、T041、T082
  **配对:** T043

- [x] **T043** — owner 数据会话业务协调
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_session_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_data_service.py`
  **逻辑/验收**：在原权限/确认/审计后创建内部 kind=data；不改 serving代次/App态，数据/迁移/停用/部署互斥；事务先提交再唤醒，在线复用helper，停用冷启动也计入60秒，超时不等于cleanup；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-35、AC-36、AC-37、AC-43、AC-48、AC-49、AC-50
  **依赖:** T017、T041、T042
  **配对:** T042

- [x] **T044** — K8s 在线及停用数据执行：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_data_executor.py`
  **逻辑/验收**：在线同Pod访问；停用仅在旧UID stopped且空生产位置启动 purpose=data，保留PVC/停用态，不创建业务Service；数据忙/未知拒绝，stop确认后释放预占与互斥，manager不签owner票据；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-11、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T043、T033
  **配对:** T045

- [x] **T045** — K8s 在线及停用数据执行
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_data_executor.py`、`src/runtime-manager/runtime_manager/api/platform_data.py`
  **逻辑/验收**：在线同Pod访问；停用仅在旧UID stopped且空生产位置启动 purpose=data，保留PVC/停用态，不创建业务Service；数据忙/未知拒绝，stop确认后释放预占与互斥，manager不签owner票据；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-11、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T043、T033、T044
  **配对:** T044

- [x] **T085** — 顺序维护资源 DDL
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/database/alembic/versions/f059_resource_phases.py`
  **逻辑/验收**：实际单head f059_merge_release_heads之后追加DDL，移除operation/kind/name唯一约束；保留资源ref主键及真实UID唯一约束。降级须运维先确认历史无重名，revision不删历史、不读写业务数据；MySQL/DM8条件DDL及单head静态验证。
  **覆盖 AC:** AC-15、AC-35、AC-48、AC-49、AC-56
  **依赖:** T074

- [x] **T083** — 固定生产名称的分阶段资源合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_phases.py`
  **逻辑/验收**：真实SQL验证同一操作backup/migrate/serve可顺序登记不同ref/UID，前一Pod停止并清理完成后才允许下一Pod；原ref幂等不改冻结模板，旧UID历史保留，未停止/未清理拒绝，不以租约到期放行。
  **覆盖 AC:** AC-08、AC-15、AC-33、AC-35、AC-48、AC-49、AC-50
  **依赖:** T085、T045
  **配对:** T084

- [x] **T084** — 顺序资源意图与历史保留
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/models/runtime_kubernetes.py`、`src/backend/bisheng/app_runtime/domain/repositories/runtime_kubernetes_repository.py`
  **逻辑/验收**：按资源ref幂等登记；固定生产名的新ref须先确认旧Pod stopped及cleanup complete，保留所有UID历史，非生产重名拒绝。移除模型旧唯一intent约束，保留UID唯一；事务内检查，不在锁内调用集群API。
  **覆盖 AC:** AC-08、AC-15、AC-33、AC-35、AC-48、AC-49、AC-50
  **依赖:** T085、T083
  **配对:** T083

- [x] **T086** — 材料分块读取的定长范围合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_ranges.py`、`src/backend/test/app_runtime/test_runtime_material_transfers.py`
  **逻辑/验收**：下载后段仅从对象存储对应offset读取length字节；验证关闭/释放连接、短读拒绝、撤权与原有分块摘要合同，不以小对象整读掩盖大对象二次复杂度。
  **覆盖 AC:** AC-26、AC-28、AC-29、AC-46、AC-47、AC-51
  **依赖:** T025
  **配对:** T087

- [x] **T087** — 对象存储 Range 流式下载接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/repositories/runtime_object_store.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_material_transfer_service.py`
  **逻辑/验收**：使用MinIO get_object offset/length和定长流，不从头跳过；backend继续独占存储凭据，连接finally释放，原授权/offset/完整性合同保持。
  **覆盖 AC:** AC-26、AC-28、AC-29、AC-46、AC-47、AC-51
  **依赖:** T025、T086
  **配对:** T086

- [x] **T046** — K8s SQLite 备份迁移恢复：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_appdb.py`
  **逻辑/验收**：停整个生产Pod后维护独占卷；复用appdb plan_digest/SQLite原子迁移journal，backup/integrity/fsync，平台内容与关联确认后才DDL；保护当前数据后恢复，失败保留maintenance和data_may_have_changed，不自动数据回滚；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-33、AC-34、AC-35、AC-46、AC-49、AC-50、AC-51、AC-52
  **依赖:** T045、T029、T084、T087
  **配对:** T047

- [x] **T047** — K8s SQLite 备份迁移恢复
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_appdb.py`、`src/runtime-manager/runtime_manager/k8s_data_helper.py`
  **逻辑/验收**：停整个生产Pod后维护独占卷；复用appdb plan_digest/SQLite原子迁移journal，backup/integrity/fsync，平台内容与关联确认后才DDL；保护当前数据后恢复，失败保留maintenance和data_may_have_changed，不自动数据回滚；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-33、AC-34、AC-35、AC-46、AC-49、AC-50、AC-51、AC-52
  **依赖:** T045、T029、T046
  **配对:** T046

- [x] **T048** — backend 数据动作签发及路由：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_grants.py`
  **逻辑/验收**：原业务Service重新核验actor及当前data操作/UID后本地签发；不向manager提供通用签发API。data操作和查询结果授权原地失效，非owner、重放、错UID拒绝；管理身份不能自签；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48
  **依赖:** T043、T047
  **配对:** T049

- [x] **T049** — backend 数据动作签发及路由
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_grant_service.py`、`src/backend/bisheng/app_runtime/api/endpoints/runtime_kubernetes.py`
  **逻辑/验收**：原业务Service重新核验actor及当前data操作/UID后本地签发；不向manager提供通用签发API。data操作和查询结果授权原地失效，非owner、重放、错UID拒绝；管理身份不能自签；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48
  **依赖:** T043、T047、T048
  **配对:** T048

- [x] **T088** — K8s 兼容源码的 profile 冻结合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_k8s_delivery_coordinator.py`
  **逻辑/验收**：prepare真实协调方法在K8s source-image解析并冻结运行/preparer profile和离线材料；Docker旧源码构建不改，完整镜像不要求bundle profile，不从manager临时配置猜基础镜像。
  **覆盖 AC:** AC-01、AC-24、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T049
  **配对:** T089

- [x] **T089** — K8s 兼容源码 profile 协调接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py`
  **逻辑/验收**：仅K8s source-image复用现有全局profile解析、冻结架构与材料归属；保持Docker和完整镜像原语义。环境注入/审批仍由原业务Owner负责。
  **覆盖 AC:** AC-01、AC-24、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T049、T088
  **配对:** T088

- [x] **T090** — 数据恢复查询及导出流合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_recovery.py`
  **逻辑/验收**：未知写结果只以新只读会话查询原request，不重做写操作；owner重检、原会话清理闸口与原参数摘要保持。HTTP分块导出落短缓存，验证长度/摘要/截止期并清理失败文件，Docker bytes兼容。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T049
  **配对:** T091

- [x] **T091** — 数据恢复协调与导出短缓存
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_session_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_data_service.py`
  **逻辑/验收**：原数据Service先验证owner；恢复原操作结果创建新result只读会话和新request_id，不重放写。K8s导出经有界分块落缓存供响应，错误/取消回收，审计按文件大小记录；不让backend访问SQLite。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T049、T090
  **配对:** T090

- [x] **T092** — 结果查询与文件响应业务入口合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_recovery_api.py`
  **逻辑/验收**：登录owner通过data/operations/{operation_id}/result读取原结果，非owner拒绝；CSV FileResponse保留文件名/类型/鉴权错误信封，下载后缓存回收；原Docker字节响应不变。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T091
  **配对:** T093

- [x] **T093** — 数据恢复和流式导出 API 接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/api/endpoints/apps.py`
  **逻辑/验收**：只委托AppDataService，不在Endpoint执行账本/存储逻辑；公开业务读取结果用统一信封，CSV短缓存FileResponse带BackgroundTask回收；保持原bytes路径。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T091、T092
  **配对:** T092

### Wave 6

- [x] **T050** — 三种交付模式的 K8s 准备链：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_delivery.py`
  **逻辑/验收**：Python3.11/Node20/static bundle预检、完整镜像直启、显式source-image准备；依赖材料命中与失效、新增依赖缺包/补包、安全解包；任务阶段独立身份/卷/限额/并发，启动失败不产生审批；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-08、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T033、T047、T089
  **配对:** T051

- [x] **T051** — 三种交付模式的 K8s 准备链
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_prepare.py`、`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：Python3.11/Node20/static bundle预检、完整镜像直启、显式source-image准备；依赖材料命中与失效、新增依赖缺包/补包、安全解包；任务阶段独立身份/卷/限额/并发，启动失败不产生审批；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-08、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T033、T047、T050
  **配对:** T050

- [x] **T052** — 无守护进程的受限 OCI 组装：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_oci_assembler.py`
  **逻辑/验收**：固定布局追加冻结基础镜像并设置既有启动语义；不执行RUN/Dockerfile，拒绝逃逸、设备/setuid/whiteout/外部硬链；仓库身份仅受信组装器使用，缺推送仓库仅阻断source-image；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-16、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T051
  **配对:** T053

- [x] **T053** — 无守护进程的受限 OCI 组装
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/oci_assembler.py`、`src/runtime-manager/Dockerfile.assembler`
  **逻辑/验收**：固定布局追加冻结基础镜像并设置既有启动语义；不执行RUN/Dockerfile，拒绝逃逸、设备/setuid/whiteout/外部硬链；仓库身份仅受信组装器使用，缺推送仓库仅阻断source-image；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-16、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T051、T052
  **配对:** T052


- [x] **T096** — owner 删除与安全清理合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_appdb.py`、`src/backend/test/app_runtime/test_runtime_kubernetes_purge.py`
  **逻辑/验收**：先验证purge缺失红阶段；错误owner意图/跨应用卷拒绝，停止和结果事实先于PVC删除，不跟随链接，重启不重复创建。
  **覆盖 AC:** AC-35、AC-48、AC-49、AC-50、AC-52
  **依赖:** T053
  **配对:** T097

- [x] **T097** — backend purge 范围和删除授权
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_kubernetes_service.py`、`src/backend/bisheng/app_runtime/domain/repositories/runtime_kubernetes_repository.py`
  **逻辑/验收**：只接受显式destroy+purge_volume的固定生产位置；由执行事实证明purge完成及全部writer停止清理后，授予原PVC条件删除。
  **覆盖 AC:** AC-35、AC-48、AC-49、AC-50、AC-52
  **依赖:** T053、T096
  **配对:** T096

- [x] **T098** — 受信 helper 清理与持久重入
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_appdb.py`、`src/runtime-manager/runtime_manager/k8s_data_helper.py`
  **逻辑/验收**：不持应用/材料身份，擦除business及受保护备份，不跟随链接；维护journal和SQL事实避免已完成purge重复执行。
  **覆盖 AC:** AC-35、AC-48、AC-49、AC-50、AC-52
  **依赖:** T096、T097
  **配对:** T096

- [x] **T099** — 生产 purge 模板及状态机接线
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`、`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：purge共用固定生产位置；恢复destroy不停止自己的当前清理Pod；生产purpose集合同步；取消重复egress注入。
  **覆盖 AC:** AC-04、AC-35、AC-48、AC-49、AC-50、AC-52
  **依赖:** T098
  **配对:** T096

- [x] **T100** — 执行器条件回收生产卷
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`、`src/runtime-manager/runtime_manager/k8s_data_executor.py`
  **逻辑/验收**：缺少应用profile的destroy只使用固定helper；PVC删除用UID/RV，确认缺失才提交cleanup；未知拒绝，不授予平台存储凭据。
  **覆盖 AC:** AC-04、AC-35、AC-48、AC-49、AC-50、AC-52
  **依赖:** T099
  **配对:** T096

- [x] **T101** — 受限 canary 启动合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_canary.py`
  **逻辑/验收**：安装计划仅preflight名称/固定镜像命令/短期范围；拒绝应用源码、生产PVC、Secret、无限授权和未绑定UID更新。
  **覆盖 AC:** AC-13、AC-14、AC-16、AC-21、AC-23、AC-49
  **依赖:** T013、T053
  **配对:** T102

- [x] **T102** — 只读 canary 准入和网络探测
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`、`src/runtime-manager/runtime_manager/k8s_capabilities.py`
  **逻辑/验收**：只读installer CM提供至多一小时预检计划，其它资源仍backend；可信idle监听、TCP/UDP DNS真探测；报告24h由外部installer每6h刷新。
  **覆盖 AC:** AC-13、AC-14、AC-16、AC-21、AC-23、AC-49
  **依赖:** T101
  **配对:** T101

- [x] **T054** — 隔离和安装前置的实际能力探测：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_capabilities.py`
  **逻辑/验收**：分项验证namespace预算、PSA/准入、status认证、存储锁/fsync、精确CRI镜像、网络允许/拒绝、材料/能力接口；必需隔离失败/未知拒绝，沙箱仅回退满足基线档；无SC但预置卷可用；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-12、AC-13、AC-16、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-42、AC-54
  **依赖:** T013、T039、T053
  **配对:** T055

- [x] **T055** — 隔离和安装前置的实际能力探测
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_capabilities.py`、`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：分项验证namespace预算、PSA/准入、status认证、存储锁/fsync、精确CRI镜像、网络允许/拒绝、材料/能力接口；必需隔离失败/未知拒绝，沙箱仅回退满足基线档；无SC但预置卷可用；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-12、AC-13、AC-16、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-42、AC-54
  **依赖:** T013、T039、T053、T054
  **配对:** T054

- [x] **T094** — 活跃材料代理候选查询合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_policy_candidates.py`
  **逻辑/验收**：真实SQL按node过滤已绑定、未停止/未清理、未撤销且未到期材料授权；停止/历史/其它节点不进入每秒投影，保留原历史记录而不全表循环逐条重验。
  **覆盖 AC:** AC-15、AC-23、AC-46、AC-47、AC-48、AC-53
  **依赖:** T055
  **配对:** T095

- [x] **T095** — 活跃材料候选 Repository 查询
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`
  **逻辑/验收**：Repository联查材料与资源记录提供material_policy_candidates(node_id,now)，不在Service写SQL；跨租户仅供已验证egress角色的node范围投影，最多10000活动候选、超限拒绝，不删除历史。
  **覆盖 AC:** AC-15、AC-23、AC-46、AC-47、AC-48、AC-53
  **依赖:** T055、T094
  **配对:** T094

- [x] **T056** — 材料用途的出站投影：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_egress.py`
  **逻辑/验收**：material代理身份由当前材料授权投影，独立于完成的prepare；只放行后台材料TLS端点和范围，撤销5秒上界，业务凭据不冒用；入口路由继续backendSQL投影不依赖manager；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-07、AC-12、AC-15、AC-21、AC-23、AC-46、AC-47、AC-53
  **依赖:** T023、T055、T095
  **配对:** T057

- [x] **T057** — 材料用途的出站投影
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_material_policy_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`
  **逻辑/验收**：material代理身份由当前材料授权投影，独立于完成的prepare；只放行后台材料TLS端点和范围，撤销5秒上界，业务凭据不冒用；入口路由继续backendSQL投影不依赖manager；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-07、AC-12、AC-15、AC-21、AC-23、AC-46、AC-47、AC-53
  **依赖:** T023、T055、T056
  **配对:** T056

### Wave 7

- [x] **T058** — Chart 入口与 values schema
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/Chart.yaml`、`deploy/kubernetes/app-runtime/values.yaml`
  **逻辑/验收**：按design固定platform/services/execution/storage/network/admission/images/offline分组，所有镜像精确引用、禁默认公网兜底与自动平台核心部署。
  **覆盖 AC:** AC-39、AC-42、AC-54
  **依赖:** T057

- [x] **T059** — 部署参数及共享入口校验
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/values.schema.json`、`deploy/kubernetes/app-runtime/templates/services.yaml`
  **逻辑/验收**：校验必需字段与形态，私网共享entry/control由安装者供应，禁止按应用外放端口；控制端点ACL及HMAC，外部backend可达性独立验证。
  **覆盖 AC:** AC-12、AC-31、AC-39
  **依赖:** T058

- [x] **T060** — RBAC 与准入安装模板
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/rbac.yaml`、`deploy/kubernetes/app-runtime/templates/admission.yaml`
  **逻辑/验收**：namespace manager最小权限，系统服务不可被manager改，验证器无集群token；status/template规则分别Fail/None，PSA restricted1.28；卸载不删除保护namespace/PV。
  **覆盖 AC:** AC-03、AC-13、AC-14、AC-15、AC-16、AC-23、AC-39、AC-41、AC-49
  **依赖:** T059、T013

- [x] **T061** — 网络和保留卷安装模板
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/network.yaml`、`deploy/kubernetes/app-runtime/templates/storage.yaml`
  **逻辑/验收**：默认deny，允许entry/manager受控端口、只经egress出站、无业务DNS直连；localPV节点绑定或验证CSI，独占卷不带Pod/Helm级联删除owner，预置scratch池和限制。
  **覆盖 AC:** AC-12、AC-21、AC-22、AC-23、AC-33、AC-34、AC-35、AC-39、AC-41、AC-42
  **依赖:** T060


- [x] **T104** — 镜像发行和清单合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_image_release.py`
  **逻辑/验收**：本地构建默认不推送，双架构同版本digest合并及不可覆盖index；helper/assembler工具和离线清单，mock不记作原生验收。
  **覆盖 AC:** AC-24、AC-27、AC-39、AC-42、AC-54、AC-56
  **依赖:** T061
  **配对:** T063

- [x] **T062** — 运行服务与 helper 镜像
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/workloads.yaml`、`src/runtime-manager/Dockerfile.helper`
  **逻辑/验收**：独立manager/app-proxy/egress/admission进程，只有manager投射限定token，helper固定受信命令非root/只读；控制面重启不连带删除应用Pod或改变冻结profile。
  **覆盖 AC:** AC-03、AC-15、AC-16、AC-39、AC-40、AC-42、AC-54
  **依赖:** T061


- [x] **T103** — 原生镜像构建脚本扩展
  **类型**：基础设施
  **文件**：`scripts/build_runtime_images.sh`
  **逻辑/验收**：扩展现有脚本，同版本helper与assembler，默认local-only，显式发行开关才push；原生smoke/许可与冻结digest清单。
  **覆盖 AC:** AC-24、AC-27、AC-39、AC-42、AC-54、AC-56
  **依赖:** T062、T104

- [x] **T063** — 同版本双架构 CI/CD 发行
  **类型**：基础设施
  **文件**：`.github/workflows/runtime-images.yml`、`src/runtime-manager/runtime_manager/image_catalog.py`
  **逻辑/验收**：扩展已有tag v*/手工入口，发布helper/admission/assembler及runtime镜像清单与licenses；amd64/arm64原生构建，compose已发行镜像引用合同不退化；不改用户tag/自动推送。
  **覆盖 AC:** AC-24、AC-27、AC-39、AC-42、AC-54、AC-56
  **依赖:** T062、T103、T104
  **配对:** T104

- [x] **T064** — 部署/离线清单验证：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：可重复read-only预检及专用namespace允许/拒绝探测；离线镜像/依赖/平台接口分别核对，CRI按冻结引用真启动；说明本地卷限制、升级兼容、原卷保留和安全卸载，不输出kubeconfig/token；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-13、AC-14、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-35、AC-39、AC-40、AC-41、AC-42、AC-54、AC-55
  **依赖:** T063、T055
  **配对:** T065

- [x] **T065** — 部署/离线清单验证
  **类型**：实现
  **文件**：`scripts/verify_k8s_runtime.py`、`deploy/kubernetes/app-runtime/README.md`
  **逻辑/验收**：可重复read-only预检及专用namespace允许/拒绝探测；离线镜像/依赖/平台接口分别核对，CRI按冻结引用真启动；说明本地卷限制、升级兼容、原卷保留和安全卸载，不输出kubeconfig/token；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-13、AC-14、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-35、AC-39、AC-40、AC-41、AC-42、AC-54、AC-55
  **依赖:** T063、T055、T064
  **配对:** T064

### Wave 8


- [x] **T105** — E2E harness 边界合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：测试配置、严格tenant/owner/prefix cleanup和55AC映射；只验证harness，不冒充真实平台通过。
  **覆盖 AC:** AC-36、AC-37、AC-55
  **依赖:** T049、T005
  **配对:** T106

- [x] **T106** — 真实 API 业务验收共享行程
  **类型**：实现
  **文件**：`src/backend/test/e2e/helpers/vibe_runtime.py`、`src/backend/test/e2e/test_e2e_vibe_k8s_runtime.py`
  **逻辑/验收**：复用既有认证helper，真实发布/审批/数据/入口和最终GET，精确MMMEE，独立测试租户/自然owner，不用manager直接API替代。
  **覆盖 AC:** AC-36、AC-37、AC-55
  **依赖:** T105
  **配对:** T105

- [x] **T066** — 真实平台 K8s E2E 执行器
  **类型**：测试
  **文件**：`scripts/e2e_k8s_runtime.py`、`features/v3.0.0/059-k8s-runtime-backend/e2e-checklist.md`
  **逻辑/验收**：按e2e-test skill复用平台认证/CLI/审批/SDK/数据业务入口，生成55条AC用例映射、危险前置和cleanup；不是只调manager API，不把mock记为真实成功；凭据从安全环境/主机既有配置读取。
  **覆盖 AC:** AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56
  **依赖:** T065、T049、T005


- [x] **T107** — 继承发布线的权限/egress测试适配
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_app_permission_registration.py`、`src/backend/test/app_runtime/test_runtime_lifecycle_v2.py`
  **逻辑/验收**：候选count stub与已交付linsight注册保持当前Owner；policy fixture显式egress角色，不放宽生产身份。
  **覆盖 AC:** AC-03、AC-36、AC-53、AC-56
  **依赖:** T066

- [x] **T108** — 资源历史约束静态合同同步
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_model_contracts.py`
  **逻辑/验收**：明确资源历史按实际UID唯一；已移除operation/kind/name约束不得恢复，保留固定位置多phase历史；DM8静态边界。
  **覆盖 AC:** AC-15、AC-48、AC-56
  **依赖:** T107

- [x] **T109** — 删除维护轻量容量预占合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_purge_capacity.py`
  **逻辑/验收**：删除以固定helper预算预占，不因原应用档位误拒绝；额度不足与成功配对。
  **覆盖 AC:** AC-11、AC-18、AC-48
  **依赖:** T097

- [x] **T110** — 删除维护轻量容量预占
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`
  **逻辑/验收**：保持原子节点锁，purge只为受限helper预占；不免除容量控制。
  **覆盖 AC:** AC-11、AC-18、AC-48
  **依赖:** T109
  **配对:** T109

- [x] **T111** — Calico 元数据来源及收尾合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：可信CNI可维护指定注解，manager仅原样保留同UID旧值；拒绝伪造、增改删、status和spec越权。
  **覆盖 AC:** AC-03、AC-14、AC-48、AC-52
  **依赖:** T011

- [x] **T112** — Calico 元数据来源隔离
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：精确保留已认证CNI字段以允许fenced finalizer收尾，不放行通用注解前缀。
  **覆盖 AC:** AC-03、AC-14、AC-48、AC-52
  **依赖:** T111
  **配对:** T111

- [x] **T113** — scratch 写入前卷校验合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_helper.py`、`src/runtime-manager/tests/test_k8s_templates.py`
  **逻辑/验收**：prepare和assemble在任何写入/材料投射前执行只读guard，校验真实文件系统/容量/安装标识，负例拒绝。
  **覆盖 AC:** AC-33、AC-34、AC-42、AC-44
  **依赖:** T009

- [x] **T114** — scratch 写入前卷校验
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_helper.py`、`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：可信guard固定命令、无业务身份，缺挂载/错误marker/无界容量拒绝。
  **覆盖 AC:** AC-33、AC-34、AC-42、AC-44
  **依赖:** T113
  **配对:** T113

- [x] **T115** — scratch 预算与安装标识接线
  **类型**：实现
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`、`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：逐purpose区分production与scratch预算，preview/probe不碰生产卷；测试先复现预算丢失。
  **覆盖 AC:** AC-33、AC-34、AC-42、AC-44
  **依赖:** T114、T100
  **配对:** T032

- [x] **T116** — static launcher 兼容合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_helper.py`、`src/runtime-manager/tests/test_k8s_templates.py`
  **逻辑/验收**：标准bundle的冻结nginx argv与PORT经受信entrypoint消费，完整image保持自身入口。
  **覆盖 AC:** AC-04、AC-24、AC-44、AC-56
  **依赖:** T008

- [x] **T117** — static launcher 保留
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：标准static bundle使用固定launcher生成/tmp配置，避免K8s command绕过镜像ENTRYPOINT。
  **覆盖 AC:** AC-04、AC-24、AC-44、AC-56
  **依赖:** T116
  **配对:** T116

- [x] **T118** — Node launcher 兼容收尾
  **类型**：实现
  **文件**：`src/runtime-manager/tests/test_k8s_templates.py`、`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：先测试node/npm/脚本名/--eval，再保留绝对路径Node launcher；完整image不包装。
  **覆盖 AC:** AC-04、AC-24、AC-44、AC-56
  **依赖:** T117
  **配对:** T008

- [x] **T119** — 探测刷新后的 sandbox 冻结
  **类型**：实现
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`、`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：同resource_ref重试按原Pod记录冻结RuntimeClass和deadline；先核对完整操作作用域，保留intent模板比对。
  **覆盖 AC:** AC-07、AC-19、AC-20、AC-40、AC-48
  **依赖:** T100
  **配对:** T032

- [x] **T120** — Chart 安装标识传递
  **类型**：实现
  **文件**：`deploy/kubernetes/app-runtime/templates/workloads.yaml`、`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：descriptor包含installation_id，与静态PV marker一致；先测试明确缺字段。
  **覆盖 AC:** AC-34、AC-39、AC-42
  **依赖:** T064
  **配对:** T064

- [x] **T121** — helper 可信解析工具链合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_image_release.py`
  **逻辑/验收**：验证prepare.py、Node/npm、本架构库、同版本wheelhouse、构建顺序与禁网真实resolve，不能只检查import。
  **覆盖 AC:** AC-24、AC-42、AC-44、AC-45、AC-54
  **依赖:** T104

- [x] **T122** — helper 可信解析工具链
  **类型**：基础设施
  **文件**：`src/runtime-manager/Dockerfile.helper`
  **逻辑/验收**：同版本manager/Node/Python preparer为唯一工具来源；离线构建自身wheel，复制SDK轮子闭包与许可证，不复制宿主/glibc。
  **覆盖 AC:** AC-24、AC-42、AC-44、AC-45、AC-54
  **依赖:** T121

- [x] **T123** — 镜像实际离线解析烟测
  **类型**：基础设施
  **文件**：`scripts/build_runtime_images.sh`、`src/runtime-manager/tests/test_image_release.py`
  **逻辑/验收**：原生image内禁网执行requirements/uv.lock/Node/static解析，ignore-scripts不得运行应用hook；任一失败禁止推送。
  **覆盖 AC:** AC-24、AC-42、AC-44、AC-45、AC-54
  **依赖:** T122、T103

- [x] **T124** — 隔离平台 bootstrap 合同
  **类型**：测试
  **文件**：`scripts/fixtures/f059/test_bootstrap.py`
  **逻辑/验收**：覆盖真实API形状、env私密权限/混合Docker配置/作用域、人工审批、服务账号及本地HTTP/SQLite/SDK/WS。
  **覆盖 AC:** AC-36、AC-37、AC-46、AC-55
  **依赖:** T105

- [x] **T125** — 隔离平台 API bootstrap
  **类型**：实现
  **文件**：`scripts/bootstrap_f059_acceptance.py`
  **逻辑/验收**：仅专用全新测试实例；真实部门挂租户、自然人/人工审批、owner mode-S、固定自定义profile；不直接SQL，不泄露凭据。
  **覆盖 AC:** AC-36、AC-37、AC-46、AC-55
  **依赖:** T124
  **配对:** T124

- [x] **T126** — 真实应用协议夹具
  **类型**：实现
  **文件**：`scripts/fixtures/f059/python_demo.py`、`scripts/fixtures/f059/node_demo.js`
  **逻辑/验收**：真实HTTP/SQLite/WS和SDK附件往返；模型/检索未配置明确不可测，禁止返回固定成功。
  **覆盖 AC:** AC-04、AC-11、AC-36、AC-46、AC-55
  **依赖:** T125
  **配对:** T124

- [x] **T127** — 完整镜像及离线材料夹具
  **类型**：基础设施
  **文件**：`scripts/fixtures/f059/Dockerfile.demo`、`scripts/fixtures/f059/offline-manifest.example.json`
  **逻辑/验收**：完整应用镜像实际包含代码；物料模板只说明格式，不伪造digest。
  **覆盖 AC:** AC-24、AC-27、AC-42、AC-45
  **依赖:** T125

- [x] **T128** — 平台验收夹具说明
  **类型**：基础设施
  **文件**：`scripts/fixtures/f059/README.md`
  **逻辑/验收**：提供准备/真实API/阶段验收/安全清理指令，区分本地协议烟测与真实集群证据。
  **覆盖 AC:** AC-42、AC-54、AC-55
  **依赖:** T125

- [x] **T129** — helper 及 PVC 作用域校验接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_kubernetes_service.py`、`src/backend/test/app_runtime/test_runtime_kubernetes_service.py`
  **逻辑/验收**：允许固定storage-guard；所有production/scratch按app/op冻结PVC，跨app同namespace卷仍拒绝；更新旧最小fixture。
  **覆盖 AC:** AC-03、AC-33、AC-34、AC-48
  **依赖:** T097
  **配对:** T016

- [x] **T130** — 自定义 bundle launcher 合同说明
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/README.md`
  **逻辑/验收**：明确Python解释器、固定Node/static launcher、只读挂载和非root要求；不适配该合同的完整image走既有入口。
  **覆盖 AC:** AC-04、AC-42、AC-44、AC-56
  **依赖:** T118

- [x] **T131** — 源码大小限制冻结接线
  **类型**：实现
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`、`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：先捕获prepare各phase丢失source_limits，再深拷贝payload冻结值；无旧字段保持兼容默认，不读现场新配置。
  **覆盖 AC:** AC-24、AC-44、AC-56
  **依赖:** T100
  **配对:** T032

- [x] **T132** — SDK 既有平台地址变量合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_k8s_delivery_coordinator.py`
  **逻辑/验收**：核对committed SDK wheel实际变量名及coordinator密封环境，Docker/K8s均能消费。
  **覆盖 AC:** AC-36、AC-46、AC-56
  **依赖:** T049

- [x] **T133** — SDK 平台地址变量接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py`
  **逻辑/验收**：v2增加BISHENG_PLATFORM_API_BASE并保留旧key；不改变模型/附件身份，不以测试mock代替SDK实际调用。
  **覆盖 AC:** AC-36、AC-46、AC-56
  **依赖:** T132
  **配对:** T132

- [x] **T134** — 安装探测安全失败分类
  **类型**：实现
  **文件**：`scripts/verify_k8s_runtime.py`、`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：先测试常量reason与异常分类，再保留probe/cleanup/publish失败；不打印任意异常文本/对象/凭据，不放宽ready。
  **覆盖 AC:** AC-19、AC-20、AC-54、AC-55
  **依赖:** T065
  **配对:** T064

- [x] **T135** — 显式公开 CA 的 HTTP/WS 合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：本地真实HTTPS/WSS正确CA允许、错误CA拒绝，路径/私钥/符号链接拒绝，无verify=False。
  **覆盖 AC:** AC-36、AC-46、AC-55
  **依赖:** T105

- [x] **T136** — 真实业务 E2E 公开 CA 接线
  **类型**：实现
  **文件**：`scripts/e2e_k8s_runtime.py`、`src/backend/test/e2e/helpers/vibe_runtime.py`
  **逻辑/验收**：F059_E2E_CA_FILE构造保留系统根的严格SSLContext，HTTP和WSS统一使用，未配置时默认信任不变。
  **覆盖 AC:** AC-36、AC-46、AC-55
  **依赖:** T135
  **配对:** T135

- [x] **T137** — 固定镜像 profile 新修订合同
  **类型**：测试
  **文件**：`scripts/fixtures/f059/test_bootstrap.py`
  **逻辑/验收**：N=1兼容、N=2包内引用/default/API导入一致，不覆写相同修订的变更镜像。
  **覆盖 AC:** AC-39、AC-42、AC-44、AC-55
  **依赖:** T124

- [x] **T138** — 验收 profile 修订参数
  **类型**：实现
  **文件**：`scripts/bootstrap_f059_acceptance.py`、`scripts/fixtures/f059/README.md`
  **逻辑/验收**：正整数--profile-revision控制导入、bundle固定引用；source-image遵守现行schema使用语言默认，实际解析后冻结。
  **覆盖 AC:** AC-39、AC-42、AC-44、AC-55
  **依赖:** T137
  **配对:** T137

- [x] **T139** — Kubernetes CREATE 默认对象合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：依据固定v1.28.15真实策略校验Pending/QoS与精确空status、omitempty空env；终态/额外状态/非空env/伪造来源仍拒绝。
  **覆盖 AC:** AC-13、AC-30、AC-49、AC-55
  **依赖:** T011

- [x] **T140** — Kubernetes CREATE 默认对象兼容
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：只容许API正常默认值与空env缺省等价，不放松status来源、CNI身份或模板冻结。
  **覆盖 AC:** AC-13、AC-30、AC-49、AC-55
  **依赖:** T139
  **配对:** T139

- [x] **T141** — 协调器旧 scratch 夹具适配
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_coordination.py`
  **逻辑/验收**：增加当前op的独占scratch PVC，不改变原探测失效、连续保护和停止证据断言。
  **覆盖 AC:** AC-19、AC-20、AC-48、AC-56
  **依赖:** T129

- [x] **T142** — 验收管理员授权可重复执行
  **类型**：实现
  **文件**：`scripts/bootstrap_f059_acceptance.py`、`scripts/fixtures/f059/test_bootstrap.py`
  **逻辑/验收**：先GET现存tenant admins，已存在跳过重复FGA授权；查询失败/格式错停止，不改业务授权API。
  **覆盖 AC:** AC-36、AC-55
  **依赖:** T137
  **配对:** T124

- [x] **T143** — canary 配置投射刷新合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：CM成功replace后确认UID/RV，只匹配本controlNS Running admission Pod、受信整卷挂载；冲突/替换/错scope/无目标均拒绝，保留spec和其他注解。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-54、AC-55
  **依赖:** T064
  **配对:** T144

- [x] **T144** — canary 配置投射刷新
  **类型**：实现
  **文件**：`scripts/verify_k8s_runtime.py`
  **逻辑/验收**：外部installer以UID/RV JSON Patch只写公开revision注解触发挂载刷新，不修改TTL/RBAC/readiness、不重启Deployment；仍等待真实admission消费计划。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-54、AC-55
  **依赖:** T143
  **配对:** T143

- [x] **T145** — 过期 canary 恢复围栏合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：未调度删除中Pod逐UID实测binding拒绝及二次读取；活跃计划/替换/错误拒绝/API不确定/未知状态不释放；停止证据不可跨资源复用。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-48、AC-49、AC-55
  **依赖:** T064
  **配对:** T146

- [x] **T146** — 过期 canary 逐资源恢复
  **类型**：实现
  **文件**：`scripts/verify_k8s_runtime.py`
  **逻辑/验收**：恢复仅接管自然过期的同UID计划；对未调度Pod获取独立绑定围栏证据，已绑定Pod等待可信终态；按停止确认、finalizer、对象消失、无PVC引用顺序清理。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-48、AC-49、AC-55
  **依赖:** T145
  **配对:** T145

- [x] **T147** — CNI 身份与能力报告绑定合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：Chart描述与admission身份同源；仅变更CNI身份使旧报告失效；只更新probe_report不改变描述摘要。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-55
  **依赖:** T143
  **配对:** T148

- [x] **T148** — 描述纳入 CNI 身份
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/workloads.yaml`
  **逻辑/验收**：内部descriptor增加cni_username，与execution.cniUsername及admission ENV同源，不改摘要算法或对外部署API。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-55
  **依赖:** T147
  **配对:** T147

- [x] **T149** — 租户上下文默认值合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_model_contracts.py`
  **逻辑/验收**：记录已保存模型草稿验证：None默认等待上下文，存储非空有索引；未声明/None/0自动填充，显式租户保留，缺上下文拒绝写入；DM8仅静态。
  **覆盖 AC:** AC-15、AC-48、AC-54、AC-56
  **依赖:** T073
  **配对:** T150

- [x] **T150** — 运行记录租户默认值修订
  **类型**：基础设施
  **文件**：`src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py`
  **逻辑/验收**：ScopedRuntimeRecord默认None且nullable=False/index=True；复用before_flush上下文注入，不改变既有DB约束，不修改公共Linsight模型。
  **覆盖 AC:** AC-15、AC-48、AC-54、AC-56
  **依赖:** T149
  **配对:** T149

- [x] **T151** — Helm 升级保留 canary 计划合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：覆盖升级保留运行中plans/profile_images和首次初始化；缺对象/归属错误/非法数据拒绝，旧无label对象需同release descriptor范围证据。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-40、AC-55
  **依赖:** T147
  **配对:** T152

- [x] **T152** — Helm 升级保留恢复计划
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/services.yaml`
  **逻辑/验收**：升级只读取同release/namespace的合法canary CM并保留动态计划；初装才初始化；合法旧资源通过descriptor安装范围校验后补标识，不静默重置计划。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-40、AC-55
  **依赖:** T151
  **配对:** T151

- [x] **T153** — 原生 Docker context 构建合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_image_release.py`
  **逻辑/验收**：当前context选择对应docker driver builder，禁止依赖不可用default context；保留host/daemon/image架构一致与原生烟测门禁。
  **覆盖 AC:** AC-42、AC-54
  **依赖:** T123
  **配对:** T154

- [x] **T154** — 原生 context 构建入口
  **类型**：实现
  **文件**：`scripts/build_runtime_images.sh`
  **逻辑/验收**：命令级选择当前原生daemon的docker driver builder，不改全局context；同版本构建、离线resolver与烟测通过后生成清单。
  **覆盖 AC:** AC-42、AC-54
  **依赖:** T153
  **配对:** T153

- [x] **T155** — 预览访问和只读 checkpoint 合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：实际访问审批预览，配对owner/nonowner/foreign拒绝，预览前后生产行不变；checkpoint只GET且请求前校验时限、app范围。
  **覆盖 AC:** AC-17、AC-18、AC-27、AC-35、AC-46、AC-55
  **依赖:** T133
  **配对:** T156

- [x] **T156** — 预览入口与只读故障观察
  **类型**：实现
  **文件**：`src/backend/test/e2e/helpers/vibe_runtime.py`
  **逻辑/验收**：走真实预览入口；故障after不调用带写入的observe，不将API观察当作故障注入证明。
  **覆盖 AC:** AC-17、AC-18、AC-27、AC-35、AC-46、AC-55
  **依赖:** T155
  **配对:** T155

- [x] **T157** — 真实 pytest 入口 CA 一致性
  **类型**：测试
  **文件**：`src/backend/test/e2e/test_e2e_vibe_k8s_runtime.py`、`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：pytest live与CLI都用显式证书SSLContext；TLS/WS不关闭证书验证。
  **覆盖 AC:** AC-42、AC-46、AC-55
  **依赖:** T155
  **配对:** T155

- [x] **T158** — 精确故障操作合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：suite slug/app/op/snapshot范围、fresh generation与ack正反，取消/恢复配对权限和终态拒绝；恢复数据对比，不以新增快照数判通过。
  **覆盖 AC:** AC-07、AC-27、AC-35、AC-43、AC-49、AC-55
  **依赖:** T155
  **配对:** T159

- [x] **T159** — 精确取消及快照恢复 harness
  **类型**：实现
  **文件**：`src/backend/test/e2e/helpers/vibe_runtime.py`
  **逻辑/验收**：只对本suite精确operation观测和取消；恢复显式确认并比对预期rows，允许保护快照去重，公开接口缺关联证据时记录未验证。
  **覆盖 AC:** AC-07、AC-27、AC-35、AC-43、AC-49、AC-55
  **依赖:** T158
  **配对:** T158

- [x] **T163** — 故障操作 CLI 参数合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：验证fault-operation阶段的slug、operation、snapshot、expected generation、ack与expected rows参数正反。
  **覆盖 AC:** AC-07、AC-35、AC-43、AC-55
  **依赖:** T159
  **配对:** T160

- [x] **T160** — 故障操作 CLI 入口
  **类型**：实现
  **文件**：`scripts/e2e_k8s_runtime.py`
  **逻辑/验收**：公开平台API执行显式suite范围操作，返回真实业务状态；不调用集群接口或自动注入基础设施故障。
  **覆盖 AC:** AC-07、AC-35、AC-43、AC-55
  **依赖:** T163
  **配对:** T163

- [x] **T161** — 空 finalizers 序列化合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：真实API省略空finalizers时，停止未确认仍拒绝，确认后允许；CNI注解保留、额外finalizer/伪造状态仍拒绝。
  **覆盖 AC:** AC-13、AC-20、AC-49、AC-55
  **依赖:** T111
  **配对:** T162

- [x] **T162** — 准入兼容省略空 finalizers
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：仅metadata.finalizers空数组按omitempty规范化为省略；不改变同UID/停止确认或非空finalizer严格比较。
  **覆盖 AC:** AC-13、AC-20、AC-49、AC-55
  **依赖:** T161
  **配对:** T161

- [x] **T164** — kubectl 子资源拒绝合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：exec/status必须以--subresource明确请求；create pods允许不代表exec允许。
  **覆盖 AC:** AC-13、AC-14、AC-55
  **依赖:** T145
  **配对:** T165


- [x] **T165** — kubectl 子资源显式检查
  **类型**：实现
  **文件**：`scripts/verify_k8s_runtime.py`
  **逻辑/验收**：使用资源TYPE加--subresource而非TYPE/NAME，真实核对exec和status拒绝。
  **覆盖 AC:** AC-13、AC-14、AC-55
  **依赖:** T164
  **配对:** T164


- [x] **T166** — 存储控制器身份配置合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：同源ENV/descriptor；非法、空、重复及自然用户身份拒绝，变化后旧报告失效。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-55
  **依赖:** T147
  **配对:** T167


- [x] **T167** — 存储控制器配置与schema
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/values.yaml`、`deploy/kubernetes/app-runtime/values.schema.json`
  **逻辑/验收**：显式控制器用户名列表，默认兼容既有部署；不赋予新RBAC权限。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-55
  **依赖:** T166
  **配对:** T166


- [x] **T168** — 存储控制器环境与描述同源
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/workloads.yaml`
  **逻辑/验收**：admission ENV与descriptor从同一execution.storageControllerUsernames读取。
  **覆盖 AC:** AC-19、AC-20、AC-30、AC-55
  **依赖:** T167


- [x] **T169** — API未绑定Pod零宽限删除合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：仅同UID/RV、Pending未绑定且无任意writer状态可接受API规范化零宽限；绑定、Unknown、终态、过期RV拒绝。
  **覆盖 AC:** AC-13、AC-20、AC-49、AC-55
  **依赖:** T161
  **配对:** T170


- [x] **T170** — 未绑定Pod删除选项兼容
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：兼容API server把未绑定Pod删除宽限归零；保留UID/RV和停止证据围栏，不放开有写入历史的强删。
  **覆盖 AC:** AC-13、AC-20、AC-49、AC-55
  **依赖:** T169
  **配对:** T169


- [x] **T171** — PSA负例和dry-run撤销合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：schema有效的特权Pod必须由真实PSA拒绝；所有dryRun失败路径撤销未创建计划并保留双重失败。
  **覆盖 AC:** AC-13、AC-19、AC-20、AC-55
  **依赖:** T164
  **配对:** T172


- [x] **T172** — PSA真实拒绝及计划清理
  **类型**：实现
  **文件**：`scripts/verify_k8s_runtime.py`
  **逻辑/验收**：privileged与allowPrivilegeEscalation同时设真；只认PodSecurity拒绝，finally撤销UID空的dryRun计划，清理失败不能吞掉。
  **覆盖 AC:** AC-13、AC-19、AC-20、AC-55
  **依赖:** T171
  **配对:** T171


- [x] **T173** — 原生隔离烟测可读目录合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_image_release.py`
  **逻辑/验收**：umask022/077下UID10001可遍历shadow并读取poison文件，防止权限拒绝导致假阳性。
  **覆盖 AC:** AC-42、AC-54
  **依赖:** T153
  **配对:** T174


- [x] **T174** — 原生隔离烟测目录权限
  **类型**：实现
  **文件**：`scripts/build_runtime_images.sh`
  **逻辑/验收**：shadow0755、poison0644；实际-I命令先读候选再确认只导入trusted模块，不改变运行镜像权限。
  **覆盖 AC:** AC-42、AC-54
  **依赖:** T173
  **配对:** T173


- [x] **T175** — 终态Pod删除规范化合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：同UID/RV可信终态0允许；伪造对象、active/Unknown/NodeLost、缺少终止证明和策略/finalizer错误拒绝。
  **覆盖 AC:** AC-13、AC-20、AC-49、AC-55
  **依赖:** T169
  **配对:** T176


- [x] **T176** — 终态Pod删除选项兼容
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：仅manager授权后验证API oldObject的停止事实，兼容Core规范化0；不代替停止确认或释放finalizer。
  **覆盖 AC:** AC-13、AC-20、AC-49、AC-55
  **依赖:** T175
  **配对:** T175


- [x] **T177** — SQLite随机哨兵升级合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_image_release.py`
  **逻辑/验收**：升级前由测试写随机数据，升级后核对值和备份，避免两版默认初始化相同造成假阳性。
  **覆盖 AC:** AC-24、AC-25、AC-26、AC-55
  **依赖:** T173
  **配对:** T178


- [x] **T178** — 真实SQLite哨兵烟测
  **类型**：实现
  **文件**：`scripts/smoke_runtime_delivery.py`
  **逻辑/验收**：真实Engine写入升级前独有随机值，v2保留并在确认备份中查询同值；不以默认初始化行代替持久化。
  **覆盖 AC:** AC-24、AC-25、AC-26、AC-55
  **依赖:** T177
  **配对:** T177


- [x] **T179** — Docker诊断真实客户端合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_operations_v2.py`
  **逻辑/验收**：真实PlatformClient仅提供node_snapshot；验证真实签名plan请求和平台错误拒绝本地容量回退。
  **覆盖 AC:** AC-01、AC-10、AC-30、AC-48、AC-50、AC-55
  **依赖:** T175
  **配对:** T180


- [x] **T180** — Docker诊断平台账本接线
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/api/platform_observe.py`
  **逻辑/验收**：修正不存在的node_plan调用为node_snapshot；保留Docker公开字段形状，不添加K8s专属字段。
  **覆盖 AC:** AC-01、AC-10、AC-30、AC-48、AC-50、AC-55
  **依赖:** T179
  **配对:** T179


- [x] **T181** — Docker既有诊断E2E合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：Docker无K8s专属ready/executor_kind允许；账本不可读、错误协议/类型/运行时、缺失或失败预检拒绝；K8s保持严格ready。
  **覆盖 AC:** AC-01、AC-30、AC-32、AC-55
  **依赖:** T163
  **配对:** T182


- [x] **T182** — Docker诊断E2E兼容
  **类型**：实现
  **文件**：`src/backend/test/e2e/helpers/vibe_runtime.py`
  **逻辑/验收**：按已知执行器核验现有公开形状；Docker必须v2、后端可用、容量可读、三运行时与全部预检成功；不放松K8s。
  **覆盖 AC:** AC-01、AC-30、AC-32、AC-55
  **依赖:** T181
  **配对:** T181


- [x] **T183** — 验收批次应用标识合同
  **类型**：测试
  **文件**：`scripts/fixtures/f059/test_bootstrap.py`
  **逻辑/验收**：删除保留slug，显式批次后缀正反、长度约束、包manifest/scenario一致、准备和bootstrap一致；不重建身份。
  **覆盖 AC:** AC-35、AC-55、AC-56
  **依赖:** T181
  **配对:** T184


- [x] **T184** — 唯一应用验收批次后缀
  **类型**：实现
  **文件**：`scripts/bootstrap_f059_acceptance.py`
  **逻辑/验收**：增加可选显式application-suffix，严格范围并冻结本批后缀；新批用独立journal，旧应用按原账本清理，不删审计行。
  **覆盖 AC:** AC-35、AC-55、AC-56
  **依赖:** T183
  **配对:** T183


- [x] **T185** — 真实报告的公开诊断合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_observe.py`
  **逻辑/验收**：使用真实executor与descriptor投射，无raw ready字段的有效报告通过；过期、身份变化、mandatory失败和API不可达拒绝，刷新后恢复。
  **覆盖 AC:** AC-01、AC-30、AC-31、AC-32、AC-55
  **依赖:** T179
  **配对:** T186

- [x] **T186** — 公开诊断复用实时评估
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/api/platform_observe.py`
  **逻辑/验收**：公开诊断调用既有probe_report评估，不修改报告TTL、摘要、公开形状或能力准入。
  **覆盖 AC:** AC-01、AC-30、AC-31、AC-32、AC-55
  **依赖:** T185
  **配对:** T185

- [x] **T187** — WAL侧文件与SQL只读配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_data_executor.py`、`src/runtime-manager/tests/test_data_executor_wal.py`
  **逻辑/验收**：真实SQLite验证无侧文件及已提交WAL；单应用helper可创建侧文件，读SQL仍拒绝写入、读取最新已提交值；实际Docker权限和隔离配对。
  **覆盖 AC:** AC-10、AC-16、AC-34、AC-36、AC-46、AC-55
  **依赖:** T066
  **配对:** T188

- [x] **T188** — 单应用数据helper的WAL目录访问
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/data_executor.py`
  **逻辑/验收**：单应用数据库目录允许SQLite创建/锁定WAL侧文件，rootfs仍只读、无网络、非root；读连接继续mode=ro，不使用immutable忽略WAL或强制checkpoint。
  **覆盖 AC:** AC-10、AC-16、AC-34、AC-36、AC-46、AC-55
  **依赖:** T187
  **配对:** T187

- [x] **T189** — 恢复后等待精确运行操作终态
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：公开app可先online；验收须等待同一resume操作completed/cleanup complete，并复核同app/operation/version/generation。失败和身份变化不能放行，不吞维护错误。
  **覆盖 AC:** AC-29、AC-33、AC-35、AC-36、AC-55
  **依赖:** T182
  **配对:** T190

- [x] **T190** — 业务验收恢复操作同步
  **类型**：实现
  **文件**：`src/backend/test/e2e/helpers/vibe_runtime.py`
  **逻辑/验收**：仅修正验收工具同步，ready/serving阶段继续轮询，终态后核对身份与数据；业务API和运行时锁不改。
  **覆盖 AC:** AC-29、AC-33、AC-35、AC-36、AC-55
  **依赖:** T189
  **配对:** T189

- [x] **T191** — 离线源码验收依赖物料合同
  **类型**：测试
  **文件**：`scripts/fixtures/f059/test_bootstrap.py`
  **逻辑/验收**：只接收显式清单和逐wheel SHA的纯Python物料；拒绝缺依赖、篡改、native wheel、路径穿越、覆盖与pth；真实SDK断言不变。
  **覆盖 AC:** AC-04、AC-24、AC-36、AC-46、AC-55
  **依赖:** T184
  **配对:** T192

- [x] **T192** — 源码验收包显式离线vendor物料
  **类型**：实现
  **文件**：`scripts/bootstrap_f059_acceptance.py`
  **逻辑/验收**：显式source-wheelhouse从固定材料清单校验并保留真实SDK/httpx闭包及许可，只向source-image包加入_vendor与启动路径引导；不读取开发venv、不pip、不联网，不改生产模板或base。
  **覆盖 AC:** AC-04、AC-24、AC-36、AC-46、AC-55
  **依赖:** T191
  **配对:** T191

- [x] **T193** — 离线源码验收前置说明
  **类型**：基础设施
  **文件**：`scripts/fixtures/f059/README.md`
  **逻辑/验收**：区分Docker source-image裸base与K8s profile；记录离线vendor材料准备和许可，完整镜像需显式提供digest；说明本地材料烟测不代表平台验收。
  **覆盖 AC:** AC-04、AC-24、AC-36、AC-46、AC-55
  **依赖:** T192

- [x] **T194** — 真实manifest引用与冻结profile分离
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`、`src/runtime-manager/tests/test_oci_assembler.py`
  **逻辑/验收**：使用真实BundleDelivery.model_dump的显式profile字符串和已解析payload.profile，覆盖prepare及运行resolved_delivery；错误类型在资源调用前明确拒绝，不被宽松桩掩盖。
  **覆盖 AC:** AC-04、AC-24、AC-25、AC-36、AC-55
  **依赖:** T186
  **配对:** T195

- [x] **T195** — K8s计划仅消费已解析profile对象
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：prepare只取已解析payload.profile，运行取resolved_delivery.profile；manifest字符串仅作为引用，不当作dict、不默默fallback错误对象，保持平台冻结/范围校验。
  **覆盖 AC:** AC-04、AC-24、AC-25、AC-36、AC-55
  **依赖:** T194
  **配对:** T194

- [x] **T196** — 无运行分配与平台故障状态配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_observe.py`
  **逻辑/验收**：真实PlatformClient的application_not_found/404映射为无实例；403/503/超时及资源故障保持不可用，Docker/K8s和正常实例保持配对。
  **覆盖 AC:** AC-01、AC-33、AC-35、AC-36、AC-55
  **依赖:** T186
  **配对:** T197

- [x] **T197** — 只读实例查询保留无分配语义
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/api/platform_observe.py`
  **逻辑/验收**：只将platform.application精确application_not_found+404转换NotFoundError；不将任意平台/API资源失败视为无写入者，不放宽删除与停止围栏。
  **覆盖 AC:** AC-01、AC-33、AC-35、AC-36、AC-55
  **依赖:** T196
  **配对:** T196

- [x] **T198** — 控制器空闲过期与失租恢复围栏
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`
  **逻辑/验收**：真实30秒租约和PlatformClient错误配对：空闲过期重新CAS领取；活跃异holder、未知响应和503不放行，既有UID恢复与新epoch事实及并发锁不生成虚假停止证据。
  **覆盖 AC:** AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55
  **依赖:** T197
  **配对:** T199

- [x] **T199** — 过期控制器租约按精确失租恢复
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：精确409/controller_lease_lost使缓存失效，fresh node快照后CAS领取；其他失败不吞，当前不确定动作拒绝；按真实到期限制缓存，不改平台API及停止围栏。
  **覆盖 AC:** AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55
  **依赖:** T198
  **配对:** T198

- [x] **T200** — backend真实冻结profile资源校验合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_frozen_profile_contract.py`
  **逻辑/验收**：真实manifest model_dump与register_resource/SQLite账本配对：prepare已解析profile、运行冻结profile、非法类型及image/purge/source-image白名单；拒绝前不写资源。
  **覆盖 AC:** AC-04、AC-13、AC-15、AC-24、AC-25、AC-36、AC-48、AC-55
  **依赖:** T199
  **配对:** T201

- [x] **T202** — 旧资源测试fixture补齐真实协议字段
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_coordination.py`、`src/backend/test/app_runtime/test_runtime_kubernetes_service.py`
  **逻辑/验收**：prepare fixture提供manifest delivery与已解析profile；直接Pod校验替身提供真实kind/image mode，保留探测/跨卷/停止证据全部拒绝断言。
  **覆盖 AC:** AC-04、AC-13、AC-15、AC-24、AC-25、AC-36、AC-48、AC-55
  **依赖:** T200

- [x] **T201** — backend按阶段消费已解析profile
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_kubernetes_service.py`
  **逻辑/验收**：prepare仅读payload.profile，其他阶段仅读resolved_delivery.profile；非法delivery/profile固定RuntimeConflict，不以stale对象fallback扩大镜像白名单；image/purge无profile合同保持。
  **覆盖 AC:** AC-04、AC-13、AC-15、AC-24、AC-25、AC-36、AC-48、AC-55
  **依赖:** T200、T202
  **配对:** T200

- [x] **T203** — K8s自动补全的UID字段合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_templates.py`、`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：真实PodPlan默认化后通过；两个helper的非v1、字段路径变化、额外字段仍拒绝。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T201
  **配对:** T204

- [x] **T204** — 冻结显式core/v1 UID选择器
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：仅两处显式apiVersion:v1，未知字段比较不放宽，旧冻结intent不改写。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T203
  **配对:** T203

- [x] **T207** — 持久创建事务与签名HTTP合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_creation.py`、`src/backend/test/app_runtime/test_runtime_kubernetes_api.py`
  **逻辑/验收**：仅唯一403拒绝可独立not_created收尾；未知、旧记录、重复、跨epoch和无UID普通停止拒绝；含真实SQL、签名API、role配对和混合unknown阻塞。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T204
  **配对:** T208

- [x] **T214** — 锁读后刷新资源identity map
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_creation_concurrency.py`
  **逻辑/验收**：真实双Session交错预读与提交，锁读必须刷新旧缓存；begin/fence双向互斥，非MySQL锁性能实测。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T207
  **配对:** T208

- [x] **T208** — 资源账本单次创建与未创建围栏
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/repositories/runtime_kubernetes_repository.py`、`src/backend/bisheng/app_runtime/domain/models/runtime_kubernetes.py`
  **逻辑/验收**：现有observed_state存versioned creation，CAS begin/rejected/fence/not_created；明确403且fence后fresh404才确认无执行体，不伪造UID；未知持久阻塞；锁读populate_existing，无新DDL。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T207、T214
  **配对:** T207

- [x] **T211** — 既有资源Service夹具接入创建事务
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_kubernetes_service.py`
  **逻辑/验收**：注册后尚不允许CREATE；真实begin后才允许，原只读不写、UID停止和权限拒绝保持。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T208

- [x] **T212** — 创建收尾Service与只读准入接线
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_kubernetes_service.py`
  **逻辑/验收**：动作按字段范围校验，新增四个内部观察；not_created和stopped各自校验，所有Pod确认后才能释放预占；准入只给started新意图CREATE。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T207、T208、T211
  **配对:** T207

- [x] **T213** — 签名观察API创建动作输入
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/api/endpoints/runtime_kubernetes.py`
  **逻辑/验收**：严格schema声明创建动作/attempt/status，exclude_unset避免默认字段进入其它动作；独立manager鉴权不变，无外部deploy API变更。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T207、T212
  **配对:** T207

- [x] **T205** — manager明确拒绝与未知创建恢复合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`
  **逻辑/验收**：403可持久收尾、未知不重发、回执丢失重启续办、发现实际Pod正常UID停止、同名异物拒绝，不DELETE未创建Pod。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T204、T213
  **配对:** T206

- [x] **T206** — manager单次创建与独立无执行体收尾
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：POST前取得唯一begin回执，只有403持久rejected；cleanup先fence再fresh404，不确定保留旧资源；重拉账本绑定UID，证明后再次出现对象拒绝。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T205
  **配对:** T205

- [x] **T209** — 准入拒绝安全诊断合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission_diagnostics.py`
  **逻辑/验收**：真实review拒绝日志只固定reason白名单，恶意异常文本/类名/凭据/UID不得泄漏；成功无拒绝日志。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T206
  **配对:** T210

- [x] **T210** — 准入拒绝固定枚举诊断
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：仅8固定原因或admission_refused；原API响应及拒绝策略不变，不追认历史403。
  **覆盖 AC:** AC-13、AC-14、AC-48、AC-49、AC-52
  **依赖:** T209
  **配对:** T209

- [x] **T215** — 实际固定容器日志与诊断合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_client.py`、`src/runtime-manager/tests/test_k8s_diagnostic_contract.py`
  **逻辑/验收**：真实KubernetesClient/MockTransport接_phase：固定helper日志可读，保留preparation_phase_failed与脱敏tail；UID/scope不符不读日志，未知容器仍拒绝。
  **覆盖 AC:** AC-13、AC-15、AC-24、AC-47、AC-48、AC-55
  **依赖:** T214
  **配对:** T216

- [x] **T216** — 补齐固定helper日志名单
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_client.py`
  **逻辑/验收**：只增加模板实际使用的storage-guard/schema-init/assembler；不吞ValueError、不放任意容器或减弱UID。
  **覆盖 AC:** AC-13、AC-15、AC-24、AC-47、AC-48、AC-55
  **依赖:** T215
  **配对:** T215

- [x] **T217** — 材料根路径反向代理合同
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_material_ingress_contract.py`
  **逻辑/验收**：精确prefix转发原始URI/query/chunk body；无凭据仍401，签名拒绝配对，禁止宽internal/workspace别名。
  **覆盖 AC:** AC-13、AC-15、AC-24、AC-47、AC-48、AC-55
  **依赖:** T216
  **配对:** T218

- [x] **T218** — 材料根路径nginx与安装说明
  **类型**：实现
  **文件**：`docker/nginx/conf.d/default.conf`、`deploy/kubernetes/app-runtime/README.md`
  **逻辑/验收**：仅material-access前缀到backend，16MiB、streaming/超时及原始路径保持；platform.origin必须可达此独立根路径，backend验签不变。
  **覆盖 AC:** AC-13、AC-15、AC-24、AC-47、AC-48、AC-55
  **依赖:** T217
  **配对:** T217

- [x] **T219** — 延迟调度节点绑定与停止证明配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`
  **逻辑/验收**：创建时Pending且nodeName为空，后续同UID调度完成再停止；覆盖节点变化/清空、UID替换、API不确定、绑定回执不确定、已有confirmed证明不得改绑。严格mock验证停止证明节点必须等于账本，不伪造节点。
  **覆盖 AC:** AC-33、AC-49、AC-52
  **依赖:** T214、T216
  **配对:** T220

- [x] **T220** — 同UID首次节点绑定刷新
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：request_stop/confirm_stopped前新鲜读取同UID Pod，只允许空节点补齐为实际nodeName；不改变已确认停止证明，不放宽backend stop scope，未知结果保持资源占用。
  **覆盖 AC:** AC-33、AC-49、AC-52
  **依赖:** T219
  **配对:** T219

- [x] **T221** — 可选依赖锁空值及安装接续合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_helper.py`
  **逻辑/验收**：真实manifest lock:null与省略、显式路径配对，使用可信common resolver覆盖环境变量与prepare配置接续；非法类型拒绝。
  **覆盖 AC:** AC-15、AC-24、AC-47、AC-55
  **依赖:** T220
  **配对:** T222

- [x] **T222** — 可选依赖锁空值规范化
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_helper.py`、`src/runtime-manager/runtime_manager/k8s_prepare.py`
  **逻辑/验收**：仅将已验证的可选lock None视为未指定的空字符串，显式字符串保留，非法类型拒绝，不改变来源/锁校验。
  **覆盖 AC:** AC-15、AC-24、AC-47、AC-55
  **依赖:** T221
  **配对:** T221

- [x] **T223** — 终态清理重试保留原始失败诊断
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_operations_v2.py`
  **逻辑/验收**：首次失败阶段、tail、维护/数据变化标记在真实cleanup重试后保留；停止/清理按本轮真实结果，保留期清空的tail不复活。
  **覆盖 AC:** AC-48、AC-49、AC-52、AC-55
  **依赖:** T220
  **配对:** T224

- [x] **T224** — 清理重试保留首次失败事实
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：终态重试携带当前持久failure诊断字段，缺失tail不重建；phase不变、停止和cleanup仅使用实际结果，不复活操作。
  **覆盖 AC:** AC-48、AC-49、AC-52、AC-55
  **依赖:** T223
  **配对:** T223

- [x] **T225** — 异步收尾等待与重启配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_operations_v2.py`、`src/runtime-manager/tests/test_executor_selection.py`
  **逻辑/验收**：准备或探活完成后清理暂未结束保持非终态，结果不重做；取消/期限/失租保持围栏，确认清理后才完成。
  **覆盖 AC:** AC-04、AC-33、AC-35、AC-49、AC-52、AC-55、AC-56
  **依赖:** T224
  **配对:** T226

- [x] **T226** — 编排异步清理有界等待
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：修正K8s正常异步删除被当作准备失败的语义；同根收尾路径按原操作检查点/期限等待，不吞真实异常、不伪造清理完成。
  **覆盖 AC:** AC-04、AC-33、AC-35、AC-49、AC-52、AC-55、AC-56
  **依赖:** T225
  **配对:** T225

- [x] **T227** — K8s异步删除API合同
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`
  **逻辑/验收**：DELETE受理后同UID对象仍在时cleanup返回pending；真实消失后才完成，换UID/未知拒绝，不能重复创建或误删。
  **覆盖 AC:** AC-33、AC-49、AC-52
  **依赖:** T220

- [x] **T228** — 初始化与健康阶段期限配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`
  **逻辑/验收**：多init正常累计超过90秒可在各自阶段期限内就绪；单阶段/健康/原操作期限仍有界；重启重试不重新计时，时间或状态不确定不延长，同UID限制保持。
  **覆盖 AC:** AC-24、AC-25、AC-28、AC-43、AC-48、AC-49、AC-52、AC-55
  **依赖:** T226、T227
  **配对:** T229

- [x] **T229** — 修正初始化与应用就绪期限
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：按既定阶段有界初始化与健康检查，修正全部init与健康共用一次90秒误判；不扩大原操作总期限、不改变资源围栏/API/DDL。
  **覆盖 AC:** AC-24、AC-25、AC-28、AC-43、AC-48、AC-49、AC-52、AC-55
  **依赖:** T228
  **配对:** T228

- [x] **T230** — 已取消数据操作拒绝新动作配对
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_grants.py`、`src/backend/test/app_runtime/test_runtime_data_sessions.py`、`src/runtime-manager/tests/test_k8s_data_executor.py`
  **逻辑/验收**：真实owner取消提交后不能新签数据票据/继续等待ready或开始新RPC；active=False清理、已开始写入unknown与互斥仍保留。
  **覆盖 AC:** AC-33、AC-36、AC-43、AC-48、AC-49、AC-55
  **依赖:** T226
  **配对:** T231

- [x] **T231** — 取消数据会话的签发与RPC围栏
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_grant_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_data_session_service.py`、`src/runtime-manager/runtime_manager/k8s_data_executor.py`
  **逻辑/验收**：后端签发事务与ready读取核取消；manager当前操作校验拒绝取消后的新动作，不伪造回滚/停止或释放未知写入者。
  **覆盖 AC:** AC-33、AC-36、AC-43、AC-48、AC-49、AC-55
  **依赖:** T230
  **配对:** T230

- [x] **T232** — 终态finalizer移除后kubelet删除配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_admission.py`
  **逻辑/验收**：原带finalizer路径保持；无finalizer仅fresh同scope/UID已持久停止证明允许绑定kubelet DELETE0；缺失/伪造/过期/换UID拒绝。
  **覆盖 AC:** AC-35、AC-48、AC-49、AC-52、AC-55
  **依赖:** T229
  **配对:** T233

- [x] **T233** — 终态Pod正常删除准入收尾
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_admission.py`
  **逻辑/验收**：修正SQL停止已确认且平台finalizer已移除后kubelet收尾被误拒；不放宽manager force-delete或未知写入者释放。
  **覆盖 AC:** AC-35、AC-48、AC-49、AC-52、AC-55
  **依赖:** T232
  **配对:** T232

- [x] **T234** — 同步业务E2E请求预算配对
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_k8s_e2e_contract.py`
  **逻辑/验收**：成功授权的精确同步preview/stop/resume/delete使用settings预算，其他请求仍短截止；总预算取消且POST仅一次，不重试未知结果。
  **覆盖 AC:** AC-24、AC-25、AC-28、AC-33、AC-36、AC-49、AC-55
  **依赖:** T233
  **配对:** T235

- [x] **T235** — 共享E2E同步请求期限适配
  **类型**：实现
  **文件**：`src/backend/test/e2e/helpers/vibe_runtime.py`
  **逻辑/验收**：共享helper只为精确同步成功调用覆盖read预算并限制总耗时，连接/写入/pool短而有界；不改产品操作期限、拒绝断言、普通GET或restore202合同。
  **覆盖 AC:** AC-24、AC-25、AC-28、AC-33、AC-36、AC-49、AC-55
  **依赖:** T234
  **配对:** T234

- [x] **T236** — 维护容器材料身份UID接线配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_templates.py`
  **逻辑/验收**：真实模板到helper身份reader验证migrate/restore具备受控downward PodUID；purge无材料身份、普通app/data-helper不获材料UID、reserved env仍拒绝。
  **覆盖 AC:** AC-33、AC-34、AC-35、AC-48、AC-49、AC-50、AC-51、AC-55
  **依赖:** T235
  **配对:** T237

- [x] **T237** — 可信维护容器注入材料PodUID
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：仅有material_secret的可信maintenance容器从core/v1 metadata.uid取得材料签名身份绑定；保留无材料身份purge和其他角色隔离，不改helper/API/DDL。
  **覆盖 AC:** AC-33、AC-34、AC-35、AC-48、AC-49、AC-50、AC-51、AC-55
  **依赖:** T236
  **配对:** T236

- [x] **T238** — 同名已闭合历史Pod停用配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_operations_v2.py`
  **逻辑/验收**：两条已停止且清理完成的历史维护UID不得重新fresh/request_stop；当前服务UID照常停止并等待全操作清理，单一完成标记/未知状态/换UID拒绝。
  **覆盖 AC:** AC-35、AC-36、AC-48、AC-49、AC-52、AC-55
  **依赖:** T237
  **配对:** T239

- [x] **T239** — 停用跳过已闭合历史Pod
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：仅stop_state=confirmed且cleanup_state=complete的Pod跳过重复停止；保留旧操作全资源cleanup等待及当前deadline/controller/UID围栏。
  **覆盖 AC:** AC-35、AC-36、AC-48、AC-49、AC-52、AC-55
  **依赖:** T238
  **配对:** T238

- [x] **T240** — 过期停用清理闭环配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_operations_v2.py`
  **逻辑/验收**：expired stop不得以自身空资源报app已停止；先timed_out/pending持久回执，再仅同归属旧terminal操作own cleanup；响应未知、换代、换UID、未知writer拒绝，重启可续且首因保留。
  **覆盖 AC:** AC-35、AC-36、AC-48、AC-49、AC-52、AC-55
  **依赖:** T239
  **配对:** T241

- [x] **T241** — 过期停用的有界安全收尾
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：精确operation_expired且fresh deadline已过才记timeout；终态pending保留active fence，以旧terminal操作原有自身cleanup逐轮收尾，最终全app停止guard仍由backend验证。无新业务动作/期限延长/跨op过期授权。
  **覆盖 AC:** AC-35、AC-36、AC-48、AC-49、AC-52、AC-55
  **依赖:** T240
  **配对:** T240

- [x] **T242** — 离线数据CPU真实预占配对
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_sessions.py`、`src/backend/test/app_runtime/test_runtime_data_repository.py`
  **逻辑/验收**：offline frozen tier及实际预占均128Mi/100m，99m拒绝/100m允许且拒绝无残留；online保持25m且不增预占，60秒/租户/并发2和mutex保持。
  **覆盖 AC:** AC-18、AC-33、AC-43、AC-48、AC-49、AC-55
  **依赖:** T241
  **配对:** T243

- [x] **T243** — 离线数据Pod预占100m CPU
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_session_service.py`、`src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py`
  **逻辑/验收**：仅offline可信tier与实际容量预占由25m调100m；原同步响应、60秒期限、票据、并发和停止释放规则不变。
  **覆盖 AC:** AC-18、AC-33、AC-43、AC-48、AC-49、AC-55
  **依赖:** T242
  **配对:** T242

- [x] **T244** — 离线数据模板CPU与平台tier配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_templates.py`
  **逻辑/验收**：data-layout和data-helper按可信plan CPU100m生成requests=limits；旧冻结25m模板不变，serve sidecar及其他helper保持25m，内存/权限/期限不变。
  **覆盖 AC:** AC-18、AC-33、AC-43、AC-48、AC-49、AC-55
  **依赖:** T241
  **配对:** T245

- [x] **T245** — 离线数据helper沿用可信tier CPU
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：仅purpose=data的helper使用plan.cpu_millicores，在线sidecar与其他helper25m保持；无helper镜像/descriptor/网络/API变更。
  **覆盖 AC:** AC-18、AC-33、AC-43、AC-48、AC-49、AC-55
  **依赖:** T244
  **配对:** T244

- [x] **T246** — 应用包可执行文件路径配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_templates.py`
  **逻辑/验收**：真实static镜像nginx位于/usr/sbin；rendered PATH在probe/preview/serve保留依赖bin优先及标准系统sbin/bin，image模式不覆盖镜像PATH；既有PATH注入拒绝保持。
  **覆盖 AC:** AC-24、AC-25、AC-27、AC-54、AC-55
  **依赖:** T245
  **配对:** T247

- [x] **T247** — 应用包保留标准系统可执行路径
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：仅bundle受控PATH补/usr/local/sbin、/usr/sbin、/sbin；不改冻结command/entrypoint/args/profile，不改image模式及用户PATH拒绝。
  **覆盖 AC:** AC-24、AC-25、AC-27、AC-54、AC-55
  **依赖:** T246
  **配对:** T246

- [x] **T248** — OCI 目录继承权限与危险位配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_oci_assembler.py`
  **逻辑/验收**：source/environment继承fsGroup的SGID目录可归档且不携带特殊位；SUID目录、SUID/SGID普通文件仍拒绝，既有链接/硬链接/whiteout与特殊文件拒绝保持。
  **覆盖 AC:** AC-15、AC-16、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T247
  **配对:** T249

- [x] **T249** — OCI 归档移除目录继承的SGID位
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/oci_assembler.py`
  **逻辑/验收**：仅允许目录的继承SGID，由已有mode &0777去除；目录SUID及所有非目录SUID/SGID继续拒绝，不改OCI根布局、凭据挂载、冻结基础镜像和镜像推送合同。
  **覆盖 AC:** AC-15、AC-16、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T248
  **配对:** T248

- [x] **T250** — OCI 镜像可执行路径配对
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_oci_assembler.py`
  **逻辑/验收**：固定crane配置在三个运行时保留依赖bin优先与标准sbin/bin，static入口可找到/usr/sbin/nginx；不接受用户PATH替换，不改变冻结镜像或command。
  **覆盖 AC:** AC-24、AC-25、AC-27、AC-28、AC-54
  **依赖:** T249
  **配对:** T251

- [x] **T251** — OCI 镜像保留标准系统可执行路径
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/oci_assembler.py`
  **逻辑/验收**：源码镜像固定PATH补标准sbin，与已实测T247的bundle合同一致；不改base/entrypoint/command/registry/凭据和用户可配置项。
  **覆盖 AC:** AC-24、AC-25、AC-27、AC-28、AC-54
  **依赖:** T250
  **配对:** T250

- [ ] **T067** — Docker 与平台回归
  **类型**：测试
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/docker-regression.md`、`features/v3.0.0/059-k8s-runtime-backend/docker-regression.json`
  **逻辑/验收**：运行相同原有测试选择与首轮基线比对；三种交付/状态/SDK/附件/数据/权限，标真实与模拟；原F086共享修复按release来源继承。
  **覆盖 AC:** AC-01、AC-02、AC-04、AC-10、AC-24、AC-36、AC-37、AC-46、AC-53、AC-56
  **依赖:** T066

- [x] **T068** — 189 专用资源安装验收
  **类型**：测试
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/installation.json`、`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/installation.md`
  **逻辑/验收**：在192.168.106.189重新只读核对UID，再安装专用e2e-f059资源、合格local PV/PVC和镜像；验证真实拒绝与允许、包源/材料/SDK连通，保留原资源清单，不修改既有kube-system。
  **覆盖 AC:** AC-03、AC-12、AC-13、AC-14、AC-16、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-33、AC-34、AC-39、AC-42、AC-54、AC-55
  **依赖:** T065

- [ ] **T069** — 真实平台发布审批及数据验收
  **类型**：测试
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/platform.json`、`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/platform.md`
  **逻辑/验收**：首发/更新/容量不足前后阶段、bundle三语言/完整镜像/source-image、审批预览、owner与非owner、SDK/OBO/附件、停用查改导出和恢复删除。记录HTTP及SQL操作/PVCUID/材料与镜像摘要。
  **覆盖 AC:** AC-02、AC-04、AC-05、AC-08、AC-10、AC-11、AC-17、AC-18、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-33、AC-35、AC-36、AC-37、AC-44、AC-45、AC-46、AC-47、AC-50、AC-51、AC-55
  **依赖:** T068

- [ ] **T070** — 故障与升级卸载验收
  **类型**：测试
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/fault-upgrade.json`、`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/fault-upgrade.md`
  **逻辑/验收**：initImagePull/材料拒绝、取消、manager SIGKILL/并发/晚到请求、同名UID、未知写入者、快照确认/DDL后失败、HTTP/WS/出站撤权、升级manager保留Pod/PVC/profile、卸载保留资产；不能以单节点证明跨节点fencing。
  **覆盖 AC:** AC-06、AC-07、AC-09、AC-18、AC-35、AC-40、AC-41、AC-43、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-55
  **依赖:** T069

- [ ] **T071** — 模型静态兼容与发行证据
  **类型**：测试
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/model-release-validation.md`、`features/v3.0.0/059-k8s-runtime-backend/model-release-validation.json`
  **逻辑/验收**：按已确认口径只检查DM8/MySQL模型、类型/约束/登记和单Alembic head；另收CI双架构镜像/锁/离线物料证据，未执行架构和跨节点项明确限制，不算已测。
  **覆盖 AC:** AC-15、AC-39、AC-42、AC-48、AC-54、AC-55、AC-56
  **依赖:** T070、T067

### Wave 9

- [ ] **T072** — L2 代码审查及交付核对
  **类型**：审查
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/code-review.md`、`features/v3.0.0/059-k8s-runtime-backend/delivery-validation.json`
  **逻辑/验收**：按sdd-code-review技能以755d4456e5及release-line确认基准审查真实diff，修复边界/并发/权限/信息泄漏；核对所有任务L1和AC证据、Docker保留，更新design现状和交付证据；不自动合并/发tag。
  **覆盖 AC:** AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56
  **依赖:** T071

## 实际偏差记录

暂无实现偏差。推翻已确认 spec/design 时先按 SDD-Guide 第 3 节重新确认；普通实现落点同步 design，并在此留指针。

## 阶段记录

- 2026-10-21：用户确认修订设计；本轮拆解覆盖 55 条有效 AC，开始 tasks 自动审查；尚未宣称已实现或部署。

- 2026-10-21：T001 配置实现/验证通过；T006 客户端测试先行，红阶段为缺少待实现模块（12 passed / 17 errors），不把该阶段记为接口实现成功。

- 2026-10-22：公共修复已授权并进入发布线9d156f261c；继承产生的真实三head新增T074登记，保留原revision父链；为继承最新共享组件逐文件适配Vibe调用，未改变产品合同。

2026-10-22并行计划实施：用户明确授权主agent+三开发子agent；共同快照c90927b1f，独立工作树/文件owner，主agent唯一189写入者。新增清理/canary/发行脚本/harness任务补齐批准范围，未推翻D1–D8。

2026-10-22补充登记T109–T134：来自并行代码审查与实际环境准备发现的既有合同遗漏；任务登记晚于部分修复，红绿历史按各日志/agent报告原样记录，不倒填任务时间。正式双架构发行、109/189业务及故障验收保持未完成。

189实际CNI更新走pods/status维护其保留注解，暴露T111/T112原测试遗漏；重开该配对，补同UID/status不变的可信CNI metadata合法路径与伪造终态负例。原拒绝不会改为通配放行。

2026-10-22续办登记T145–T154：用户批准恢复围栏、CNI报告绑定和模型约束；真实环境发现Helm重置计划、原生构建发现context不匹配，补配对任务。模型草稿079e22fce已先保存，红绿历史按实际保留，不倒填。

2026-10-22续办L1：T111/T112、T143–T157及T161/T162代码合同已复核；runtime整套1058/10skip（最终Chart与finalizer另216/198定向），backend1587/18skip、模型组合44与跨库静态64通过。真实189旧canary已终态，Helm计划遗失后按精确UID自然到期恢复仍在复验；不据局部通过勾选T067–T072。

2026-10-22现场修复登记T164–T174：API subresource语法、真实存储控制器身份、未绑定Pod删除宽限规范化、PSA有效负例与dryRun计划撤销、native smoke目录可读权限。代码先后与红绿记录按实际提交及日志保留；本地runtime1129/10skip和集成安装263通过，真实15项探测、业务与故障仍由T067–T072验收，不以代码合同替代。

现场继续登记T175–T178：真实终态Pod也发生Core零宽限规范化；native SQLite固定初始化值不足以证明跨升级保留，补随机哨兵。修复与重新冻结候选镜像后再闭合L1。

T179–T182来自109真实诊断：真实PlatformClient没有node_plan，旧桩掩盖接线错误；Docker现有公开响应无K8s专属字段。采用真实客户端合同及明确形状分别修复，不以降低预检通过门槛替代。

T179/T180经真实PlatformClient签名GET配对（红5→绿37）完成；最终候选7e720073b完整runtime1184passed/10skipped。109真实平台安装诊断通过，业务仍在运行；T067–T072不提前完成。

T183/T184配对与主线组合135passed；109 r2 prepare/bootstrap真实API通过并启动独立journal平台回归。旧默认批次slug、审计和journal保留，未改产品删除语义。最终候选189四轮基线完成、原生amd64串行烟测中；T067–T072保持未完成。

T185/T186：189报告尚在86400秒有效期内，原公开诊断错误读取不存在的raw ready字段；配对红3/绿92后本地合入。T187/T188：109真实WAL读取失败，最小Docker复现确认只读挂载不能创建侧文件；禁止immutable忽略已提交WAL。发布线a77accb43没有runtime-manager模块，修复属于尚未合入发布线的托管特性，不能向发布线放孤立文件。

T187/T188：0af6eda1b已合入；相关离线52通过/3真实默认跳过，实际Docker三种WAL布局3通过；SQL拒写和事务一致性配对均通过，原有容器/网络不变。下一候选完整集成/原生及109业务复验仍待执行。

T189/T190：109修复后observe-v1真实通过；停用恢复时app先online，紧接数据GET遇到16167临时维护，稍后同op completed/cleanup complete及rows200确认。补验收工具同步，未将临时拒绝改成业务成功。

T189/T190经7b728fcb6配对15项先红后绿、完整93合同通过；同runtime镜像54b生产目录与新HEAD字节不变。109续办保留既有应用/journal，189报告过期真实拒绝16121/precheck_build/无审批已通过；恢复及其他负例继续真实验证。

T068完成：候选54b3ea2c1/Helm10第五实际探测16项+正常清理+真实公开诊断通过；三组报告负例实际发布16121/precheck_build/无审批操作并原样恢复、无manager重启。旧canary按自然到期同UID清理完毕，namespace Pod/PVC与计划均空。T067/T069/T070/T071/T072仍待完成。

T191–T193现场夹具补登记：109第四source-image真实失败16124/precheck_probe/startup_exited；该离线路径的空requirements与顶层SDK导入不自足，补显式可校验vendor物料，不更改生产模板、base或SDK正向断言。完整镜像需显式加入场景。

T194/T195：189 首个 bundle 的真实payload类型为payload.profile=dict、delivery.profile=str、resolved_delivery=None；只读复算在_plan:195重现AttributeError.get，未创建资源。修复解析对象与manifest引用混用，失败记录保留。

T191–T193：66e507ec8合入，170合同及裸Python禁网原生SDK/附件/SQLite/WS/certifi/TLS配对通过。依赖保持原始8wheel字节；scanner实际10文件扫描、8wheel按binary跳过、0命中；不宣称依赖源码已扫描，原展开模式3个假阳性证据保留。109/189真实source-image仍待复验。T194补OCI旧夹具缺失delivery字段，第二文件owner明确转给A。

T194/T195通过54488cdd4合入候选9e7e86cab；主树全runtime1217passed/13skipped，未跳过setuid参数；A权限上下文的04755→0755限制不代表宿主文件系统全局行为。170夹具/harness在真实backend conftest集成通过。190/195完成，5项真实交付/L2仍待；新候选原生及189真实重部署继续。

T196/T197：189四个失败draft的只读清理预检在GET instance收到16121，实际默认node配置正确；无assignment时控制API返回application_not_found/404，而manager未映射成无实例。补精确缺失与真正平台故障配对，不改清理工具来忽略故障。

T196/T197经0a8f5a252合入候选0e493c07a，真实client/HMAC/ASGI先红4/38、相关75全绿，主树完整runtime1259passed/13skipped。四个真实draft均只读确认application_not_found/404；新镜像清理链路待验，不修改工具绕过16121。192/197完成，正式CI/真实交付/L2仍pending。

T198/T199现场红例：189新prepare d0b665da84014b2fab43ef60f1b282b6、app2bde519a30f946a091f5ae4aa5cf2248，14:20:36领取epoch2/lease_until14:21:06；14:24:11开始永久renew409，尚无Pod/PVC且terminal fact也被拒绝。未修改租约，保留运行记录；修复与配对L1待合流。

T198/T199完成于00fbdce05/合流候选e4052d1c2：16新安全配对先红绿、相关173passed；主树完整runtime1275passed/13skipped（setuid未跳过），Ruff/架构守卫通过。明确保留首轮缺Helm的51工具失败记录。空闲失租仅精确lost fresh CAS恢复，未知响应当前动作拒绝；既有UID停止/新epoch事实与expired prepare只清理终结均覆盖。194/199完成；同PID真实空闲恢复与最新双架构验收进行中，不提前标业务交付。

T200/T201现场登记：189 e405/Helm12同Pod a7bc860e/restart0，旧过期op正常failed/cleanupcomplete；空闲后同holder epoch3→4并提交preparing fact成功，证明租约恢复。新r3资源注册503/AttributeError，backend校验仍混用manifest.profile字符串与解析对象；尚无Pod/PVC、失败正常cleanup。37条真实Service/SQLite配对先红26/11，独立测试提交ad8d028b7；补同样阶段对象边界，未扩大规格或放宽审批/镜像校验。

T200/T201/T202完成：新增37真实Service/SQLite合同先红26/11→全绿，完整backend首轮11旧fixture缺协议字段/1670passed/18skip；仅补真实kind/mode/prepare对象后完整1681passed/18skip，拒绝断言不动。新37与旧两模块Ruff/架构守卫通过。197/202完成，189按独立backend新源码复验；manager仍固定e405/f004镜像，不转标新backend SHA为该镜像来源。

2026-10-22 T203–T214现场收尾登记：用户优先K8s部署，暂停新增arm验证。真实189 r4 POST403后无UID意图永久unknown，新增单次创建事务及独立not_created路径；明确拒绝和未知响应分开，旧r4无持久receipt保持隔离/PVC，不追认或直接改SQL。模板fieldRef默认差异已本地精确复现，历史403原因未恢复；新安全枚举用于后续现场定位。

T203–T214 L1合流：runtime1328passed/13skip、backend1723passed/18skip；另4个真实双Session identity-map交错主树通过（旧逻辑内存插件对照4fail）。96测试任务、214总项、209完成；仅五真实交付/审查门pending。amd64709821ecb原生构建及bundle/SQLite烟测通过，不替代K8s平台闭环；本轮不新增arm测试/公开推送/tag。旧r4无creation证明保持held，其PVC不删。

2026-10-23 T215–T218：189 r5已真实创建/启动准备Pod并按同UID/kubelet终态正常清理，_diagnostic日志名单遗漏遮蔽原失败；补245相关回归。进一步无凭据对比证实TLS origin根material路径404而backend401，产品nginx也缺转发；仅限定该prefix补接线，完整签名/材料业务复验仍pending。

T217/T218主树材料相关80passed/1skip（本机无nginx代理集成）；189原生amd64完整产品nginx配置语法通过，首次去除CHOWN导致tmpfs目录初始化失败记录保留，最小CHOWN复验通过。现场TLS精确根路径新连接401/APIenv200，不替代signed transfer。213/218，五交付门仍pending。

T219/T220 L1合流：固定源码706b138614f029c52d7be49bbc50453e847f0fd4；旧实现3个关键配对红测明确因账本节点不一致失败，新executor134通过、相邻302通过；主树runtime1371passed/13skipped。仅executor35行增量，无backend/API/DDL变化。215/220、99测试任务；现场正常对账与业务验收进行中。

T219/T220真实恢复通过：189 Helm15/source706b；原失败op同UID首次node绑定→kubelet_terminal→三资源cleanupcomplete/APIabsent，全由正常对账执行。第三次正常发布8070bb…已接受，完整T069仍pending。

2026-10-23 T221–T224登记：r5第三次prepare inputs通过，resolve失败后正常cleanupcomplete。原fact3保留TypeError诊断，后续terminal cleanup重试fact4覆盖为failed_stage=failed/空tail。189隔离native helper A/B确认dependencies={}成功，仅lock:null触发os.environ赋值TypeError，非缺少wheel。修复可选字段合同及首次诊断保留，不补写历史事实。

T221–T224 L1合流：源143606851370d6091b120d348549329b8113c6a6，helper新增24配对/相关318通过；操作新增15配对/31操作及246相邻通过。主树runtime1410passed/13skip；219/224、101测试任务。helper相关首轮2个本机监听sandbox拒绝后原样授权复跑通过，未改用例跳过。189原生None/省略A/B根因已确认，新manager/helper及真实安装报告刷新进行中，无新ARM/公开发行。

集成追溯复核修正：仅T223新增测试曾沿用F086 AC-63，现按F059标注AC-48、AC-49、AC-52、AC-55；保留既有F086旧测试注释。T221模块覆盖补AC-47、AC-55；功能代码及143镜像冻结不变。

2026-10-23 T225–T227：r6 prepare8fb6b53a…的inputs/resolve/install/upload全部真实成功，4Pod同UID停止、8资源最终正常清理；单次cleanup返回pending被执行器误作preparation_cleanup_pending终态，平台16227/precheck_build。按既定有界异步对账合同修复，保留历史不复活操作；无新helper/API/DDL。

T225–T227开发收尾：当前222/227完成（103测试任务）；主树runtime1438passed/13skip、Ruff/format/arch/diff通过。首次旧selection预期失败/等待已保留，改为持久事实序列与虚拟时钟到期held后65相关通过。r6 fresh API逐一确认8资源消失，4Pod停止证明，proof SHA110aab26…；镜像/189业务续办不由这些本地通过替代。

2026-10-23 T228/T229：r7完整prepare已completed/cleanupcomplete，prepared_delivery与delivery一致；probe081663…在90秒内经历data-layout/schema-init/material-fetch，环境安装仅12秒即被统一readiness截止停止。cached镜像事件17:47:32→17:48:51→17:49:03证实串行阶段共用90秒，不把它误判为拉镜像/源码传输失败。按既定4.6阶段约束修复并保留原失败现场。

2026-10-23 T230/T231：只读交叉审查以真实cancel Service＋SQL＋Ed25519红例复现：owner已提交payload.cancel_requested，仍running/ready的数据会话可新签票据；manager RPC也未拒绝该标志。收紧当前授权而非增加取消业务或假装回滚，和T228/T229按独占文件并行。

T228–T231合流：来源a1de5271f5f00cef0cba06d41f09c673a9190525，runtime1483passed/13skip（32.30s），backend app_runtime/app_publish1734passed/19skip（48.25s）；两个模块Ruff/format及逐文件架构守卫通过。当前226/231、105测试任务，余五项保持验收/发行/L2门，不声明业务上线已通过。ARM暂缓。

2026-10-23 T232/T233：r8的4init合计96秒后probe appReady真实通过。当前同UID8c83f28c…已kubelet_terminal/stopconfirmed，finalizers缺省但deletionGracePeriodSeconds仍30，Pod仍存在。现有kubelet终态DELETE准入要求STOP finalizer尚在，形成移除finalizer后误拒。按同UID持久停止证明补窄分支，原操作未终态，期望修复后自然对账，不人工清理或复活。

T232/T233本地L1完成：1bd926bb2两文件先红4/203绿后准入208与邻接585通过；合流b5d243f0a全runtime1519passed/13skip（32.78s）。首次默认沙箱30fail/11error均为localhost绑定、setuid权限受限，授权重跑通过，原日志保留。r8原操作随后timed_out，未复活；清理修复后只让终态正常对账。新增T234/T235校正E2E75秒请求预算，产品持久期限不变。当前228/235、107测试任务；ARM暂停。

T234/T235通过21250d329合入d13e9ee91：新预算合同先红5/12绿，112合同全绿；主树完整backend1753passed/19skip（48.48s），runtime生产与已通过1519/13skip版本一致。开发修复已闭合，当前230/235；五项实际交付/发行/L2继续保留。189 Helm19已固定a06镜像4666d753…，r8原timed_out保持且4资源fresh API absent/cleanupcomplete；proof SHAa37f1bab…。r9新六场景仅采用d13验收工具源码，生产runtime与a06逐字节相同；不重标镜像来源。

T236/T237来自r10真实上线维护失败：probe、预览访问/拒绝、审批均真实通过；deploy d9729fe5…maintenance_phase_failed后正常cleanupcomplete，生产PVC保留。原Pod日志已清理，未声称取得现场KeyError；固定8a helper、非root/禁网/合成身份/空临时卷A/B证明缺MATERIAL_POD_UID报KeyError，只注入UID则backup(None)通过。模板确实漏配maintenance UID，按原材料身份合同补配对，不放宽权限。

T236/T237已通过79a15870f合入249d5fc85：模板→实际身份reader先红2/11正反绿，534相邻全绿；主树完整runtime1532passed/13skip（32.72s）及静态门通过。原生amd64构建/导入后私有digest42c6c3c5…、Helm20同源三个控制服务更新，descriptor/helper143/profile2和有效报告不变，平台ready/controller_epoch15。owner fresh核旧failed/cleanupcomplete、同已批准version/approval后，仅一次manual-publish新attempt已提交；结果pending不重发，原r10套件期限900秒不延长。当前232/237，真实业务/故障/发行/L2门保留。

2026-10-23 T238/T239：r10首版observe真实通过，停用9f57c389…被两个同名但已闭合维护UID拦住。464bf9027两行精确合取条件跳过历史Pod；红2/62→479相关通过，当前服务UID及未知状态围栏不变，全操作cleanup等待保留。登记与L1按实际先后记录。原停用deadline19:27:30已自然过期、仍running/pending，续办suite正常失败退出；不能延时或复活，另核过期清理闭环。234/239，109测试任务。

2026-10-23 T240/T241：原停用过期claim被拒，_failure只清自身空资源却误报全app已停，被正确的backend全writer guard409拒绝，造成running循环。先登记测试/实现；先真实终态pending回执再原有own cleanup，不延时期限、不放宽后端。234/241、110测试任务。

T240/T241首轮独立复核发现503恢复阻断，NEEDS_FIX，仍pending。d489全runtime1570/13skip及原生构建通过只对应该中间候选，尚未push/部署；修订后重新冻结最终镜像，不能覆盖首轮失败与证据。

T240/T241复审闭合：0bd6aa173合入d7c0cc4fd；503恢复精确到期清理与期限内正常stop两配对先红2/1绿，96操作及511相邻通过，独立96/静态复审PASS。主树全runtime1573passed/13skip（32.88s）。非精确expiry的不确定stop保留active非终态，不制造failed死锁；原terminal非timeout首因保持。236/241，剩五项真实验收/发行/L2门，不能由本地通过代替。

T242–T245：Helm21/source d7已使原stop真实timed_out/cleanupcomplete，同UID停止/APIabsent/PVC原UID保留。首个停用rows数据动作done但ready55秒、清理69秒超原60秒；offline data4b25…失败保留。189同8a helper非root/禁网/128MiB导入25m耗31.699s/0.7926CPU，100m耗6.9965s/0.6971CPU。仅把离线Pod CPU参数与真实预占调100m（所有容器串行init同预算），不改60秒/同步响应/单writer/sidecar。此为实现资源参数修正，不推翻D1–D8或AC。236/245、112测试任务。

T242–T245 L1闭合：992905292与f84415f25同源合流6f254f337；backend两行+runtime单行。backend初红4/31绿，95相关通过；模板初红2/95绿，598相关通过。主树完整runtime1586passed/13skip（34.14s）、backend1764passed/19skip（50.14s），Ruff/format/逐文件guard/diff通过。240/245，五真实验收/发行/L2门保持；189实际100m新数据会话待复验。

T246/T247现场登记：r10 static probe UID2d74bfe5…全部init成功、app exit127；同固定2f0311镜像在bundle受控PATH无法找到nginx，补全标准sbin后/usr/sbin/nginx与实际entrypoint nginx -t成功。根因为模板PATH遗漏而非缺镜像/源码。240/247、113测试任务；原失败和期限保持，不手工改Pod。

T246/T247 L1闭合：9项bundle运行时/阶段配对先红，模板106、完整runtime1595passed/13skip（33.42s），独立292相关合同及PATH/secret拒绝补核通过；Ruff/format/逐文件guard/diff通过。真实同镜像sbin A/B及entrypoint nginx -t通过不替代K8s复验。242/247、113测试；r10原static失败终态和四资源同UID正常cleanup已冻结，恢复使用独立新attempt，不延长或复活旧操作。

T248/T249现场登记：源码准备70eb72dbbbf44e00a7c536507bfcca35安装及上传完成，组装器oci_privilege_bits_refused；操作failed/cleanupcomplete。只读stat保留scratch34/claimUID47a1e29e-b55f-46ec-955f-759ef174e2b1：267个SGID目录、零带特殊位普通文件，fsGroup继承与固定OCI归档拒绝冲突。仅归档去掉目录SGID，不放行SUID目录或带特殊位文件；D7既定安全合同内实现补漏。242/249、114测试任务。

T250/T251登记：独立审查发现OCI固定PATH与T247修复前完全相同且缺sbin；同固定2f0311静态镜像的原生red127/green nginx -t已证明该路径需求。补齐源码交付相同启动合同，独立配对测试，不改用户镜像模式。242/251、115测试任务。

T248–T251 L1闭合：SGID真实目录2正例先红/10危险位拒绝已绿；OCI PATH三运行时3项先红；最终完整runtime1610passed/13skip（33.01s），Ruff/format/逐文件guard/diff通过。产品改动仅oci_assembler一处权限分类和一条PATH；既有来源/凭据/固定布局不变。246/251、115测试，真实源码新attempt和能力报告刷新仍待执行。
