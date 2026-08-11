# 灵思技能包编写指南

本文讲**灵思（Linsight）任务模式**技能包怎么写、怎么随部署分发。
与仓库里的 `.claude/skills`、`.agents/skills`（Claude Code 自己的技能）**没有任何关系**，两者互不通用。

## 内置技能：放哪、怎么生效

源码放在 **`src/backend/bisheng/linsight/builtin_skills/<name>/`** —— 必须在 `src/backend/` 之内，
因为 `src/backend/Dockerfile` 是 `COPY ./ ./`，构建上下文就是 `src/backend`，仓库根的目录不会进镜像。
放在包内之后，docker 镜像、裸机 rsync、pip 安装都自动带上。

| 目录 | 说明 |
|---|---|
| `bisheng-pptx/` | PPT 制作技能（BiSheng 适配版）。用 python-pptx 生成 .pptx，含中文排版规范、模板套用、交付前自检脚本。用户要「PPT／幻灯片／汇报材料」时用 |
| `bisheng-xlsx/` | Excel 表格技能。用 openpyxl 生成 .xlsx，交付前必须经 LibreOffice Calc 重算公式再体检。用户要「表格／报表／台账／预算测算／财务模型」时用 |
| `bisheng-docx/` | Word 文档技能。用 python-docx 生成 .docx，覆盖 `w:eastAsia` 中文字体、目录域、页码、表格列宽、封面。用户要**带版式**的正式文档时用；只是「把刚才的内容存成 Word」走自带的 `export_docx`，别用本技能 |

生效链路是**应用启动时自动 seed**（`domain/services/builtin_skill_seeder.py`，挂在 `main.py` 的
lifespan 上，和既有的两个 backfill 同一位置）：读包 → 遍历活跃租户 → 写入
`SKILLS_ROOT/data/skills/{tenant_id}/<name>/` 并建 `linsight_skill` 行（`source='builtin'`）。
所以 `docker compose up` 起来技能就在选择器里，**不需要任何运维脚本**。

几条设计约束，加新内置技能前先了解：

- **幂等靠内容比对**：磁盘上已装的 bundle 与镜像里的逐字节比，不同才重写。升级镜像重启即更新，
  没变的话只花几次文件读取。`__pycache__`/`.pyc`/`.DS_Store` 被 seeder 与打包脚本一致跳过，
  所以本地跑过脚本留下的 `__pycache__` 不会让每次启动都判成「变了」。
- **用户改过的永不覆盖**：管理端编辑内置技能会把 `source` 翻成 `manual`（`SkillService._mark_forked`），
  该租户的副本从此不再被 seed 覆盖。这是刻意的——升级时静默回滚客户的修改，比让副本漂移糟糕得多。
- **新租户会补种**：启动 seed 只覆盖当时存在的租户，所以 `TenantService.acreate_tenant` 的 Step 6
  也会为新租户 seed 一次。
- **每租户一份物理拷贝**。现在三个包合计约 210KB（pptx 77KB / xlsx 74KB / docx 63KB），
  100 个租户 21MB 可忽略；但如果将来内置技能带模板库/字体（官方 `presentations` 包 4.7MB），
  就该改走「只读目录 + DB 只存指针」的形态。
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
- **`pandoc` 存在，但不用它做 PPT**。发布镜像手工装了 pandoc 3.6.4 到 `/usr/bin`
  （`src/backend/base.Dockerfile:21-27`），`pandoc -o out.pptx` 确实能跑，但只产出「标题＋项目符号」
  的裸版式，配色/版式/图表/图片位置全不可控。SKILL.md 里要写「有，但不用，因为…」——
  把存在的东西写成「不存在」，模型自己 `which` 到之后会开始怀疑整张环境表。

### bisheng-xlsx 的环境前提（实测）

- **依赖已经在镜像里**。`openpyxl>=3.1.5` 是 `src/backend/pyproject.toml` 的正式依赖（第 56 行），
  `import openpyxl` 直接可用。`XlsxWriter` 也在，但只能新建、不能读改已有文件，也不能和 openpyxl
  混用 —— 一律走 openpyxl。`markitdown` 不在。
- **需要用户勾选代码执行器**（`bisheng_code_interpreter`）。
- **公式必须经 LibreOffice Calc 重算**。openpyxl 写出的公式只有公式文本、**没有缓存值**，
  不重算就等于交了一张全空的表（Excel 打开会自己算，但预览、pandas、下游接口读到的全是 None）。
  包内 `scripts/recalc_check.py` 用 `soffice` 把文件就地重写一遍，再扫结果里有没有 `#NAME?`/`#REF!`。
- **Calc 组件不是每台机器都有**。发布镜像装的是 Debian `libreoffice` 元包（`base.Dockerfile:12`），
  Calc 在；114 这类手动只装了 `libreoffice-writer` 的机器**没有** Calc，重算会失败。
  此时脚本如实报错并给降级方案（公式改成 Python 先算好、写数值），**不要假装重算过了**。
- **不要用「有没有 `scalc` 可执行文件」判断 Calc 在不在**。非 Debian 布局（如 macOS 版 LibreOffice）
  根本没有 `scalc` 这个文件，而 Calc 完全可用 —— 这样探针会 100% 假阴性，把能用的部署判死。
  同理，**判重算成败要看文件有没有被重写**（mtime + size），不能只看退出码：soffice 什么都没转也会 exit 0。

### bisheng-docx 的环境前提（实测）

- **依赖已经在镜像里**。`python-docx>=1.2.0` 是 `src/backend/pyproject.toml` 的正式依赖（第 80 行），
  `import docx` 直接可用。
- **需要用户勾选代码执行器**（`bisheng_code_interpreter`）。
- **中文字体必须显式写 `w:eastAsia`**。`run.font.name` 只设西文，中文会退回 Calibri/宋体。
  包内 `set_run_font()` 一次写 ascii/hAnsi/eastAsia 三个属性；只设 latin 的文档看着「设过字体」，
  打开全是错字体。
- **渲染预览走 LibreOffice Writer，比 pptx 宽松**。发布镜像的 `libreoffice` 元包和 114 那种只装了
  `libreoffice-writer` 的机器**都有** Writer，docx→pdf 两边都转得出来（pptx 需要的 Impress 只有前者有）。
  没有 `soffice` 时脚本跳过预览，不影响 .docx 的生成与交付。
- **与自带 `export_docx` 的边界必须在 SKILL.md 里写死**。`export_docx` 走 MarkDocx：只吃 `output/`
  下的 markdown，实测产出 US Letter 21.6×27.9cm、左右边距 3.2cm、表格 `tblW=auto`（无列宽无表头底纹）、
  无目录域无页码域无页眉页脚、图片固定 5.7 英寸。要 A4、目录、页码、列宽、封面，或要改用户上传的
  .docx，才用本技能。边界不写死，模型会拿重路线做轻活，或者反过来用 `export_docx` 交一份没版式的稿。

## 打包与导入

```bash
bash scripts/pack_linsight_skill.sh src/backend/bisheng/linsight/builtin_skills/bisheng-pptx
bash scripts/pack_linsight_skill.sh src/backend/bisheng/linsight/builtin_skills/bisheng-xlsx
bash scripts/pack_linsight_skill.sh src/backend/bisheng/linsight/builtin_skills/bisheng-docx
# → dist/bisheng-pptx.zip / dist/bisheng-xlsx.zip / dist/bisheng-docx.zip
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
  写成 `/skills/...` 指向的是宿主机根目录，`open()` 必 FileNotFoundError
  （`base_executor` 的 `_ABSOLUTE_PROVISIONED_RE` 只会附一条提醒，**不拦截**，所以错了也照跑照崩）。
  **两套路径命名空间是刻意区分的，不要「统一」掉**：给 `read_file` 的引用**带**前导斜杠，
  给代码执行器的路径（`skills/`、`output/`、`uploads/`、`scratch/`）**不带**。
- 调包内脚本一律 `subprocess.run([sys.executable, "skills/<name>/scripts/x.py", ...])`。写 `python` 会被
  `infer_lang` 判成 sh，且 PATH 里的 `python` 未必是后端 venv。
- 提交给执行器的代码里**只要出现三反引号围栏，就只会执行围栏内的内容**（`CODE_BLOCK_PATTERN`）——
  别在代码参数里贴 markdown。
- 包里的二进制资产（模板 .pptx、字体、图片）**不能被 `read_file` 读**（会被二进制守卫拦下），
  只能由代码执行器打开。
- `output/` 是唯一交付区（每次运行自动创建）；`skills/`、`scratch/`、`uploads/` 都不会被当作交付物。
  `scratch/` **从不**自动创建，要自己 `os.makedirs`。跨轮追问时服务端只把上一轮的 `output/` 与 `uploads/`
  拷进新会话，**`scratch/` 跨轮即丢**。
- 交付物排序按文件类型（`linsight/domain/utils.py` 的 `_DELIVERABLE_TYPE_RANK`）：
  md/docx/pdf/html = 0，xlsx/csv = 1，pptx = 2，未知 = 3，图片 = 4，同档再按 mtime。
  这是**按类型**不是按轮次：只要 `output/` 里有一个 `.md`，它就**永远**压过 `.xlsx`/`.pptx` 成为用户看到的
  头条文件 —— 过程稿、提纲、草稿一律放 `scratch/`。
- 脚本**始终 exit 0，所有诊断走 stdout 的 `print()`**。执行器是二选一：`returncode != 0` 只回 stderr
  （stdout 整段丢弃）；`returncode == 0` 只回 stdout（stderr 整段丢弃）。用非零退出码表达失败，报告会整个消失；
  同理，转发子进程输出要 stdout / stderr **各打一行**，`print(r.stdout or r.stderr)` 这种写法会因短路吞掉 stderr。
- 判是否产出以 **exitcode 0 + 日志**为准。exitcode 0 时执行器会把本轮新建/修改的文件同步进工作区
  （`local_executor.sync_to_workspace`），之后 `ls`/`read_file` 一般能看到，但不要因为一次 `ls` 没看到就重做。
- 最后两轮工具会收窄到 `write_file`/`edit_file`/`export_*`（`resilience_middleware`），
  代码执行器被拦掉 —— 交付物要尽早产出，不要拖到收尾。

> ⚠️ **E2B 沙箱模式下技能包结构性不可见 —— 三个内置包共同的失效前提。**
> copy-in 的文件清单在工具初始化时快照，早于技能物化（`e2b_executor.py` 的
> `path_namespace_rules(include_skills=False)`），且 `_materialize_working_set` 目前直接返回空。
> 结果是沙箱里 `skills/` 整个不存在，调包内脚本必 `FileNotFoundError`；单次执行上限也从本地的
> 600 秒（`local_executor.py:25`）降到 **300 秒**（`e2b_executor.py:32`）。
> 依赖包内脚本/模板的技能只在默认的 LocalExecutor 下成立。**SKILL.md 里要给出可执行的自救判定**
> （探一次 `os.path.isdir("skills/<name>/scripts")`）**和降级路线**（改走纯库内联写法、把 helper 抄进构建脚本、
> 自检改为自己核对并告知用户），否则模型只会在 `FileNotFoundError` 上反复重试直到耗尽轮次。

**自检脚本（三个内置包共用的约定）**

- 双段输出：`=== 内容 ===`（读出来给模型看的正文）+ `=== 体检 ===`（Finding）。Finding 三级
  ERROR / WARN / INFO，每条 message 必须带「现象（带具体数字）→ 怎么改」，只有 ERROR 阻塞交付。
- 结尾固定 `合计: x ERROR / y WARN / z INFO` + 终止串 **`结论: 通过`**（SKILL.md 拿它当模型的停止条件，
  字面不许改）。同一个包里如果有第二个脚本也打这串（如 xlsx 的重算脚本），SKILL.md 必须把两步的先后写清楚。
- **检查器必须可满足**：阈值按「明显坏掉」定，不要照抄写作规范。规范允许的写法（如 design-zh 允许的
  10pt 注释字号）若被判 ERROR，一份完全合规的稿子也永远到不了「结论: 通过」，模型就会学会无视整份报告。
  阈值刻意比规范松一档时，在常量旁写明对应条款，并在报告结尾点明「没报 ERROR ≠ 符合规范」。
- 脚本崩溃也要 exit 0：主体抽成函数，`main()` 里 `except Exception` → 打 `[FATAL]` +
  `traceback.print_exc(file=sys.stdout)` + 一句「怎么办」。损坏/加密/改过扩展名的文件都会走这条路，
  非零退出会让整份报告被执行器丢弃，模型看到的是空白。
- 脚本的模块 docstring 与代码注释用**英文**，`print` 出去的文案用**中文**；祈使句，
  不写「可能 / 建议尝试」这类软话（模型会当成可选项）。

## 待办：灵思交付物的 .pptx 在线预览（已评估，未实施）

当前 `.pptx` 交付物在前端是 `unsupported`，只能「下载后查看」
（`client/src/components/Linsight/Artifacts/artifactUtils.ts` 的 `DOCUMENT_EXTS` 不含 pptx；
答案正文里的 `.pptx` 链接也不会被解析成可点预览）。**只有 pptx 有这个问题** ——
`.docx`/`.xlsx`/`.csv` 都在 `DOCUMENT_EXTS` 里，前端用 mammoth / xlsx 直接渲染，无需后端转换。

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
