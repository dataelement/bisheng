# 灵思技能包编写指南

本文讲**灵思（Linsight）任务模式**技能包怎么写、怎么随部署分发。
与仓库里的 `.claude/skills`、`.agents/skills`（Claude Code 自己的技能）**没有任何关系**，两者互不通用。

## 内置技能：放哪、怎么生效

源码放在 **`src/backend/bisheng/linsight/builtin_skills/<name>/`** —— 必须在 `src/backend/` 之内，
因为 `src/backend/Dockerfile` 是 `COPY ./ ./`，构建上下文就是 `src/backend`，仓库根的目录不会进镜像。
放在包内之后，docker 镜像、裸机 rsync、pip 安装都自动带上。

| 目录 | 说明 |
|---|---|
| `bisheng-pptx/` | PPT 制作技能（BiSheng 适配版）。用 python-pptx 生成 .pptx，含排版规范、模板套用、交付前自检脚本 |

生效链路是**应用启动时自动 seed**（`domain/services/builtin_skill_seeder.py`，挂在 `main.py` 的
lifespan 上，和既有的两个 backfill 同一位置）：读包 → 遍历活跃租户 → 写入
`SKILLS_ROOT/data/skills/{tenant_id}/<name>/` 并建 `linsight_skill` 行（`source='builtin'`）。
所以 `docker compose up` 起来技能就在选择器里，**不需要任何运维脚本**。

几条设计约束，加新内置技能前先了解：

- **幂等靠内容比对**：磁盘上已装的 bundle 与镜像里的逐字节比，不同才重写。升级镜像重启即更新，
  没变的话只花几次文件读取。
- **用户改过的永不覆盖**：管理端编辑内置技能会把 `source` 翻成 `manual`（`SkillService._mark_forked`），
  该租户的副本从此不再被 seed 覆盖。这是刻意的——升级时静默回滚客户的修改，比让副本漂移糟糕得多。
- **新租户会补种**：启动 seed 只覆盖当时存在的租户，所以 `TenantService.acreate_tenant` 的 Step 6
  也会为新租户 seed 一次。
- **每租户一份物理拷贝**。现在这个包 80KB，100 个租户 8MB 可忽略；但如果将来内置技能带模板库/字体
  （官方 `presentations` 包 4.7MB），就该改走「只读目录 + DB 只存指针」的形态。
- **不要写进 Alembic 迁移**：项目铁律是 revision 只做 DDL，数据 seed 一律走独立流程。

**不打算内置的技能**（客户定制、一次性）不用放这里，直接用下面的打包流程做成 zip 在管理端导入即可。

### bisheng-pptx 的环境前提（实测）

- **依赖已经在镜像里，无需额外安装**。`python-pptx>=1.0.2` 是 `src/backend/pyproject.toml` 的正式依赖，
  main / hotfix/2.6.0 / 3.0 各线都有（都在第 81 行）。实测：
  116（`bisheng-backend:release`，2.6）与 180（`v2.6.0-fix2`）容器内 `python-pptx 1.0.2`、
  `PyMuPDF 1.26.6`、`Pillow`、`lxml`、`matplotlib`、`pandas`、`reportlab`、`openpyxl`、`XlsxWriter` 全部在位；
  `defusedxml` 和 `markitdown` 都没有（本技能不依赖它们，这正是不照搬官方 skill 的原因之一）。
  > ⚠️ 在容器里核实依赖必须用 **`/app/.venv/bin/python`**，不能用 `python`／`bash -lc "python ..."` ——
  > 后者解析到 `/usr/local/bin/python3`（venv 的 base 解释器），看不到 venv 的 site-packages，
  > 会把装好的包全部误判成缺失。
- **需要用户勾选代码执行器**（`bisheng_code_interpreter`），否则无法生成文件。
- **预览渲染需要 LibreOffice 带 Impress**。镜像（`base.Dockerfile` 装 Debian `libreoffice` 元包）
  实测**有** impress：116、180 上 pptx→pdf 都成功（`impress_pdf_Export` 过滤器）。
  但 114 这类手动只装了 `libreoffice-writer` 的机器**没有** impress，转换会报
  "source file could not be loaded"。这只影响可选的视觉 QA，不影响 .pptx 的生成与交付，
  脚本会给出明确提示并跳过。
- **镜像里没有 node/npm、unzip/zip、pdftoppm**（180 实测）—— 官方 skill 的 pptxgenjs 路线、
  解包重打包路线、pdftoppm 出图路线在这里全部走不通。

## 打包与导入

```bash
bash scripts/pack_linsight_skill.sh src/backend/bisheng/linsight/builtin_skills/bisheng-pptx
# → dist/bisheng-pptx.zip
```

脚本会先校验后端在导入时会卡的那几条（SKILL.md 在包根、frontmatter `name` 等于目录名且是 kebab-case、
zip ≤10MB、解包 ≤100MB），失败在本地就报出来，不用等管理端返回 11051/11052/11059。

导入：管理端 → 灵思 → 技能 → 上传 zip（需要**租户管理员**权限）。技能是**租户私有**的，
Root 租户的技能不会下放给子租户，每个租户都要各导一份。

用户侧使用：在任务模式的技能选择器里勾选它。**技能是纯手动勾选，没有自动匹配** ——
没勾选的技能包根本不会被复制进会话工作区，模型物理上看不到。

## 写技能包时必须知道的事

**格式**

- `SKILL.md` 必须在包根，带 YAML frontmatter。
- `name` 必填，`^[a-z0-9]+(-[a-z0-9]+)*$`，≤64，**必须等于目录名**。非法名会被 slugify（中文转拼音）静默改写。
- `description` 必填，≤1024 字符。**这是唯一进入模型 prompt 的文字** —— 正文完全不注入。
  技能会不会被用起来，100% 取决于 description 写没写全场景与关键词。
- `metadata.display-name`：管理页与用户勾选器里显示的名字，可中文，≤255。不写就退回 `name` 那个英文 slug。
- 其它键（`license`、`allowed-tools` 等）原样保留、不校验。**`allowed-tools` 在 bisheng 里不生效**，
  本轮可用的工具完全由用户在前端勾选的工具决定，技能无法声明依赖。
- 同租户内 `name` 和 `display-name` 任一重复都会被拒（11055），不会自动加后缀。

**运行时**

- 模型必须自己 `read_file("/skills/<name>/SKILL.md", limit=1000)` 才能读到正文（progressive disclosure）。
  正文里引用别的文件也要给全路径 `/skills/<name>/references/xxx.md`。
- 代码执行器（`bisheng_code_interpreter`）的 cwd 是工作区根，包内文件用**相对路径** `skills/<name>/...` 打开。
  写成 `/skills/...` 会被判定为逃出工作区。
- 包里的二进制资产（模板 .pptx、字体、图片）**不能被 `read_file` 读**（会被二进制守卫拦下），
  只能由代码执行器打开。
- `output/` 是唯一交付区；`skills/`、`scratch/`、`uploads/` 都不会被当作交付物。
- 交付物排序按文件类型：md/docx/pdf/html = 0，xlsx = 1，pptx = 2，其它 = 3，图片 = 4。
  同一轮里往 `output/` 写 `.md` 会让它顶掉 `.pptx` 成为用户看到的头条文件 —— 过程稿一律放 `scratch/`。
- 脚本**不要用非零退出码**：执行器在失败路径只回传 stderr、丢弃 stdout，报告会整个消失。
  用输出文本表达结论，始终 exit 0。
- ⚠️ **E2B 沙箱模式下技能包不可见**：copy-in 的文件清单在工具初始化时快照，早于技能物化，
  且 E2B 的 `_materialize_working_set` 目前直接返回空。依赖包内脚本/模板的技能只在默认的 LocalExecutor 下成立。

## 待办：灵思交付物的 .pptx 在线预览（已评估，未实施）

当前 `.pptx` 交付物在前端是 `unsupported`，只能「下载后查看」
（`client/src/components/Linsight/Artifacts/artifactUtils.ts` 的 `DOCUMENT_EXTS` 不含 pptx；
答案正文里的 `.pptx` 链接也不会被解析成可点预览）。

**把 pptx 加进 `DOCUMENT_EXTS` 这一行远远不够。** `FilePreview` 对 ppt/pptx 的策略是复用 PDF viewer
（`pages/knowledge/FilePreview/viewers/index.ts` 里 `pptx: "pdf"`），前提是后端给出一个已经转好的 `preview_url`。
知识库能做到，是因为它在入库解析阶段就生成了预览 PDF 并把对象名持久化在 `KnowledgeFile.preview_file_object_name`
（见 `knowledge_service.get_file_share_url`）。灵思交付物**完全没有这套**：只有
`linsight/final_result/{svid}/{file_id}{ext}` 一个对象和 `output_result["final_files"]` 里的元数据，
既没有预览字段，也没有转换时机；`POST /workbench/file_download` 只是把 object key 换成预签名 URL。

要做的话需要补齐：

1. 后端一个转换服务：复用现成的 `knowledge/rag/pipeline/loader/utils/libreoffice_converter.convert_ppt_to_pdf()`，
   把结果缓存到 `linsight/final_result_preview/{svid}/{file_id}.pdf`。
2. 转换时机建议**首次请求时懒转 + 缓存**（收割时同步转会给每个任务收尾加上 LibreOffice 的 10–30s 冷启动，
   而多数交付物用户并不会点开预览；异步 Celery 方案还要额外维护状态位）。需要处理并发去重与失败降级。
3. 一个返回 `preview_url` 的端点（或在现有 `file_download` 上加 `preview=true` 分支），沿用同一套分享链接鉴权。
4. 前端：`DOCUMENT_EXTS` 加 `pptx`、`PreviewBody` 取 `preview_url`、转换失败时回落到现在的「下载后查看」。

**工作量估计 ~2–2.5 人天**（后端 1–1.5、前端 0.5、测试 0.5）。

**风险（产品决策点）**：服务端只有文泉驿正黑一种中文字体，转出来的 PDF 版式与用户本机 PowerPoint 打开的效果
会有出入 —— 预览越像"最终稿"，这种不一致越容易变成投诉。真要上，预览页需要明确标注
「预览为服务端渲染，实际排版以 PowerPoint 打开为准」。

结论：**建议单独立项**，不随技能包一起做。
