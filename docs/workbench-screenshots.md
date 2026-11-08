# 企业工作台截图协议与验证记录

## 实施状态与范围

本变更在父会话准备的隔离副本 ".build/workbench-screenshots/backend" 实施，源文件来自分支 v3.0.0-fix-dsh 的活动 worktree HEAD。父会话负责将审核后的补丁应用至权威 worktree；本文不宣称已应用、部署至 109 或完成正式生产认证浏览器验收。无提交、无部署、无 repo-wide git 写操作，未修改第三方原 tgz、已交付 ZIP 或任何 peer 依赖。

已静态读取下载区 alpha3-market 的 21 个原 tgz 的 package.json，均未声明 dsh.workbench。旧包与旧数据库条目正常返回空截图；不会扫描包内任意图片猜测封面。

## 包声明（新增且最终确认的协议）

在 package.json 中声明：

```json
{
  "dsh": {
    "workbench": {
      "screenshots": [
        { "path": "./assets/screenshots/overview.png", "alt": "工作台概览" },
        { "path": "assets/screenshots/detail.webp", "alt": "详情" }
      ]
    }
  },
  "files": ["assets/screenshots", "lib", "dsh", "cordis.patch.yml"]
}
```

示例仅展示新增字段，原有 dsh.bundle、dsh.client、入口与 Patch 声明仍须保留。npm files 必须包含真实图片。path 是 package/ 根内相对文件路径，允许单个 ./ 前缀，规范化后去掉此前缀；alt 可省略，默认为空字符串。截图项严格只允许 path 与 alt 字段。缺少 workbench、缺少 screenshots 或 screenshots=[] 均代表无图；显式 null、字符串数组及其他错误类型会拒绝。

限制：

- 最多 8 张，顺序即展示顺序；第一张为封面，重复规范路径拒绝。
- 单图非空且最多 5 MiB，总计最多 20 MiB（均为真实归档成员字节数）。
- 路径最多 512 字符；禁止绝对路径、URL、盘符、空/点/父级路径段、反斜杠、控制字符及 %?#。
- 支持 PNG、JPEG（.jpg/.jpeg）、WebP。扩展名与实际格式必须一致；不支持 SVG/GIF 或动画。
- 真实容器校验加像素解码；单边不超过 8192，面积不超过 16,000,000 像素；压缩炸弹告警按失败处理。
- alt 最多 256 字符，不能含控制字符。
- 沿用原归档安全限制：拒绝软/硬链接、路径穿越、重复路径和敏感文件；不执行 JS、Patch 表达式或安装脚本，也不解包到磁盘。

## 列表与详情响应

以下接口的每个工作台均新增顶层 screenshots 和 cover，管理员列表与普通列表相同：

- GET /api/v1/dsh/market/workbenches
- GET /api/v1/dsh/market/admin/workbenches
- GET /api/v1/dsh/market/workbenches/{workbenchId}

```json
{
  "screenshots": [{
    "id": "<64位小写十六进制资源ID>",
    "url": "/api/v1/dsh/market/workbenches/<workbenchId>/versions/<versionId>/screenshots/<imageId>",
    "sha256": "<原图片字节的64位小写SHA256>",
    "media_type": "image/png",
    "width": 1600,
    "height": 900,
    "bytes": 70442,
    "alt": "工作台概览"
  }],
  "cover": {
    "id": "<64位小写十六进制资源ID>",
    "url": "/api/v1/dsh/market/workbenches/<workbenchId>/versions/<versionId>/screenshots/<imageId>",
    "sha256": "<原图片字节的64位小写SHA256>",
    "media_type": "image/png",
    "width": 1600,
    "height": 900,
    "bytes": 70442,
    "alt": "工作台概览"
  }
}
```

cover 为对象或 null，不是 URL 字符串。screenshots 无图时为 []，包括上线前已存储、manifest 没有 screenshots 的旧条目。url 为根相对 API 路径；外部响应不包含原图片 path。全部字段为服务端计算或已验证声明，不能接受客户端自报 hash、MIME 或尺寸。

## 读取图片、认证与版本绑定

GET /api/v1/dsh/market/workbenches/{workbenchId}/versions/{versionId}/screenshots/{imageId}

成功直接返回图片原始字节，Content-Type 为 image/png、image/jpeg 或 image/webp，并带 ETag（双引号包围图片 sha256）、Cache-Control: no-store、X-Content-Type-Options: nosniff。不返回 JSON 成功信封。

复用 market_actor：既有企业桌面 Bearer 凭据，或既有平台 Bearer/cookie 登录身份。同租户普通用户可读取租户分发工作台；无需管理员权限。租户来源于经验证身份，绝不来源于图片 URL/查询参数或调用方提供的存储路径。跨租户账号、跨租户超级管理员均不能读取其他租户的工作台图片。客户端必须通过现有认证请求链取字节，不将 token 放入 URL、日志或直接交给无认证 img。CustomMiddleware 的 owns_dsh_credential 精确白名单同步加入此 GET 路径（32位小写hex工作台/版本、64位小写hex图片ID），确保桌面凭据由 market_actor 处理，不受陈旧浏览器 cookie 或调用方租户 header 干扰；未放宽其他路径或方法。

图片元数据存放在已有 MarketWorkbenchVersion.manifest JSON 中，无数据库 schema 迁移或本地共享图片缓存。原 tgz 继续由现有 storage 以 tenant + 原包 digest 读写。资源 ID 为 SHA256(artifactDigest + NUL + canonicalPath + NUL + imageDigest)，每个列表 URL 又含 workbenchId 和 versionId，从而绑定版本与精确原包。读取仅接受该版本清单中的 ID，不支持任意文件路径或远端 URL 代理。

与 artifact endpoint 保持一致：只允许当前版本。升级、删除后的旧版本 URL 返回 26207；同版本不同原包覆盖时图片 ID 改变（即使图片字节未改变），旧 ID 返回 26207。读取先检查工作台/当前版本/租户，再验证原包字节数与 SHA256，读取后重查版本；图片读取、实际解码与清单元数据核对完成后再次检查当前版本，以拒绝并发覆盖/升级/删除。

错误：

| 场景 | 返回 |
| --- | --- |
| 未认证或无效凭据 | 既有认证 HTTP 401 |
| 不存在、跨租户、非当前版本、未知/过期图片 ID | 既有业务信封 status_code=26207 |
| 原包缺失/损坏、图片元数据或绑定异常、读取期间版本变化 | 既有业务信封 status_code=26208 |
| 上传/预检截图声明非法 | status_code=26205，data 中 code/rule/field/message |

截图校验 rule 为 WB-12；code 为 WORKBENCH_SCREENSHOT_DECLARATION / PATH / TYPE / MISSING / LIMIT / IMAGE。原归档全局规则可先报 WB-01/02/03 等现有错误，截图规则不会替换它们。

相同 SemVer 优先级但字符串不同的包仍会按既有规则报 version_conflict，例如 1.0.0 与 1.0.0+enterprise.screenshots.1；不因截图而放宽版本身份约束。若需覆盖已导入版本，应走既有同字符串版本、不同摘要的显式覆盖流程。

## 实际测试与工具环境

解释器：/Users/alex/Documents/Code/dataelem/bisheng/src/backend/.venv/bin/python。实际 Python 3.12、Pillow 12.0.0、pytest 9.0.3；项目声明要求 Python 3.11.x、Pillow >=12.3.0，因此这里只是现有本地环境的行为验证，未修改依赖或 lockfile。

工作目录为隔离副本 src/backend，PYTHONPATH="$PWD"，禁止写入字节码，避免误导入原主树 bisheng：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" WORKBENCH_ORIGINAL_TGZ="/Users/alex/Documents/Code/dataelem/awesome-dsh-workbench/downloads/alpha3-market/packages/andoaidlaksldk__dsh-mind-workbench--1.0.15.tgz" /Users/alex/Documents/Code/dataelem/bisheng/src/backend/.venv/bin/python -m pytest test/dsh_market/ -q -p no:cacheprovider -k "not test_market_error_code_survives_platform_exception_envelope" --junitxml=../../../market-screenshots-tests-final.xml
```

结果：169 passed、1 deselected，无跳过。新增 test_workbench_screenshots.py 共 52 个参数化行为用例，覆盖支持格式、声明形状、错误路径、缺失/伪造/截断图片、动画、数量/大小/像素限制、软链接、有图导入→列表→详情→读取原图与原包、无图/旧条目、普通账号/桌面账号/跨租户/未认证、同版本覆盖/升级/删除、存储读取期间及图片解码期间并发变化、清单篡改和原包损坏。

唯一排除项 test_market_error_code_survives_platform_exception_envelope 导入整个 bisheng.main，隔离副本未包含兄弟 bisheng_langchain，首次完整运行在该项报 ModuleNotFoundError（其他 162 项通过，彼时尚未加最后 4 例）。尝试加原工作树兄弟包后触发本地 Pandoc 架构/下载初始化，进程 exit 0 但没有可靠 pytest 汇总，故不视为该项通过。最终通过 WORKBENCH_ORIGINAL_TGZ 启用了原 mind 包导入/下载回归，原先的 1 个跳过项已实际通过。最后新增真实 CustomMiddleware + market_actor + DshAccessService 的本地签名桌面会话测试，验证陈旧浏览器 cookie/租户 header 不干扰、撤销会话 401、跨租户拒绝，以及路由所有权严格限定 GET 和精确 ID 格式。Ruff 对五个生产修改文件与新增测试执行 format、check、F821 未定义名检查，均通过。

测试使用每例独立 SQLite 内存库、MemoryStorage 和现有 FastAPI TestClient，复用现有测试 fixture；没有外部中间件或线上数据创建。fixture 的内存资源随测试退出释放；覆盖/删除故事也通过真实删除接口验证失效。真实生产凭据校验、109 部署和浏览器 UI 视觉验收由父会话单独记录。

## 本地浏览器联调 fixture（不进入生产补丁）

单独脚本位于 .build/workbench-screenshots/browser/backend_app.py，父会话管理启动与停止。复用真实 router/repository/service、SQLite 与 MemoryStorage，只覆写为回环测试身份，明确不代表生产认证。启动时仅在 PYTHONPATH 放副本 src/backend 与 browser，绑定 127.0.0.1:43882。只读测试 Bearer 标记为 local-tenant2-user、local-tenant2-other-user、local-tenant2-desktop、local-tenant3-user；不接受未知凭据。/__fixture__ 返回 local_auth_fixture=true、production_login=false。

已用 TestClient 验证两条独立工作台：含真实下载思维导图与门店图的合成 tgz，以及无截图/无项目主页的 legacy tgz；列表总数2、图片200、无认证401、租户3读取租户2图片返回26207。原第三方 tgz 未修改。

## 真实派生包验证

最终以 downloads/workbench-screenshot-ready/repack-manifest.json 的 path 列表为权威输入（validated-packages 目录、保持原版本号），实际 validate_workbench_bundle 对 21 个派生包逐一读取、解码，全部通过。所有包导入同一个 SQLite 租户2后共21条，43张图片经 service.screenshot 逐张读取、重新验证原包及图片摘要/元数据；列表与详情截图元数据相同，原包 download 字节一致。租户3列表为0，43张图片均跨租户拒绝。另有3条明确标注 source-only-not-repacked 的记录没有可安装tgz，单独报告，不计入21包。

与 alpha3-market 原 tgz 对比，原包20个通过、1个律案包因 package/ 之外的 AppleDouble 普通成员 ._package 被既有安全规则拒绝；父会话只在派生包中移除冗余macOS元数据并记录provenance，原包未修改。报告位于 .build/workbench-screenshots/real-package-validation.json，保存每包源摘要、原包基线、导入状态与43张图的摘要/尺寸/字节数/跨租户拒绝记录。可重跑脚本位于 .build/workbench-screenshots/real_package_validation.py。此验证不代表第三方代码运行兼容或线上安装验收。

## 后续实施与 109 状态（2026-11-08）

本文前述“隔离副本”“尚未部署”是初次验证时的历史状态。随后在权威 worktree 保留原有截图 WIP 与 config 支持，补充了版本读取期间的 revision 校验、持久化图片元数据和非法 Unicode 校验，以及桌面与浏览器凭据的会话隔离。

109 的 backend 和 backend_worker 已更新至 bisheng-backend:workbench-screenshots-20261108，镜像 SHA-256 为 9b2f3ae7f2ebab772e1efef007224aa1ff2e332f87239a27379794abb1b21dc8；frontend 和 Harness 未升级。部署前原 Compose 与后端镜像已备份，健康检查返回 OK，代理下的无凭据截图请求返回业务码 401（HTTP 200 平台异常信封）。

当前代码重新静态校验 21 个派生 TGZ，声明的 43 张图片均解码成功，读取原始字节后 SHA-256 与元数据一致。两个真实多图包分别在隔离 SQLite/MemoryStorage 与真实 router/repository/service 的测试中完成预览、导入、列表、详情和逐图校验；覆盖、升级和删除测试使用内存中派生的合成包。market、Web 会话和真实包故事分进程运行 234 passed，权限中间件单独运行 21 passed。最初将权限测试排在真实包故事前时，故事 fixture 绕过认证中间件且未安装租户上下文，出现 3 个失败。为该隔离故事的模拟账号补充逐请求租户上下文建立与清理后，market、Web 会话、权限和真实包故事按该顺序单进程重跑为 255 passed。旧权限测试仍未恢复部分模块级替身，其他测试顺序未证明安全，不能据此声称消除了所有测试隔离问题。

另以签名桌面凭据组合两份原始多图派生包，使用真实 router、repository、service、CustomMiddleware、market_actor 与 DshAccessService，逐张比对 5 张返回图片的原始字节及 SHA-256，并验证列表、详情、陈旧浏览器 cookie、跨租户拒绝、无凭据拒绝和撤销会话拒绝；独立重跑 1 passed。该测试以 service 导入准备数据，并使用 SQLite、MemoryStorage 及测试密钥、身份和会话提供器，不代表真实管理员导入或 109 认证验收。

109 当前 multi_tenant.enabled=false；思维导图和门店选址条目均已存在且同版本包字节不同。经用户选择不覆盖或删除现有条目。因此 109 真实账号有图读取、真实跨租户与线上覆盖/升级/删除生命周期尚未验收。Dia 已登录但未启用可用自动化接口；不得为验证导出凭据或擅自重启浏览器。
