# zhgyl 定制线合并手册

本手册只在 `feat/zhgyl-3.0-beat1` 维护。主版从 `feat/3.0.0` 向定制线合入，定制代码不反向合入主版。
历史升级结果另见 `features/v3.0.0-beta3/docflow/upgrade-3.0-20261110.md`。

## 合并前

- 工作区保持干净，先获取并同步 zhgyl 远端；以同步后的目标 tip 为定制检查基线。
- 保存目标相对于已合入主版的文件清单，逐项检查自动合并和删除，不能只看冲突文件。
- 先跑 DocFlow、ZIP 和安全测试，合并后用相同范围比较失败集合。
- 冲突逐块合并；语言文件按 JSON 键递归合并，禁止整文件取某一侧。

## 长期保留的定制与常见冲突

### DocFlow OCR

- 保留 `KnowledgeConf.docflow`、完整凭据校验、环境变量引用与 provider 启用判断。
- 保留 `DocFlowJob` 租户模型登记、任务租约、账户容量、检查点以及 ES/Milvus 入库恢复。
- `NormalPipeline` 的 `ingest_documents` 委托不能退回普通双写；重试不能先删除 DocFlow 已确认的入库阶段。
- 预览、临时附件、正式知识库三条解析链均须保留结构分段和缓存 provider 隔离。
- DocFlow 既有索引坐标为 1-based；旧平台预览依 `parse_type` 选择 `startIndex=1`。
  新共享引用链按 0-based 处理，必须在引用出参边界归一化，不能改写既有索引或对已归一化坐标重复减一。
- 主版新增解析 provider 时，DocFlow 配置隔离测试里的 AST 类清单须同步依赖；不能删掉主版 provider 让测试通过。

### ZIP 上传与工作流附件

- 保留 `/knowledge/upload-archive`、服务端 manifest、属主/租户校验、路径与大小/数量限制、取消及失败清理。
- 同时检查日常聊天、工作流输入、任务模式的 manifest 校验与名称/相对路径接线，不能只保留上传端点。
- 原 ZIP 和展开后的附件共用批次限制；串行队列中被删除的上传不能继续发请求。
- 上传期间禁止提交，但不能同时禁用共享表单的值回写。`WorkflowForm.submitDisabled` 只控制提交锁。
- 删除已完成附件不能减少正在上传计数；失败不能重复减计数；发布值时按真实列表计算上传状态。
- 主版与定制可能占用相同错误码。主版租户变化保留 `10993`，ZIP 使用 `10994`，三语源文件一起更新并重新生成产物。

### 安全与部署路径

- 保留安全报告 5.2–5.5 的数据集鉴权、租户/白名单限制、上传归属元数据、续签权限、会话/标注任务授权和注册开关校验。
- 部署前缀使用现有 `VITE_BASE_URL`，不能替换成未被 Docker 构建接线的新变量。
- 主版 Vite 共享代理、环境加载和 `/apps/` 路由继续采用主版实现；定制前缀叠加在共享实现上。
- 平台进入 workspace、SSO、个人令牌安装包、资源路径、字体和 SPA basename 必须一致处理部署前缀。

## 合并后检查

1. 对比定制文件、配置和接线是否丢失；被主版移除的旧预览迁移到新入口，不能为了保留定制复活死代码。
2. 重跑 `test/knowledge/docflow`、`test/knowledge/test_archive_*`、`test/security/test_report_52_55.py`，
   并检查 workflow/workstation 附件和 citation 回归。自包含测试可用 `--noconftest`；依赖应用导入的测试使用隔离测试配置。
3. `alembic heads` 只能有一个 head。若确实分叉，新建空 merge revision，不修改已发布迁移。
4. 权限模型改变时重新计算模型及性能基准合同 checksum，同步 fixture 与对应断言。
   部署前执行授权模型发布脚本的 dry-run/apply，不能仅重启或设置 `force_write_model`。
5. 所有修改过的语言 JSON 检查重复键；错误码产物运行 `packages/locales/scripts/build.mjs` 生成，不能手工解决产物冲突。
6. 前端测试、类型检查和构建按用户约定交给镜像阶段；未执行不能记为通过。
7. 提交前检查残留冲突标记、差异空白和定制增量架构守卫；既有问题与新增问题分别记录。
