# 灵思技能包源码

这里放**灵思（Linsight）任务模式**技能包的源码 —— 就是管理端「灵思 → 技能」里上传的那种 zip。
与仓库里的 `.claude/skills`、`.agents/skills`（Claude Code 自己的技能）**没有任何关系**，两者互不通用。

技能包不随后端发布，运行时数据落在 `SKILLS_ROOT`（默认 `src/backend/data/linsight_skills/`，已 gitignore）。
源码放在这里是为了版本管理和评审。

| 目录 | 说明 |
|---|---|
| `bisheng-pptx/` | PPT 制作。python-pptx 生成 .pptx，含排版规范、模板套用、交付前自检 |
| `bisheng-xlsx/` | Excel 表格。openpyxl 生成 .xlsx，含公式禁用清单、LibreOffice 重算、审计配色 |
| `bisheng-docx/` | Word 文档。python-docx 生成 .docx，含中文字体（w:eastAsia）、目录页码、排版自检 |

三个都是 **Anthropic 官方 xlsx/pptx/docx skill 的 BiSheng 适配版**，不是直接搬运。
为什么必须重写而不能原样导入，见
`docs/PRD/2.6 灵思 deepagents 迁移 PRD/Anthropic office skills 依赖审计与 bisheng 环境缺口.md`。
一句话：官方把主干押在这套环境里根本没有的东西上（Node/pptxgenjs/docx-js、markitdown、
pdftoppm、defusedxml），而且**官方 skill 的 LICENSE 是专有条款，明文禁止 reproduce 和
derivative works，不能打包分发**。

## 环境前提（实测）

- **依赖已经在镜像里，无需额外安装**：`python-pptx>=1.0.2`、`python-docx>=1.2.0`、
  `openpyxl>=3.1.5`、`pymupdf`、`pandas`、`matplotlib`、`Pillow`、`lxml` 都是
  `src/backend/pyproject.toml` 的正式依赖。
  > ⚠️ 在容器里核实依赖必须用 **`/app/.venv/bin/python`**，不能用 `python`／`bash -lc "python ..."` ——
  > 后者解析到 `/usr/local/bin/python3`（venv 的 base 解释器），看不到 venv 的 site-packages，
  > 会把装好的包全部误判成缺失。
- **需要用户勾选代码执行器**（`bisheng_code_interpreter`），否则无法生成任何文件。
- **镜像里没有** node/npm、`zip`/`unzip`、`pdftoppm`、`markitdown`、`defusedxml`（实测确认）。
  `libreoffice` 元包**有** Writer/Calc/Impress；但 114 这类手工部署的机器可能只装了
  `libreoffice-writer`，那样 xlsx 重算和 pptx/预览渲染都会失败 —— 三个技能都会明确报出来并降级，
  不会假装成功。
- **pandoc 3.6.4** 在发布镜像里有（手工部署的机器未必）。

## 打包与导入

```bash
bash scripts/pack_linsight_skill.sh linsight-skills/bisheng-xlsx
# → dist/bisheng-xlsx.zip
```

脚本会先校验后端在导入时会卡的那几条（SKILL.md 在包根、frontmatter `name` 等于目录名且是
kebab-case、zip ≤10MB、解包 ≤100MB），失败在本地就报出来，不用等管理端返回 11051/11052/11059。

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
- `metadata.display-name`：管理页与用户勾选器里显示的名字，可中文，≤255。
- 其它键（`license`、`allowed-tools` 等）原样保留、不校验。**`allowed-tools` 在 bisheng 里不生效**，
  本轮可用的工具完全由用户在前端勾选的工具决定，技能无法声明依赖。
- 同租户内 `name` 和 `display-name` 任一重复都会被拒（11055），不会自动加后缀。

**运行时**

- 模型必须自己 `read_file("/skills/<name>/SKILL.md", limit=1000)` 才能读到正文（progressive disclosure）。
  正文里引用别的文件也要给全路径 `/skills/<name>/references/xxx.md`。
- 代码执行器（`bisheng_code_interpreter`）的 cwd 是工作区根，包内文件用**相对路径** `skills/<name>/...` 打开。
  写成 `/skills/...` 会被判定为逃出工作区。
- 包里的二进制资产（模板、字体、图片）**不能被 `read_file` 读**（会被二进制守卫拦下），
  只能由代码执行器打开。
- `output/` 是唯一交付区；`skills/`、`scratch/`、`uploads/` 都不会被当作交付物。
- 交付物排序按文件类型：md/docx/pdf/html = 0，xlsx = 1，pptx = 2，其它 = 3，图片 = 4。
  往 `output/` 多放一个 `.md` 会顶掉 xlsx/pptx 成为用户看到的头条文件 —— 过程稿一律放 `scratch/`。
- 脚本**不要用非零退出码**：执行器在失败路径只回传 stderr、丢弃 stdout，报告会整个消失。
  用输出文本表达结论，始终 exit 0。三个技能包的脚本都遵守这条。
- 调包内脚本一律 `subprocess.run([sys.executable, ...])`。`infer_lang` 会把以 `python `/`pip`
  开头的整块代码当 sh 跑，而 PATH 里的 `python` 未必是后端 venv 那个。
- ⚠️ **E2B 沙箱模式下技能包不可见**：copy-in 的文件清单在工具初始化时快照，早于技能物化，
  且 E2B 的 `_materialize_working_set` 目前直接返回空。依赖包内脚本的技能只在默认的
  LocalExecutor 下成立。

## 自测

三个技能包的脚本都在一个与后端依赖等价的容器里跑过（`python:3.11-slim` + 同一条 apt 行 +
python-pptx/docx/openpyxl/pymupdf 同版本），用「故意写坏的文件」验证每条检查都会响、
且合法写法不误报。复现方式见依赖审计文档的 §8 POC 记录。
