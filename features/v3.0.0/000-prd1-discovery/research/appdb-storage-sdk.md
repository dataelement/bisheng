# appdb-storage-sdk

## summary
应用数据库/附件存储/SDK-CLI 三块地基中，现状可复用的是「单实例平台库的引擎与双库方言层」「MinIO 全套对象操作与 prefix 隔离范式」「v2 检索 RPC 与 BishengLLM 模型封装」；而 PRD 要求的 per-app 数据库供给、schema diff 迁移引擎、迁移前快照、bisheng-sdk 包、bisheng CLI、平台侧安装包分发全部为零基础新建。仓库今天既无任何 CLI（无 [project.scripts]、无 click/typer），也无可分发的 wheel 打包管线（backend pyproject 无 [build-system]，bisheng_langchain 在本 monorepo 中是无打包元数据的 vendored 目录）。除 alembic 之外不存在任何 schema 快照/备份机械——「迁移前自动快照」目前只是运维 runbook 里的手工 mysqldump，且 DM8 侧连等价工具集成都没有，是 C2 双库法则下的最大技术风险。

## current_state
【(a) MySQL/DM8 供给与访问 — 已在代码核实】平台库是单 URL 单例：`bisheng/core/database/connection.py` 的 `DatabaseConnectionManager` 持有一对 sync/async engine（pymysql→aiomysql、dmPython→dmAsync 自动换驱动），DM8 的 schema 经 `_normalize_dm_url` 移入 `?schema=` 查询串（DaMeng 以 connect kwarg 选 schema，URL path 会被 dmPython 拒绝）——这是「DM8 天然 schema-per-app」的关键锚点。双库差异全部收敛在 `core/database/dialect_helpers.py`：Boolean→SMALLINT、JSON/LONGTEXT→CLOB、Computed 列转触发器、`JsonType`/`LargeText` TypeDecorator、以及一组反射探测 primitives（`table_exists`/`column_exists`/`index_exists`/`get_column_type`，带 DM8 大小写三态回退）。迁移采用双轨契约（src/backend/AGENTS.md 明文）：整表新建走 SQLModel `create_all`（alembic env.py 在每次 online upgrade 前先跑 `alembic_helpers/online.py::create_missing_model_tables`），存量表变更走 alembic revision（`core/database/alembic/versions/` 现 58 个），autogenerate 只反射 MySQL、DM8 兼容靠人工审。`alembic_helpers/mysql_impl.py::BishengMySQLImpl` 只做等价索引去重。全仓 grep 无 CREATE DATABASE/CREATE SCHEMA 动态建库代码、无任何快照/备份模块（scripts/ 全是 backfill 一次性脚本）；「迁移前备份」只存在于运维记忆（手工 mysqldump），DM8 无对应集成。多租户注意：平台库新表须被 `core/database/model_discovery.py::import_all_sqlmodel_models` 发现，tenant_filter 只拦 SELECT；但 per-app 库在 SQLModel metadata 之外，隔离靠库/schema 边界而非 ContextVar。【(b) MinIO — 已核实】`core/storage/minio/minio_storage.py::MinioStorage`：双 client（endpoint 内部直连 + `sharepoint` 公网地址走 `share_minio_client`），bucket 固定两只（`MinioConf.public_bucket` 默认 "bisheng"（其 `knowledge/images/*`、`tmp/images/*` 挂匿名读策略）+ `tmp_bucket` "tmp-dir" 带生命周期过期），完整 put/get/list/copy/remove 同异步双份 API；预签名只有 GET（`get_share_link[_sync]` → `presigned_get_object`，`clear_host` 剥掉 host 交前端 nginx 代理），无 presigned PUT。prefix 级隔离的成熟范式在灵思：`linsight/domain/services/workspace_backend.py` 以 `workspace/{svid}/` 为对象键前缀圈定工作区，且已有跨版本 copy-forward 快照机械（166-181 行 `list_objects`+`copy_object_sync` 整前缀复制）——正是「应用代码版本快照」可照搬的形态。`core/storage/tenant_storage.py` 的 4 个租户前缀函数零调用方（grep 证实，dead code，F008 未落地）。【(c) SDK/打包 — 已核实】`src/backend/pyproject.toml` name="backend"，无 [build-system]、无 [project.scripts]、无 entry_points——后端从不被打成 wheel，uv sync 就地运行；`src/backend/bisheng_langchain/` 无 setup.py/pyproject（仅 ruff known-first-party 引用），在本仓是 vendored 模块非发布物（PyPI 上的 bisheng-langchain 来自上游公开仓，属推断）。平台今天不提供任何安装件下载：main.py/router.py 无 StaticFiles，文件下发全走 MinIO share link + nginx。【(d) CLI — 已核实】全仓无 CLI：无 click/typer 导入，find 无 *cli* 模块（仅 mcp_manage/clients 误中）。【DEV-07 五件套对应现状】auth：会话态走 `common/dependencies/user_deps.py::UserPayload.get_login_user`；v2 开放面现状零鉴权（`open_endpoints/api/dependencies.py` 走 `get_default_operator_async`），SAK（bs-sak-）体系在伴生 PRD（213/232/286 行）待建。retrieve：`open_endpoints/api/endpoints/filelib.py:621 retrieve_chunks` → `chat_svc.aretrieve_chunks`（F030 RPC）已存在。chat：服务端有 `llm/domain/llm/llm.py:193 class BishengLLM`（LangChain BaseChatModel 包平台模型）；HTTP 面只有 workbench 专用 `workstation/api/endpoints/chat.py:94 /chat/completions`（LoginUserDep 会话鉴权，非开放 OpenAI 兼容端点；PRD-1 第 91 行明示要新的兼容 base URL）。storage：MinioStorage 可包。appdb：零现状。

## key_files
- src/backend/bisheng/core/database/connection.py — DatabaseConnectionManager 单 URL 引擎单例；_normalize_dm_url 证明 DM8 以 ?schema= 选 schema（schema-per-app 的落点）；per-app engine 池可以此为模板但需重管 pool_size（默认 100/engine 会爆连接）
- src/backend/bisheng/core/database/dialect_helpers.py — 双库方言收敛层：类型映射 + table_exists/column_exists 等反射 primitives，appdb diff 引擎的现成积木
- src/backend/bisheng/core/database/alembic_helpers/online.py — create_missing_model_tables：平台库「新表 create_all + 存量表 revision」双轨契约的实现；appdb 不能复用 alembic_version 单表机制，只能借鉴
- src/backend/bisheng/core/database/alembic/env.py — online 迁移入口（361 行 run_migrations_online），无任何快照钩子
- src/backend/bisheng/core/storage/minio/minio_storage.py — MinIO 全套对象操作；双 client（endpoint/sharepoint）；get_share_link 仅 presigned GET（608 行）；bucket 策略与 tmp 生命周期在 _init_bucket_conf
- src/backend/bisheng/linsight/domain/services/workspace_backend.py — workspace/{svid}/ 前缀隔离 + copy-forward（166-181 行整前缀 copy_object_sync）——应用附件命名空间与代码版本快照的现成范式
- src/backend/bisheng/core/storage/tenant_storage.py — get_minio_prefix 等 4 个租户前缀函数零调用方=dead code（F008 未落地），勿当既有能力引用
- src/backend/pyproject.toml — 无 [build-system]/[project.scripts]：后端非 wheel、无 CLI 入口；SDK/CLI 必须另起独立包工程
- src/backend/bisheng/open_endpoints/api/endpoints/filelib.py — 621 行 retrieve_chunks → aretrieve_chunks：SDK retrieve 面可直接包的 v2 RPC（fail-closed 与 type=3 view_file 缺口需同步修）
- src/backend/bisheng/llm/domain/llm/llm.py — 193 行 BishengLLM：平台托管模型的服务端封装，chat 面的服务端积木；HTTP 兼容端点需新建
- src/backend/bisheng/database/models/flow_version.py — FlowVersion：既有「应用版本记录」表设计范式，RT-05 版本列表/回滚记录可参照
- src/backend/bisheng/open_endpoints/api/dependencies.py — v2 现状零鉴权（get_default_operator_async），SDK auth 面依赖伴生 PRD 的 SAK 落地

## reuse
- storage 面：MinioStorage（core/storage/minio/minio_storage.py）put/get/list/copy 同异步全套 + get_share_link 预签名 GET 可直接薄包为 SDK storage 模块；应用附件命名空间照搬 linsight workspace_backend.py 的 `<prefix>/{id}/` 键前缀隔离范式
- 应用代码版本快照：workspace_backend.py 166-181 行的整前缀 copy-forward（list_objects+copy_object_sync）就是 MinIO 侧不可变版本快照的现成实现模式，RT-05 版本内容存储可复用
- retrieve 面：open_endpoints/api/endpoints/filelib.py:621 retrieve_chunks → chat_svc.aretrieve_chunks（F030 RPC）可包为 SDK retrieve；权限过滤骨架（view_file 双层过滤）已在 F029 存在
- chat 面服务端：llm/domain/llm/llm.py:193 BishengLLM 已封装平台托管模型调用（含各厂商适配），新的 OpenAI 兼容端点可在其上薄包
- appdb 迁移引擎的探测积木：dialect_helpers.py 的 table_exists/column_exists/get_column_type/is_column_nullable（含 DM8 大小写回退）+ JsonType/LargeText 类型映射可直接用于 per-app schema diff
- per-app 引擎管理模板：DatabaseConnectionManager（connection.py）的 URL 归一化（尤其 DM8 ?schema=）、sync/async 双引擎、会话回滚语义可派生为 AppDbConnectionManager
- auth 面：会话态 UserPayload（common/dependencies/user_deps.py）+ 伴生 PRD 的 bs-sak- 服务账号密钥体系（PRD-1 v1.5 已对齐：应用 token=SAK）——SDK auth 读平台注入身份属新建，但校验端复用伴生 PRD 的 R1 凭据体系
- 版本记录表设计：database/models/flow_version.py FlowVersion 的「data 快照 + 版本行」范式可参照设计应用版本表（版本号/类型/终态标注）

## gaps
- per-app 应用数据库供给全链路：动态建库/建 schema（全仓无 CREATE DATABASE/SCHEMA 代码）、按应用签发最小权限 DB 凭据、per-app 引擎池与生命周期管理（现有 manager 是单 URL 单例）
- app schema 声明与 diff 引擎：PRD 未指定声明载体（bisheng-app.yaml? SDK model?），需新建「加列自动迁移 / 改删列检测→显式确认位（--confirm-schema-change）传递到发布管线」的整套 diff+执行机制；不可复用平台 alembic（版本链与 alembic_version 均是平台库专属）
- 迁移前自动快照：仓内零快照机械（scripts/ 无备份脚本，运维靠手工 mysqldump）；需为 MySQL 与 DM8 各建自动快照通道 + 快照存储位（MinIO?）+ 保留/恢复策略
- bisheng-sdk 独立包工程：五件套（auth/retrieve/chat/storage/appdb）从零写；仓库现无任何可发布 Python 包（backend 无 build-system，bisheng_langchain vendored 无打包元数据）
- bisheng CLI 从零建：login/skills sync/dev/deploy/logs 五命令；全仓无 click/typer/console_scripts
- 平台侧安装件分发：CLI/SDK 安装包下载端点（DEV-01 接入信息区）——现平台无 StaticFiles/artifact 端点，需新建（可落 MinIO+share link）；「依赖包经平台内网镜像安装」的内网 pip 镜像属部署假设，代码零支撑
- OpenAI/Anthropic 兼容 base URL 端点（PRD-1 line 91）：现仅有 workbench 专用 /chat/completions（LoginUserDep 会话鉴权），开放兼容面需新建并挂 SAK 鉴权
- storage SDK 缺 presigned PUT 与 app 级命名空间/配额记账（现只有 public/tmp 两只 bucket，public 带匿名读策略——app 附件不能直接混入）
- deploy 托管预检：契约检测（自带中间件识别、依赖构建、启动探活）与 schema 破坏性变更检测全新建

## risks
- C2 双库法则是最大风险：DM8 侧无 mysqldump 等价物集成（dexp 是外部二进制），「迁移前自动快照」在 DM8 上如何自动化未证实；且有 DM8 undo 写放大致 -7120 的历史事故（灵思 history 大 UPDATE），大快照/大迁移在 DM8 上有把实例拖垮的前科
- MySQL 与 DM8 的隔离原语不对称：MySQL 的 database≈schema、DM8 是同实例内 schema（?schema= connect kwarg）+ 用户权限体系——schema-per-app 与 db-per-app 两方案在双库上语义不一致，方案必须双库各自验证 DDL 权限模型
- 连接数爆炸：DatabaseConnectionManager 默认 pool_size=100+overflow 20，若每 app 一对 sync/async 引擎照抄默认值，几十个应用即可打满 MySQL/DM8 连接上限；需全新的小池+LRU 引擎缓存策略
- 平台 alembic autogenerate 只反射 MySQL（AGENTS.md 明文），appdb diff 引擎若基于 alembic autogenerate 复用，DM8 侧的类型反射（CLOB/SMALLINT 回读）会与声明类型不等值，误报「改列」触发确认闸口——需用 dialect_helpers 的归一化探测而非裸 autogenerate
- SDK 面挂 v2 的前提是伴生 PRD P0 落地：v2 现状零鉴权（get_default_operator_async 匿名超管越权是活缺口），SDK auth/retrieve 上线顺序被伴生 PRD 硬依赖锁定
- retrieve fail-closed 红线：现 aretrieve_chunks 的 type=3 分支漏 view_file 过滤（已知越权缺口），SDK retrieve 若直接薄包会把缺口带进新面；必须先修再包
- app 附件若沿用 public_bucket 会继承 knowledge/images/* 匿名读策略与 sharepoint 公网可达性，泄漏面大；新 bucket 则牵动 MinIO 顺序约束与商业版 nginx 代理配置（sharepoint SigV4 签 Host 的既有坑）
- C3/C4 边界：per-app 库在 tenant_filter ContextVar 体系之外，租户隔离完全靠库边界+凭据，等于为 appdb 新开一条隔离审计线（constitution C3 的例外需在 design 阶段 Constitution Check 里显式论证）
- CLI 分发形态若选 wheel+内网 pip 镜像，客户纯内网环境的镜像基础设施是部署假设非产品能力，交付时容易变成实施黑洞；若选单文件二进制（PyInstaller）则需新建跨平台构建管线

## open_questions
- 应用数据库隔离粒度拍板：schema-per-app（DM8 天然、MySQL 用独立 database 模拟）还是 db-per-app？以及 DB 凭据模型——每 app 独立 DB 账号（GRANT 限本 schema）还是平台统一账号+逻辑隔离？
- app schema 的声明载体与真源：bisheng-app.yaml 内声明表结构、SDK 端 model 元数据、还是首个版本由平台从运行时 DDL 捕获？diff 的比较基线存哪（平台库记录 vs 现库反射）？
- 迁移前快照的范围与保留策略：只快照受影响表还是整库？保留几份/多久？存 MinIO 还是 DB 侧？是否计入租户存储配额（PRD-1 已定附件不计配额，快照未提及）？恢复动作是产品能力还是运维手册？
- appdb SDK 的接线方式：托管运行期直连 DB（平台注入连接串+凭据）还是经平台 API 代理？本地 dev 期（bisheng dev）appdb 连什么——平台侧真库、开发者本地库、还是平台代开的 dev 库？
- CLI 安装包形态：pip wheel（依赖内网 pip 镜像假设）vs 单文件二进制？「平台自身分发」的下载端点挂 v1 还是独立静态面？SDK 与 CLI 是否同一个包？
- OpenAI/Anthropic 兼容 base URL（DEV-01）与 SDK chat 面的关系：chat 模块走该兼容端点还是私有 RPC？兼容端点是否属于本 PRD 交付边界（还是伴生开放 API PRD）？
- DM8 客户是否在 PRD-1 首发范围内？若允许「appdb 首发仅 MySQL、DM8 二期」可大幅降险，但违背 C2 需要显式豁免决策
- 改/删列显式确认的授权语义：--confirm-schema-change 只需 owner 的 key 即可，还是审批单上也要展示并由审批人二次把关（RT-05 说发布时不再二次确认，但审批人视角未明确）？
