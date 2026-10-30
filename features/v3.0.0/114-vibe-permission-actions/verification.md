# F114 开发与必要定向验证

## 1. 当前结论

2026-10-30，用户已分别确认规格和设计，已完成任务拆解与本地实现。**102/104 项代码、文档及 L1 任务完成；T063 真实部署 E2E、T064 最终 L2 和质量门禁仍未完成**。用户随后明确要求先提交合入 feat/3.0.0，由用户手动部署116后再做E2E；此次按该授权调整交付顺序，不代表验收通过。未执行 backend/前端全量测试，未更新 116/189、迁移存量资源、补历史 Grant、公开推送或发行镜像。

本地实现提交：`6ac7704998087267af69b72adf542895b2694ff1`；该提交之后先补充证据定位与HTML，再按用户要求集成发版线；本次集成范围和定向结果见§7。工作树：`codex/114-vibe-permission-actions`。开发起点：`bb62790ad22a3204493e7dce5878e0a4f7109599`。集成前本地发版线为 `ac2b09c8a2789021652d585f25d519888cfd0c0f`，已于 `5d04b8290` 合并继承；随后获取远端 `56f543e6ee631d000071352baba8ebccd2a69427` 并集成，保留双方历史与兼容增强。

## 2. 本地实现范围

- 复用六动作；基础管理五动作 OR；内容、数据、日志、配置与私有依赖 edit；确认配置重建 edit AND publish；删除不再加 owner 状态限制。
- 真实服务账号与自然人归属分离；首发沿 F048 初始授权，审批申请人与原 owner 固定；候选、自审、指定/重试和业务撤回接线。
- 仅具体租户视角；默认/失效回经验证所属租户，无法确定拒绝；专用管理写范围头、旧 F113 头兼容、前端跨页/跨标签缓存与旧响应防护。
- 用户凭据当前动作与系统自愈意图分型；准备/维护前、数据、启动和切换复核；维护确认后才停旧 writer；auto_commit 无授权豁免。
- 双用途预览同 Version 锁、同 UoW 登记会话/凭据/operation/容量/封装环境；提交后 wake，ready 开入口；当前用途、任务/动作、冻结版本及签名 OBO 重验；只吊销当前预览凭据。
- backend、manager、代理默认且仅支持运行控制 v2；旧控制/导入/upgrade/rebind 不可达，公共构建、SQLite、SDK、平台 API 与交付模式保留。

## 3. 实际定向执行

下表是分阶段实际运行记录，**不把重复复跑相加成一个通过总数**。原始脱敏输出在 [evidence](./evidence/results.json) 所列文件；不是远端验证。

| 检查 | 实际结果 | 边界 |
| --- | --- | --- |
| 首轮 F114 backend 选集＋单 Alembic head | 139 passed，7个既有依赖警告 | 本特性选集，非 backend 全量；发生在最终仓储收敛前 |
| 仓储调整受影响授权/构建列表/预览身份 | 44 passed | 只复测受影响6个文件 |
| 新预览凭据 SQL / rollback / UTC 有效期 | 14 passed | SQLite 内存事务；不是 MySQL/DM8 真并发证明 |
| 历史 NULL 预览不收养/不阻塞新扫描 | 1 passed，5 deselected | 部署前必须用旧版回收旧预览；不新增迁移器 |
| 私有材料真实主体 edit | 先2个失败复现旧 owner 门槛；修复后2 passed | 当前人/SA、撤权、其它应用拒绝配对 |
| manager v2启动与阶段许可顺序 | 6 passed | mock平台、受限执行器；非真实 Engine/K8s |
| 离线补包范围与既有目录导入 | 5 passed，4 deselected | 缺失/非法范围不上传；公开目录不加Vibe动作 |
| app-proxy preview / 平台路由 | 首次17 passed、1过时路径断言失败；仅该用例修正后复跑通过 | v2签名fake；不代表真实HTTP/WS部署 |
| Platform 动作组件 / 范围 / 顶部单选 | 动作3项，范围2项，顶部2项通过 | 7个定向case；未做真实浏览器验收 |
| Client 审读/预览面板 | 19 passed | 2个定向suite；不替代真实身份/任务 |
| 后端 Ruff / 架构守卫 | 111个声明内Python文件通过；无VIOLATION | 额外人工将新增SQL收回Repository；未改宪法 |
| manager / proxy / tool Ruff | 18个声明内Python文件通过 | 仅变更文件 |
| 变更前端 ESLint | Platform、Client受影响文件通过 | 不是工作区整体绿灯 |
| 三语错误源生成、check-i18n | 生成成功；无新增i18n漂移 | 未修改baseline或手改派生件 |
| E2E收集 | 3 tests collected | **仅收集，未向116/189发请求，不能算E2E通过** |

关键后端命令（cwd `src/backend`，只读配置由 `config` 环境变量提供，不随文档或 Git 交付）：

```sh
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest   test/app_runtime/test_f114_*.py test/app_publish/test_f114_*.py   test/approval/test_f114_*.py test/admin/test_f114_*.py   test/app_governance/test_f114_*.py test/open_api/test_f114_*.py   test/database/test_alembic_single_head.py -q --tb=short -p no:cacheprovider
```

该命令记录的是首轮选集。后续仓储只跑上述受影响6文件，新增 SQL/私有材料/历史预览分别按表单独执行；不会为每次修复重复全选集。旧 v1 控制 HTTP fixture 显式 retired skip，未将 skip 算作成功；共用工具和入口覆盖保留。

## 4. 未通过的工作区质量门禁

| 门禁 | 实际情况 | 处理边界 |
| --- | --- | --- |
| `pnpm lint` | Platform整体通过；Client被未修改 `AiChatInput.tsx:375` 的 `hasAttachedFiles` 未使用阻断 | 文件与HEAD及当前发版线相同；不混入无关修复 |
| Platform `pnpm typecheck` | 17个错误 | 当前安装缺少/过旧图标、rehype/remark、dnd/router类型等，未把失败隐去 |
| Client `pnpm typecheck` | 134个错误 | 当前工作区共享包/图标与依赖类型未满足；包括已存在的 `AppPreviewPanel` Eye 图标行。未为此重新安装依赖、写suppression或跑无关修复；未做一次独立干净基线对照 |

类型检查失败不能自动等同代码没有问题。上述为6ac770499实现阶段的工作区结果，不能当作最新集成线的质量结论。用户要求先合入供手动部署；正式验收仍须在正确安装/构建依赖的工作区或 CI 完成门禁，只定位新增错误；T064 保持未完成。

## 5. 真实部署 E2E 待办（专用对象、必要范围）

依 AGENTS.md §6、已确认设计 §6.5/§7 和 e2e-test，真实 E2E 仍是必需项。本轮设计确认只授权开发；更新 116/189、重启服务和创建真实测试对象尚未获得本轮具体授权。

### 5.1 自动化入口与当前缺口

`test/e2e/test_f114_permission_actions.py` 已准备3个光明/拒绝配对case，使用专用已批准的 `e2e-f114-*` app 和4种非管理员测试身份；`F114_E2E=1` 才执行。环境变量包括 `E2E_API_BASE`、`F114_APP_ID`、`F114_TENANT_ID`、`F114_EDITOR_TOKEN`、`F114_PUBLISHER_TOKEN`、`F114_USE_TOKEN`、`F114_FOREIGN_TOKEN`。凭据仅运行进程内使用，不写报告或Git。setup/teardown只操作该应用 `E2E_F114_TEMP` 测试配置，不删除业务对象。

当前测试依赖预置 fixture，并未自动创建租户/人员/SA；它只覆盖安全摘要与私有内容、保存不重启和旧范围拒绝。**不能宣称覆盖71条AC的真实E2E**。取得环境授权后，还需补齐以下实执行证据或相应API case：

| 场景 | 具体执行与预期 | 当前状态 |
| --- | --- | --- |
| 前置与保护 | 只读盘点镜像/协议/旧预览/路由UID和数据；旧预览用旧版确认回收，原生v2正式应用不主动重建 | 未执行 |
| 真实 SA 首发/代发布 | 临时A/B租户，固定自然人owner；SA无动作拒绝，有edit+publish可迭代；owner/tenant不变，审计真实主体 | 未执行 |
| 六动作页面配对 | edit-only、publish-only、delete-only、manage_permission-only、use-only；私有组件无权不发请求，直接API同样拒绝 | 未执行 |
| 租户切换 | 超管仅A/B具体范围；Root非全平台；旧表单、延迟响应、另一标签页与失效回退，非超管伪造拒绝 | 未执行 |
| 审批 | 自审排除与真实单管理员例外；异常分配和task失效；publish代撤回只作用当前冻结实例 | 未执行 |
| 双预览 | 管理本人上限、审批归属人上限；HTTP/WS/OBO/模型/检索；无真实密钥；并发重复启动只一组身份，终态只吊销该凭据 | 未执行 |
| 分阶段撤权/故障 | 维护前撤权旧版继续服务；维护后撤权无新启动；回复丢失/重启同序重放，无容量误释放 | 未执行 |
| 自愈与取消 | 原提交者停用不阻止已批准意图自愈；停用意图不复活；当前取消者需原操作全部动作，必要清理保持 | 未执行 |
| Docker/K8s v2 | 各一次本特性主流程/拒绝配对，共用构建/SQLite/附件保留；不跑全部旧场景、不做arm或跨节点能力宣称 | 未执行 |
| 导出与收尾 | edit撤权后审计/数据导出下载拒绝；只清理专用对象，核对非测试应用与数据不变 | 未执行 |

DM8仅静态使用JsonType、关系列和500个ID分批，不宣称真实数据库或跨节点/arm验证通过。正式CI镜像发行、公开推送和tag均独立记录。

## 6. L1、预审与交接

[task-reviews.md](./task-reviews.md) 记录104项的L1范围、配对与依赖；[code-review.md](./code-review.md) 仅为当前预审，最终 L2 待真实E2E和门禁后执行。原独立设计复审保留，不冒充独立代码审查。当前仍有验收缺口，不标整体完成；依用户后续明确授权先本地合入发版线，116部署由用户执行，之后再补真实E2E与最终审查。


## 7. 用户授权的先合入交接（2026-10-30）

用户原话：“先提交合并到feat/3.0.0 分支。我来手动部署到116环境，之后在进行e2e的验收测试”；随后“继续”。本次只办理本地提交与合并，不更新116/189，不发行镜像或tag，不把T063/T064改成完成。未新获得远端推送授权。

详细冲突处理、保留内容、必要测试及部署前置见 [integration.md](./integration.md)。合并包含本地发版线ac2b09c8a及本轮获取的远端56f543e6e；原工作区两份代码草稿与一份未跟踪文档均先存SHA-256并核对内容，不能覆盖。

- 环境变量摘要读取继续用Repository严格过滤到当前具体租户；授权保留管理上下文并检查真实主体edit，不恢复owner/admin快捷放行。
- 远端新增的服务账号全平台只读入口与AC-09至AC-18冲突，按已确认“仅具体租户”收敛；保留租户名称、取消/失效控制和其它兼容增强。
- 定向结果：后端首轮22项通过、13项测试夹具不兼容；只复跑这13项后全部通过。前端27项通过；变更文件Ruff/ESLint通过。没有重跑全量测试，也没有进行真实部署验收。
