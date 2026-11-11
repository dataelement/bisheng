# Design: 深度研究 PPT 制作改用 PPTD 页面设计引擎

**关联**：[spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**：v3.1.0-beta1
**最后更新**：2026-11-11

---

## 1. 目标与非目标

- **目标**：把 dsh-desktop 的 PPT 引擎（PPTD 页面描述格式 + `dsh-ppt` CLI）装进后端镜像，并把内置技能 `bisheng-pptx` 的内容整体换成「模型逐页写 PPTD → 引擎检查 → 导出 .pptx」的流程。模型自己设计每页版面，引擎负责几何检查和原生对象导出。
- **非目标**：不引入桌面端的 PPT 模式界面、个人模板库、图片槽位；不做看图质检；不保留用户模板的母版结构；不新增平台工具、接口、数据表或错误码。

---

## 2. 关键约束

遵循 `docs/constitution.md` C1–C7。本特性不改数据库，不新增接口。特有约束如下。

- **执行环境**：代码执行器有 local / container / e2b 三种模式，由代码执行器工具配置的 `type` 决定，缺省 local。local 在 linsight worker 所在的后端镜像中运行；container 在 `bisheng-sandbox` 镜像的 code-runner 中运行（官方 docker-compose 自带 code-runner-1/2）；e2b 是外部服务，本特性不覆盖。本地隔离模式下，子进程使用一次性的非特权 uid，`prlimit` 限制地址空间 2GB、进程数 256、文件数 1024、CPU 600 秒；环境变量只有白名单（`local_isolation.child_env`：PATH、LANG、HOME=工作区等），**不继承** `PPTD_RUNTIME` 一类自定义变量。
- **引擎运行时**：`dsh-ppt` 要求 Node `^22.19 || >=24`。它的导入链依赖 6 个公开 npm 包：pptxgenjs 4.0.1、sharp 0.35.5（带原生库，按架构区分）、js-yaml 4.3.2、fflate 0.8.3、jsdom 29.1.1、@aiden0z/pptx-renderer 1.2.4。运行时不联网。
- **镜像形态**：应用镜像 `src/backend/Dockerfile` 基于 `dataelement/bisheng-backend:base.vN`。base 镜像由 `.github/workflows/base_ci.yml` 在推送 `base.v*` tag 时分别构建 arm64、amd64 并推到 Docker Hub。**推 tag 即公开发布**，需要用户确认后执行。
- **种子程序**：`builtin_skill_seeder` 只在 API 进程启动时运行，按包内容哈希判断是否覆盖；来源不是 builtin 的行（租户改过）一律跳过；`enabled` 和 `default_checked` 只在新建行时写入，更新时不动。
- **贴牌**：按 `builtin_skills/AGENTS.md`，客户能读到的文字（description、SKILL.md、references、模板说明、脚本输出）不能出现品牌名；技能名 `bisheng-pptx` 和包内路径是既有技术标识，保持不变。

---

## 3. 方案对比与选定

### 决策 1：同名原地替换 `bisheng-pptx`

- **备选**：
  - A. 新建技能 `ppt-deck`，种子程序增加「退役内置技能」清单，把旧技能停用。优点：新旧名称清楚；缺点：要写退役逻辑并处理「管理员重新启用」等状态，管理员设置不能延续，两条技能行长期共存。
  - B. 两个技能并存，靠 description 划分场景。缺点：2026-11-11 验证中，已勾选新技能时 P1 仍被 bisheng-pptx 抢走，靠模型路由不可靠。
  - C. 保持技能名 `bisheng-pptx`，把包内容整体换成 PPTD 版本。种子程序发现内容哈希变化后自动覆盖。
- **选定**：C（2026-11-11 用户确认）。
- **原因**：不需要任何新机制；升级后只有一个 PPT 技能；`enabled`、`default_checked`、权限授予挂在原行上，自然保留；html-report 的触发描述本来就引用「PPT 制作」，不用改。
- **回滚**：回退到旧镜像时，种子程序同样按哈希把旧内容写回，不需要额外操作。
- **何时该重新考虑**：需要新旧两种 PPT 能力同时对用户开放时（例如某些客户坚持保留母版套版）。

### 决策 2：Node 与 npm 依赖进 base 镜像，dsh-ppt 库随应用镜像拷入

- **备选**：
  - A. 全部（Node、依赖、dsh-ppt 库）进 base 镜像。缺点：库升级也要重打 base，仓库里的库和镜像里的库可能不一致。
  - B. 全部在应用镜像 Dockerfile 安装。缺点：每次应用构建都下载 Node、执行 npm ci，构建变慢，层不复用。
  - C. base 镜像装 Node 和锁定版本的 npm 依赖，路径 `/opt/pptd-runtime/{bin/node,node_modules}`；应用镜像只 `COPY` 仓库内的 dsh-ppt 库到 `/opt/pptd-runtime/engine`（运行时目录名不带上游品牌，因为引擎缺失时 `pptd.py` 会把路径打印给用户）。
- **选定**：C（用户选「进 base 镜像」，库按 C 拆分）。
- **原因**：依赖很少变，放 base 层复用；库是纯 JS（约 1.7MB），跟随代码提交，避免两处版本不一致。目录布局与 114 验证时完全相同。Node ESM 从 `/opt/pptd-runtime/engine/lib/` 向上查找，正好命中 `/opt/pptd-runtime/node_modules`。
- **代价**：本特性需要把 base 从 v10 升到 v11 并推 tag；推 tag 前，应用镜像构建不能切到 v11。
- **何时该重新考虑**：依赖升级频率变高，或 base 镜像改由其他流程统一维护时。

### 决策 2b：沙箱镜像同样内置引擎（2026-11-11 用户确认）

- **背景**：design 初版只覆盖 local 模式。container 模式下脚本在 `bisheng-sandbox` 里运行，没有 Node，升级后「PPT 制作」会提示引擎不可用。
- **选定**：`docker/bisheng-sandbox/Dockerfile` 增加 `pptd-runtime` 构建阶段（apt 镜像源同最终阶段、下载 Node、`npm ci`、加载 sharp、拷引擎），最终阶段 `COPY --from` 到 `/opt/pptd-runtime`。沙箱镜像随 `v*` 正式版构建发布，不另推 tag。
- **被否方案**：在最终阶段直接安装。最终阶段装完 venv 后会卸载 curl 和编译器，单独阶段可以不留下 curl 和 npm 缓存。
- **验证**：114 上以官方 `bisheng-sandbox:v3.0.0` 叠加该构建阶段，按 compose 的 code-runner 参数（root 运行器、只读根文件系统、cap_drop ALL、2GB 内存）启动，经 `ContainerExecutor` 执行 `pptd.py env/check/render`：会话 uid 10000，gov-red 12 页通过并导出，含拷入拷出 6.4 秒。
- **防漂移**：`test_every_install_path_pins_the_same_runtime` 校验 base、沙箱、install.sh 三处 Node 版本与锁文件一致。

### 决策 3：引擎路径固定为 `/opt/pptd-runtime`

- **备选**：A. 环境变量；B. 由 `sys.prefix` 推算；C. 固定路径。
- **选定**：C。脚本仍读取 `PPTD_RUNTIME` 作为开发覆盖，默认值是 `/opt/pptd-runtime`。
- **原因**：执行器子进程不继承自定义环境变量（§2），A 在生产中不生效；B 依赖 venv 位置，源码部署时不可靠。镜像部署和源码部署的安装脚本都装到同一路径。
- **注意**：`/root` 权限是 550，非特权 uid 进不去，因此不能用 nvm 或装在 `/root` 下的 Node（114 实测）。

### 决策 4：dsh-ppt 库从 dsh-desktop 固定 commit 拷入仓库

- **选定**：从 `dataelement/dsh-desktop` 的 `packages/ppt-runtime/core`（commit `46666d3`，包版本 0.1.1-rc.2，MIT）拷 `lib/`、`LICENSE`、`THIRD_PARTY_NOTICES.md` 到 `src/backend/pptd_runtime/dsh-ppt/`；另写 `package.json` 与 `package-lock.json`，只列 §2 中的 6 个依赖。上游 `package.json` 中的 cordis、dsh-* 等 peer 依赖只服务桌面插件入口，CLI 不加载，不安装。
- **原因**：上游本身也是以编译后的 `lib/` 形式在仓库中维护；该包不发布到公开 npm。
- **被否方案**：在构建期从 dsh-desktop 仓库拉取。该仓库需要凭据，且会让后端构建依赖另一个仓库的可用性。
- **升级方式**：在 `src/backend/pptd_runtime/README.md` 记录来源 commit 和同步步骤。
- **何时该重新考虑**：上游把 `dsh-ppt` 发布到可访问的 npm registry 时，改为在 `package.json` 中按版本依赖。

### 决策 5：技能包内容

技能包沿用 114 验证过的 `pptd-deck` 包，改名为 `bisheng-pptx` 并做三处调整：

1. **frontmatter**：`name: bisheng-pptx`，`metadata.display-name: PPT 制作`，description 写清触发词和与 html-report 的分界（AC-05），不写 `default-checked`。
2. **新增转换流程**（AC-15/16）：`pptd.py convert <上传的.pptx> scratch/deck` 调用引擎 `convert`，汇总 normalized/unsupported 诊断输出给模型；SKILL.md 增加「改写已有 PPT」「按用户模板制作」两条分支。
3. **模板去品牌**（AC-13）：模板 ID 去掉 `dsh-`、`curated-` 前缀（例如 `blue-professional`、`nordic-operating-report`）；模板说明和参考页中的品牌字样改成中性表述；增加静态测试扫描整个包。

脚本 `scripts/pptd.py` 保持 114 验证版本的行为：`check` 叠加字号下限，`render` 在字号不合格时拒绝导出，导出后把 macOS/Linux 中文字体名改写为 Microsoft YaHei。旧包的 `scripts/`、`templates/*.pptx`、`references/` 全部删除，生成旧模板的 `src/backend/scripts/pptx_templates/` 一并删除。

- **被否方案**：保留旧脚本作为引擎不可用时的兜底。这会让两条生成路径并存，模型在引擎报错时转向旧路径，掩盖真实问题（与「不用兜底掩盖模型缺陷」一致）。
- **何时该重新考虑**：出现大量无法安装引擎的部署形态时。

### 决策 6：政企红色模板用生成脚本编写，沿用旧 gov-red 的配色与版式

- **选定**：`src/backend/scripts/pptd_templates/gen_gov_red.py` 生成 `gov-red/source-zh/`（12 页），配色取旧 gov-red 模板（`8B1A2B` 深红、`C9A84C` 金等），页面结构参照旧模板的封面、目录、章节、指标、表格、时间轴等版式；字阶直接按本技能的字号下限设计；`design.md` 手写。测试校验提交的工程与脚本输出一致。
- **实施偏差**：原计划以 `convert` 的转换结果为起点。转换结果是平铺坐标、无主题样式的元素（`MiSans` 字体、无 textStyles），整理成本高于直接生成，因此改为生成脚本。
- **原因**：沿用客户已经接受的视觉（深红主色、金色点缀），并保证 html-report 的 gov-red 主题配色可以对照校验（AC-20）。生成脚本让配色或网格调整可以一次性重建 12 页。
- **何时该重新考虑**：客户提供正式的 VI 规范时，以 VI 为准重做。

### 决策 7：html-report 配色校验改为只对照 gov-red

- **现状**：`test/linsight/test_html_slides.py` 要求 html-report 的 5 个主题与 `bisheng-pptx/templates/catalog.json` 的 5 个模板一一对应，并要求版式 ID 等于 5 套模板共有版式的交集。替换后这个文件不存在。
- **选定**：html-report 的主题和版式保留自身定义；测试改为：(1) html-report `gov-red` 的主色、强调色与新 `gov-red/source-zh/deck.pptd` 的 `theme.colors` 一致；(2) html-report 版式 ID 对照它自己声明的固定清单。
- **被否方案**：给 PPTD 模板补齐 html-report 的 5 个主题。另外 4 个主题（蓝图、经营、深空、课堂）在 PPTD 侧已有风格相近的模板，强行同名只为满足测试，没有用户价值。
- **何时该重新考虑**：产品要求网页幻灯片与 .pptx 使用同一套主题清单时。

### 决策 8：版本契约登记

在 `release-contract.md` 表 1 新增 F014 行（Owner：内置技能 `bisheng-pptx` 的内容与 PPTD 引擎运行环境），表 3 新增依赖行；F006 行中「与『PPT 制作』技能的模板目录保持一致」改为「gov-red 配色与 PPT 制作技能的 gov-red 模板一致」。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

`镜像构建：base.Dockerfile 安装 Node + node_modules → Dockerfile COPY dsh-ppt 库到 /opt/pptd-runtime/engine`

`API 启动：seed_builtin_skills → bisheng-pptx 内容哈希变化 → 写新包到对象存储并更新行（enabled/default_checked 不动）`

`深度研究任务：materialize_session_skills 把包复制到工作区 skills/bisheng-pptx/ → 模型读 SKILL.md、模板 → 写 scratch/deck/ → 代码执行器运行 pptd.py check/render → 子进程调用 /opt/pptd-runtime/bin/node engine/lib/bin.js → output/<标题>.pptx`

### 4.2 关键约定

| 约定 | 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 引擎路径 | `/opt/pptd-runtime/{bin/node,node_modules,engine/lib/bin.js}` | 镜像与安装脚本一致 | `scripts/pptd.py` |
| 工程目录 | `scratch/deck/deck.pptd` + `scratch/deck/pages/NN.page` | 模型写入，不交付 | 引擎 check/render |
| 交付 | `output/<中文标题>.pptx` | 只放最终文件 | 结果面板 |
| 脚本结论字串 | `结论: 通过，可以 render` / `已导出` | 只由 `pptd.py` 打印（AGENTS 规则：终止字串只能由检查脚本输出） | 模型 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `src/backend/base.Dockerfile` | 安装 Node（按 TARGETARCH 下载官方二进制）与 `pptd_runtime/package-lock.json` 锁定的依赖 | 不包含 dsh-ppt 库 |
| `src/backend/Dockerfile` | 拷 dsh-ppt 库到 `/opt/pptd-runtime/engine` | 不执行 npm |
| `docker/bisheng-sandbox/Dockerfile` | `pptd-runtime` 阶段装 Node、依赖、引擎，最终阶段拷入 | 不改运行器 |
| `src/backend/pptd_runtime/` | 上游库副本、依赖清单、`install.sh`（源码部署用）、来源说明 | 不放技能内容 |
| `builtin_skills/bisheng-pptx/` | SKILL.md、references、templates、`scripts/pptd.py` | 不自己生成 PPT（不使用 python-pptx） |
| `builtin_skill_seeder.py` | 不改动 | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 执行器子进程不继承自定义环境变量，PATH 来自 worker | 依赖环境变量定位引擎，生产环境找不到 | 决策 3 固定路径 |
| 2 | `/root` 为 550，非特权 uid 不能执行 `/root` 下的 Node | 源码环境用 nvm 的 Node，技能报「引擎不可用」 | `install.sh` 把 Node 拷到 `/opt/pptd-runtime/bin` 并 `chmod -R a+rX` |
| 3 | `npm install` 会删除 `node_modules` 下不在 package.json 中的目录 | 把 dsh-ppt 放进 `node_modules` 后再装依赖，它会被删掉 | dsh-ppt 放在 `node_modules` 之外（同级目录） |
| 4 | 引擎在 Linux 上把中文字体写成 `Noto Sans CJK SC` | 客户 Windows 打开时字体回退，版面变形 | `pptd.py render` 导出后改写为 Microsoft YaHei |
| 5 | 桌面端模板 design.md 自带 8.5–11.5pt 的正文字阶 | 模型照抄，投影上看不清（桌面端 35–71% 文字 <10pt） | SKILL.md 规定字号以技能为准，`pptd.py` 字号下限阻断导出 |
| 6 | 执行器非零退出时只回传 stderr，stdout 被丢弃 | 检查报告丢失，模型反复重试 | `pptd.py` 全部输出走 stdout，结论用文字表达 |
| 7 | sharp 原生库按架构区分（`@img/sharp-linux-x64` / `-arm64`） | 在 x86 上打出的 node_modules 拷到 ARM 机器不能用 | base 镜像分架构分别 `npm ci`；arm64 由 AC-22 验证 |
| 8 | 升级只覆盖 `source=builtin` 的行 | 以为所有租户都已替换，其实改过技能的租户仍是旧版 | AC-18 接受；发布说明中写明 |
| 9 | 16 套桌面端模板由 dsh-desktop 构建脚本 `scripts/generate-zara-ppt-templates.mjs` 生成，仓库里只有上游素材；本包的模板取自已验证的桌面端发行包 | 以为能从 dsh-desktop 仓库直接拷模板，找不到 | `templates/LICENSES.md` 记录来源与许可（Zara MIT、html-anything Apache-2.0） |
| 10 | 模板参考页里有第三方产品名（WorkBuddy、Kimi 等）和 `DSH` 字样 | 贴牌客户在技能详情里看到别家品牌 | 迁入时改写；`test_pptx_pptd_skill.py::test_no_brand_on_the_customer_readable_surface` 扫全包 |
| 11 | nordic-operating-report、swiss-signal-grid、modular-logistics-system 的参考页本身低于字号下限（最小 7.5pt） | 以为模板参考页照抄就能通过检查 | 有意保留：SKILL.md 规定字号以技能为准，模型照抄会被 `pptd.py check` 拦下并放大 |
| 12 | 上游 dsh-desktop main（`46666d3`）的 `lib/` 与桌面端发行包不完全一致（6 个文件，字体别名与预览相关） | 以为锁定的版本就是验证过的那份 | 已用锁定版本重跑模板 check/render；T08 用锁定版本重跑 4 题 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 技能名 `bisheng-pptx`、显示名「PPT 制作」 | 技能存储行 | 技能管理页、工作台技能选择、html-report 描述 |
| `gov-red` 模板配色 | `templates/gov-red/source-zh/deck.pptd` 的 `theme.colors` | html-report 配色校验测试 |

### 6.2 我依赖别人的

| 依赖 | 形式 | 风险点 |
|---|---|---|
| dsh-desktop `packages/ppt-runtime/core` | 拷贝的编译产物 | 上游改格式时需要手动同步，同步后要重跑 4 题对比 |
| Node 官方二进制、npm 公开包 | base 镜像构建期下载 | 构建环境需要能访问 nodejs.org 与 npm registry |
| 代码执行器本地隔离 | 运行时 | 若 AS 上限调低到 2GB 以下，sharp 可能无法加载（实测 2GB 正常） |
| 内置技能种子按哈希更新 | 启动时行为 | 种子逻辑若改为「只新建不更新」，替换不再生效 |

---

## 7. 测试与可观测

- **单元/静态测试**（`test/linsight/`）：技能包能被种子程序识别；frontmatter 只含允许的键；全包扫描无品牌字样；17 套模板的 `deck.pptd` 与参考页能被 YAML 解析；`pptd.py` 字号下限的正反样本；字体改写的正反样本；html-report gov-red 配色一致。
- **引擎集成测试**（有 `/opt/pptd-runtime` 时运行，否则跳过）：对仓库内的样例工程执行 check/render/convert，断言导出成功、页数正确、无整页图片、字体为 YaHei/Arial。
- **环境验收**：114（x86，源码部署，跑 `install.sh`）重跑 2026-11-11 四道题，对照 AC-11/14/21。arm64 不使用客户环境，由 base 镜像 arm64 原生构建中的 sharp 加载检查覆盖（AC-22）。
- **114 实测（2026-11-11）**：`install.sh` 首次 2 分 20 秒（主要是下载 Node），`/opt/pptd-runtime` 327MB；nobody + `prlimit --as=2GB` 下 gov-red 12 页 check 1.56 秒、render 1.63 秒，264 个原生元素（AC-02）；重启 API 后 3 个租户的 `bisheng-pptx` 哈希更新、enabled/default_checked 保持原值（AC-17）。
- **114 四题验收（2026-11-11，DeepSeek-V4.1-Flash，每题 1 次，skills=bisheng-pptx）**：

  | 题 | 墙钟 | 页 | 字/页 | 图表/表格 | 字号中位 | <10pt | 模板 |
  |---|---|---|---|---|---|---|---|
  | P1 央国企年度总结 | 273s | 12 | 189 | 2/1 | 13.0 | 0% | gov-red |
  | P2 医院技术方案 | 454s | 11 | 310 | 0/3 | 11.0 | 18% | — |
  | P3 季度经营分析 | 499s | 9 | 306 | 2/2 | 11.0 | 17% | nordic-operating-report |
  | P4 新员工培训 | 288s | 12 | 239 | 0/0 | 14.0 | 13% | — |

  对照：旧 bisheng-pptx 137–198s、字/页 164–208；桌面端 13–26 分钟、<10pt 35–71%。4 份文件字体只有 Microsoft YaHei + Arial，无图片（AC-10/11/14/21 满足，样本量 1）。
- **手动验证**：
  - 引擎：`/opt/pptd-runtime/bin/node /opt/pptd-runtime/engine/lib/bin.js --help` 应打印用法。
  - 隔离环境：`runuser -u nobody -- prlimit --as=2147483648 /opt/pptd-runtime/bin/node /opt/pptd-runtime/engine/lib/bin.js check <样例工程>`。
  - 升级替换：重启 API 后查 `select name,source,enabled,default_checked,content_hash from linsight_skill where name='bisheng-pptx'`，哈希变化、其余列不变。
  - 端到端：114 上 `/opt/taskmode-eval/pptcmp/server_run.py`（skills 填 `bisheng-pptx`）重跑 4 题，用 `metrics.py` 与 `render.py` 出指标和缩略图。
- **观测**：worker 日志中按 trace 检索 `pptd.py`；技能输出的「已导出」行包含页数和原生元素数。

---

## 8. 后续改进 / 不打算做的事

- 看图质检、图片生成槽位：等出现「几何检查通过但用户仍觉得难看」的具体案例再评估。
- 保留母版的套版：需要上游 convert 支持母版，目前不做。
- 上游自动同步：上游变动频率低，暂时手动同步。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-11 | 初版 | spec 确认（同名替换方案） |
| 2026-11-11 | 增决策 2b：沙箱镜像内置引擎（container 模式） | 用户追问沙箱镜像时发现遗漏 |
| 2026-11-11 | 引擎运行目录改名 `engine`；决策 6 改为生成脚本；§5 增坑 9–12 | 实现中发现 |
