# Anthropic 官方 office skills（xlsx / pptx / docx）依赖审计与 bisheng 环境缺口

> **调研日期**：2026-08-11
> **对象**：`github.com/anthropics/skills` 的 `skills/xlsx`、`skills/pptx`、`skills/docx`（浅克隆全量源码逐文件读取，非凭记忆）
> **对照基线**：`src/backend/pyproject.toml` + `uv.lock`、`src/backend/base.Dockerfile`、`local_executor.py` / `e2b_executor.py`、114 手动部署环境、E2B `code-interpreter-v1` 默认模板
> **方法**：多 agent 并行提取 + 对抗式核验（关键结论均要求一手来源；被证伪的原始判断已按修正表述改写）
> **姊妹篇**：[灵思代码执行沙箱选型调研（私有化场景）](./灵思代码执行沙箱选型调研（私有化场景）.md)

**一句话结论**：依赖缺口按 skill 分档差别极大 —— **xlsx 在官方镜像上主干本来就能跑通，docx 只死「创建」一半，只有 pptx 是真·大面积失效**；但即使依赖全部补齐，官方 skill 里 11 条「只对 Claude 成立」的假设也不会消失，因此**唯一现实选项是做适配版**（`linsight-skills/bisheng-pptx/` 已验证该路线），而非原样导入 —— 后者还额外撞上 LICENSE 的专有条款红线。

---

## 1. 三个 skill 的依赖全景

标记含义：**阻塞** = 缺了主干路径直接死；**降级** = 有替代路径，功能打折；**可选** = 有 which/try 守卫或走不到；**—** = 该 skill 完全不引用。

| 依赖项 | 类型 | xlsx | pptx | docx | 关键度（取三者最高） | 用途 |
|---|---|---|---|---|---|---|
| openpyxl | py | **阻塞** | — | — | 阻塞 | xlsx 创建/编辑主干 + `recalc.py:21` |
| pandas | py | 降级 | — | — | 降级 | xlsx 批量进出，openpyxl 可完全替代 |
| defusedxml | py | 可选 | **阻塞** | **阻塞** | 阻塞 | `clean.py` / `thumbnail.py` / `merge_runs.py` / `comment.py` / `office/validate.py` 首行 import |
| lxml | py | 可选 | **阻塞** | **阻塞** | 阻塞 | `validators/base.py:11` XSD 引擎唯一实现 |
| markitdown（CLI 形态） | py/bin | 降级 | **阻塞** | — | 阻塞 | pptx 唯一文本读取路径 + Content QA；xlsx 仅 quick look |
| Pillow | py | — | 降级 | — | 降级 | 仅 `thumbnail.py` 拼标注网格 |
| python-pptx | py | — | 可选 | — | 可选 | pptx 里被官方**主动劝退**的次选路径 |
| **pptxgenjs** | node | — | **阻塞** | — | 阻塞 | pptx「创建新 deck」官方主推，SKILL.md 近半篇幅为其 footgun |
| **docx (docx-js)** | node | — | — | **阻塞** | 阻塞 | docx「创建新文档」官方主推 |
| sharp / react / react-dom / react-icons | node | — | 降级 | — | 降级 | pptx 图标流水线（sharp 带 libvips 原生二进制，最难离线） |
| node | bin | — | **阻塞** | **阻塞** | 阻塞 | 跑上面两条 JS 主干 |
| npm | bin | — | 降级 | 降级 | 降级 | SKILL.md 唯一自愈路径，隐含 registry 可达 |
| **soffice + Calc** | bin | **阻塞** | — | — | 阻塞 | `recalc.py` 公式重算（SKILL.md 标 mandatory） |
| **soffice + Impress** | bin | — | **阻塞** | — | 阻塞 | pptx→pdf（视觉 QA 与 `thumbnail.py`） |
| **soffice + Writer** | bin | — | — | **阻塞** | 阻塞 | docx→pdf 渲染自检 + `accept_changes.py` 宏 |
| pdftoppm (poppler-utils) | bin | — | **阻塞** | **阻塞** | 阻塞 | PDF→JPG，两个 skill 的视觉 QA 唯一实现 |
| pandoc | bin | — | — | **阻塞** | 阻塞 | docx 唯一读取路径 `pandoc -t markdown` |
| zip | bin | — | **阻塞** | **阻塞** | 阻塞 | 「解包→改 XML→回包」主干的回包步 |
| unzip | bin | — | 可选 | **阻塞** | 阻塞 | docx SKILL.md:52 用 `unzip`；pptx 用 python zipfile 解包 |
| gcc | bin | 可选 | 可选 | 可选 | 可选 | 仅 AF_UNIX 被禁时现场编 LD_PRELOAD shim，容器内永不触发 |
| git | bin | 可选 | 可选 | 可选 | 可选 | `redlining.py` 逐字 diff，有 try/except 兜底；仅 docx 分支可达 |
| timeout / gtimeout / grep / find | bin | 可选 | 可选 | 可选 | 可选 | 均有 which 守卫或基础镜像自带 |
| ghostscript / ImageMagick / pdftk | bin | — | — | — | **零引用** | 三个 skill 全文 grep 无命中，**不要装** |

共享 `scripts/office/` 树（三份逐字节相同，md5 已核）：

| 共享文件 | md5 | xlsx | pptx | docx |
|---|---|---|---|---|
| `office/soffice.py` | 2508a6df… | 用（recalc） | 用（转 pdf） | 用（转 pdf） |
| `office/validate.py` | 5e0197ec… | **空转**（`case "xlsx"` 直接 `sys.exit(0)`） | 用（required） | 用 |
| `office/validators/`（base/docx/pptx/redlining） | base=566ce69b… | 不可达 | 用 | 用 |
| `office/helpers/__init__.py` | e3ed7338… | 不可达 | 用（safe_extract/rezip） | 用 |
| `office/schemas/`（43 个 XSD，976,913 B） | — | **完全不可达** | 用 pml/dml-main/dml-chart/opc-* | 用 wml/opc-*/microsoft/* |

各 skill 独占资产：xlsx = `recalc.py`（308 行）；pptx = `clean.py` / `thumbnail.py` / `add_slide.py` + `helpers/pptx_*.py`；docx = `merge_runs.py` / `comment.py` / `accept_changes.py` + `scripts/templates/`（5 个批注骨架 XML，其中 `people.xml` 是死资产，`comment.py` 从不 copy 它）。

---

## 2. 缺口矩阵（核心交付物）

> ⚠️ **必读的环境区分**：114 是 RHEL 上手动装的开发测试机，与 `src/backend/base.Dockerfile` 构建出的官方发布镜像**不是同一套依赖基线**，两者的缺口面**互补而非包含**——114 有 node、官方镜像没有；官方镜像有完整 libreoffice 元包（含 Impress/Calc）和 pandoc 3.6.4，114 只有 libreoffice-writer。**"在 114 上装好跑通了"绝不等于"发布版能跑"**，反之亦然。任何验收都必须在两套环境各跑一遍，或者只以镜像为准。

| 依赖项 | bisheng 官方镜像 | 114 手动部署 | E2B `code-interpreter-v1` | 缺口结论 |
|---|---|---|---|---|
| openpyxl / pandas / Pillow / lxml / python-pptx / python-docx | ✅ pyproject 直接依赖（lxml 为 transitive） | ✅ 同 venv | ⚠️ 待验证，非模板承诺内容 | 镜像/114 无缺口；E2B 不可依赖 |
| defusedxml | ❌ pyproject + uv.lock 零命中 | ❌ | ⚠️ 待验证 | **全线缺失**，纯 python 包，最便宜的一修 |
| markitdown | ❌ 零命中 | ❌ 命令不存在 | ⚠️ 待验证 | 全线缺失；pptx 读取路径断 |
| soffice 二进制 | ✅ apt `libreoffice` 元包 | ✅ | ❌ 模板不承诺 | — |
| └ Calc（xlsx） | ✅ 元包 Depends 带入 | ❌ **只装了 writer** | ❌ | 114 上 `recalc.py` 必失败，且**伪装成 `soffice exited N` 或"never rewrote the file"，极易误判为超时** |
| └ Impress（pptx） | ✅ 元包带入 | ❌ | ❌ | 114 上 pptx→pdf 100% 失败 |
| └ Writer（docx） | ✅ | ✅ | ❌ | — |
| pandoc | ✅ 手装 3.6.4 二进制（base.Dockerfile:22-27） | ⚠️ 待验证 | ❌ | docx 读取路径，镜像唯一开箱即用的一条 |
| pdftoppm (poppler-utils) | ❌ apt 清单无（⚠️ 是否被 libreoffice 依赖链顺带带入待镜像内实测） | ❌ 待验证 | ⚠️ 待验证 | 视觉 QA 断 |
| zip / unzip | ❌ python:3.11-slim 不自带、apt 清单无 | ⚠️ 待验证（RHEL 通常自带） | ⚠️ 待验证 | pptx/docx 编辑主干回包步断；可用 `helpers/rezip()` 绕开 |
| node | ❌ **两个 Dockerfile 全文 grep 零命中** | ✅ v22.17.1（手动装，非交付基线） | ⚠️ 模板带 node 但不承诺 | 官方交付形态下 pptx/docx 创建主干 100% 死 |
| npm | ❌ | ⚠️ 在但 `npm install` 静默失败 | ⚠️ | 自愈路径断 |
| pptxgenjs / docx-js / sharp | ❌ | ❌ | ❌ | 同上 |
| 中文字体 | ✅ fonts-wqy-zenhei | ⚠️ 只有 Noto CJK | ❌ 不承诺任何 CJK | `local_executor.py:106-109` 硬注入 `family="WenQuanYi Zen Hei"` 在 114 **命中不到字体**，只出 warning；两边 LO 渲染宽度不一致，视觉 QA 结论不可跨环境复用 |
| Liberation / Carlito / Caladea（metric 兼容替换） | ❌ `--no-install-recommends` 已丢掉 LO 的 Recommends | ❌ 待验证 | ❌ | pptx SKILL.md:129-134 整套字号/溢出 QA 的可信度前提 |
| gcc | ✅ build-essential | ✅ | ⚠️ | 无风险（走不到） |
| **技能包 `skills/` 子树本身** | ✅ local 模式物化到 cwd | ✅ | ❌ **结构性不可见** | 见下 |

**E2B 那一列其实不必逐项看**：`_generate_tools`（拍 `os.walk` 快照建 copy-in 清单）在 `_create_agent`→`materialize_session_skills` 之前执行（task_exec.py:411→427 / 535→542 / 612→628），技能文件落盘时快照已拍完，**skills/ 永远进不了沙箱**；且 `e2b_executor.py:83` 用 `include_skills=False` 把 skills 路径提示从工具描述里刻意剥掉了。结果是最坏组合：模型能通过 `read_file` 读到 SKILL.md 正文（那条路走 WorkspaceBackend/MinIO，与沙箱无关），却拿不到说明书里的脚本。E2B 侧还有三条独立硬伤：单次执行超时回退 300s（local 是 600s，技能文案是按 600s 写的）、copy-in 单文件 5MB 硬阈值且超限静默丢弃、`_walk_sandbox` 只 `files.list('./')`（SDK 默认 depth=1）导致 `output/` 子目录产物不出现在返回的 `new_files` 里。

---

## 3. 短期方案：114 环境补齐清单

### 3.0 先定位后端 venv（这是必须先做的一步）

代码执行器起子进程用的是 **`sys.executable`**（`local_executor.py:172`），即灵思 worker 自己的解释器。**装到系统 python 一律无效**。

```bash
# 找出 linsight worker 进程的真实解释器
pgrep -af 'linsight|uvicorn|celery' 
readlink -f /proc/<PID>/exe        # → /path/to/.venv/bin/python
export VENV_PY=/path/to/.venv/bin/python    # 待验证：114 上的实际路径
```

⚠️ 连带坑：模型如果在代码里写 `subprocess.run(["python", "scripts/recalc.py", ...])`，那个 `python` 走的是 **PATH**，未必是 venv。适配版技能必须要求用 `sys.executable`。同理 `infer_lang`（`local_executor.py:78-92`）把以 `python ` / `pip` 开头的整块代码判成 **sh 直接执行**，模型贴一行 `python scripts/recalc.py` 会走 shell 分支、解释器再次跑偏。

### (a) Python 包 — 必须装进后端 venv

| 命令 | 解决什么 |
|---|---|
| `$VENV_PY -m pip install defusedxml`（或 `uv pip install --python "$VENV_PY" defusedxml`） | 让 pptx 的 `clean.py`/`thumbnail.py`、docx 的 `merge_runs.py`/`comment.py`、以及三家共用的 `office/validate.py` 不再在首行 ImportError。**性价比最高的一条** |
| `$VENV_PY -m pip install 'markitdown[pptx,xlsx]'` | 恢复 pptx 的读取路径与 Content QA（`markitdown output.pptx \| grep -iE ...` 占位符残留检查）、xlsx 的 quick look。⚠️ 其传递依赖体量**待验证**（不同版本 magika/onnxruntime 是否为可选 extra 有差异），装前先 `pip install --dry-run` 看清单 |

已有无需装：openpyxl 3.1.5、pandas 2.3.3、Pillow 12.0.0、lxml 6.0.2、python-pptx 1.0.2、python-docx 1.2.0、pymupdf 1.26.6、pypandoc 1.15。

**离线获取**：在同架构联网机上 `pip download defusedxml 'markitdown[pptx,xlsx]' -d ./wheels --platform manylinux2014_x86_64 --python-version 311 --only-binary=:all:`，rsync 到 114 后 `$VENV_PY -m pip install --no-index --find-links ./wheels defusedxml markitdown`。defusedxml 是纯 python wheel，无平台问题。

### (b) 系统包

| 命令 | 解决什么 |
|---|---|
| `sudo dnf install -y libreoffice-calc` | **114 当前最硬的阻塞**：xlsx skill 的 `recalc.py` 主干（SKILL.md 标 mandatory）。没有 Calc 过滤器时 soffice 命令存在但加载不进 xlsx，报错伪装成超时 |
| `sudo dnf install -y libreoffice-impress` | pptx→pdf 转换，`thumbnail.py:191-198` 与视觉 QA 的前置 |
| `sudo dnf install -y poppler-utils` | 提供 `pdftoppm`，pptx/docx 视觉 QA 的唯一实现（bisheng 已有 pymupdf 可替代，但会打破 `slide-01.jpg` 零填充命名约定，SKILL.md 与 `thumbnail.py:215` 的 glob 都依赖它） |
| `sudo dnf install -y zip unzip` | pptx/docx「解包→改 XML→回包」主干的回包步（`zip -Xr` 的 `-X` 是刻意去 extra field） |
| `sudo dnf install -y liberation-fonts google-crosextra-carlito-fonts google-crosextra-caladea-fonts` | 给 SKILL.md 点名的 Arial/Times/Calibri/Cambria 做 metric-compatible 替换，否则视觉 QA 量出来的行宽/溢出结论不可信 |
| `sudo dnf install -y wqy-zenhei-fonts` | 让 `local_executor.py:106-109` 硬注入的 `family="WenQuanYi Zen Hei"` 真正命中，与官方镜像对齐；否则 matplotlib 中文出豆腐块且只有 warning |
| — | **ghostscript / ImageMagick 不用装**：三个 skill 零引用 |

**离线获取**：联网同版本 RHEL 上 `dnf download --resolve --destdir=./rpms libreoffice-calc libreoffice-impress poppler-utils zip unzip liberation-fonts`，拷贝后 `sudo dnf install -y ./rpms/*.rpm --disablerepo=*`。注意 libreoffice-impress 的依赖闭包较大（会拉 core/common/ure/语言包），`--resolve` 必须带。

### (c) node 包

```bash
# 先确认 npm 静默失败的真因（几乎总是无外网 / 无 registry）
npm config get registry && npm ping
# 内网 registry 镜像写法
npm config set registry https://registry.npmmirror.com   # 或企业 Nexus/Verdaccio 地址
npm config set strict-ssl false                          # 仅当内网 Nexus 用自签证书

npm install -g pptxgenjs        # pptx「创建 deck」主干
npm install -g docx             # docx「创建文档」主干
npm install -g sharp react react-dom react-icons   # pptx 图标流水线（degraded）
export NODE_PATH=$(npm root -g)  # 全局安装后 require() 才找得到，必须注入执行器进程环境
```

**离线获取**：联网机 `npm pack pptxgenjs docx`（纯 JS，直接可搬）；`sharp` **不能这么搬**——它带 libvips 预编译原生二进制，必须 `npm install --os=linux --cpu=x64 --include=optional sharp` 后整棵 `node_modules` 打包搬运，且信创 arm64/龙芯平台可能根本没有对应预编译产物（**待验证**，届时需源码编译 libvips）。

**注意 114 上 npm 装完只对 114 有效，跟发布镜像毫无关系**——官方镜像连 node 运行时都没有。

---

## 4. 官方镜像要不要改（中长期）

| 依赖 | 建议 | 理由 | 体积增量量级 |
|---|---|---|---|
| `defusedxml` → pyproject | **加** | 纯 python、无传递依赖、解锁三个 skill 的校验/清理脚本；同时它是 `python-pptx` 依赖链里**没有**的（uv.lock:5057-5062 已核） | < 100 KB |
| `poppler-utils` → base.Dockerfile apt | **加** | 视觉 QA 的唯一实现；也是通用能力（PDF 转图在别处也用得上） | ~10-15 MB（含依赖，量级估计，待实测） |
| `zip` `unzip` → apt | **加** | 成本近乎零，且 OOXML 手术是三个 skill 的通用路径；顺带解决其它 skill 里裸 `unzip` 的失败 | < 1 MB |
| `fonts-liberation` `fonts-crosextra-carlito` `fonts-crosextra-caladea` → apt | **加** | 现在 `--no-install-recommends` 把 LO 的 Recommends 字体全丢了，这三个是 Arial/Calibri/Cambria 的 metric 兼容替换，直接决定 LO 渲染保真度与 QA 可信度 | ~10-12 MB |
| `markitdown[pptx]` → pyproject | **暂缓，先实测依赖闭包** | 功能上可被 python-pptx/openpyxl/pymupdf 自造替代（代价是输出格式不是 `<!-- Slide number: N -->`，SKILL.md 的 grep 检查会连带失效）。若其传递依赖拉进 onnxruntime 级别的东西，收益不抵体积 | 待验证 |
| **node + npm + pptxgenjs/docx-js/sharp** | **不加** | ① node20 runtime 本身 ~120 MB+；② sharp 的 libvips 预编译二进制按平台分发，信创 arm64/龙芯无保证；③ 引入第二套包管理器和第二条供应链，私有化离线交付的镜像审计成本陡增；④ **收益可被 python-pptx/python-docx 完全替代**（bisheng 已有），代价只是放弃官方 SKILL.md 的 API 指导——而这份指导本来就要重写（见 §5） | +150 MB 起，且不可控 |
| ghostscript / ImageMagick / pdftk | **不加** | 三个 skill 零引用 |
| E2B 自建模板 | **走沙箱路线才做** | 现状 `Sandbox()` 调用处（`e2b_executor.py:88`）没传 `template=`，走 SDK 默认 `code-interpreter-v1`；模板 id 在前端表单、`extra` schema、executor 构造函数三处都无处可配。要走沙箱需同时改这三处 + 自建预装 libreoffice/pandoc/CJK 字体的模板 + 把 skills 物化提到 `_generate_tools` 之前 | 独立工作项 |

合计 apt 侧增量约 **20-30 MB**（量级估计，需实测），相对当前 base 镜像（含 libreoffice 元包 + playwright chromium，GB 级）可忽略。

---

## 5. 直接用官方 skill 的可行性判断

### 结论：**(c) 做适配版**，且这是唯一现实选项。

理由不是依赖装不齐——依赖按 §3/§4 补完后，xlsx 主干在官方镜像上**本来就能跑**、docx 只死"创建"一半。真正的判死点是下面这批**跟依赖无关的、对 Claude 特有能力的假设**，装再多包也不会消失：

| 假设 | 出处 | 对 Qwen/DeepSeek 的后果 | 能否靠装依赖解决 |
|---|---|---|---|
| **API 知识靠模型脑内**：pptx「The model knows the API; these are the footguns」，docx 同款，xlsx 一行 openpyxl 示例都不给 | pptx SKILL.md:31 / docx:21 / xlsx:11 | 整个创建主干 = 模型现场手写 JS/py，只给 20 条"别踩的坑"不给 API。弱模型写出的错误恰恰**不在**那 20 条里，`validate.py` 只查 OOXML 不查 JS，抓不住 | 否 |
| **视觉 QA 靠看图**：pptx 整节 12 类目视缺陷 + `Pass the absolute paths directly to the view tool`；docx `ls page-*.jpg # then Read the images` | pptx:204-232 / docx:42 | ① 硬编码了 agent 侧工具名 `view`/`Read`，灵思没有同名工具；② 灵思 qwen3.5 走 dashscope，**已知不收 base64 图片**（180 html-ppt 的教训）。这一整节等于空转 | 否 |
| **负向清单靠自律**：xlsx 要求恰好六个函数写 `_xlfn.` 前缀、禁用 XLOOKUP/XMATCH/SORT/FILTER/UNIQUE/SEQUENCE，**同行亲口承认这种情况 `recalc.py` 报 `total_errors: 0`** | xlsx:67-68 | Qwen/DeepSeek 生成 Excel 公式默认吐 XLOOKUP 概率很高，校验器抓不住 → 交付一个在 Excel 里全是 `#NAME?` 的文件 | 否 |
| **长上下文同时持有 ~35 条互相牵制的设计禁令**：pptx 85 行散文规则含 14 条 Avoid（两条全大写 NEVER）；xlsx 要求写每个 cell 时同时满足"用公式不硬编码/百分比存小数/蓝字硬编码黑字公式绿字跨表红字跨文件" | pptx:80-164 / xlsx:80-95 | 指令跟随弱的模型生成到第 8 张 slide 就漂回默认样式 | 否 |
| **裸 shell 视角**：`markitdown deck.pptx`、`(cd unpacked && zip -Xr ../out.pptx .)`、`pdftoppm -jpeg -r 150` | 三家通篇 | `bisheng_code_interpreter` 执行的是 **Python**，模型必须自己包一层 subprocess；弱模型经常把 shell 命令当 Python 直接写。且 `infer_lang` 会把 `python ...` 开头的整块判成 sh，行为再次分叉 | 否 |
| **相对路径 + 特定 sys.path 布局**：「Script paths are relative to this skill's directory」，且 `scripts/office/` 无 `__init__.py`（PEP 420），xlsx/pptx 的 `from office.helpers import` 要求 `scripts/` 在 sys.path，而 `office/validate.py` 的裸 `from helpers import` 要求 `scripts/office/` 在 sys.path——**两套导入根互不兼容** | xlsx:18/37, docx:17, pptx:19 | 灵思 cwd = 任务工作区、skill 物化在 `skills/<name>/`，原样执行必然 `No such file`；改写成 `python -m` 或拍平目录必 ImportError | 否 |
| **原地精确编辑工具**：docx「edit `unpacked/word/document.xml` **in place** — do NOT reformat or pretty-print」，隐含 Claude Code 的 `Edit`（str_replace） | docx:55 | 灵思是 `write_file` 全量覆盖，且**已知大参数被截断触发死循环**；照做会把 document.xml 整体重写并顺手 pretty-print，正中明令禁止 | 否 |
| **多轮工具循环 + 自我纠错**：xlsx 的"先写 2-3 个公式验证 → 再铺开 → 重算 → 修"四段式；pptx「a subagent works well for this」 | xlsx:45-50 / pptx:206 | 灵思子代理 **30 轮预算跨 task 调用共享**（已知坑），逐页图审会把预算烧光 | 否 |
| **clean exit ≠ clean 产物的元认知**：`errors_found` 也 exit 0，只有 `error` 键才非零退出 | xlsx:44-48 | 弱模型看到 exit 0 就宣布完成 | 否 |
| **假设有外网可 pip/npm install**：三家都写「Only if an import fails: `pip install` / `npm install`」 | xlsx:16,99 / pptx:31,50 / docx:21 | 私有化内网下变成几十秒 pip 超时空转，而不是快速失败换路径；且 `local_executor` 描述里明说"do NOT run pip install"，两条指令直接打架 | 否 |
| **身份烙印**：`comment.py:321` `--author` 默认 `"Claude"` | docx | bisheng 产出的 Word 批注作者一律显示 Claude | 改代码即可（属适配工作） |

外加两个**与 bisheng 执行器正面相撞**的工程点，同样必须在适配层解决：

1. **失败时 stdout 被整段丢弃**（`local_executor.py:205-215`：`if proc.returncode: logs = stderr` 否则 `logs = stdout`，二选一）。而这些 skill 的诊断信息几乎全走 stdout——`recalc.py:303-304` 失败 JSON 走 stdout + exit 1，`validate.py:169` 失败 exit 1 而所有 FAILED 明细都是 `print`。结果：模型拿到一片空白 stderr，pptx SKILL.md:202 承诺的「Every failure names its fix」直接归零。
2. **失败即丢产物**（`local_executor.py:340-341/394-406`：exitcode != 0 直接 return，`file_list` 为空）。前半段已写好 `output/x.pptx`、最后一行报错，产物一律不回传。

### 三选一的判据

- **(a) 原样导入**：排除。执行期必炸（defusedxml/node/markitdown），且 LICENSE.txt 明文禁止「Extract these materials from the Services or retain copies outside the Services / Reproduce or copy / Create derivative works」，三份 LICENSE md5 相同（f8515c36…），frontmatter 均为 `license: Proprietary`。**bisheng 是开源仓 + 商业私有化交付，把这套文件打成技能包分发（尤其提交进公开仓）是合规红线**，不是技术问题但会卡发布。
- **(b) 装依赖后原样导入**：排除。上表 11 条假设无一能靠装包解决；node 那条在官方镜像上还额外不可解。
- **(c) 适配版**：**已被验证有效**。仓库里的 `linsight-skills/bisheng-pptx/` 就是范例——**实测源码 70,009 B（7 个文件，不含 `__pycache__`）对比官方 pptx 的 1,139,175 B**，体积 1/16，且把 pptxgenjs 换成 python-pptx、把 view 工具换成脚本自检、把路径改成工作区语义、附带 `references/pptx-cookbook.md` 与 `design-zh.md` 两份中文参考（正是官方缺的那份 API 速查）。xlsx 与 docx 照此复刻即可。

**适配版的最小改造清单**（三家共通）：① 主干路径改 python（xlsx 本来就是；pptx→python-pptx；docx→python-docx），连带**整段替换** SKILL.md 里的 footgun 章节，否则模型会拿 pptxgenjs/docx-js 的 API 名去调 python 库；② 所有脚本路径改成基于 `skills/<name>/` 的绝对路径调用，并统一 sys.path 布局；③ 诊断结论改写 stderr（或反过来改执行器保留 stdout）；④ 脚本一律 `exit 0`（bisheng 技能包约定）；⑤ 删掉视觉 QA 章节，换成脚本化的结构自检（`inspect_deck.py` 那种）；⑥ 删掉 `pip install` / `npm install` 的自愈指引，改成"换已装库"；⑦ `accept_changes.py` 的 `/tmp/libreoffice_docx_profile` 硬编码单例改带 uuid 的临时目录（照抄同目录 `soffice.py:41-45`），并把 `:76-80` 那个「TimeoutExpired 返回 Successfully accepted」的**超时伪装成功**改成如实报错——否则多任务并发会静默产出未接受修订的文件；⑧ `soffice.py:50` 的 `$TMPDIR/lo_socket_shim.so` 固定文件名同样是并发不安全点（虽然容器内走不到）。

---

## 6. 技能包体积与 bisheng 限制的冲突

| 项 | 字节 | 占比 | 对照限制 |
|---|---|---|---|
| xlsx 全目录 | 1,102,893 B (~1.05 MB) | — | zip ≤ 10 MB ✅ / 解包 ≤ 100 MB ✅ |
| pptx 全目录 | 1,139,175 B (~1.09 MB)，**实测 zip 后 169,845 B** | — | ✅ 余量两个数量级 |
| docx 全目录 | 1,128,695 B (~1.08 MB)，61 个文件 | — | ✅ |
| └ 其中 `office/schemas/` | 976,913 B | xlsx 88.6% / docx 86.5% / pptx 85.8% | 三份互为重复 |

**结论：体积不是约束，压根不用裁也能装。** 但三家同时上架会有 3 × 954 KB 的 XSD 重复占用解包空间（约 2.9 MB），值得留意的是**它在 xlsx 上是 100% 死重**——`validate.py:142-148` 对 xlsx 家族在构造任何 validator 之前就 `sys.exit(0)`，连 `base.py:58` 映射的 `sml.xsd`（242,277 B，全包最大单文件）都永远不会被加载。

裁剪建议（若走原样打包路线才需要，走适配版则自然不存在）：

- **xlsx**：删 `scripts/office/schemas/`（976,913 B）+ `scripts/office/validators/`（~88 KB）+ `scripts/office/helpers/`（~20 KB），只留 `scripts/recalc.py` + `scripts/office/soffice.py`。剩 ~126 KB，**主干路径零功能损失**。
- **pptx**：可删 `sml.xsd`(242 KB) + `wml.xsd`(171 KB) + `schemas/microsoft/`(52 KB) ≈ 465 KB。前提是先实测 `pml.xsd` 的 `@import` 链（已核实只 import `dml-main.xsd` / `shared-commonSimpleTypes.xsd` / `shared-relationshipReference.xsd`，不碰 sml/wml）。
- **docx**：可删 `sml.xsd` + `pml.xsd` + `dml-chart.xsd` + `dml-diagram.xsd` 等约 460 KB，以及 `helpers/pptx_*.py`（~11 KB）。**但 XSD 之间有 `xs:import` 交叉引用**（`base.py:21` 用 base_url 解析），删前必须实测 `wml.xsd` 加载链，别硬删。
- **三家同上架**：`office/soffice.py` / `office/validate.py` / `office/validators/base.py` / `office/helpers/__init__.py` 四文件 md5 完全相同，可抽成一份共享，省 ~1 MB × 2。

⚠️ 两个删不得的红线：① `base.py:111` 的 `schemas_dir = Path(__file__).parent.parent / "schemas"` 是相对 `__file__` 解析的，**只拷 `scripts/*.py` 不带 `schemas/` 会让 `_load_schema` 抛异常，而异常被 `base.py:809-810` 吞成一条 error 字符串，表现为"所有文件都有新错误"的假阳性洪水**；② 技能包 name 必须匹配 `^[a-z0-9]+(-[a-z0-9]+)*$`，非法名现在会被 `slugify_pinyin` 自动改写并原地重写 SKILL.md 的 frontmatter（deepagents 硬约束：frontmatter name 必须等于目录名）。

**待验证清单**（成本极低，建议上线前在容器/114 各跑一次一次性确权）：

```bash
which pdftoppm zip unzip node npm markitdown soffice pandoc gs
soffice --headless --convert-to pdf /tmp/probe.pptx   # 探 Impress
soffice --headless --convert-to pdf /tmp/probe.xlsx   # 探 Calc
$VENV_PY -c "import defusedxml, lxml, openpyxl, pptx, docx; print('ok')"
fc-list | grep -iE 'liberation|carlito|caladea|wqy|noto.*cjk'
```

其余待验证项：114 上 pandoc 是否存在及版本；`markitdown[pptx,xlsx]` 的传递依赖闭包；`poppler-utils`/`zip`/`unzip` 是否被官方镜像的 libreoffice 元包或 `playwright install-deps` 间接带入；信创 arm64/龙芯平台 sharp 的 libvips 预编译可得性；E2B `code-interpreter-v1` 模板的实际库清单（Anthropic 从未文档化该运行时的 node/LibreOffice/pandoc/markitdown 版本，属结构性盲区，只能实测反推）。
