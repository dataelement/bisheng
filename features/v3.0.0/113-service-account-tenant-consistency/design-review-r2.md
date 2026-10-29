# F113 设计复审 R2

> 历史发现记录：三项设计问题已在[修订复审 R3](./design-review-r3.md)关闭；以下结论针对修订前设计，不表示业务代码已修复。

日期：2026-10-28。依据用户“先评审设计”，由主 agent 重新按 `sdd-review` 的 24 项清单核对规格和实际调用链；不是独立代理评审。

**结论：NEEDS_FIX。发现 2 项 high、1 项 medium，暂不进入任务拆解和编码。** 上一轮自审的 LGTM 作为历史记录保留，本报告是当前评审结论。

被审文件：[design.md](./design.md)，SHA-256：`3a38f9afe674ad09d05661c2fcb6bb1e3aa9628d2a5125bb65c52381b8207196`。源码基线：`3d0406bc6615a4c04dcc3e846879d8e7524df47f`。本次仅静态复审，没有业务代码、规格 AC、数据库或环境修改，没有执行功能测试。

## 1. 发现项

ISSUE: §4.3 的应用读取接线遗漏发布状态入口；只修 AppQueryService 不会修复 PublishStatusService 的平台 owner 短路，迁出人员仍可能通过直接请求读取原 Root 租户应用的版本、审批和部署详情 | SEVERITY: high | LOC: design.md:126

### R2-01：补齐发布状态读取的独立入口

- **依据**：AC-29、AC-36、AC-37。规格要求原 owner 在新租户不能仅凭 owner 相同读取旧租户应用状态/版本。
- **实际调用链**：`GET /api/v1/apps/{app_id}/publish-status` → `PublishStatusService.get_publish_status` → `_require_viewer`。该路径不调用 `AppQueryService._load_visible`。`_require_viewer` 的平台分支在 owner 相等时直接返回；只有 CLI/MCP 分支当前先检查租户。见 [平台路由](../../../src/backend/bisheng/app_publish/api/endpoints/publish_status.py:49)、[授权分支](../../../src/backend/bisheng/app_publish/domain/services/publish_status_service.py:205)。
- **影响**：对于本次已确认的 Root 资源共享查询场景，目标 App 仍可能被底层查询加载；补上详情页和日志校验后，直接请求 publish-status 仍可能返回 current/pending 版本、failure、approval、capabilities 等内容。不能把“页面无法打开”当作独立 API 已经拒绝。
- **建议**：在设计动作矩阵登记平台 publish-status 的真实接线点，将租户边界放在其 owner 分支之前。CLI/MCP 保留 owner-only，同租户权限和原超管例外不扩大。纯内部 `runtime_hint` 保持由已授权调用方约束，勿直接套用不存在的自然人身份。
- **必要定向验证**：同 owner、不同租户直接请求平台 publish-status 被拒绝，且不进入发布详情装配；同租户 owner、无权用户与原超管分别配对。旧 Root 应用为关键用例。

ISSUE: §4.3 没有覆盖版本审阅、源码树/文件和差异的 ReviewAccess owner 分支；仅校验版本列表，或仅在新预览时检查发布资格，不能阻止迁出 owner 继续读取旧应用源码 | SEVERITY: high | LOC: design.md:126

### R2-02：补齐源码与版本审阅的租户边界

- **依据**：AC-29 的“不新增跨租户可见或管理例外”和 AC-36、AC-37 的版本读取及调用者来源约束。
- **实际调用链**：版本审阅上下文、源码树、源码文件通过 `SnapshotBrowseService`，差异通过 `VersionDiffService`，统一进入 `ReviewAccess.require`。该函数首先按 owner ID 返回 `ROLE_OWNER`，不核对 actor 的认证租户。`ReviewAccess.load_app` 只经 `VersionService.get_app_scoped` 调用 AppDao，仍受 Root 共享行规则影响。见 [owner 分支](../../../src/backend/bisheng/app_publish/domain/services/snapshot_browse_service.py:103)、[源码读取](../../../src/backend/bisheng/app_publish/domain/services/snapshot_browse_service.py:247)、[版本差异](../../../src/backend/bisheng/app_publish/domain/services/version_diff_service.py:120)。
- **影响**：即使应用详情、版本列表和新预览均已拒绝，知道原 app/version 引用的迁出 owner 仍可能直接读取源码内容或差异。新预览的冻结 owner 校验不会保护这些只读入口。
- **建议**：将 ReviewAccess 及其全部消费者加入动作/权限矩阵。owner 和租户管理员分支应按认证租户限定；单独说明原有超管、持有审批任务的审阅者如何按既有合同校验，不能把所有审阅者一律当 owner，也不能新增“旧 owner 是审批人”的隐含放行。若已有明确审批任务例外，保留可信任务来源和版本对应关系并明确边界。
- **必要定向验证**：迁出 owner 对 review-context、tree、file、diff 的直接请求拒绝，且拒绝发生在读取源码快照前；原同租户 owner、无权用户、超管和合法审批审阅者配对，验证未误伤原审阅入口。

ISSUE: §4.3/§4.4 要求可信后台来源且禁止伪造调用者，但未定义审批正式启动如何替换现有 _owner_actor → 人工 publish 调用链，内部与人工启动的契约不闭合 | SEVERITY: medium | LOC: design.md:136

### R2-03：明确审批正式启动的可信调用接口

- **依据**：AC-14、AC-34、AC-37、AC-38；设计自身要求“无 actor 不作为通用豁免”“不构造来自 App 租户的假登录用户”。
- **实际调用链**：`bring_online` → `_settle` → `AppStateService.publish(actor=_owner_actor(app))`。`_owner_actor` 根据目标 App 构造 `user_id/tenant_id`，并不是本次请求的认证身份。设计为内部元信息明确了 `update_meta_for_release(deployment_id)`，但为正式启动仅写了 stage 入口，没有给出相应接口和接线。见 [调用点](../../../src/backend/bisheng/app_publish/domain/services/publish_online_service.py:259)、[构造身份](../../../src/backend/bisheng/app_publish/domain/services/publish_online_service.py:544)。
- **影响**：接手者可能继续保留目标 App 构造的 actor，使新人工租户闸门仅检查自填身份；也可能直接移除 actor 导致正常审批启动被拒绝。stage 前资格检查方向正确，但不能代替对“哪个入口可代表审批执行启动”的定义。
- **建议**：补充一个明确的内部批准版本启动契约（名称可在修订时确定），说明调用者、可信 deployment/approval/version 引用、租户与版本校验、状态唯一写入方和审计身份。人工 publish/manual/resume 与后台批准执行分别接入，共用原启动实现，不能新增外部无身份端点或重写状态机。明确替换 `_settle` 的 synthetic owner 调用；发布页 manual-publish 的人工租户/权限和冻结资格检查须在 `_settle` 的协议 v1 数据迁移前完成，而非只放在最后的 `_start`。
- **必要定向验证**：真实批准来源允许、引用不匹配/缺失拒绝、人工跨租户拒绝且迁移未调用；旧批准版本自动恢复仍走原可信任务合同。只测这些接线，不要求重跑完整编排或通用审批流程。

## 2. 24 项清单复核

| 检查项 | 复审结果 |
|---|---|
| 1–8：目标、边界、特有约束、宪法及决策依据 | 未发现新的阻断项；无新增表、无资源迁移、独立权限主体和共享 scope 决策保持 |
| 9–12：数据流、契约、模块职责、规格一致 | **未通过**：F055 发布状态与版本源码读取接线遗漏；后台正式启动调用流未闭合 |
| 13–15：反直觉事实、影响、处理位置 | 需补充上述 F055 独立读取路径和 synthetic owner 启动事实 |
| 16–18：提供/依赖契约和风险 | **未通过**：审批正式启动的可信内部接口缺少完整契约 |
| 19–20：定向测试、可执行验收路线 | 总体策略通过；须补上 R2-01 至 R2-03 的允许/拒绝配对，不扩大到全量测试 |
| 21–24：后续边界、历史、规格一致、任务偏差 | 无 tasks/实现偏差；规格不必为本次遗漏改目标，设计待修并复审 |

## 3. 下一步

修订设计及同步 HTML，补齐上述接线和定向测试映射后再次评审。未获得设计单独确认，不拆任务或编码。上述是设计与当前源码的静态发现，不宣称在116复现或完成验收。
