# F055 实施与验证记录

## 2026-09-14 导入入口与示例数据

- 导入按钮位于页面标题区域右上角，源码提交 `510f28b603c25562765375c947d27e2d6033c152`。
- 已合入现场 `9ae5cbe9c` 的客户端更新；部署前逐文件确认后端、客户端 src、共享包与现场一致，复用现场 client 构建，仅重建 frontend 容器。
- PASS：插件市场 7 项测试、导航 1 项测试、目标文件 ESLint、platform 生产构建、页面与 client 构建哈希、后端健康检查。
- 当前登录管理员的租户已导入 7 个约 8–9 KB 的工具示例：文本统计、JSON 格式化、URL 编码、Base64 编码、SHA-256 摘要、文本按行去重、Markdown 表格。全部采用显式“示例”名称。
- 首包通过真实已登录浏览器上传；另外 6 包通过现有 MarketService 导入，身份范围取自首包上传记录。7 包格式校验、员工目录及对象存储下载哈希核对均通过；页面显示 7 个插件，JSON 示例详情可打开，截图确认导入按钮在右上角。
- 示例代码在本地 v0.9.0 集成工作树的 Harness `0.1.5-rc.2` 和 Cordis 下加载并执行；注册表使用收集器 fixture。远端版本 SHA 的两次读取遇到 TLS 错误，本轮采用已安装运行库核验，Desktop 应用代码保持原版本。原生 Desktop 安装及模型调用为 NOT_RUN。
- 可复现示例源码、ZIP、构建脚本与交付报告：工作区 `outputs/enterprise-plugin-market-20260914/`。

更新：2026-09-10。当前确认范围为登录租户内的导入、详情、删除，见 spec.md。环境分支实现提交 744c34458；原功能分支实现提交 63a381ddd；Desktop 跨端验证提交 b7a05fa。

| 检查 | 结果与范围 |
| --- | --- |
| 后端 pytest | PASS：27 项，包含删除、旧状态重导入、租户/权限、并发 revision、下载并发删除、安装授权保留和旧表迁移幂等 |
| Alembic 单头检查 | PASS：1 项；环境 f055_market_deleted，原功能分支 f053_market_deleted |
| 页面/导航测试 | PASS：8 项；简化控件、身份变化重置、导入、删除确认、末页回退、版本只读及权限入口 |
| Ruff、arch-guard | PASS |
| platform lint、i18n、生产构建 | PASS |
| 前端根 typecheck | FAIL：既有 f048DashboardPermissions.test.tsx:91 过期 props；routeFilterPurity.test.ts:16 类型收窄问题 |
| 跨仓库联调 | PASS：真实 ASGI / SQLite / Cordis Loader，删除后继续运行、目录移除、重导入恢复、旧禁用及设备报告 |
| client 构建 | 本次复用现场构建，源码/共享包/依赖锁与 b37d227db 一致 |
| 登录用户完整上传删除流程、原生 Desktop UI、DM8、断外网设备 | NOT_RUN |

后端在独立 Python 3.11 环境执行；跨仓库联调显式替换身份和对象存储。实际 3006 的迁移、MySQL/MinIO 和容器健康见 deployment.md。上表记录的是首版交付证据。后续契约改为在线会话与未签名发布快照，不再部署 `BISHENG_DSH_MARKET_SIGNING_KEY`。Desktop 运行代码与安装包保持原版本；企业 HTTPS/网关绑定按用户决定留待后续。

复跑：仓库根 PYTHONPATH=src/backend python -m pytest --confcutdir=src/backend/test/dsh_market src/backend/test/dsh_market src/backend/test/database/test_alembic_single_head.py -q；前端 pnpm --filter bisheng exec vitest run src/test/dshMarket.test.tsx src/test/headerMenuChildAdmin.test.tsx；pnpm --filter bisheng lint、pnpm check-i18n、pnpm build:platform、pnpm typecheck。Desktop 运行 scripts/test-enterprise-market-integration.mjs 并传入 BISHENG 路径与 Python。

## 2026-10-15 工作台压缩包扩展

- [x] 定义 `.tgz` 静态规则、上传/查询/下载设计与 Desktop 接入契约；见本目录的 `workbench-*.md` 和 `desktop-workbench-api.md`。
- [x] 实现独立的 tar 校验器、工作台 SQLModel/Repository/Service、MinIO 前缀、管理员预览/上传/任务、Desktop 列表/详情/下载路由及 DSH 凭证白名单。
- [x] 企业插件管理页新增工作台区域，三语言文案及 26205–26208 错误码由 locales 源生成。
- [x] 两个用户样包本地静态校验分别得到 `repository` 和 `legacy`；后端市场相关测试 60 项通过；平台页面测试 12 项通过；平台 typecheck、目标文件 ESLint、locales check、check-i18n 通过。
- [ ] 真实 MinIO、MySQL/DM8、管理员浏览器完整上传及 Desktop 下载/运行联调；当前工作分支未部署。


## 2026-10-21 PR #2502 移植至 work-110

- [x] 从 PR #2502 的单个业务提交 `29ab7fd1318b21466e3a05d9ace7a8dcc360516c` 移植取消市场签名密钥、无签名快照、npm ZIP/tgz 导入和三语言提示；未合并 `feat/bisheng-work-120` 分支历史。
- [x] 保留 work-110 的原生无席位会话、既有平台登录入口、第三方安装开关和工作台路由；没有引入上游 `market_employee` 席位门禁。
- [x] 后端 72 项、管理端页面/导航 16 项、现有客户端市场/社区包/工作台 45 项通过；Ruff、修改文件 ESLint、platform typecheck、i18n 和架构检查通过；服务端与当前客户端完成 ZIP/tgz 制品及无签名快照协议检查。
- [x] 全仓前端 lint 93 个错误、client 类型检查 1 个错误与改动前 HEAD 基线逐项相同，均在本次范围之外。旧市场测试将本地会话撤销误判为席位撤销 403，已对齐为原生会话失效 401。
- [ ] 本轮代码的 109 环境部署、真实 npm 依赖安装和原生客户端市场完整操作未执行；本轮验证是本地 ASGI/SQLite/存储适配器与客户端解析器的协议联调。

完整来源、分支差异和复跑证据见 [PR #2502 移植说明](pr-2502-work110-port.md)。

## 2026-11-07 工作台 config 静态校验修复

- [x] 基于远端 main 62f589391 创建 fix/workbench-config-validation 独立工作树。
- [x] 支持可选 mapping config、受限 config.root dshHomePath；解析事件和语法树双重限制深度/节点，拒绝未知标签/表达式及循环引用。
- [x] 保持 26205 外层业务码并添加结构化校验原因；平台保留 ApiError，区分网络、超时、HTTP/413、大小、损坏和内容错误，三语言同步。
- [x] 原始思维导图 1.0.15 TGZ API 预览/导入/下载与 SHA-256 保真回归，旧包与拒绝用例回归。
- [x] 同步 WB-08、设计和错误响应契约；测试与 baseline 比较见[修复验收记录](workbench-config-fix-validation.md)。
- [ ] 在目标 alpha3 宿主安装、启动、编辑/导出并重启验收；目前本机已识别宿主版本不匹配，目标路径待提供。静态成功不代表版本适配完成。

## 2026-11-07 工作台 TGZ 多选

- [x] 用户确认只支持多选 TGZ，暂不支持 ZIP；补充确认通过项全部导入、失败项逐项告知，有效升级继续走现有版本规则。
- [x] 抽取工作台导入对话框，串行预览/导入，保留原始 File、单包显示名、租户头、业务错误明细与逐项结果。
- [x] 取消和卸载中止活动请求与后续队列；同步锁防重复提交；已完成结果在手动关闭时刷新，旧租户返回不更新新页面。
- [x] 后端真实接口工作台测试 39 项通过，包含原始 TGZ 和混合升级/校验失败/正式导入冲突/后续成功。没有新增后端批量或 ZIP 接口。
- [x] 独立多选代码审查 PASS，已修复活动导入取消和历史重复包状态优先级问题；最终质量检查记录见[多选规格](workbench-multiselect-spec.md)。
- [ ] 真实登录/数据库/MinIO 页面手动验收；此前 alpha3 运行验收仍按[原包验收记录](workbench-config-fix-validation.md)等待目标环境。

## 后续用户确认：覆盖、100 MiB 与删除

- [x] 同步专用验收合同及既有 spec/design/客户端文档，保持其他安全限制。
- [x] 插件同版本内容/元数据/摘要/审计原子覆盖、A→B→A 与并发任务插入恢复、下载摘要二次校验。
- [x] 工作台同版本覆盖、活动任务重新执行、100 MiB 上限与 revision CAS 管理员删除，无表结构变更。
- [x] 管理页删除、三语言覆盖/删除提示，单包 100 MiB、批量 50、去掉 64 MiB 总量限制。
- [x] 独立审查发现的工作台任务插入竞争和真实 Escape/确认身份生命周期回归修复通过最终组合验证。
- [x] 最终 Python 3.11 冻结环境后端 118 / 前端 100 回归、质量门禁、生产构建和七维审查通过。
- [x] 109 登录恢复后完成实际代理 1024 MiB、候选镜像自检与回滚点、三服务发布、健康与实际资源摘要、100 MiB multipart/未登录删除拒绝检查；已登录业务 UI 手工清单保留待验。
