# Tasks: F059 K8s 应用托管执行后端

**关联**：[spec.md](./spec.md) · [design.md](./design.md) · [任务评审](./tasks-review.md)

## SDD 状态

| 文档/阶段 | 状态 | 依据 |
| --- | --- | --- |
| Spec Discovery | ✅ 已确认 | 会话确认开源交付及 K8s 续办范围 |
| spec.md | ✅ 已评审、用户已确认 | 55 条有效 AC；规格确认不替代设计确认 |
| design.md | ✅ 已评审、用户已确认 | 用户明确回复“确认设计，进入任务拆解，继续推进 SDD 流程。”；确认正文摘要 b846e993909cda416502d33fdbf6b2174357068673840c2fc0f7d75fe9dc76a4 |
| tasks.md | ✅ 已拆解、评审通过 | tasks-review.txt 为 LGTM；76 项任务按依赖推进，无新增人审暂停点 |
| 实现/任务评审 | 🟡 实施中 | 33 / 76 完成；详见 task-reviews.md |
| E2E/L2审查 | 🔲 未开始 | 189 先前仅只读盘点，不能以静态检查代替真实验收 |

## 开发模式

沿用已附加工作树 `codex/059-k8s-runtime@755d4456e5`。顺序执行，各任务最多两个目标文件；测试先于对应实现，infra 配置/模型/锁/安装清单无需强行编写镜像实现的测试。独立验证已有批准的拒绝/故障合同。

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

- [ ] **T030** — 受信材料 helper 与离线环境物化：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_helper.py`
  **逻辑/验收**：material-fetch 只安全取冻结材料；无凭据 environment 阶段在固定 /opt/venv/Node/static 路径物化；prepare 分下载/安装编译/上传独立 Pod，代码不会借传输身份执行；环境键包含 profile/ABI/架构/锁/安装输入；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-16、AC-24、AC-25、AC-26、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T009、T029
  **配对:** T031

- [ ] **T031** — 受信材料 helper 与离线环境物化
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_helper.py`、`src/runtime-manager/runtime_manager/k8s_prepare.py`
  **逻辑/验收**：material-fetch 只安全取冻结材料；无凭据 environment 阶段在固定 /opt/venv/Node/static 路径物化；prepare 分下载/安装编译/上传独立 Pod，代码不会借传输身份执行；环境键包含 profile/ABI/架构/锁/安装输入；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-16、AC-24、AC-25、AC-26、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T009、T029、T030
  **配对:** T030

- [ ] **T032** — K8s 执行能力与资源操作：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_kubernetes_executor.py`
  **逻辑/验收**：实现 prepare/launch/observe/request_stop/confirm_stopped/cleanup/logs/data 能力，只有 adapter 拼 Core API；固定名称/UID 账本、Service就绪端点、bounded wait、平台资源事实及数据/维护前后 stop 闸口；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-04、AC-05、AC-07、AC-08、AC-09、AC-11、AC-18、AC-33、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T031、T011、T019
  **配对:** T033

- [ ] **T033** — K8s 执行能力与资源操作
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/kubernetes.py`、`src/runtime-manager/runtime_manager/executors/protocol.py`
  **逻辑/验收**：实现 prepare/launch/observe/request_stop/confirm_stopped/cleanup/logs/data 能力，只有 adapter 拼 Core API；固定名称/UID 账本、Service就绪端点、bounded wait、平台资源事实及数据/维护前后 stop 闸口；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-04、AC-05、AC-07、AC-08、AC-09、AC-11、AC-18、AC-33、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T031、T011、T019、T032
  **配对:** T032

- [ ] **T034** — Docker 能力适配且保留旧合同：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_docker_executor.py`
  **逻辑/验收**：抽离既有 Docker/本机路径算法到适配器，通用 checkpoint/facts/操作归属保留；基于现有三路径/生命周期测试比较原输入输出，不用假 K8s API 模拟 Docker；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-01、AC-04、AC-10、AC-36、AC-37、AC-56
  **依赖:** T033
  **配对:** T035

- [ ] **T035** — Docker 能力适配且保留旧合同
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/executors/docker.py`、`src/runtime-manager/runtime_manager/operations.py`
  **逻辑/验收**：抽离既有 Docker/本机路径算法到适配器，通用 checkpoint/facts/操作归属保留；基于现有三路径/生命周期测试比较原输入输出，不用假 K8s API 模拟 Docker；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-01、AC-04、AC-10、AC-36、AC-37、AC-56
  **依赖:** T033、T034
  **配对:** T034

- [ ] **T036** — 通用操作状态机和 composition root：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_executor_selection.py`
  **逻辑/验收**：按配置选唯一执行器并共用操作状态/事实编排；K8s 不初始化 Docker 或 v1本地循环；不接受调用方执行路径/PodSpec，重复唤醒、manager关闭/恢复、待上线前后容量语义保持；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-01、AC-02、AC-04、AC-05、AC-07、AC-08、AC-09、AC-36、AC-37、AC-39、AC-48、AC-56
  **依赖:** T035
  **配对:** T037

- [ ] **T037** — 通用操作状态机和 composition root
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/operations.py`、`src/runtime-manager/runtime_manager/api/operations.py`
  **逻辑/验收**：按配置选唯一执行器并共用操作状态/事实编排；K8s 不初始化 Docker 或 v1本地循环；不接受调用方执行路径/PodSpec，重复唤醒、manager关闭/恢复、待上线前后容量语义保持；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-01、AC-02、AC-04、AC-05、AC-07、AC-08、AC-09、AC-36、AC-37、AC-39、AC-48、AC-56
  **依赖:** T035、T036
  **配对:** T036

- [ ] **T038** — 状态、日志和能力 API：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_observe.py`
  **逻辑/验收**：保留业务 API 范围、since/tail/脱敏，仅读取 app/previous 和删除前有界诊断；新增认证 capabilities，前置 blocked 原因清楚；健康存活不冒充已就绪，K8s禁用v1编排注册；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-02、AC-07、AC-10、AC-30、AC-31、AC-32、AC-36、AC-37、AC-40、AC-53
  **依赖:** T037
  **配对:** T039

- [ ] **T039** — 状态、日志和能力 API
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/api/platform_observe.py`、`src/runtime-manager/runtime_manager/main.py`
  **逻辑/验收**：保留业务 API 范围、since/tail/脱敏，仅读取 app/previous 和删除前有界诊断；新增认证 capabilities，前置 blocked 原因清楚；健康存活不冒充已就绪，K8s禁用v1编排注册；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-02、AC-07、AC-10、AC-30、AC-31、AC-32、AC-36、AC-37、AC-40、AC-53
  **依赖:** T037、T038
  **配对:** T038

### Wave 5

- [ ] **T040** — 数据 helper 动作票据与 journal：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_data_helper.py`
  **逻辑/验收**：只持 backend 公钥；5秒受理票据绑定 app/UID/action/body/nonce，有界60秒执行和串行；platform目录持久started/done，未知不重做；owner数据白名单SQL和流式导出，结果查询新只读ID指向原ID；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-16、AC-33、AC-34、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T021、T009
  **配对:** T041

- [ ] **T041** — 数据 helper 动作票据与 journal
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_data_helper.py`、`src/runtime-manager/runtime_manager/data_grant.py`
  **逻辑/验收**：只持 backend 公钥；5秒受理票据绑定 app/UID/action/body/nonce，有界60秒执行和串行；platform目录持久started/done，未知不重做；owner数据白名单SQL和流式导出，结果查询新只读ID指向原ID；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-16、AC-33、AC-34、AC-36、AC-37、AC-43、AC-48、AC-50
  **依赖:** T021、T009、T040
  **配对:** T040

- [ ] **T042** — owner 数据会话业务协调：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_sessions.py`
  **逻辑/验收**：在原权限/确认/审计后创建内部 kind=data；不改 serving代次/App态，数据/迁移/停用/部署互斥；事务先提交再唤醒，在线复用helper，停用冷启动也计入60秒，超时不等于cleanup；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-35、AC-36、AC-37、AC-43、AC-48、AC-49、AC-50
  **依赖:** T017、T041
  **配对:** T043

- [ ] **T043** — owner 数据会话业务协调
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_session_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_data_service.py`
  **逻辑/验收**：在原权限/确认/审计后创建内部 kind=data；不改 serving代次/App态，数据/迁移/停用/部署互斥；事务先提交再唤醒，在线复用helper，停用冷启动也计入60秒，超时不等于cleanup；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-35、AC-36、AC-37、AC-43、AC-48、AC-49、AC-50
  **依赖:** T017、T041、T042
  **配对:** T042

- [ ] **T044** — K8s 在线及停用数据执行：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_data_executor.py`
  **逻辑/验收**：在线同Pod访问；停用仅在旧UID stopped且空生产位置启动 purpose=data，保留PVC/停用态，不创建业务Service；数据忙/未知拒绝，stop确认后释放预占与互斥，manager不签owner票据；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-11、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T043、T033
  **配对:** T045

- [ ] **T045** — K8s 在线及停用数据执行
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_data_executor.py`、`src/runtime-manager/runtime_manager/api/platform_data.py`
  **逻辑/验收**：在线同Pod访问；停用仅在旧UID stopped且空生产位置启动 purpose=data，保留PVC/停用态，不创建业务Service；数据忙/未知拒绝，stop确认后释放预占与互斥，manager不签owner票据；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-11、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52
  **依赖:** T043、T033、T044
  **配对:** T044

- [ ] **T046** — K8s SQLite 备份迁移恢复：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_appdb.py`
  **逻辑/验收**：停整个生产Pod后维护独占卷；复用appdb plan_digest/SQLite原子迁移journal，backup/integrity/fsync，平台内容与关联确认后才DDL；保护当前数据后恢复，失败保留maintenance和data_may_have_changed，不自动数据回滚；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-33、AC-34、AC-35、AC-46、AC-49、AC-50、AC-51、AC-52
  **依赖:** T045、T029
  **配对:** T047

- [ ] **T047** — K8s SQLite 备份迁移恢复
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_appdb.py`、`src/runtime-manager/runtime_manager/k8s_data_helper.py`
  **逻辑/验收**：停整个生产Pod后维护独占卷；复用appdb plan_digest/SQLite原子迁移journal，backup/integrity/fsync，平台内容与关联确认后才DDL；保护当前数据后恢复，失败保留maintenance和data_may_have_changed，不自动数据回滚；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-33、AC-34、AC-35、AC-46、AC-49、AC-50、AC-51、AC-52
  **依赖:** T045、T029、T046
  **配对:** T046

- [ ] **T048** — backend 数据动作签发及路由：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_data_grants.py`
  **逻辑/验收**：原业务Service重新核验actor及当前data操作/UID后本地签发；不向manager提供通用签发API。data操作和查询结果授权原地失效，非owner、重放、错UID拒绝；管理身份不能自签；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48
  **依赖:** T043、T047
  **配对:** T049

- [ ] **T049** — backend 数据动作签发及路由
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_data_grant_service.py`、`src/backend/bisheng/app_runtime/api/endpoints/runtime_kubernetes.py`
  **逻辑/验收**：原业务Service重新核验actor及当前data操作/UID后本地签发；不向manager提供通用签发API。data操作和查询结果授权原地失效，非owner、重放、错UID拒绝；管理身份不能自签；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-36、AC-37、AC-43、AC-48
  **依赖:** T043、T047、T048
  **配对:** T048

### Wave 6

- [ ] **T050** — 三种交付模式的 K8s 准备链：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_delivery.py`
  **逻辑/验收**：Python3.11/Node20/static bundle预检、完整镜像直启、显式source-image准备；依赖材料命中与失效、新增依赖缺包/补包、安全解包；任务阶段独立身份/卷/限额/并发，启动失败不产生审批；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-08、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T033、T047
  **配对:** T051

- [ ] **T051** — 三种交付模式的 K8s 准备链
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_prepare.py`、`src/runtime-manager/runtime_manager/executors/kubernetes.py`
  **逻辑/验收**：Python3.11/Node20/static bundle预检、完整镜像直启、显式source-image准备；依赖材料命中与失效、新增依赖缺包/补包、安全解包；任务阶段独立身份/卷/限额/并发，启动失败不产生审批；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-08、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54
  **依赖:** T033、T047、T050
  **配对:** T050

- [ ] **T052** — 无守护进程的受限 OCI 组装：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_oci_assembler.py`
  **逻辑/验收**：固定布局追加冻结基础镜像并设置既有启动语义；不执行RUN/Dockerfile，拒绝逃逸、设备/setuid/whiteout/外部硬链；仓库身份仅受信组装器使用，缺推送仓库仅阻断source-image；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-15、AC-16、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T051
  **配对:** T053

- [ ] **T053** — 无守护进程的受限 OCI 组装
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/oci_assembler.py`、`src/runtime-manager/Dockerfile.assembler`
  **逻辑/验收**：固定布局追加冻结基础镜像并设置既有启动语义；不执行RUN/Dockerfile，拒绝逃逸、设备/setuid/whiteout/外部硬链；仓库身份仅受信组装器使用，缺推送仓库仅阻断source-image；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-15、AC-16、AC-25、AC-27、AC-28、AC-42、AC-54
  **依赖:** T051、T052
  **配对:** T052

- [ ] **T054** — 隔离和安装前置的实际能力探测：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_capabilities.py`
  **逻辑/验收**：分项验证namespace预算、PSA/准入、status认证、存储锁/fsync、精确CRI镜像、网络允许/拒绝、材料/能力接口；必需隔离失败/未知拒绝，沙箱仅回退满足基线档；无SC但预置卷可用；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-12、AC-13、AC-16、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-42、AC-54
  **依赖:** T013、T039、T053
  **配对:** T055

- [ ] **T055** — 隔离和安装前置的实际能力探测
  **类型**：实现
  **文件**：`src/runtime-manager/runtime_manager/k8s_capabilities.py`、`src/runtime-manager/runtime_manager/k8s_templates.py`
  **逻辑/验收**：分项验证namespace预算、PSA/准入、status认证、存储锁/fsync、精确CRI镜像、网络允许/拒绝、材料/能力接口；必需隔离失败/未知拒绝，沙箱仅回退满足基线档；无SC但预置卷可用；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-12、AC-13、AC-16、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-42、AC-54
  **依赖:** T013、T039、T053、T054
  **配对:** T054

- [ ] **T056** — 材料用途的出站投影：契约与失败用例
  **类型**：测试
  **文件**：`src/backend/test/app_runtime/test_runtime_material_egress.py`
  **逻辑/验收**：material代理身份由当前材料授权投影，独立于完成的prepare；只放行后台材料TLS端点和范围，撤销5秒上界，业务凭据不冒用；入口路由继续backendSQL投影不依赖manager；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-07、AC-12、AC-15、AC-21、AC-23、AC-46、AC-47、AC-53
  **依赖:** T023、T055
  **配对:** T057

- [ ] **T057** — 材料用途的出站投影
  **类型**：实现
  **文件**：`src/backend/bisheng/app_runtime/domain/services/runtime_material_policy_service.py`、`src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py`
  **逻辑/验收**：material代理身份由当前材料授权投影，独立于完成的prepare；只放行后台材料TLS端点和范围，撤销5秒上界，业务凭据不冒用；入口路由继续backendSQL投影不依赖manager；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-07、AC-12、AC-15、AC-21、AC-23、AC-46、AC-47、AC-53
  **依赖:** T023、T055、T056
  **配对:** T056

### Wave 7

- [ ] **T058** — Chart 入口与 values schema
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/Chart.yaml`、`deploy/kubernetes/app-runtime/values.yaml`
  **逻辑/验收**：按design固定platform/services/execution/storage/network/admission/images/offline分组，所有镜像精确引用、禁默认公网兜底与自动平台核心部署。
  **覆盖 AC:** AC-39、AC-42、AC-54
  **依赖:** T057

- [ ] **T059** — 部署参数及共享入口校验
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/values.schema.json`、`deploy/kubernetes/app-runtime/templates/services.yaml`
  **逻辑/验收**：校验必需字段与形态，私网共享entry/control由安装者供应，禁止按应用外放端口；控制端点ACL及HMAC，外部backend可达性独立验证。
  **覆盖 AC:** AC-12、AC-31、AC-39
  **依赖:** T058

- [ ] **T060** — RBAC 与准入安装模板
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/rbac.yaml`、`deploy/kubernetes/app-runtime/templates/admission.yaml`
  **逻辑/验收**：namespace manager最小权限，系统服务不可被manager改，验证器无集群token；status/template规则分别Fail/None，PSA restricted1.28；卸载不删除保护namespace/PV。
  **覆盖 AC:** AC-03、AC-13、AC-14、AC-15、AC-16、AC-23、AC-39、AC-41、AC-49
  **依赖:** T059、T013

- [ ] **T061** — 网络和保留卷安装模板
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/network.yaml`、`deploy/kubernetes/app-runtime/templates/storage.yaml`
  **逻辑/验收**：默认deny，允许entry/manager受控端口、只经egress出站、无业务DNS直连；localPV节点绑定或验证CSI，独占卷不带Pod/Helm级联删除owner，预置scratch池和限制。
  **覆盖 AC:** AC-12、AC-21、AC-22、AC-23、AC-33、AC-34、AC-35、AC-39、AC-41、AC-42
  **依赖:** T060

- [ ] **T062** — 运行服务与 helper 镜像
  **类型**：基础设施
  **文件**：`deploy/kubernetes/app-runtime/templates/workloads.yaml`、`src/runtime-manager/Dockerfile.helper`
  **逻辑/验收**：独立manager/app-proxy/egress/admission进程，只有manager投射限定token，helper固定受信命令非root/只读；控制面重启不连带删除应用Pod或改变冻结profile。
  **覆盖 AC:** AC-03、AC-15、AC-16、AC-39、AC-40、AC-42、AC-54
  **依赖:** T061

- [ ] **T063** — 同版本双架构 CI/CD 发行
  **类型**：基础设施
  **文件**：`.github/workflows/runtime-images.yml`、`src/runtime-manager/runtime_manager/image_catalog.py`
  **逻辑/验收**：扩展已有tag v*/手工入口，发布helper/admission/assembler及runtime镜像清单与licenses；amd64/arm64原生构建，compose已发行镜像引用合同不退化；不改用户tag/自动推送。
  **覆盖 AC:** AC-24、AC-27、AC-39、AC-42、AC-54、AC-56
  **依赖:** T062

- [ ] **T064** — 部署/离线清单验证：契约与失败用例
  **类型**：测试
  **文件**：`src/runtime-manager/tests/test_k8s_installation.py`
  **逻辑/验收**：可重复read-only预检及专用namespace允许/拒绝探测；离线镜像/依赖/平台接口分别核对，CRI按冻结引用真启动；说明本地卷限制、升级兼容、原卷保留和安全卸载，不输出kubeconfig/token；测试只定义输入/结果，不加入实现。
  **覆盖 AC:** AC-13、AC-14、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-35、AC-39、AC-40、AC-41、AC-42、AC-54、AC-55
  **依赖:** T063、T055
  **配对:** T065

- [ ] **T065** — 部署/离线清单验证
  **类型**：实现
  **文件**：`scripts/verify_k8s_runtime.py`、`deploy/kubernetes/app-runtime/README.md`
  **逻辑/验收**：可重复read-only预检及专用namespace允许/拒绝探测；离线镜像/依赖/平台接口分别核对，CRI按冻结引用真启动；说明本地卷限制、升级兼容、原卷保留和安全卸载，不输出kubeconfig/token；通过配对测试后完成 L1 task-review。
  **覆盖 AC:** AC-13、AC-14、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-35、AC-39、AC-40、AC-41、AC-42、AC-54、AC-55
  **依赖:** T063、T055、T064
  **配对:** T064

### Wave 8

- [ ] **T066** — 真实平台 K8s E2E 执行器
  **类型**：测试
  **文件**：`scripts/e2e_k8s_runtime.py`、`features/v3.0.0/059-k8s-runtime-backend/e2e-checklist.md`
  **逻辑/验收**：按e2e-test skill复用平台认证/CLI/审批/SDK/数据业务入口，生成55条AC用例映射、危险前置和cleanup；不是只调manager API，不把mock记为真实成功；凭据从安全环境/主机既有配置读取。
  **覆盖 AC:** AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56
  **依赖:** T065、T049、T005

- [ ] **T067** — Docker 与平台回归
  **类型**：测试
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/docker-regression.md`、`features/v3.0.0/059-k8s-runtime-backend/docker-regression.json`
  **逻辑/验收**：运行相同原有测试选择与首轮基线比对；三种交付/状态/SDK/附件/数据/权限，标真实与模拟；原F086共享修复按release来源继承。
  **覆盖 AC:** AC-01、AC-02、AC-04、AC-10、AC-24、AC-36、AC-37、AC-46、AC-53、AC-56
  **依赖:** T066

- [ ] **T068** — 189 专用资源安装验收
  **类型**：测试
  **文件**：`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/installation.json`、`features/v3.0.0/059-k8s-runtime-backend/e2e-evidence/installation.md`
  **逻辑/验收**：在192.168.106.189重新只读核对UID，再安装专用e2e-f059资源、合格local PV/PVC和镜像；验证真实拒绝与允许、包源/材料/SDK连通，保留原资源清单，不修改既有kube-system。
  **覆盖 AC:** AC-03、AC-12、AC-13、AC-14、AC-16、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-33、AC-34、AC-39、AC-42、AC-54、AC-55
  **依赖:** T067

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
  **依赖:** T070

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
