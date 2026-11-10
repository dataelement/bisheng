# 企业工作台压缩包校验规则

> 状态：当前工作分支已实现静态校验，尚未提交或部署。适用于 BiSheng 租户管理员上传本地 `.tgz` 并向本租户 Desktop 提供工作台信息与原始包的场景。静态校验通过或原包下载成功不代表 Desktop 已安装、已加载或可离线运行。
>
> 依据：[DSH 工作台开发规范](https://dshdesktop.com/workbench/docs/development/) §2–3、§8；[工作台市场验收规范](https://dshdesktop.com/workbench/docs/market-acceptance/) §3–4。后者的公开仓库、投稿与截图要求只适用于公共市场，不自动成为企业私有上传要求。BiSheng 的额外资源限制和归档安全规则在下文单独标明。

## 1. 身份与校验结论

一个压缩包只包含一个 npm/DSH 工作台包。三个标识不得混用：

| 标识 | 来源 | 使用位置 |
| --- | --- | --- |
| `package_name` | 包根 `package.json.name` | npm 安装与 patch 的 `insert[].name` |
| `patch_entry_id` | `cordis.patch.yml` 的 `insert[].id` | Harness 插件树条目 |
| `workbench_key` | 包根 `package.json.repository` 指向的 GitHub 仓库，规范化为小写 `owner/repo` | 新版 Desktop 工作台身份、市场卡片与会话归属 |

`workbench.json.id`、旧客户端 `register({ id })` 只能作为兼容线索，不是新包的 `workbench_key`。服务端不得通过执行客户端 JS 推断身份。

校验器返回以下之一，供上传预览和导入共用：

| 结果 | 条件 | BiSheng 行为 |
| --- | --- | --- |
| `standard` | 包结构合格，且包根有规范 GitHub `repository` | 保存 `workbench_key=owner/repo`，可进入租户信息目录；仍标记“运行未验证” |
| `legacy_metadata_only` | 基本包结构合格，缺 `repository`，但可从旧 `workbench.json` 取得非空旧 ID | 保留原包和旧 ID 供管理、查询；不伪造 `owner/repo`，不声明支持客户端安装 |
| `rejected` | 必需字段、路径、归档安全或身份校验失败 | 不切换已可用版本；返回可定位的规则号与原因 |

没有 `repository` 也没有旧 ID 的包拒绝导入。`legacy_metadata_only` 仅为花学样包等旧格式的兼容过渡，不放宽新包规范。

## 2. 可执行的静态规则

以下“必须”由 BiSheng 上传接口检查；“提示”不阻断上传，但进入预览和版本详情。校验器不执行包内任意脚本、`!!js`、Node 模块或外部网络请求。

| 规则 | 级别 | 判定 |
| --- | --- | --- |
| WB-01 归档 | 必须 | gzip 压缩的 tar；所有条目在唯一 `package/` 根下，存在且只存在一个根 `package/package.json`。不能只凭文件扩展名判定格式。 |
| WB-02 资源 | 必须 | 企业首版选择压缩后 ≤ 8 MiB、展开后 ≤ 256 MiB、≤ 10,000 个条目、`package.json` ≤ 1 MiB。8 MiB 与公共市场包体上限对齐，是此企业接口的设计取值；若客户确需更大包，应单独评估资源与客户端安装能力。 |
| WB-03 路径与类型 | 必须 | 拒绝绝对路径、`..`、反斜杠、空路径段、大小写或 Unicode 规范化后重复路径；仅接受普通文件和目录，拒绝符号链接、硬链接、设备、FIFO 等特殊条目。逐项限额、流式读取，不落地解压。 |
| WB-04 敏感文件 | 必须 | 拒绝 `.env`、私钥、凭证、数据库、浏览器登录态等明显敏感文件名及路径；不可仅靠黑名单保证素材授权，页面提示管理员核查。公开市场还须遵守其发布权与许可证规则。 |
| WB-05 JSON | 必须 | 包根 JSON 为 UTF-8 对象，拒绝重复键、过深结构和超限字符串；`name` 是合法 npm 包名，`version` 是完整 SemVer，支持 `0.3.0-desktop.1` 等预发布段。 |
| WB-06 入口 | 必须 | `main`、`exports["."]` 指向服务端入口，`exports["./client"]` 指向已构建的客户端入口；解析导出路径后必须仍位于本包内且目标为普通文件。支持明确的字符串或可唯一解析的 `import`/`default` 条件导出；歧义导出拒绝。 |
| WB-07 DSH 声明 | 必须 | `dsh.bundle.patch` 指向包内 patch；`dsh.client.platform == "web"`；`dsh.client.inject` 是字符串数组并包含 `dsh-desktop-workbenches`。只有客户端声明、没有 bundle 的包拒绝。 |
| WB-08 patch | 必须 | patch 为合法 YAML 数组；只**解析语法树**，不求值 `!!js`。企业首版只接受一条 `insert`，条目仅有 `id`、`name`，其 `name` 等于 `package_name`，`id` 非空；拒绝其他操作或额外字段。扩展 patch 结构需另行评估宿主安全边界。 |
| WB-09 仓库身份 | 标准包必须 | `repository` 可为 npm 的字符串或 `{type,url}`；接受 `https://github.com/owner/repo[.git]` 及 npm 常见的 `git+https://github.com/owner/repo.git`，规范化后必须恰有 owner/repo 两段，移除 `.git` 与末尾斜杠并小写化。拒绝用户信息、查询、片段和含糊路径。上传只能验证声明格式，不能证明上传者拥有该仓库。 |
| WB-10 旧清单 | 条件必须 | 若有 `workbench.json`，要求它是受限 JSON 对象，`version` 与根包一致、`entry` 指向包内普通文件；其 `id` 只作为旧 ID。无 `repository` 时必须有合法旧 ID，否则拒绝。 |
| WB-11 依赖与许可 | 提示 | 记录 `dependencies`、`peerDependencies`、`engines`、`license` 和外部服务声明，展示缺少可随包解析依赖、原生模块或 `UNLICENSED` 等风险。压缩包无需自带 `node_modules`，因此静态上传不承诺脱机安装。 |

服务端不能可靠地从任意构建后的 JS 中静态证明 `desktopWorkbenches.register({ repository, title }, Component)` 已执行、模块加载器 ID 与包名一致、所需宿主服务存在或 UI 正常。这些属于 Desktop 实际安装与运行验收；查询结果应显式返回 `verification_level=static`，不能把 WB-01 至 WB-11 全通过解释成运行验收通过。

## 3. 样包判定基线

仅以用户提供的两个原始 `.tgz` 为样本，不执行其中的安装、构建或检查脚本。

| 样包 | 静态观察 | 预期结论 |
| --- | --- | --- |
| `dsh-media-workbench-0.12.6.tgz` | 根包有 `repository=https://github.com/cinderzhan/dsh-media-workbench.git`，入口和 patch 均在包内；没有 `workbench.json` | `standard`，`workbench_key=cinderzhan/dsh-media-workbench`；没有 `workbench.json` 不报错。客户端注册代码中的版本与根包版本存在差异，列为运行联调提示。 |
| `dsh-huaxue-workbench-0.3.0-desktop.1.tgz` | 根包无 `repository`；有 `workbench.json.id=huaxue`，包与清单版本一致，入口和 patch 在包内 | `legacy_metadata_only`；保留 `legacy_id=huaxue`，`workbench_key=null`，不将 `huaxue` 冒充新协议的仓库身份。 |

两个原始样包已在本地运行静态校验器：媒体包得到 `standard`，花学包得到 `legacy_metadata_only`。这不代表 Desktop 安装成功。公开工作台市场 v1 还要求仓库根目录单工作台；媒体包内的嵌套 `packages/` 目录是否满足其仓库收录规则，要结合真实仓库与市场检查判断，不能只看 `.tgz` 名称。

## 4. 验收用例

1. 两个样包分别得到 `standard` 与 `legacy_metadata_only`，且不运行任何脚本；预览与正式导入结论一致。
2. 缺入口、缺 patch、patch 包名不符、SemVer 错误、同版不同摘要均返回确定的规则号；失败不改变当前版本。
3. 路径穿越、大小写重复、链接、特殊文件、超限展开大小和归档截断均被拒绝；校验过程的内存、磁盘与 CPU 用量受上限控制。
4. 租户 A 的包与元数据不会被租户 B 读取；只有当前版本可下载，旧版本和失败任务不可下载；原始包 SHA-256 在存储、数据库与下载响应中一致，客户端下载后复算相同摘要。
5. 客户端查询能区分标准身份与旧包身份，并能读到“运行未验证”；仅静态校验通过的包不显示成“已安装”。
