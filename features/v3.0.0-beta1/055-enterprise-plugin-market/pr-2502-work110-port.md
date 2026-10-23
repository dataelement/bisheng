# PR #2502 移植说明

日期：2026-10-21。目标分支：`feat/bisheng-work-110`。

## 来源与范围

来源：[PR #2502](https://github.com/dataelement/bisheng/pull/2502)，提交 `29ab7fd1318b21466e3a05d9ace7a8dcc360516c`。目标基线为 `926fda34e7515e97f4352838e31fc0de224c3bce`。本次按该提交的功能差异移植，不执行源分支 merge，不引入 `feat/bisheng-work-120` 的其他提交。

用户已确认同时移入 npm 插件包导入。

- 市场能力改为 contract_version=2，`enabled=true`，不读取 `BISHENG_DSH_MARKET_SIGNING_KEY`，不返回 `public_key` 或 `lease_seconds`。
- `/sync` 返回 `{tenant_id,user_id,device_id,synced_at,policies}`，移除签名、编码 payload 和离线租约时间；能力、目录、同步和制品响应禁止缓存。
- 支持 manifest ZIP、社区 package.json ZIP / npm tgz；保留安全路径与容量限制，支持预发布版本比较，gzip 制品返回正确类型和文件名。
- 导入页接受 `.zip`、`.tgz`、`.tar.gz`，同步中英日文案。
- 保留原生桌面令牌和本地会话校验、平台 JWT/Cookie 的既有市场入口；认证异常保留客户端错误码。JWT 自身签名仍正常校验，移除的是市场独立签名私钥。

## 相对源 PR 的适配

源 PR 新增 `market_employee` 并要求有效桌面席位；本分支已经取消席位管理，因此不移入该门禁，也不移入“有效席位”文案。现有 `market_actor` 和管理员隔离保持有效。

保留本分支能力响应中的 `allow_third_party_plugins`、`allow_third_party_workbenches`、相关管理接口及工作台上传/查询/下载实现。功能可发现不代表第三方安装开关已开启，两项开关默认关闭。

为适配 npm gzip 制品，测试 RPC harness 同时处理 ZIP/gzip；补充三种上传后缀的页面测试、npm ZIP/tgz 预览到下载的完整接口测试、版本比较和市场错误码包装测试。旧测试中的席位 fixture 改为本地会话 fixture，撤销会话按当前运行语义返回 401。

## 验证

| 检查 | 结果 |
| --- | --- |
| 后端市场模块 | 72 项通过，覆盖工作台、租户隔离、管理员边界、无密钥/遗留密钥、无签名快照及 npm ZIP/tgz |
| 管理页与导航 | 16 项通过，包括 ZIP/tgz/tar.gz 上传 |
| 现有客户端市场、社区包与工作台 | 45 项通过；客户端源码未改动 |
| 跨项目协议 | 两种社区制品均通过服务端预览、导入、目录、下载，再经当前客户端 `readCommunityPackage` 和 `acceptMarketSnapshot` 校验 |
| Ruff、修改文件 ESLint、platform typecheck、i18n、架构守卫 | 通过 |
| 全仓 frontend lint | 93 个错误，与基线的文件、行号、规则及信息逐项相同 |
| 全仓 frontend typecheck | client `src/hooks/useAiChat.test.ts:294` 缺少 ChatMessage 字段，与基线相同；platform 通过 |

本地日志：`/tmp/work110-pr2502-backend.log`、`/tmp/work110-pr2502-frontend-tests.log`、`/tmp/work110-pr2502-crossrepo.log`、`/tmp/work110-pr2502-client-tests.log`。基线日志为 `/tmp/work110-pr2502-basefront-lint.log`、`/tmp/work110-pr2502-basefront-typecheck.log`。

复跑后端：仓库根设置 `PYTHONPATH=src/backend`，使用 Python 3.11 执行 `python -m pytest --confcutdir=src/backend/test/dsh_market src/backend/test/dsh_market -q`。管理页：在 `src/frontend` 执行 `pnpm --filter bisheng exec vitest run src/test/dshMarket.test.tsx src/test/headerMenuChildAdmin.test.tsx`。

本轮未部署 109，不代表已经完成真实 MySQL/DM8/MinIO、npm 依赖安装或原生客户端市场完整验收。服务端升级市场契约后，客户端需支持契约 v2；当前取消席位客户端分支已具有该协议。仍只支持契约 v1 的旧客户端市场需单独验证，不能视为兼容。
