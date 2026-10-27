**Verdict: REVISE — 存在 1 项阻塞问题和 1 项应修正问题；这是设计建议，不代表实施授权。**

| 维度 | 评价 | 依据 |
|---|---|---|
| Requirements and quality attributes | 🟡 Yellow | 新增密钥、OBO 和审计需求大体覆盖，但既有实例的隔离持续性及凭据回收留痕尚未闭环。 |
| Boundary quality | 🟡 Yellow | Owner 边界清楚；凭据回收的实际写方未进入新增审计生产合同。 |
| Pattern restraint | 🟢 Green | 复用现有 operation、执行器及专表，没有引入通用工作流或统一审计大表。 |
| Data/state modeling | 🟢 Green | revision、guard、执行事实、同一事务 receipt，以及导出 attempt/epoch 的关系已明确。 |
| YAGNI/change tolerance | 🟢 Green | 明确排除部署 key 轮换、热加载及外部 Vault，范围适当。 |
| Failure/scale realism | 🔴 Red | 宿主隔离失效后的动作仅限制新操作，无法收敛仍在运行的应用。 |
| Decision capture | 🟢 Green | 主要取舍、兼容边界和验证限制均有记录。 |

## Blocker

### B1 — 宿主隔离规则丢失后，既有执行体没有恢复或隔离路径

- **维度：** Failure/scale realism；requirements and quality attributes。
- **设计锚点：** `054-app-domain-runtime/design.md:155` 将持续任务定义为“只验证”，宿主/dockerd 重启后只要求先验证再放行新部署；`:161` 的证明消费点限于新操作 create/claim/提交路由，既有应用继续保留。`:151` 的失败恢复针对安装更新过程，未覆盖运行期间规则丢失。
- **需求锚点：** `054-app-domain-runtime/spec.md:172–175`，AC-66 要求阻断应用主动直连宿主服务，AC-68 要求重启后隔离保持有效。
- **可复现失败序列：** 应用已正常运行且证明通过 → 受控故障注入移除本模块 INPUT 跳转，模拟宿主防火墙重载丢失规则 → 应用进程继续运行 → 下一次 verifier 报 failed → backend 拒绝新部署，但现存应用仍可持续连接原本禁止的宿主监听端口。证明过期或失败本身不会关闭这条网络路径。
- **为什么重要：** 新部署准入只能避免增加不安全实例，不能恢复现有实例已经失去的隔离。这不涉及防御恶意宿主 root，而是设计自身持续验证所检测出的故障没有执行消费者。
- **最小修正方向：** 增补宿主规则的运行期收敛合同：由宿主 unit 恢复自有规则并读回、配对验证；恢复失败时，明确隔离或停止受影响执行体的责任方及失败状态，同时保留原 writer 停止证明。不要泛称每次 dockerd 重启都会删除规则；应验证具体支持环境的启动和规则恢复顺序。

## Should-fix

### S1 — 补 `CredentialService._audit` 的应用关联，仍覆盖不到实际运行期凭据回收

- **维度：** Boundary quality；requirements and quality attributes。
- **设计锚点：** `056-app-square-governance/design.md:95–99`、`:142` 指定由凭据 Owner 在签发/撤销时补可信应用关联，具体落点为 `CredentialService._audit`。
- **已核实代码锚点：**
  - `src/backend/bisheng/app_publish/domain/services/app_credential_service.py:186–213`：新 operation 经 `stage()` 签发候选凭据。
  - `src/backend/bisheng/app_runtime/domain/services/runtime_projection_service.py:50–55`：正式切换直接将旧 `RuntimeCredentialBinding` 标记为 `revoked`。
  - 同文件 `:64–68`：失败/停止候选的终结路径也直接撤销 binding。
  - `src/backend/bisheng/open_api/domain/services/credential_service.py:305–333`：上述 binding 撤销不经过 `_audit`。
- **可复现失败序列：** 正式 v1 运行 → 发布 v2，或执行新增同版本配置刷新 → stage 签发新凭据 → 切路由时旧 binding 被撤销、旧凭据失去运行资格 → 按应用查询操作审计。即使 `_audit` 已补 `target_app_id`，仍只有新凭据签发事件，没有这次旧凭据回收事件。
- **为什么重要：** F056 AC-59 和 F055 AC-81 承诺按应用追溯运行期凭据签发/回收；真实回收写方没有对应事件生产合同，查询侧无法补出缺失事实。
- **最小修正方向：** 将 projection 的 binding 撤销纳入凭据 Owner 的公开应用协议，在真实状态变化处持久记录带可信 app 关联的回收事件，并按 credential/operation/action 去重；同时覆盖切换撤旧和失败候选清理。无需新增并列凭据管理服务。

## Nit

无。

本次仅核对设计、规格、发布契约和当前源码；未修改文件、未执行测试或远程操作。
