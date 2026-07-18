# E2E 验证清单: F041 工作流 / 助手应用支持选择知识空间

**测试环境**: Platform 前端（`npm start` :3001，vite 代理指向本地后端 :7860）/ Client `:3001/workspace`
**后端**: localhost:7860（真实中台 192.168.106.116：MySQL/Redis/Milvus/ES/MinIO/OpenFGA）
**账号**: admin / `Bisheng@top1`（super_admin，配置者）+ 至少一个普通用户（运行使用者，对目标空间文件有**差异化** `view_file`）

> API 端可自动化的 AC（AC-02/03/04/05/10/11）已由 `test/backend/test/e2e/test_e2e_f041_knowledge_space_select.py` 覆盖并通过（6/6）。
> 本清单覆盖**需真实向量库检索 / 差异化权限 / 浏览器交互**的 AC——单测已覆盖过滤/分级纯逻辑，此处验证端到端真实链路。

**前置数据**：
- 一个知识空间 S（含 ≥2 个已解析成功的主版本文件：F_a、F_b）。
- 普通用户 U 对 F_a 有 `view_file`、对 F_b 无。
- admin（配置者）对 F_a、F_b 均可见。

---

## Platform 前端 — 选择器 & 开关 UI

### AC-01 / AC-03 / AC-04: 助手应用知识空间 tab + 混选 + 回显
- [ ] 以 admin 登录 Platform → 应用 → 新建/编辑一个助手
- [ ] 展开「知识库」→ 选择器出现 **两个 tab**：`文档知识库` / `知识空间`（原无 tab 的平铺改为 tab 呈现）
- [ ] 切到「知识空间」tab，列表 = 我创建+我加入+部门空间（无广场），搜索框可按名过滤
- [ ] 混选：文档库选 1 个 + 知识空间选 S，保存
- [ ] 预期：保存成功；**刷新/重开**助手配置，文档库项回到「文档知识库」tab、S 回到「知识空间」tab（各归其位，type 标记生效）

### AC-01（工作流三节点）: rag / knowledge_retriever / agent 均出「知识空间」tab
- [ ] 新建工作流，分别添加「知识库问答」「知识库检索」「助手(agent)」节点
- [ ] 每个节点的知识库选择器均出现 `文档知识库 / 知识空间 / 临时会话文件` tab（agent 节点无临时文件 tab 属正常）
- [ ] 选中知识空间 S 保存，重开回显正确归到「知识空间」tab

### AC-06 / AC-07: 节点改名（三语）+ 存量不受影响
- [ ] 画布左侧节点面板 & 已放置节点标题：`文档知识库问答` → **知识库问答**，`文档知识库检索` → **知识库检索**
- [ ] 切换界面语言 中/英/日，三语均显示新名（英：Knowledge Base QA / Knowledge Base Retrieval；日：知識ベースQA / 知識ベース検索）
- [ ] 打开一个**存量**含这两个节点的旧工作流：不报错、节点配置完好（内部 type 未变、无需迁移）

### AC-10 / AC-11: 4 入口权限校验开关 + tips（三语）+ 新增开关默认关
- [ ] 助手应用「知识库」区块下方出现 **用户知识库权限校验** 开关 + ? tips 悬浮（中/英/日详细文案：开=按使用者本人、关=按配置者可见范围共享、文档库不受影响）
- [ ] agent 节点「知识库」组出现同名开关 + tips
- [ ] 知识库问答/检索节点：展开「高级检索配置」→ 打开总开关后出现「用户知识库权限校验」子开关，其 tips 已更新为详细文案
- [ ] **新增**开关（助手应用、agent 节点）默认 **关闭**

### AC-08 / AC-09: 元数据过滤对知识空间仅内置字段
- [ ] 知识库问答/检索节点选中知识空间 S → 展开「高级检索配置」→「默认元数据过滤」
- [ ] 字段候选**只出内置**（document_id / document_name / upload_time / update_time / uploader / updater），**不**出自定义 metadata_fields、不报错

---

## 检索过滤（真实向量库 + 差异化权限）

### AC-12 / AC-13: 开档 = 仅运行使用者有 view_file 的空间文件进结果
- [ ] 助手/工作流选空间 S，**开启**用户知识库权限校验，发布
- [ ] 以普通用户 U 运行，提问命中 F_a 与 F_b 内容
- [ ] 预期：仅 F_a 的 chunk 进入回答；F_b 的 chunk / 文件名 / 来源 / 预览链接 / 角标**均不出现**

### AC-14 / AC-16: 关档 = 按配置者可见范围共享（不越配置者边界）
- [ ] 同上配置但**关闭**开关，以普通用户 U 运行
- [ ] 预期：F_a、F_b 都能被检索到（借用配置者 admin 的可见范围）；若把配置者对某文件的 view_file 收回，则该文件不再进结果
- [ ] IF 检索身份对空间无任何 view_file → 空命中、不报错、对话继续（AC-16）

### AC-15: 权限变更即时生效（缓存 TTL ≤ 10s / invalidate）
- [ ] 开档下，U 第一次检索只见 F_a → admin 授予 U 对 F_b 的 view_file → 等 ≤10s → U 再次检索应见 F_b
- [ ] 反向收回后下一次检索不再见 F_b

### AC-23 / AC-24 / AC-25: 混合范围 / 管理员短路 / 异常文件
- [ ] AC-23: 助手同时含文档库+空间，开档时空间按 U 的 view_file 过滤、文档库沿用既有 check_auth，结果合并
- [ ] AC-24: 以管理员运行 → 跳过 view_file 过滤（可见空间全量）
- [ ] AC-25: 空间被删除 / 文件解析中 / 解析失败 → 不纳入检索、不报错

---

## 角标溯源 accessScope 分级（Client `/workspace`）

### AC-19 ~ AC-22: per_user vs shared
- [ ] **开档**（per_user）：U 无权文件的角标整条不出现（AC-20，同 F029）
- [ ] **关档**（shared）+ U 对文件无 view_file：角标**保留**、显示文件名/知识库名/snippet/可点角标，但点开**无** previewUrl/downloadUrl（仅元数据）；单条 resolve 不再抛 NotFoundError（AC-21）
- [ ] **关档**（shared）+ U 对文件**有** view_file 或为 admin：完整溯源（含预览/下载 URL）（AC-22）

---

## 运行时回归（worker）

### 坑 5.2: 无 "Event loop is closed"
- [ ] 起 `workflow_celery` worker（`uv run celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery`）
- [ ] 以**非配置者**账号触发含知识空间检索节点的工作流
- [ ] 预期：worker 日志无 `Event loop is closed`、无 OpenFGA/aiomysql 单例报错；检索正常返回（run_async_safe 单一持久 loop 生效）

## 回归检查
- [ ] 助手编辑页、工作流画布正常加载，无 console 报错
- [ ] 存量助手（仅文档库）、存量工作流（含改名前两节点）行为不变
- [ ] 不同角色（admin / 普通用户）在开/关两档下看到的检索集合符合权限设定
