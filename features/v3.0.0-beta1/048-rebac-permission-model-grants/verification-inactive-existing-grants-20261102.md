# 停用模型既有授权：修复与验证记录

日期：2026-11-02。分支：`codex/permission-inactive-grant-20261102`。
基线：最新远端 `feat/3.0.0` 的 `368894d9a`；主工作树及其他未提交内容未改动。

## 1. 已确认规则与问题

本次实现用户认可的方案，纠正 F048 AC-15、AC-164、AC-166 的实现偏差：

- 停用权限模型只阻止新增绑定、移动到该模型及复制新的该模型绑定；既有有效授权继续生效。
- 名单、搜索、我的权限说明与审批当前授权摘要应保留这些真实来源。
- 原管理权限、等级/同级策略、protected、继承、租户边界和乐观锁继续约束撤销及替换。

116 只读排查发现：空间 3254 的部门 310 来源仍有效，引用已停用自定义模型“1111”；
wangxinlei1 属于该部门，因此在“我加入的”中可见符合既有规则。问题是权限说明按模型
active 过滤，导致管理页面漏掉这项授权。此处保留排查结论，未在本轮重新写入数据库或 FGA。

## 2. 实现

| 层次 | 修改 |
|---|---|
| SQL 来源读取 | `load_source_page` 保留已知模型的既有来源；仍限定同租户、ACTIVE/CURRENT Grant、ACTIVE assignee 和合法继承路径；分页有界 |
| 权限说明 | `PermissionExplainService` 保留停用模型的直接/继承来源和动作；inactive Grant / assignee 仍排除 |
| 审批摘要 | `read_effective_action_sources` 继续按具体 action、CURRENT 状态、读围栏和容量限制返回来源，不按模型可分配状态删除来源 |
| 既有来源管理 | 与新分配共用等级/同级判断，仅去掉旧来源模型 active 要求；服务端以此细化 editable，无完整名单扫描 |
| API | 名单返回真实 model.active；若来源模型不属于读取的 Catalog 快照则明确返回版本冲突；mutation 响应保留其他未撤销的停用模型来源 |
| 两套 SPA | 显示“该权限已停用，已有授权仍有效。”；管理旧来源与选择新目标分开，保留服务端只读限制 |
| Client 设置表单 | 知识空间、频道 hydrate 保留 modelActive；移动到可分配目标后更新该元数据 |

无数据库结构变更、新错误码、新依赖或 OpenFGA 模型变更。没有迁移、启用或撤销 116 的存量授权。

## 3. 定向验证

| 检查 | 结果 | 范围/限制 |
|---|---|---|
| Backend pytest | **55 passed** | `test_inactive_model_existing_roster.py`、F048 explain/resource API/grant policy/grant sources、F115 action sources，以及 catalog runtime 中有界分页和最近 CUSTOM 祖先的两个测试（含 active 参数）；覆盖读取时 Catalog 模型缺失的冲突响应 |
| Platform Vitest | **9 passed** | `src/test/f048PermissionGrantTab.test.tsx`；包含停用来源精确 REMOVE、只读行拒绝、新目标排除及已有版本冲突路径 |
| Client 组件/纯函数 | **25 passed** | `PermissionGrantTab`、`PermissionListTab`、`permissionDraftPolicy`，在临时 Vitest 适配器执行原断言 |
| 前端 lint | **PASS** | 从 `src/frontend` 执行 `pnpm lint`，覆盖两个 SPA 及共享包 |
| 三语 key / i18n | **PASS** | `node scripts/check-i18n.mjs`；无新增漂移，既有 84 项 frontend-only 基线保留 |
| TypeScript | **基线阻塞，无新增诊断** | Platform 23 项、Client 135 项；在 `368894d9a` 临时只读源码副本、同一组已安装依赖下逐条比较一致（忽略绝对路径与新增 import 引起的行号偏移） |
| Ruff / arch-guard / diff-check | **PASS** | 本次改动范围；不执行全量测试 |
| 真实部署 E2E | **未执行** | 本轮未更新 116；见下方验收清单，T202 保持未完成 |

### 本地 runner 限制

Client 原 Jest 在测试初始化时报缺少 `canvas.node`；node 环境纯函数用例还会被全局 setup
的 Element 引用阻断。未安装依赖或修改仓库 runner。临时 Vitest 适配只转换 jest/vi API、
同步 locale 读取及导入路径，并对齐 clearMocks/restoreMocks；使用原 Button、共享 UI 和
原插画组件，绕过未使用的 barrel 导出，权限逻辑和断言不变。临时文件均在 `/private/tmp`。

额外运行的 Platform `f048PermissionDialog` 有一个旧用例把 subject Tab 查询成 button；
在未修改基线 `368894d9a` 上同样复现。未改业务 Tab 语义或扩大本次修复范围。

架构守卫以仓库相对路径检查全部改动通过。传入绝对工作树路径时，RULE-9 会将路径中的
`/bisheng/` 仓库名误当应用包前缀，从而对 permission 测试中原有的 OpenFGA import 报警；
已核对其 import 与基线完全相同，未修改守卫或添加例外。

## 4. 任务与静态复审

按 `task-review` 检查 T199–T201：分层、命名、序列化、数据库、前端约定、信息泄漏及设计
同步通过；无新增 ORM/原生 SQL、凭证、菜单或鉴权短路。新增文案三语同时提供，两个 SPA
组件分别实现；修改的前端文件均不超过 600 行。

本缺陷按 `sdd-code-review` 七维度由同一代理复审：

| 维度 | 结论 |
|---|---|
| 边界 | 空页/搜索/直接与继承、停用模型、inactive Grant/assignee 均有定向验证；缺失模型不凭空恢复 |
| 权限与认证 | 普通主体测试管理等级及拒绝路径；原 OpenFGA 鉴权、租户/目标及新目标 active 限制保留 |
| 并发 | 未更改写协议；资源/Catalog/assignee 版本、幂等和投影账本继续由原写服务校验 |
| 信息泄漏 | 没有加入环境凭证、内部地址或跨租户数据；说明 API 仍位于原阅读门禁之后 |
| 测试 | 本地定向验证通过；TypeScript/旧 Dialog 用例有已复现的基线限制，真实部署证据待补 |
| 风格 | Ruff、lint、架构守卫通过；无新增忽略/抑制或依赖 |
| 文档 | F048 design 的职责、名单字段、已知坑、内部 API 与修订历史已同步 |

代码静态复审完成；不以此宣称整个 F048、CI 或真实环境 E2E 全部通过。

## 5. 部署后最小验收（待执行）

1. 对空间 3254 只读核对授权名单/搜索：可见部门 310、“1111”、active=false 及停用提示；
   wangxinlei1 仍可在“我加入的”看到空间，普通使用/下载动作保持原结果，设置权限不额外放开。
2. 专用 `e2e-inactive-grant-` 测试资源：创建模型和部门/用户组绑定后停用模型；
   管理者仍能读取来源，普通成员可见性及具体动作保持；无管理权限者拒绝读完整名单或写入。
3. 新增/移动/复制到已停用模型均拒绝；高等级、protected、继承来源或过期版本仍拒绝修改。
4. 在专用资源精确撤销或移动旧来源；保留同一用户的另一有效来源，确认其可见性仍存在；
   最后一项来源撤销后才失去对应访问。
5. 仅清理本次创建的测试对象；空间 3254、Grant 15396 及存量模型不作变更。

交付目标：用户于 2026-11-02 要求将本修复提交并推送到 `feat/3.0.0`。
本记录覆盖代码及本地定向验证；真实环境 E2E 待部署后补充，不包含环境更新。交付提交号以 Git 历史为准。

## 6. 合入验证（2026-11-02）

- 修复提交：`ff2b89aa077d1f155542433f8e6b81c5d75b6923`。
- 合入基线：刷新后的远端 `feat/3.0.0`，`a6ea4a7987e05259f5779f0e011971e7c4c0709c`。
- 保留该基线的成员关系历史版本修复及知识空间查询优化；`control_state.py`、`runtime.py`
  自动合并，设计文档逐段保留双方内容，并将本次已知坑编号调整为 36。
- 合并后原 55 项回归加成员关系重新激活的 8 项回归，**63 passed**；Ruff、架构守卫、
  冲突标记扫描和 diff-check 通过。前端与修复提交逐文件一致，沿用已完成的 34 项定向结果。
- 未执行全量测试或更新 116；T202 真实部署 E2E 仍待完成。
