# DocFlow OCR 接入与运行说明

## 范围

DocFlow 是可选的 PDF/图片解析 provider，复用知识库文件上传、分段预览、普通分段、标题结构分段、Milvus 向量化和 Elasticsearch BM25。Office、音视频和其他 provider 的默认路径保持原有实现。工作流临时文件可复用 OCR，但沿用临时集合的原生命周期。

本实现不调用额外大模型重排，不把纯文本、排版文本与 Markdown 分别 embedding。正式正文是语义化 Markdown，而不是旧代码节点的围栏空间排版。API 与 Worker 必须可以直接访问 MK IP 和对象存储。

## 配置

在管理后台「系统配置」保存的 YAML 中，将以下内容合并到 `knowledges`（复数）；不要删除原有字段。运行时 `ConfigService.get_knowledge()` 读取数据库系统配置的 `knowledges`，不是挂载 `config.yaml` 的 `knowledge`。旧版交付说明使用单数的写法有误，按该写法填写不会启用本解析器。凭据可直接填写，或使用环境变量引用，并在 API 与所有解析 Worker 中设置相同变量。不要提交或输出实际密钥。

```yaml
knowledges:
  loader_provider: docflow
  docflow:
    url: http://10.131.122.218:8080
    host: mk.avicsupply.com
    app_key: env:MK_APP_KEY
    app_secret: env:MK_APP_SECRET
    docflow_app_id: env:DOCFLOW_APP_ID
    docflow_secret_code: env:DOCFLOW_SECRET_CODE
    workspace_id: "2109876750294872064"
    parser_revision: "1"
    timeout: 120
    poll_timeout: 120
    poll_interval: 3
    max_concurrency: 5
    trust_env: false
    upload_headers: {}
```

`max_concurrency` 是同一 MK 账户/空间的分布式在途任务上限，不是每个 Worker 的独立上限。所有使用同一账户的部署须约定同一个值。修改远端空间解析配置后递增 `parser_revision`，显式失效旧解析结果。配置缓存生效和 Worker 环境变量更新遵循现有系统配置生命周期；环境变量变化后应重启相应进程。

上传使用 `/openapi/sys-attach/fileStream/upload`、multipart 字段 `fdFile`，不自动添加 Bearer。兼容 `fdId` 和 `fdAttachFileId`。MK token 与 DocFlow 凭据独立，后者在 MK 注册接口处须正确透传或固定配置。

## 数据库与存储

新增 `knowledge_docflow_job` SQLModel 表，带显式 tenant_id。按仓库现行规范，新整表由在线 Alembic upgrade 中的模型发现/create_all 创建，不添加修改既有表的 revision。部署前仍需执行项目标准 `alembic upgrade head`，并在目标 MySQL/DM8 验证表和索引已创建。不能只复制 Python 文件后直接启用 provider。

解析任务键包含租户、文件 SHA256、端点、空间与凭据指纹。数据库只存摘要、阶段和远端标识，不存密钥。原始 OCR JSON、入库分段快照和向量缓存使用 MinIO 临时桶，继承现有 7 天生命周期。缓存到期后：已知远端任务优先重新查询；向量缓存到期可能重新计算。SQL 检查点不是永久可用缓存的承诺。

同一文件名、不同文件内容不会混用结果；不同租户不共享解析/向量产物。预览和正式入库共享原始结果，不依赖 API/Worker 的共享本地磁盘。

## 解析与 Markdown

完整结果必须包含 `document.pages[].lines[]`。空全文、缺页、分类完成但未 OCR、识别失败均不作为成功入库。当前要求关闭 DocFlow 空间的文件拆分与多图切分；没有原文页映射的子任务会明确失败，防止漏页。

正文采用保守的分栏和上沿归行。显式标题类型优先，几何推断标题仅采用有限条件。文字中的 HTML/Markdown 控制符被转义。明确的表格网格支持 `rows` 或 `items` 中的行数组/`cells`，单元格需含文字、位置及可选 rowspan/colspan；普通网格转 Markdown 表格，合并单元格保留 HTML。未标明表头时使用空的格式表头，不把首行数据冒充表头。非该结构的 `data.tables` 不猜字段协议，保留 OCR 全文并记录警告。现场真实表格响应应加入回归后再宣称该格式完整支持。

分段 metadata 只使用现有契约：indexes、bboxes、pages、types；bbox_list 使用 TextBbox。索引是最终 Markdown 的 Python 字符半开区间，生成的格式符号不伪造坐标。标题结构模式通过 DocFlowStructureSplitter 切分标题区域后复用现有 SplitterTransformer，不扩大旧 provider 的扩展名白名单。

图片使用转正像素坐标。无旋转 PDF 根据实际页宽高缩放为 PDF 预览坐标；有旋转/纠偏关系尚未核实的页保留正文、关闭该页坐标映射并告警。此限制不会伪装成高亮正确。跨页合并表格、手写内容和插图提取不从缺失字段中推测。

## 任务与失败恢复

- Redis 租约隔离同一解析任务，并带心跳和 token 所有权检查；账户槽位限制总并发。
- 上传成功保存附件 ID；提交前先保存 `submitting`，返回后保存全部远端文件 ID。
- 查询超时再次解析时恢复查询，不重新提交。
- `submitting` 表示提交结果不确定，禁止自动重放。运维先在同一空间核实远端文件，再在正确租户上下文调用 `DocFlowService.reconcile(job_key, file_ids, batch_number)`；方法会核对文件在空间内可见，后续原任务可恢复。
- 远端附件未提供删除协议，不能自动猜测删除地址。上线时由 MK/合合管理员约定远端保留和清理策略。
- SQL 检查点清理应走运维维护流程，勿删除仍可能恢复的 `submitting`/`submitted` 记录。清理成功记录会失去相应缓存复用机会。

## 入库一致性

DocFlow 的文件解析和重试增加独立文件租约，不依赖公平调度开关。常规 provider 保持现有执行方式。知识库文档身份包含目标集合/索引、模型以及模型/服务端配置摘要。

入库依次记录 deleting、writing_vector、vector_done、writing_es、done。确认 vector_done 后 ES 失败只补 ES。向量写入不确定时按 document_id 清理后重放，复用已保存的文档向量，避免通常情况下的重复 embedding。ES 使用稳定 chunk ID。Milvus 当前集合使用 auto_id，不能冒充已经实现稳定 Milvus 主键。

同一分段快照完成后不重复入库。状态变更造成的 update_time 变化不触发重新 embedding；恢复时复用首次写入的分段快照，保持两个索引的元数据一致。文本、其他元数据或模型配置变化则清理并重新处理。

没有跨 Milvus/ES 的分布式事务，也不承诺外部模型恰好调用一次。模型返回与缓存写入之间崩溃可能重算；补偿期间存在索引可见性的短窗口。人为删除/重建集合后须同步处理旧入库检查点，不能保留指向已删除索引的 done 状态。

## 测试和上线

前端平台和客户端已接入 `docflow` 解析器标识。DocFlow 的来源坐标使用从 1 开始的页码，PDF 预览不能直接套用 ETL 的从 0 开始约定；OFD 使用既有转换后的 PDF 预览，图片使用原图。

本次本地检查记录见 `features/v3.0.0-beta3/docflow/verification.md`。真实环境验收仍以同目录的 `e2e-checklist.md` 为准。

定向测试入口：

```bash
cd src/backend
PYTHONPATH=. python -m pytest --confcutdir=test/knowledge/docflow test/knowledge/docflow -q
```

该套件注入 HTTP、Redis、MinIO 和检索服务，以真实 converter、Loader、标准分段器及 SQLite SQLModel 验证协议和恢复行为，不是生产 middleware 联调结果。另需在目标环境执行 MySQL/DM8、Redis、MinIO、Milvus、ES 与真实 MK 的全链路验收：预览→确认→入库→检索→引用。

灰度时先准备专用空间，关闭拆分，配置额度和清理周期。使用图片、多页 PDF、双栏和表格样本；核实只有一个正文进入分段/embedding。历史文件不会自动重新解析。回退时切回原 loader_provider，既有索引可继续使用，失败 DocFlow 文件按受控流程处理。
