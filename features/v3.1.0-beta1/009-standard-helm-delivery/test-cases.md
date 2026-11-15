# 标准 Helm 交付测试用例（测试工程师参考）

## 依据与范围

- spec.md：2026-11-10已确认及后续范围收敛；design.md：用户授权按最新讨论更新并实施。
- 目标版本：v3.1.0-beta1 / codex/3.1.0-beta1/standard-helm-delivery，源码已实现；现场待验。
- 代码基线：19ba119e48；新增行为按规格推导。实际集群和镜像验收本轮不执行。
- 已保存端点的运行环境由开启转关闭沙箱的联动场景延期。

## 环境、账号与测试数据

| 代号 | 角色或数据 | 准备方法 | 确认方式或待确认项 |
| --- | --- | --- | --- |
| CL | 独立测试集群 | 提供支持NetworkPolicy的CNI和当前受支持CSI；专用namespace | 真实验收环境待后续安排，本轮不连接线上 |
| U | 首位注册用户、普通用户 | 空库按正常注册流程创建 | UI和权限结果共同确认，不能只测超管 |
| APP | Python/Node/Static样例 | 使用测试前缀并按样例范围清理 | 具体正式镜像和catalog待发行，不编造digest |

## 具体测试用例

| ID | 功能点 | 优先级 | 前置条件 | 步骤 | 预期结果 | 测试结果 | 结果说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-HELM-001 | 默认全新安装 | P0 | 隔离新测试集群，发行镜像清单及合适存储已提供 | 1. 安装默认Chart；查看依赖、登录并首次注册。 | 1. 平台、Vibe和沙箱可用；首个注册用户为超管；没有预建用户。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-002 | 无预检报告发布 | P0 | Vibe已开启，未生成环境诊断报告 | 1. 发布合法应用；完成构建与健康检查。 | 1. 发布按实际状态进行，不要求报告。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-003 | 过期诊断不阻断 | P0 | 合法部署；手动报告年龄超过24小时 | 1. 构建、访问、恢复应用。 | 1. 报告年龄不改变业务准入和入口。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-004 | 手动诊断真实失败 | P1 | 隔离环境有可控失败的网络目标 | 1. 显式运行诊断并查看逐项输出。 | 1. 真实失败或未检测，不伪造通过；诊断不单独停用应用。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-005 | 应用构建错误 | P0 | Python或Node样例含不存在的依赖 | 1. 提交发布并查看构建日志。 | 1. 构建失败有对应原因，不生成误成功版本。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-006 | 未知写入者保护 | P0 | 专用测试Pod已绑定数据卷 | 1. 模拟原UID状态未知；尝试接管和清卷。 | 1. 不确认停止、不清卷、不释放仍在用的预约。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-007 | 全外部基础组件 | P0 | 提供各组件专用连接及已有Secret | 1. 关闭所有内置依赖并安装。 | 1. 无内置基础组件实例；平台使用授权范围内的外部服务。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-008 | 混合基础组件 | P1 | 外部MySQL/Redis与专用账号 | 1. 仅部署其他内置依赖。 | 1. 不接管外部release，内外依赖均解析正确。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-009 | Gateway关闭 | P0 | 默认gateway.enabled=false | 1. 渲染并安装；测试原生DSH登录。 | 1. 无Gateway工作负载/库/初始化/悬空路由；DSH按自身开关工作。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-010 | Gateway开启 | P1 | 合法Gateway镜像、SQL和许可Secret | 1. 开启安装；访问Gateway及查看初始化日志。 | 1. 使用对应版本初始化，非法库状态明确失败。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-011 | 全新关闭功能 | P1 | 全新空配置；runtime和sandbox显式false | 1. 渲染安装；查看平台入口及引用。 | 1. 不安装对应组件、不等待其初始化；保留未启用引导语义。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-012 | 官方目录幂等 | P0 | 正式可信catalog；已有管理员默认选择 | 1. 执行正式种子两次；提交冲突版本。 | 1. 只补缺项并记录系统来源；默认选择不被覆盖；冲突失败。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-013 | 参数三方一致 | P0 | 非默认Helper额度、超时和节点选择 | 1. 渲染策略并发起新操作，重启Manager后继续。 | 1. Backend/Manager/Admission一致；冻结规格与原期限不变。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-014 | 部署文件独立 | P0 | 普通新集群参数 | 1. 检查发行文件和容器启动命令。 | 1. 无122主机值或ConfigMap Python启动补丁。 | 通过（源码） | 源码部分见verification.md |
| TC-HELM-015 | StorageClass三态 | P1 | 分别使用默认class、指定class及静态卷 | 1. 渲染对应values，查看PVC和应用卷申请。 | 1. 省略、指定和空字符串语义区分；不格式化节点磁盘。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-016 | 持久数据恢复 | P0 | 有界ext4/xfs测试CSI及持久应用数据 | 1. 写入数据；重启或更新应用；检查数据。 | 1. 容量/锁/持久化检查保留；数据一致且单写。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-017 | 升级密钥保留 | P0 | 标准Chart已有安装、密钥和用户配置 | 1. 正常升级；比较Secret、公钥、默认项。 | 1. 不重新生成签名根或覆盖用户设置。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-018 | 双release隔离 | P0 | 同集群两个隔离安装 | 1. 渲染并安装；比较名称、selector和webhook。 | 1. 互不选择对方Pod；不改共享控制namespace安全标签。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-019 | 阶段网络限制 | P0 | 在线依赖下载与企业包源 | 1. 下载缺失依赖；在安装/编译阶段尝试直连。 | 1. 获准下载经Egress；其他阶段保留原限制，不能绕过。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-020 | 离线策略保留 | P1 | 已选择离线的标准安装 | 1. 升级后发布缺包样例。 | 1. 明确缺包失败，不自动联网。 | 待集群验证 | 源码部分见verification.md |
| TC-HELM-021 | 教程及发行边界 | P1 | 仅本地源码和模板 | 1. 按README核对新装、外部依赖、开关、故障与卸载。 | 1. 说明完整；无兼容镜像时拒绝正式打包；模板不冒充集群安装。 | 通过（源码） | 源码部分见verification.md |

## 用例依据与待确认项

| 用例 ID | 需求依据 | 设计或代码依据 | 待确认项或差异 |
| --- | --- | --- | --- |
| TC-HELM-001 | AC-08, AC-12, AC-13, AC-15 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-002 | AC-01, AC-04, AC-05 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-003 | AC-02, AC-07 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-004 | AC-03, AC-04 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-005 | AC-05, AC-07 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-006 | AC-06 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-007 | AC-09, AC-10, AC-21 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-008 | AC-09, AC-10 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-009 | AC-11 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-010 | AC-11, AC-15 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-011 | AC-12 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-012 | AC-14, AC-15 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-013 | AC-16, AC-17 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-014 | AC-18 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-015 | AC-19 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-016 | AC-20, AC-06 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-017 | AC-21, AC-25 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-018 | AC-22 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-019 | AC-23 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-020 | AC-23 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
| TC-HELM-021 | AC-24, AC-25, AC-26 | design.md / verification.md 当前源码与测试记录 | 集群行为待正式镜像和隔离环境；本轮只做源码/模板回归 |
