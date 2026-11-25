## 2026-11-14 用户确认：Milvus 原生持久消息例外

用户明确要求“Milvus密码加密保持现状”。本次据此保留 Milvus 原生账号认证、凭据更新和 RocksMQ 持久消息机制；内部消息中可还原的 Base64 密码作为明确的验收例外，不认定为已加密。该例外只覆盖 Milvus 自身生成的内部消息和数据文件。应用配置里的受管密码字段仍须密文，密钥仍外置。原生中间件配置按 2026-11-15 选项 C 以受限明文挂载，不再要求密封进内存文件系统。迁移会话、改密计划和恢复备份里的敏感材料继续加密保存。

不引入 Milvus 透明加密卷、FUSE、SYS_ADMIN 或原生镜像分叉。撤销仅因该发现而新增的整批改密拒绝门禁；保留正常的整批身份预检、维护确认、认证和故障恢复检查。仍执行原部署命令。其余未完成回归、业务、迁移和发布验收继续保留待验，不能据此宣布全部交付完成。

下方此前“Milvus阻塞/需重新确认/拟增加拒绝门禁”是历史发现，按本节用户确认的新范围执行；原扫描证据保留。

---

# Design：中间件密码与配置加密治理

**关联**：[已确认 spec](./spec.md) · [HTML 方案](../../../docs/中间件密码与配置加密治理方案.html) · [版本契约](../release-contract.md) · [验收记录](./verification.md)
**版本**：v3.1.0-beta2 / F003。**更新**：2026-11-16。
**状态**：当前实现是选项 C。应用配置的受管密码字段为密文，密钥外置；原生中间件文件以 `native_storage=plaintext` 挂载；原命令负责输入、加密、同步、启动检查和恢复。Go `credential-runtime` 与 `sealed-files-v2` 交付门禁已拆除。HTML 方案 v2.1 的业务背景、入口、组件处理、旧版升级、旧 ES 无认证升级和验收范围已按代码并入本文。该 HTML「四、技术实现」里的静态启动工具、内存文件系统和交换分区拒绝条件与选项 C 及现码冲突，不再作为实现依据。DM、完整故障矩阵、L2 审查、正式发布镜像，以及 Gateway、rootless、未验证原生旧布局仍未关闭。Helm 自 2026-11-16 起不在本次范围。
**核查基线**：凭据模块与 `docker/lib/credential-*.sh`、`docker/install.sh` 的当前工作区；验收数字以 [verification.md](./verification.md) 为准，不把 HTML 里的 213 项无跳过当作最新全量结果。

## 0. 当前状态：原命令部署及选择改密增量

原入口逐组件选择改密已经实现并有独立实测。应用侧缺的是外置密钥和字段密文，不是把原生启动文件再密封一次。§4.14 是选项 C：普通宿主账号可部署，原生文件明文挂载且权限受限。不能用 v1 任务进度或覆盖镜像代替未关闭的交付门禁。

用户要求保留原部署命令，由部署过程中引导补齐必要信息。本章取代下文把手动生成配置包作为日常安装前提的旧流程；下文纯加密、原生适配和恢复基础能力继续复用。本章的原入口引导、自动配置、身份复用与断点续跑已实施并有本地回归；真实配套镜像与全业务验收仍待完成。

目标交互：

```text
bash docker/install.sh  或  bash scripts/deploy.sh install
  → 检查当前环境，识别新装/已有部署/失败重试
  → 仅在必要信息缺失时引导运维输入，密码隐藏
  → 首次自动建立外置key；已有部署复用有效key
  → 内部生成/复用加密配置，自动同步原生消费者
  → 自动设置权限、挂载、校验和启动
  → 显示部署结果；失败保留状态，原命令再次执行可恢复检查
```

正常部署不显示需要运维填写的bundle/key/revision参数；辅助工具降为脚本内部能力和维护/排障入口。新装key自动创建不代表自动生成组件密码，组件密码继续由客户提供。普通重复部署不默默更换身份或执行账号改密；旧key缺失不能被新key“修复”。

两个原命令入口的回归覆盖首次引导、密码不回显、重复执行不覆盖、失败重试、非交互输入、配置/密钥缺失、部署锁及存量身份保护。旧SOP已替换为HTML原命令手册；底层工具不再是日常部署的人工前置步骤。

## 1. 目标与非目标

客户环境使用各自的中间件密码，不能共用一套默认弱密码。运维仍只执行 `bash docker/install.sh` 或 `bash scripts/deploy.sh install`。部署程序完成密码输入、应用字段加密、原生配置同步、启动检查和故障恢复。重新部署时逐项询问 MySQL、Redis、MinIO、ES、Milvus 是否改密，默认保留；独立统计 ES 单独询问。首次部署隐藏输入并二次确认。运维不手工运行加解密命令。

MySQL、Redis、ES、Milvus 及统计 ES 至少 6 个字符；MinIO 原生密钥至少 8 个字符。不要求数字、字母、符号同时出现。空值、内嵌换行、NUL、占位符和已知默认弱密码仍拒绝。

在这条原命令链路上，补齐外置密钥、应用配置密文和普通宿主账号部署。输入、历史计划和失败恢复走同一套检查点。应用重启直接读已挂载的明文原生文件和密文配置，不增加解密命令。

不新增业务 HTTP API，不改变账号权限、业务及租户归属，不强制 Vault/KMS，不提供密码热更新或零停机保证，不通过关闭认证、删数据或关闭 TLS 恢复连接。不把 Helm、rootless、未验证的原生旧布局或 DM 算进本轮通过范围。只迁移当前共用加密工具保护的数据。Milvus 内部 Base64 消息保持用户确认的例外，不据此改原生镜像。

## 2. 关键约束

- 遵循 [constitution.md](../../../docs/constitution.md) C1–C8 和本版本契约；数据维护使用已有 ORM/session 和双 DB 能力，不进入 Alembic revision。
- 外置密钥必须先于配置解密、数据库连接及 Alembic 可用；迁移、API、Celery、Beat、Linsight 均读取同一部署版本，不能只在 API 生命周期初始化。
- 保持 `encrypt_token(str) -> bytes`、`decrypt_token(str|bytes) -> str` 和已约定旧密文格式，DB 不新增列。
- 旧镜像不能读取新密钥生成的密文。新部署模板只与支持本设计的镜像配套；不新增顶层 YAML 节，避免旧镜像遇到未知字段直接退出。
- 先保持服务端密码不变完成密钥外置，再逐组件改密。存量弱密码/无认证不能因“仅外置密钥”被标记为已治理。
- Compose 宿主机继续无需 Python：工具放在后端镜像；Bash 包装器使用 Docker 运行。
- 当前 Milvus 镜像为 2.5.10，后端 pymilvus 约束为 `>=2.6,<3.0`；必须验证实际组合，不顺带升级依赖。
- 后端 Dockerfile 使用 `COPY ./ ./`，改造前后端构建目录与仓库根未发现 .dockerignore，本次已新增后端排除规则；Git ignore 不能保护 Docker 构建上下文。实际秘密文件必须在构建上下文之外，另加构建排除和镜像扫描门禁。
- 客户秘密文件是显式分发的静态部署输入，不作为跨节点业务状态存储；密钥不依赖被其解锁的 DB/Redis/MinIO 提供。

## 3. 方案对比与选定

### D1：外置文件与有序密钥环

- **备选**：源码固定密钥；普通环境变量包含密钥；强制 Vault/KMS；外部只读文件。
- **选定**：通过 `BS_SECRET_KEYS_FILE` 读取外部文件，保留 Fernet；首密钥加密，所有有效密钥用于认证解密。
- **原因**：消除源码固定秘密；复用已有算法/字段；不新增客户基础设施，且能在数据库连接前完成引导。
- **重新考虑条件**：客户已有统一KMS时替换密钥提供层；本次全量密码文件加密采用§4.14，不改变业务字段Fernet契约。

### D2：配置准备与实际改密分阶段，原入口协调

- **备选**：安装时自动改所有账号；人工重复修改每个消费者；生成配置包并显式切换。
- **选定**：新增设计仍先离线生成未激活包、check只读；运维明确逐项选择与维护授权后，由原入口调用原生管理适配器，按阶段验证及激活。未支持的外部组合在预检阶段停止。
- **原因**：用户2026-11-13明确要求五项均可选择改密；已验证手工原生流程可作为适配参考，但初始化不等于存量改密、Milvus超时不等于未写入，必须保留阶段计划及新连接核实。
- **重新考虑条件**：独立外部控制面/无停机需求另行设计；本次仅在已验证管理身份和单机适配范围内编排，不承诺任意外部账号自动恢复。

### D3：沿用字段，在配置边界集中解密

- **备选**：另建所有认证字段；各客户端工厂独立解密；现有配置模型统一解析。
- **选定**：统一处理已知秘密字段；ES 沿用 `ssl_verify.basic_auth`，Milvus 沿用 `connection_args`，SDK 只收已解密参数。
- **原因**：ES 同步/异步/统计与 Milvus 工厂/ORM 路径容易漏配，分散处理还会重复解密；现有 `!env` 必须检查真实生效来源。
- **重新考虑条件**：认证形式确实超出现有模型时再扩展，不预先增加第二套密码来源。

### D4：版本化配置包与连接重建

- **备选**：原地覆盖挂载文件；运行中热更新；新目录输出后显式激活。
- **选定**：每次输出新目录，检查成功后由原安装器自动更新路径（专项维护仍可显式指定），并按依赖重建容器/重启服务。
- **原因**：原子替换单文件可能保留旧 inode；restart 不应用新 env；版本目录可与恢复材料配对。
- **重新考虑条件**：有跨进程可验证热更新协议时；本次不依赖该能力。

### D5：独立维护工具迁移密文

- **备选**：同时换真实密码与密钥；塞进 Alembic；维护窗口独立重加密。
- **选定**：停凭据写入和消费者，使用外部新旧密钥迁移、处理缓存并验证，再移除旧 key；后续逐组件改实际密码。
- **原因**：共用工具还保护组织同步和沙箱；DB/Redis 不存在共同事务，需要阶段状态与可重复恢复。
- **重新考虑条件**：明确要求无维护窗口并引入凭据版本协议，另行设计。

### D6：原入口自动编排

- **备选**：要求运维先运行多条凭据工具命令；另建部署入口；原安装器内部完成准备与恢复。
- **选定**：保留两个原命令，正常新装只引导客户输入密码；key、配置版本和路径自动管理。识别旧部署后在同一入口确认维护并迁移密文。
- **原因**：用户明确要求治理不能增加部署命令和人工配置联动，已有离线工具可作为内部能力复用；账号改密仍与密钥外置分开。
- **重新考虑条件**：支持全新部署形态或客户接入统一秘密控制面时另行评估；不因安全底层细节增加日常步骤。

## 4. 实现与数据流

### 4.1 改造前基线

1. `docker/install.sh:32` 首次复制 `.env.example`，不生成业务 config.yaml。
2. Compose API/Worker 挂载已有 YAML 到 `/app/bisheng/config.yaml`；ConfigService 在模块导入时解析 YAML/`!env` 并构造 Settings。
3. `settings.py:26–66` 存在固定密钥；MySQL/Redis 已解密，MinIO/ES/Milvus 未统一解密。
4. API 先执行 Alembic；Worker 容器内还有 Linsight、Beat。连接池及 Milvus alias 不会因宿主机改文件自动刷新。
5. 共用加密还覆盖 `org_sync_config.auth_config`、config 表的沙箱 `token_enc` 及 Redis 缓存。

### 4.2 实现主线

```text
原安装命令 → 获取配套工具镜像（不兼容时原入口引导选择）
  → 新装：隐藏输入/确认公司密码 → 自动外置key/准备配置
  → 已部署：复用现用身份；缺文件引导匹配备份
  → 旧版本：维护授权 → 自动导入现用来源/key → adopt-key
  → 离线校验和原子状态保存
  → 新装/普通复用：初始化/启动原生组件 → 只读新连接检查
  → 旧版本：保留原生组件 → 暂停本机应用 → 备份/DB迁移/resume/主key复检
  → 自动挂载并重建应用 → 业务验收
```

真实账号改密属于显式维护分支：§4.13已将逐项选择、原生账号修改、配置激活与恢复编排接入原入口。底层离线prepare仍只生成产物。独立密钥轮换不随改密执行。


运行与工具使用同一 YAML/`!env` 读取逻辑及 Settings 模型；将纯读取逻辑抽为无业务连接的共享函数，使用局部 SafeLoader。禁止 eval、source 客户输入或把密码拼进 Shell。

### 4.3 密钥文件与读取契约

**当前实现**：`secret_crypto.py` 已接入 Settings 和全部既有 encrypt_token/decrypt_token 调用方。固定 key 已移除；ConfigService 和 entrypoint 在 Alembic/服务初始化前校验 key 与显式数据库配置。字段解析、离线 CLI 与维护逻辑使用相同加密基础，验证证据见 [verification.md](./verification.md)。

```json
{"version": 1, "keys": ["<当前 Fernet 密钥>", "<可选过渡 Fernet 密钥>"]}
```

- `BS_SECRET_KEYS_FILE` 是进程可见的绝对路径；不从 YAML、普通密钥 env 或源码常量兜底。
- 校验 version=1、非空/不重复的 keys 及每项 Fernet 格式。首项加密，其余只用于兼容解密；无有效项直接失败。
- 运行初始化时读取并缓存为进程快照；导入纯加密模块不读文件。更改密钥环必须重建全部进程，不做自动刷新。
- 默认目录 0700、文件 0600，按实际 UID/GID 只读挂载；禁止 world-readable。支持 Kubernetes Secret 符号链接与已配置 fsGroup 的最小读取权限，不能一律拒绝 symlink 或非 0600。
- 公共函数返回类型不变；原 key 只能由运维显式外部提供，不在新源码/镜像里保留兼容常量。
- 错误只包含路径/字段/阶段与原因类别，不包含 key、token 或原始异常值。

### 4.4 字段与格式

| 字段 / 来源 | 实现契约 | 错误处理 |
| --- | --- | --- |
| MySQL/DM `database_url` | 密码段保留裸 token；解密后由 SQLAlchemy URL 设置并只编码一次。既有 `bisheng_DATABASE_URL` 来源走同一校验 | 不允许明文旁路；生产缺 URL 不落 SQLite |
| Redis/Celery URL 与 dict 内 `url` | 密码段裸 token，按对应客户端规则编码一次 | 不根据前缀猜测明文，不漏 dict 内 URL |
| Redis dict | `password/sentinel_password` 为 `encrypt(token)`；保留 username、db、master、hosts | 标记损坏失败，不扩大现有 Sentinel 支持范围 |
| MinIO `secret_key` | `encrypt(token)`；移除 minioadmin 默认；账号不变 | 旧明文只由离线迁移工具接收，runtime 不回退明文 |
| ES `ssl_verify.basic_auth` | 解析字典/字符串以及二元 list/tuple，再解密密码；同模型覆盖独立 telemetry ES | prepare 将 URL 内认证物化到 basic_auth；与已有认证冲突即拒绝 |
| Milvus `connection_args` | JSON 后解密 password 或整个 token；覆盖工厂与 ORM 两路 | 认证输入冲突即拒绝，不将密文传 SDK |
| `!env` | prepare 物化本次负责的秘密字段为密文并记录原来源；保留非秘密引用 | 环境缺失、多源冲突或不可安全转换拒绝，不静默默认 |

只处理已知字段，不递归扫描所有“看起来像密码”的业务数据。验证器不原地污染输入，不通过重新验证已解密字典或 assignment validator 二次解密；客户端沿用已解析模型。

合法空值与损坏密文分开：新装不允许缺少必需认证；仅 `adopt-key` 转存旧配置时保留已有无认证组件和旧弱值，并记为待治理，不能通过最终 enforce。此阶段没有提交新密码，不重设服务端；新增密码输入仍执行 AC-07 校验。这是 AC-28 的分步迁移，不提供通用弱密码放行开关。

### 4.5 输入清单、配置包与激活

清单 version=1，实际密码只以文件路径或交互输入提供，不内嵌清单。相对路径基于清单目录解析。示例：

```yaml
version: 1
mysql:
  password_file: ./mysql.password
redis:
  password_file: ./redis.password
minio:
  access_key_file: ./minio.user
  secret_key_file: ./minio.password
elasticsearch:
  username: elastic
  password_file: ./elasticsearch.password
milvus:
  user: root
  password_file: ./milvus.password
```

独立统计 ES 使用 `telemetry_elasticsearch` 同形输入，不默认复用另一个集群的凭据。Gateway 自有业务数据库密码不因 root 改密被覆盖。

密码文件最多去掉一个结尾 LF/CRLF，保留前后空格；拒绝空值、内嵌换行/NUL、占位符、已知默认弱值以及不满足组件长度限制的输入。MySQL、Redis、ES、Milvus 与统计 ES 最少 6 个字符；MinIO 原生密钥最少 8 个字符。纯数字、纯字母、纯符号均可，不要求字符种类组合。合法特殊字符交给各格式序列化，不用统一 Shell 转义或 percent-encoding 代替。

输出到全新目录，由必填 `--out-dir` 指定，例如 `docker/.generated/credentials/<版本>/` 或外部安全目录；已有目录拒绝覆盖。失败不激活，原始配置文件不改。目录 0700、文件默认 0600；需要非 root 容器读取时明确设置最小 UID/GID/组权限。

```text
<bundle>/
  manifest.json                  # 非秘密版本、mode、来源、文件清单、待治理项
  config.yaml                    # 客户配置副本，秘密字段已物化为密文
  mysql.password                 # 服务端原生 Secret
  mysql-client.cnf               # 初始化/健康检查用原生凭据
  redis.password / redis-users.acl
  minio.user / minio.password
  openfga.yaml                   # 原生 datastore 配置，含受控实际密码
  gateway-application.yml        # 仅启用时，保留其他配置及变量引用
  milvus.yaml                    # 认证和对象存储原生配置
```

仅输出所需文件。manifest 不包含秘密、明文摘要或可用于猜测低熵密码的单文件摘要；只对不含明文秘密的产物记完整性摘要。敏感文件校验用权限、格式及内存中的一致性比较；配置版本随机生成，不由秘密派生。

标准安装器自动激活并保存 `.env` 的 `BISHENG_CREDENTIALS_DIR` 为配置包绝对路径，`BISHENG_SECRET_KEYS_FILE` 为宿主机密钥路径；`BISHENG_CREDENTIAL_REVISION` 自动读取 manifest 的随机版本；正常部署不要求运维填写三项参数。Compose 映射为 `BS_SECRET_KEYS_FILE=/run/secrets/bisheng-fernet-keys.json`；密钥只挂给 Python 消费者。

API/Worker 改挂 bundle/config.yaml，原 docker/bisheng/config/config.yaml 作为新装基础模板，不含可用默认密码；客户现有文件不覆盖。移除已物化字段对应的旧秘密 env，非秘密引用保留。安装激活时 native 文件显式赋予受控部署组0640，目录0700，相关容器附加该 GID；外部 key 不随之放宽。激活只改变客户端路径，不代表服务端密码已变；必须按 §4.7 顺序重建容器。

### 4.6 CLI 与安装契约

已实现入口 `python -m bisheng.core.config.credential_tool`；为离线配置作者工具，不为 prepare 初始化业务连接，也不导入全量应用上下文执行只读检查。

| 命令 | 结果 | 边界 |
| --- | --- | --- |
| `keygen --out PATH` | 显式新建 version=1 单 key 文件；已有路径失败 | 不回显 key，不改配置或服务 |
| `prepare --mode MODE --config PATH --inputs PATH --key-file PATH --out-dir DIR` | MODE 为 fresh/adopt-key/password-change/key-rotation；生成未激活包。adopt-key 可无新密码清单，需明确提供全部既有来源 | 无网络，不改账号/.env/原配置；不从源码提取旧 key |
| `check --bundle DIR --key-file PATH [--online] [--component NAME] [--enforce]` | 默认离线；online 新建只读连接；enforce 校验全量静态密码治理状态；认证验证额外要求 online，仍不代表业务验收 | 不建库/bucket/索引/collection，不写队列；component 子集通过不代表整体交付 |

模式的修改边界固定如下，避免分步改密时意外打开其他组件的认证：

- `fresh` 使用 `--config` 和完整 `--inputs`，生成所有本次必需组件的认证配置。
- `adopt-key` 从显式旧配置及部署输入转存；已有弱值/无认证状态保持不变，仅重加密业务值，manifest 记录待治理项。不能凭空猜测原生组件配置；来源不全即拒绝。
- `password-change` 必须指定 `--base-bundle DIR --component NAME` 和该组件的输入；从旧包复制其他配置，仅改变目标及已知依赖消费者。例如 minio 联动 Milvus 对象存储，但不修改 Milvus 登录密码。
- `key-rotation` 必须指定 `--base-bundle DIR`；仅重加密业务值，原生凭据和认证状态不变。上述两种增量模式不同时接收另一份冲突的 --config。
- `--env-file PATH` 为可选显式旧部署来源，采用与现有 env.awk 一致并经夹具验证的安全解析语法；不 source、不执行替换。客户显式来源与运行环境同名值冲突则拒绝并报告变量名，不能静默选旧密码。运行时使用已物化秘密，不再依赖此旧文件。

退出码：0 本次请求通过；2 输入/文件/解密错误；3 在线连接/认证失败；4 存在阻止 enforce 的过渡项。输出仅组件、阶段、版本及成功/失败/未验证状态。

online probe 使用实际 bundle 与相同环境来源的解析参数，构造新客户端，仅执行 MySQL SELECT 1、Redis 认证 PING、MinIO 列 bucket、ES 认证、Milvus 列 collection；ES 只调用认证接口，已有索引读写属于独立业务验收；新环境无资源不触发创建。业务写入验收属于独立隔离测试，不属于 check。

宿主机包装器为 `docker/credentials.sh`，从任意 cwd 定位 docker 目录，读取既有 env.awk，不 source .env。使用 `docker run --rm --entrypoint python` 运行 .env 指定后端镜像，离线命令 `--network none`，只读挂载输入/key/显式旧 env 文件、只给目标输出写权限；不依赖尚未生成的主 Compose 凭据插值。仅传清单使用的非秘密环境值，旧明文来源经只读文件读取，不继承整台主机环境。online 模式加入实际中间件网络，容器内地址按该网络验证，不能把宿主机可达等同于应用网络可达。

`install.sh --prepare-only` 继续不登录、不拉取、不启动：没有现用配置包时只生成.env并使用进程内非秘密占位路径做Compose结构检查，不要求密码/工具镜像，不把占位值写入.env，也不宣称凭据验证通过。已有完整配置包时做本地离线检查，本地缺工具镜像则明确失败。正常安装先登录/拉取配套后端工具镜像，再离线检查配置，之后拉取其余镜像；旧镜像缺新工具入口时明确停止，不退回默认密码流程。

新装按“原命令隐藏输入并确认客户密码 → 自动准备配置 → 原生文件初始化中间件 → online check → 应用启动”分阶段，不继续将一次 up 全服务视为认证初始化完成。实际改密不随 install 或容器启动自动执行。

### 4.6.1 原入口自动编排与恢复状态

- `install.sh` 在改写Gateway配置及其他部署参数前，初始化 `.generated/credential-security/`（0700）并取得排他目录锁；PID存活时拒绝并发，明确的已退出PID允许原命令回收。异常退出通过trap释放锁并恢复终端回显。
- 新装按基础模板检测五项组件和可选统计ES，逐项隐藏输入并两次确认；使用文件描述符3读取组件列表，保留终端stdin。先关闭回显再显示提示，避免快速粘贴的密码被终端回显。通过既有密码校验后保存私有输入；只在没有现用身份且不存在旧数据时生成部署key。
- 后端镜像执行 `requirements` / `validate-inputs` / `keygen` / `prepare` / `check`，不要求宿主机Python。每次准备使用独立新目录，离线检查成功后以原子替换写入 `prepared.env`（仅路径）；随后将路径和随机revision在私有临时副本中整体准备并原子替换.env，防止中断时新包配旧key/revision。中断或.env激活写入丢失时复用此指针，不重建key或重置密码。
- 已配置密钥或配置包丢失时，TTY（可交互终端）提示匹配备份完整路径，再走原检查；非交互明确停止。不能生成替代key或把旧数据当新装。可选 `BISHENG_CREDENTIAL_INPUTS_FILE` 仅供自动化首次新装，已经激活时不据此静默改密。
- 检测到原标准容器或本机非空中间件数据而无新包时，先在原入口确认维护窗口/所有其他节点停写；自动读取旧容器配置、Config.Env JSON及旧settings导出的key。密钥只进入私有文件，失败时引导备份；不从新源码/Git自动查找固定旧key。旧环境快照经严格格式与重复名校验，在局部解析环境中使用，所有!env物化，迁移后不依赖被替换容器的旧环境。
- 新主key与旧key组成过渡环，配置以 `adopt-key` 重加密且保留原生身份、认证状态与pending。源文件/环境/密钥检查通过后拉齐镜像，在维护授权下停止本机标准frontend/gateway/API/worker，再运行现有DB工具全租户dry-run、apply、primary-only verify；备份在0700的migration-backup持久保存。存在plan时自动resume；仅复检成功才写complete标记。
- adopt只以 `--no-deps --force-recreate` 重建API/worker，以 `--no-deps` 启动frontend，已有gateway用原容器恢复；不执行原生组件up或套用fresh认证文件。迁移失败保持业务停止，原命令可续跑；不能宣称旧弱值/无认证已完成治理。多节点停写与反向恢复仍须维护负责人执行，标准脚本不越权停止未知节点。

### 4.7 组件部署与恢复

| 组件 | 选定适配 | 顺序与恢复 |
| --- | --- | --- |
| MySQL | MYSQL_ROOT_PASSWORD_FILE；健康检查/Gateway 初始化使用 mysql-client.cnf，不在 argv/MYSQL_PWD env 中嵌密码 | 新装先验证，再启 OpenFGA/应用；存量先确认用户@Host，显式改密再同步全部客户端。失败核实真实状态，成组恢复。原有 openfga 建库职责移到显式 mysql-init 一次性服务；健康检查和只读 check 均只 SELECT 1 |
| OpenFGA | 原生 datastore YAML，run/migrate 同时挂载；删除旧 OPENFGA_DATASTORE_URI 覆盖 | 不假设 distroless 有 Shell；Go MySQL DSN 不采用 SQLAlchemy URL 的通用密码编码规则 |
| Gateway | 复制现有 application.yml，写入 Redis 真实凭据，保留 license/HMAC/业务 DB 及变量引用 | root 改密只联动初始化任务；Redis 改密联动 Gateway；不擅改其业务账号密码 |
| Redis | 保留原 redis.conf，挂载 ACL hash 文件；default 用户关闭 nopass，保留现有 key/channel/命令语义；健康检查脚本从 Secret 读取并仅在进程内设置 REDISCLI_AUTH，不传 -a 参数，关闭 xtrace | 首次维护窗口切换全部消费者；轮换先保存新旧 hash，全部新连接通过后删旧 hash。同步持久化源；只读 ACL 文件不盲目 ACL SAVE |
| MinIO | 原生 ROOT_USER_FILE/ROOT_PASSWORD_FILE，不继续旧 ACCESS_KEY/SECRET_KEY 明文 env | 停消费者与 Milvus → 更新/重建 MinIO → 验证对象 → 启 Milvus → 启毕昇。失败整组恢复；受影响签名链接重新生成，保留对象数据 |
| Elasticsearch | 使用锁定 Bitnami 的原生安全入口；初始化/恢复用镜像内安全工具，客户通过交互或受控 stdin 提供密码 | 入口变量、工具路径、TLS 须镜像门禁确认，不能猜不存在的 _FILE；存量用 API 改密。仅改密码通常无需 ES 重启；失败用有效管理身份或已验证 reset-password 流程 |
| Milvus | 挂载原生 milvus.yaml，开启 authorizationEnabled；defaultRootPassword 仅初始化；对象存储传实际 MinIO 凭据 | 存量验证管理身份再 update_password，接口失败也要新连接确认真实状态；重启客户端清 alias。失败通过有效管理身份恢复，不清元数据、不关闭认证 |

MySQL、YAML、JSON、ACL、Go DSN 使用对应格式，不对密码做 sed 替换、eval 或未转义 SQL 拼接。实际管理 SQL 使用交互原生终端或经过参数处理的显式管理操作，不让 prepare/check 执行。

OpenFGA 原生配置加载、Bitnami 安全入口与工具位置、Milvus 配置挂载位置须在锁定镜像测试中固定到交付脚本和手册；若不支持则阻止该交付组合并修订设计，不能在多个猜测路径间静默回退。

### 4.8 存量重加密、断点与缓存

已实现 `scripts/rewrap_credentials.py`，按 scripts/AGENTS.md 提供 Shell 入口和 README。读取与服务相同的 `config`、外部 key 和 settings singleton；默认 dry-run，只读 DB，不初始化全量上下文。

```text
预检全部目标 → 密文备份 fsync → 每批事务更新
  → DB_COMPLETE_CACHE_PENDING
  → 初始化服务上下文、清确切缓存
  → 首密钥独立复检 → COMPLETE
```

- 参数：`--backup-dir DIR`、`--apply`、`--resume DIR`、`--verify-primary-only`；跨租户维护额外显式 `--all-tenants`。dry-run 不改 DB/缓存/服务。
- 仅维护 org_sync_config.auth_config 和 config 表 key=sandbox_endpoint 的 token_enc。组织表在授权维护范围中显式 bypass tenant filter，保留 tenant_id；当前 config 是全局唯一 key，不假造每租户沙箱配置。
- 空值跳过；非空值要求可解且结构合法。只变更加密表示，保留 endpoint、未知 JSON 字段、逻辑凭据和原时间；写更新时显式保留时间字段。
- 已由首 key 可解的值不再生成新 token，保证重试字节稳定；其他值解密后用首 key 重加密。备份/journal 只记录行标识、tenant、原/新密文和阶段，不含 key、明文或其摘要。
- 先完整写盘并 fsync 备份，再写 DB。每批最多 100 行，采用双 DB 支持的 ORM 事务/行锁，锁后在内存核对旧值；不使用供应商 JSON SQL 或大文本相等条件。
- 已提交批保留，当前批失败回滚。journal 落后时以 DB 等于备份旧值/目标新值辨认；出现第三值停止，不覆盖并发变更。备份失败不得提交 DB。
- 需要 Redis 的 apply 阶段按 scripts/AGENTS.md 初始化同 settings 的应用上下文并 finally 关闭。该显式维护允许正常上下文初始化；dry-run 和只读 check 不借此触发 MinIO bucket/policy 写入。
- DB 提交后若上下文初始化或缓存清理失败，记录 CACHE_PENDING 并非零退出，不能声称 DB 已回滚；resume 跳过完成项后重做缓存和复检。
- 只删除 settings.redis_url 对应实例/DB 的 `config:sandbox_endpoint`，不硬编码模板 /1，不清其他缓存或队列；此时消费者已停，不等自然 TTL 碰运气。
- 非空沙箱页 token 解密失败不再经 `_merge_sandbox_page/_probe_token` 静默改用部署凭据；仅 InvalidToken 转为脱敏配置失败。未配置页 token 时正常使用部署来源，其他无关回退语义不扩改。
- `--verify-primary-only` 检查静态配置和所有目标 DB 值；未完成不能移除旧运行 key。恢复旧镜像必须配套旧密文，在停写窗口按字段恢复，不全库覆盖新增业务记录。

### 4.9 源码、多节点与 Helm 边界

- 2026-11-16 起，Helm 不在本次密码治理范围。`docker/helm/bisheng` 恢复到治理前的 Chart：不增加外部凭据 Secret、`configRevision`，也不在 Helm 中改中间件密码或拒绝旧 values。下文若仍把 Helm 外部 Secret 写成当前实现，以本节为准。
- 源码/systemd 设置 config、BS_SECRET_KEYS_FILE 绝对路径及读取权限，使用相同 preflight，无 Docker 依赖。
- 多节点先确认均具备新 key 解密能力再切首 key；静态配置由运维逐节点分发，不依赖 API 本地共享。

### 4.10 模块职责

| 模块 | 做什么 | 不做什么 |
| --- | --- | --- |
| `core/config/secret_crypto.py`（新） | 文件读取、Fernet/MultiFernet、脱敏异常及进程快照 | 不导入 DB、ConfigService singleton 或连接服务 |
| `core/config/settings.py` | 保持公共函数签名，集中解密、模型验证和秘密 repr 控制 | 不修改账号，不扫描任意业务数据 |
| `common/services/config_service.py` | 共享读取/来源校验、启动 preflight、沙箱解密错误显式失败 | 不生成 key，不用默认配置掩盖 InvalidToken |
| `core/config/credential_tool.py`（新） | 配置包、CLI、只读 probe | 不实际改密或写业务数据，不调用全量初始化做 check |
| `scripts/rewrap_credentials.py`（新） | 受控备份、跨租户重加密、缓存失效与恢复 | 不进入 Alembic，不取得业务 Owner 权限 |
| Compose/install/credentials.sh + lib/credential-install.sh / credential-migrate.sh | 原入口引导、锁/状态恢复、新装编排、授权存量迁移及路径挂载 | 不source客户文件，不隐式改真实账号；新增显式维护分支见§4.13，不停止未知节点 |
| Helm | 不在本次范围；Chart 保持治理前行为 | 不在本次交付中改 Helm 凭据、改密或 rollout |

### 4.11 构建产物与密钥隔离

在后端构建目录新增 .dockerignore，至少排除本地 `bisheng/config.yaml`、`.env`、`.env.*`、`secrets/` 和 `.generated/` 等非发布输入；秘密文件仍必须放在构建上下文外，不能只依赖文件名匹配。离线准备产物不复制到 src/backend，镜像仅包含配置模板与工具代码。

发布检查同时扫描交付源码、最终容器文件系统和镜像各层；不因新 COPY 覆盖了路径就认为下层内容消失。若基础镜像包含旧固定密钥或真实客户配置，重建干净基础镜像后才能交付；不能仅在上层删除文件。扫描只报告文件/层位置及类别，不输出秘密内容，不将待匹配的真实 key 写入测试源码。

### 4.12 实现补充与边界

- 测试 conftest 在业务 premock 导入前提供临时测试配置/key，与生产引导隔离；旧数据库环境来源缺字段时也校验，YAML和运行环境冲突拒绝；prepare物化后目标检查不沿用旧源覆盖。外部DM配置包不强制要求MySQL原生文件。

- `credentials.sh --image IMAGE [--network NETWORK] <命令>` 只使用本地工具镜像；输入清单/密码文件放同一安全目录；同目标挂载已合并，允许输出包与输入共父目录。离线 network none，online 必须显式网络；远程 daemon 必须拥有所引用宿主路径。CLI 可直接在源码/配套镜像中运行。TLS 证书路径要额外显式挂载，标准安装器面向当前单机 HTTP 拓扑，不自动套用客户集群/TLS override；新增改密分支须捕获并保留已验证的原生配置，不能从HTTP模板覆盖。
- 新装需要配套镜像先可获得；正式安装先以离线help探测工具入口，发现旧镜像时原入口引导填写配套镜像地址，非交互明确停止；prepare-only 不拉取。正式安装先获得工具镜像并静态校验，再启动原生组件；等待 liveness 后只做一次认证检查，避免启动阶段反复尝试错误密码。API/Worker 显式 force-recreate，Worker 中的 Beat/Linsight 一并重建。
- 标准 Compose 使用 default Redis 原有全权限语义。增量 Redis 改密保留旧 ACL 的命令/key/channel 权限及其他用户，仅换目标密码；带引号/转义的复杂 ACL 拒绝自动转换。Gateway Redis 配置从旧包保留后只替换密码。外部 Sentinel/Cluster/自定义初始 ACL 仍需专项适配验收。
- Milvus override 挂载 `/milvus/configs/user.yaml`，增量 MinIO 只改其中对象凭据，增量 Milvus 只改登录安全字段，保留其他原生参数。token 与 user/password 冲突拒绝，真实账号不随改密变更。
- 缓存上游 Bitnami ES8.12 支持 ELASTICSEARCH_PASSWORD_FILE；单机 HTTP 模板显式启认证及对应 TLS 开关，客户请求 TLS 时不自动关闭。MySQL 原生客户端继承 pool SSL 的 CA/cert/key 与校验模式；OpenFGA tls=true 使用 Go 信任根，私有 CA/双向 TLS 必须另外提供并验证，不能推断它与 Python 的文件挂载自动相同。
- `check` 同时比较 MySQL client/OpenFGA、Redis ACL、MinIO user/password 与 Milvus对象凭据、Milvus native登录、Gateway Redis等已知消费者的配置一致性；不会用这些静态比较宣告服务器已实际改密。
- `adopt-key`/`key-rotation` 不接受新密码 inputs。adopt 记录 pending，不通过普通安装器的全量 enforce 激活原生认证；在停写窗口完成静态/DB密文迁移与缓存清理后，以 --no-deps 重建现有应用，当前真实组件治理仍须另做；新增原入口选择改密完成后按§4.13内部编排。
- 构建扫描覆盖源码、镜像元数据和每层内容，识别 lower-layer 残留；真实交付镜像档案缺失时保持发布门禁未完成。
- 直接维护脚本默认 dry-run，精确目标/跨租户显式授权。前向 resume 已实现；反向恢复由 DBA 按备份、租户与当前字段值核对执行，不提供盲目整库恢复。

### 4.13 原入口逐组件选择改密（AC-48～AC-56，已实施，标准单机实测通过）

#### 4.13.1 当前能力与本轮增量

已实现逐项选择、服务端改密自动编排、持久化状态、部分改密后的复用策略及受控续跑/配对回退。新增能力使用独立live与192.168.106.166真实组件和业务证据验收，不以原9项live代替；完整交付仍受T035/T038门禁约束。

Linux实测修正：Redis通过setpriv保留Docker明确授予的补充组，仍以redis UID/GID运行且不放宽秘密文件权限；ES等待最终Java主进程，避免初始化临时JVM被误判就绪。整批新旧认证及Docker目标归属在写入前核对；双通、未知身份、外部地址或DNS与实际容器不符时拒绝执行。

原入口保持`bash docker/install.sh`及`bash scripts/deploy.sh install`，新增逻辑是内部维护分支；不新增运维必输的路径/版本参数，不让密码进入Shell求值、argv或普通环境变量，不更换现有有效密钥。只生成配置的prepare-only以及check继续无服务端写入。

#### 4.13.2 交互与执行顺序

1. 持有现有部署锁，先识别未完成改密计划；有计划时展示原选择/进度，重新确认本次维护条件后续跑，不再询问五项选择或重收已保存密码。
2. 无未完成计划时，标准新装仍按原流程询问五项密码，不额外询问是否改密。交互处理已有部署时逐项询问`是否修改…密码？[y/N]`，回车/明确n均保留；非法回答重新询问。独立统计ES配置存在时独立列项，不能复用知识ES密码。
3. 仅所选项隐藏输入/确认新密码；沿用组件校验，新值与现值相同则说明并要求重新输入或取消该项。Ctrl-C/取消恢复终端回显，没有进入真实改密。全部保留时无维护确认、不生成新改密计划，继续原有复用流程。
4. 汇总只显示组件名称及保留/修改，说明预计重启的依赖服务、已有签名链接影响、备份与其他节点停写要求。新计划必须有独立的`yes`授权，不能沿用旧密钥迁移的永久authorized文件。
5. 旧版场景先按既有授权完成外置密钥迁移、DB重加密及primary-only复检；可先收集选择，但真实改密必须在该阶段成功以后开始。旧版迁移失败不执行改密。
6. 受限文件保存全部所选输入，离线生成完整的未激活阶段配置；拉取所需镜像，校验宿主机目录/备份可用性/组件归属与适配能力。对所有目标先做只读管理能力检查，任何目标不支持则整批停止，尚未修改服务端密码。
7. 操作者确认其他节点及外部任务停写后，记录本机原运行消费者并暂停API、Worker（含Beat/Linsight）、前端、启用的Gateway和受影响的OpenFGA。脚本不能宣称自动排空外部写入者、提供全量一致性业务备份或保证在途任务恰好执行一次。
8. 固定顺序执行MySQL、Redis、知识ES、统计ES、MinIO、Milvus中所选项；每项先记写入意图，修改实际账号，核实结果，更新相关原生挂载并按依赖重建，验证后推进检查点。任何失败立即停止后续项，业务保持暂停。
9. 最后复检全部连接及未选身份不变，原子激活完整配置，按依赖恢复OpenFGA、API/Worker、Gateway、前端，检查就绪并输出本次改密结果与仍待治理的未选组件。全部业务恢复验证完成才写COMPLETE。

非交互且没有显式改密请求时保持复用；自动化可在.env中提供受限`BISHENG_CREDENTIAL_ROTATION_INPUTS_FILE`清单（复用version=1组件密码文件格式，出现的组件即所选项）及`BISHENG_ALLOW_CREDENTIAL_ROTATION=yes`。缺少授权/输入/管理前提时在变更前停止。自动化不能把首次新装的输入文件变化解释为改密请求；一次已完成请求不能因.env仍指向同一清单而反复执行，应记录其请求ID/文件内容摘要并要求新的显式请求。

#### 4.13.3 宿主编排与组件适配

| 组件 | 只读前提检查 | 实际改密及持久化 | 必须同步/验证 |
| --- | --- | --- | --- |
| MySQL | MySQL方言、锁定镜像入口、现用管理连接、CURRENT_USER与目标User@Host清单及权限；标准管理root只覆盖经确认属于本部署的localhost/%身份，其他账号布局不猜测 | SQLAlchemy/PyMySQL绑定参数执行ALTER USER；每个User@Host独立意图/检查点，不能假设DDL事务回滚。localhost由宿主在MySQL容器中通过stdin受限CNF验证，密码不进argv；管理TCP连接依据已核实的新旧状态选择 | MySQL原生password/client CNF、健康检查、OpenFGA及其migration、Gateway root初始化配置、API/Worker；必要时重建MySQL更新健康检查挂载，数据目录不变 |
| Redis | 仅标准单机；读取当前目标ACL、其他用户及命令/key/channel规则，检查ACL管理权限；复杂quoted ACL/集群/Sentinel拒绝套用 | ACL SETUSER仅替换目标口令，保留权限及其他用户；将旧nopass状态与密码状态分开记录。更新完整ACL文件并重建验证持久化，不对只读挂载执行ACL SAVE，也不把CONFIG REWRITE当作通用方案 | 缓存、Celery/Beat/Linsight、Gateway；新/旧及无凭据连接配对检查，队列不清空。无认证转认证需单独真实fixture通过才标记适配就绪 |
| MinIO | 确认本部署root身份及FILE/旧环境来源、对象存储endpoint和Milvus依赖；账号标识不改，其他IAM身份不冒充root配置 | root凭据使用新受限文件/环境映射重建MinIO使其生效；不是修改普通IAM用户API。先停Milvus，MinIO新连接验证后再用新S3配置恢复Milvus | MinIO、毕昇、Milvus S3；保留原Milvus登录及其他参数，已有对象/collection与新对象验证；旧签名链接可能失效，需重新签发 |
| ES/统计ES | 确认目标账号与安全管理能力、认证/TLS和证书、目标集群及builtin身份；两个实例分开 | 用当前有效管理身份调用security change_password API；同步原生password-file和应用basic_auth，保留证书/TLS。对已初始化节点不能以环境变量更新替代API改密 | 知识同步/异步ES、独立统计ES及原生恢复配置；匿名/旧密码不能被当作成功 |
| Milvus | 锁定2.5.10与配套SDK、实际账号和认证状态；现有认证下验证当前密码，缺失时同入口隐藏询问；无认证时无法只读验证旧密码，不允许猜默认值或用未认证list_collections证明管理凭据有效 | 使用经验证的update_password(user,old,new)，之后用全新客户端核实；更新原生user.yaml并重建清理认证缓存；默认root初始化字段不能覆盖已有账号 | 毕昇所有Milvus路径、原native认证配置；对象存储凭据单独保留。无认证启用/未知旧root密码组合，在具备可验证管理通道前整批预检停止，不伪装成支持 |

适配就绪是按实际镜像digest、认证模式和管理身份确定的能力，不是仅识别组件名称。标准已有认证路径、Redis无认证转认证、ES首次启用安全、Milvus未认证/缺管理凭据等分别标记READY或UNSUPPORTED；UNSUPPORTED必须在全部真实改密之前阻止计划，不能先改其他项后才发现不支持。当前5种手工认证改密证据仅作实现参考，新增编排仍需逐项复验。DM按用户要求保持待验证；不把DM地址交给MySQL适配器。

#### 4.13.4 原生配置保留与部分治理

- 对已有部署捕获原Compose文件列表、项目/网络、现用env和容器mount来源，保存受限渲染快照；从该快照生成仅用于所选原生服务及必要依赖的native编排文件，增量替换目标凭据。未知缺失来源/配置无法无损解析则预检停止。
- native重建使用相同项目、容器名、网络、原数据挂载和保留的非凭据配置，显式`--no-deps`限定目标集合。不能因只改Redis就用新模板重建未选MySQL/ES/Milvus，也不能将adopt生成的最小milvus.yaml视为旧实例完整配置。MinIO选中时Milvus属于必要消费者，仍必须保留其原认证状态、日志/资源/存储参数。
- 所选项执行过程使用预生成的阶段配置描述当前已完成组件；旧.env与旧包在所有目标预检前不变。每阶段原生配置采用独立会话env，最终.env只能指向与已验证服务端状态匹配的配置；所有业务消费者在完整切换成功前保持暂停。不能沿用当前install.sh在真实改密前先提交新.env的普通分支。
- 旧版可能仍有未选择治理的弱密码或无认证组件。它们允许按已导入状态保留，必须列入结果的pending清单，不能为了全局enforce通过而默默修改，也不能导致成功改Redis后下次普通部署必然失败。
- 现有`check --enforce`继续表示全量治理，不削弱为单项通过。新增计划校验独立检查所选项强度、实际认证与消费者一致性，并逐项比较未选身份/认证状态与已导入基线；持久化`deployment-policy.json`绑定基线revision、当前revision、已验证组件及保留pending项。后续复用由该策略验证受控继承；缺失/篡改/不匹配的记录必须停止，不提供通用弱密码放行开关。
- 受管策略只能保留受限、不可变导入基线中实际存在且在本次未变的身份；不能通过手填pending新增弱账号。基线/策略/配置/key一并备份与恢复，迁移后优先原命令引导恢复。

#### 4.13.5 状态、故障与恢复

目录：`docker/.generated/credential-security/rotations/<run-id>/`，父目录0700，输入/原配置/env/容器快照和日志0600；需要native组读的派生文件按既有规则单独设置。密钥继续使用当前文件，不复制到源码，不做无关组织同步/沙箱重加密。锁复用已有安装锁。

`plan.json`含version=1、run_id、原/目标/阶段revision、所选项、输入文件引用、目标身份、镜像与部署指纹、受影响服务以及原运行状态；不嵌入原文密码。`journal.json`含version=1、全局phase、当前component、每项及MySQL子账号phase、验证结果类别、业务暂停标记。密码及旧值仅在受限输入和配置文件中，不能进入进度提示。计划、输入和不可变产物需fsync后原子替换，写失败时不得进入下一项变更。

```text
COLLECTING → PREPARED → PREFLIGHT_OK → MAINTENANCE_CONFIRMED
 → CONSUMERS_STOPPED → [CHANGE_INTENT → NATIVE_VERIFIED → FILES_PERSISTED] × 所选项
 → ALL_VERIFIED → ACTIVATING → SERVICES_READY → COMPLETE
失败：NEEDS_ATTENTION（保留原component/sub-account检查点及停写状态）
恢复：识别同一plan → 再确认维护条件 → 核实实际身份 → 从未完成步骤续跑
```

网络/TLS/服务器启动失败只记UNKNOWN，不得记为旧密码拒绝。对单个可验证身份使用全新、带超时且禁盲目重试的连接分别判断：

| 新身份 | 旧身份 | 恢复决策 |
| --- | --- | --- |
| 成功 | 认证拒绝 | 密码已变，推进文件/消费者，不重复改密码 |
| 认证拒绝 | 成功 | 密码仍旧，确认维护后执行尚未完成的改密 |
| 成功 | 成功 | 明确记录为仍有双凭据/认证缓存/未认证状态，不能标完成；仅Redis已计划的短暂双凭据允许按计划撤销旧值，其他情况停止核实 |
| 均失败/任一无法判定 | 任意 | 停止后续变更，保留匹配管理通道/文件，修复网络或人工恢复，不猜测身份 |

只允许一次计划内的旧/新探测，不能把认证拒绝当成网络重试循环，避免锁号。输入新旧相同在准备阶段排除。Milvus必须使用新连接并明确区分认证错误/不可达；先持久化操作意图再调用RPC，超时不能直接重发。MinIO等重建导致的网络启动阶段使用只读liveness等待，认证仅在就绪后探测。

默认恢复是正向续跑。若运维在同一入口选择撤销/回退，必须另行显式确认并按逆序对已变目标执行服务端+native+消费者成对恢复；只有新管理身份有效、旧值/原挂载齐全、操作模式支持时才提供自动回退。禁止自动恢复原无认证状态、未知弱化操作或承诺丢失管理身份也能回退；不满足条件时明确NEEDS_ATTENTION和受控恢复材料。DB、队列、对象、索引及向量业务数据不做整库回滚、清空或覆盖。

COMPLETE后清除活动计划指针、保留受限审计与恢复材料；后续交互重新询问五项选择。未完成计划优先于普通部署，不能因当前.env已变化或用户回车而忽略它。计划绑定的实例/数据目录/密钥身份发生变化时拒绝自动续跑。

#### 4.13.6 模块、内部契约与测试门禁

| 拟变更入口 | 职责及边界 |
| --- | --- |
| docker/install.sh、lib/credential-install.sh | 识别场景，未完成计划优先，接入分支，保留原入口；只准备不变更语义不变 |
| docker/lib/credential-rotate.sh（新增） | 宿主机选择、输入、锁、维护确认、Docker/Compose生命周期、逐阶段恢复；宿主机仍无需Python |
| core/config/credential_rotation.py（新增） | 纯计划/校验/状态转换与可恢复产物，不操作Docker、不导入业务domain/ORM |
| core/config/credential_rotation_native.py、credential_rotation_cli.py（新增） | 容器内显式管理调用、只读预检与认证探测、脱敏退出；不连接Docker daemon、不在API进程运行 |
| core/config/credential_tool.py、docker/credentials.sh | 暴露内部离线plan/policy命令与挂载；原check仍只读，不把rotate伪装成check。内部plan使用现有password-change生成阶段包 |
| src/backend/test/deploy、test/credential_security | 真实PTY选择及取消、SDK边界故障、原生单机事务/认证/重启、完整恢复与镜像扫描 |

内部输入仍使用受限密码清单；新增会话目录参数使用绝对路径，在线管理必须显式指定应用网络。宿主Docker容器运行工具时只挂载所需会话/config/key，不挂docker.sock，不传秘密环境，不改API/Worker的编排权限。配套工具镜像必须声明rotation-v1能力，旧工具镜像在同入口引导选择新镜像，不能仅凭`--help`存在就开始收集/改密。

必须覆盖：全不选、五个单选、代表性多选/全选、各输入取消/不一致/非法、管理能力不足、无认证/弱值混合基线、未选原生配置完整保留、全部先预检、每个原生操作前后崩溃、MySQL子账号部分完成、Milvus超时实为成功、Redis认证持久化、MinIO/Milvus两者组合、旧签名URL、Gateway/统计ES启用/关闭、未知状态不重试、文件/磁盘故障、配对回退限制、同请求自动化幂等、原入口非交互复用、旧版先迁移以及镜像秘密扫描。每组件至少一个真实正反认证及原数据读写/重启保留；未经验证模式保持UNSUPPORTED，不能只写文档就交付。

手动验收只需原命令，选中目标/输入新密码/确认维护；检查汇总与原业务。故障注入只在隔离可销毁环境执行；重新执行同一命令核对原计划和进度，密钥不变。该功能尚未实施，不在现有测试机直接试验账户变更；DM及原有完整交付门禁继续保留。

上游依据仅验证接口约束，不替代锁定镜像门禁：[Milvus update_password](https://milvus.io/api-reference/pymilvus/v2.5.x/MilvusClient/Authentication/update_password.md)要求旧密码；[Redis ACL规则](https://redis.io/docs/latest/commands/acl-setuser/)区分nopass/resetpass；[ACL SAVE](https://redis.io/docs/latest/commands/acl-save/)写配置ACL文件，不能用于只读挂载。实际认证改密参考本地2026-11-13手工原生演练，当前新增自动编排无通过记录。

### 4.14 普通宿主账号与持久密码加密（AC-57～AC-70）

**2026-11-15 用户确认选项 C**：收窄本节。应用侧字段密文 + 外置密钥 + 原命令改密保留；原生中间件配置改回宿主机明文挂载；拆除 Go `credential-runtime` 交付与 `sealed-files-v2` 原生密封门禁。下文凡与选项 C 冲突的「原生必须密封 / tmpfs 明文 / Go 垫片」描述以本节为准废止。

**2026-11-14真实验收发现（历史）**：RocksMQ 可还原 Base64 等 Milvus 内部持久化问题仍为已知例外，不扩大为「应用配置也可明文」。

#### 4.14.1 约束与决策（选项 C）

遵循constitution C1～C8与release-contract。不新增业务HTTP接口、业务表或运行时编排特权，不让后端服务读取Docker socket。全部Docker操作留在原宿主安装器。

| 决策 | 选定及原因 | 被否方案 / 重新考虑条件 |
| --- | --- | --- |
| 应用加密 | 复用 Fernet；`config.yaml` 受管密码字段密文；Python cryptography | 不引入第二种自创加密协议 |
| 原生加载 | Compose 直接 bind 明文原生文件（password/`_FILE`/yaml/conf/ACL）；无 Go 启动垫片 | 若未来再要求原生不落明文盘，需重新确认设计后再引入密封/垫片 |
| 密钥可见性 | 外置主 keyring，仅挂给 backend/worker 等应用消费者 | 不把主 key 挂进 Redis/MySQL 等原生容器 |
| 持久版本 | revisions 目录含密文 `config.yaml` + 明文原生文件；manifest 标记 `native_storage=plaintext` | 旧 `native/*.sealed.json` 仅作只读导入兼容，新产出不再生成 |
| 非root宿主 | 部署账号生成文件，原生明文 0600/0640 + 必要组；不要求 root/sudo | rootless 另验 |

后端镜像不再构建或携带 `/opt/bisheng/credential-runtime`。安装器只需 Python `credential_tool`（prepare/check/rotation）。

#### 4.14.2 持久目录和格式契约（选项 C）

```text
credential-security/
  keys/keys.json                 主 keyring（外置、受限）
  revisions/<revision>/
    config.yaml                  应用侧受管字段密文
    manifest.json                version=2、revision、native_storage=plaintext、native_files
    mysql.password / redis.password / …  明文原生文件（0600/0640）
    openfga.yaml / openfga.env / milvus.yaml / …
  rotations/<run-id>/            改密计划、密文敏感态、stages
  migrations/<run-id>/           旧格式转换备份与进度
```

- 新产出 `native_storage=plaintext`；旧 `native/*.sealed.json` 仅只读导入兼容，不再生成。
- 主 keyring 格式不变；HKDF salt 常量名仍为历史字符串 `bisheng/credential-runtime/v2`（密码学常量，不表示仍交付 Go 垫片）。
- Compose 将原生明文文件 bind 到 `/run/secrets/…`（及 OpenFGA/Milvus 既定路径）；**不**挂载 Go 启动器、**不**使用 `/run/bisheng-secrets` tmpfs。

#### 4.14.3 从输入到启动的数据流（选项 C）

1. 原安装器取部署锁，核对 Docker/目录/既有配置；首装生成外置 key，已有环境复用或恢复，不替换有效旧 key。
2. 交互密码经 stdin 密封输入；禁用 xtrace；禁止秘密进 argv/普通 env。
3. `credential_tool` 准备 revision：密文 `config.yaml` + 明文原生文件；`check`/online 在工具进程内解密应用字段。
4. Compose 直接挂载明文原生文件启动中间件；backend/worker 只挂主 key 读应用密文。
5. 改密/ES 启用等维护路径仍用 §4.13 / ES migration 检查点；原生重建由 `compile_native` 导出**仅受影响服务**的 Compose，不依赖 credential-runtime binary。

#### 4.14.4 逐组件适配边界（选项 C）

沿用 §4.7 / §4.13 的受管身份、版本锁定与真实改密语义。原生文件以明文挂载为准：MySQL/Redis/MinIO/ES 使用 `/run/secrets/*_FILE` 或等价路径；OpenFGA 用 `openfga.env` + yaml；Milvus 挂 `user.yaml`/`milvus.yaml`。无认证 Milvus 的改密仍为 UNSUPPORTED，直至具备可验证管理通道。

| 组件 | 当前处理 | 失败时 |
| --- | --- | --- |
| MySQL | 先核对 User@Host，再改原生账号，保存密文配置和明文 client/password 文件，重连后更新后端与依赖服务 | 维护窗口内可能短暂停服。保留计划与原材料，原命令核实后续跑。不把 DDL 当成可自动回滚，不盲目重复 ALTER |
| Redis | 保留实际配置、其他用户和 ACL 规则，只换选中口令，切换明文 ACL 文件并验证新连接 | 缓存和任务需要重连。复杂 quoted ACL、集群和 Sentinel 在写入前拒绝，避免覆盖客户自定义配置 |
| MinIO | 核验本部署 root，用明文 ROOT_*_FILE 更新原生凭据，同步后端和 Milvus 对象存储，验证文件读写 | 旧临时下载链接可能失效，对象保留，需重新签发。失败由原命令按计划恢复，不改 Milvus 登录密码 |
| ES | 服务端识别认证状态。无认证时在原命令选择保留或启用；启用时保留原数据卷和索引并设密。已认证走 §4.13 改密 | 连接短暂中断。多节点、已有 TLS、未知 file realm 保持现状。失败保留现场，原命令续跑，或经确认后按 §4.15 配对回退 |
| Milvus | 保持原生账号认证和凭据更新。部署生成的应用字段加密；原生 yaml 明文挂载。用户已接受 RocksMQ 内部 Base64 密码例外 | 不引入 FUSE、SYS_ADMIN、透明加密卷或原生镜像分叉。无认证或未知旧 root 在具备管理通道前整批预检停止 |

#### 4.14.5 环境预检、权限和重启（选项 C）

保留非 root 宿主、目录权限、Docker 授权与部署锁要求。删除「静态 Go 工具每次启动解密预检 / 强制 tmpfs 物化」作为交付条件；普通 `compose up`/容器 restart 直接读明文挂载即可。rootless、主机重启、DM、真实 K8s 等未验收项仍待专项。

#### 4.14.6 旧格式转换与恢复（选项 C）

经核验的受管 v1 包由 `credential_sealed_migration.prepare_migration` 转为 v2，真实密码不变。外层阶段是 `SEALED → VERIFIED → CONSUMERS_SWITCHED → COMPLETE`。切换前把旧文件写入加密备份；`config.yaml` 的受管字段保持密文，原生文件按选项 C 以明文写入新 bundle。旧 3.0.0 目录只读导入（`--allow-external-source`），记入 `external_backups`，不删除、不覆盖。

清理发生在消费者切换之后。`cleanup` 要求会话里的 `deployment.id` 与当前存储一致，并先核对加密备份能还原出原字节。容器看不到某个旧文件，不能当成删除成功；`migrate-bindings` 发现仍有 bind 指向旧明文时拒绝清理。输入类副本在确认不再被恢复流程需要后才处理；客户原始文件和外部备份不擅自删除。中断后重新执行原命令，从 `sealed-migration.active` 续跑。失败不得删除状态目录、覆盖现用密钥，或在没有对应计划时改原生密码。

主密钥要和对应凭据材料一起备份。这是运维要求，安装脚本不会把密钥拷到另一个审批位置。密钥丢失后不能从密文重建密码。不得再生成 Go 垫片或把明文应急目录当作恢复手段。改密中断的配对回退仍按 §4.13.5；ES 启用认证的回退按 §4.15，不把数据目录整份恢复或删除。

#### 4.14.7 模块职责（选项 C）

| 模块 | 增量职责 | 不承担 |
| --- | --- | --- |
| `secret_crypto.py` / `credential_artifacts.py` | 主 key、应用密文、明文原生读写、旧 sealed 只读导入 | Docker 生命周期 |
| `credential_bundle.py` / `credential_tool` | prepare/check/rotation；`native_storage=plaintext` | 构建 Go 垫片 |
| `credential_rotation*.py` / compose | 改密计划、仅导出选中服务的原生重建 | 猜测未认证管理身份 |
| `docker/lib/credential-runtime.sh` | Option C 占位/权限辅助（无 Go 提取） | 安装宿主 Go 依赖 |
| Compose / install / sealed-migrate / es-migrate | 明文挂载与原命令迁移 | 宣称 Helm sealed-files-v2 已验收 |

#### 4.14.8 验收要点（选项 C）

- 交付镜像与安装器路径不得依赖 `/opt/bisheng/credential-runtime`。
- 现网挂载与 health 脚本使用 `/run/secrets`，不得再要求 `/run/bisheng-secrets`。
- 改密 `compile_native` 在 plaintext 包上不得要求 `sealed_runtime`。
- 协议层 Fernet/角色派生单测仍有效；原「Python↔Go 互通 / tmpfs 物化」验收项随垫片拆除而废止，见附录 A。

> 选项 C 之前的 sealed-files-v2 / Go `credential-runtime` 详设见文末 **附录 A（已废止）**，不得再作为实现依据。

## 5. 已知坑与处理位置

| # | 已核实事实/限制 | 不知道会怎样 | 处理 |
| --- | --- | --- | --- |
| 1 | MySQL 初始化变量不更新已有账号 | API/OpenFGA 失联 | §4.7 真实改密和新连接验证 |
| 2 | OpenFGA 无 Shell，Go DSN 不是 SQLAlchemy URL | 包装启动失败/密码编码错误 | §4.7 原生配置及镜像门禁 |
| 3 | Redis 检查接受 NOAUTH，Gateway 也用 Redis | 假健康、商业版漏配 | §4.7 ACL/检查/Gateway |
| 4 | MinIO 初始化会处理 bucket/policy | 只读检查产生写入/权限收紧破坏启动 | §4.6 probe 不用全量上下文 |
| 5 | MinIO 与 Milvus 共用对象存储凭据 | 向量对象访问失败 | §4.7 成组切换恢复 |
| 6 | Milvus defaultRootPassword 只在 root 不存在时用 | 存量文件改了但密码没变 | §4.7 存量管理接口 |
| 7 | Milvus 密码写存储后刷缓存仍可报错 | 恢复错误状态/盲目重试 | §4.7 新连接确认 |
| 8 | 连接池/Milvus alias 缓存认证 | 改文件仍用旧连接 | §4.5 重建全部消费者 |
| 9 | 组织/沙箱共用 key，沙箱可能隐性回退 | 漏迁移被隐藏或部分业务失败 | §4.8 全量预检及错误显式化 |
| 10 | YAML 导入时加载，未知顶层字段被拒 | 镜像配置不匹配重启循环 | §2 配套版本门禁 |
| 11 | 单文件 inode 与 env 不随 restart 更新 | 新配置未真正生效 | §4.5 新目录与 recreate |
| 12 | 缓存与 Celery Sentinel 支持不同 | 只测一路却承诺全面支持 | §4.4/§7 外部部署专项 |
| 13 | pymilvus 与 Milvus 服务端跨小版本 | 文档接口不等于组合已通过 | §2/§7 锁定组合验证 |
| 15 | 组件列表循环重定向stdin会截断隐藏密码引导 | 被误判非交互/读错密码 | helper用FD3；真实PTY回归 |
| 16 | Bash3.2 + set-u展开空数组会报未定义 | 无挂载help和adopt检查提前退出 | 条件分支/兼容数组展开；系统Bash回归 |
| 17 | read提示可能早于终端关闭回显 | 快速粘贴回显秘密 | stty关闭回显后打印提示，trap恢复；PTY校验 |
| 14 | 后端 COPY 整个构建目录，且未发现 .dockerignore；Git 忽略不影响 COPY | 本地配置或 key 被带入镜像，基础层旧秘密也可能残留 | §4.11 构建上下文排除、镜像分层扫描；是否有基础层残留仍待实测 |

依据：本工作区前述符号，以及 [MySQL 官方镜像](https://hub.docker.com/_/mysql)、[Redis ACL](https://redis.io/docs/latest/management/security/acl/)、[Go MySQL DSN](https://github.com/go-sql-driver/mysql#dsn-data-source-name)、[Milvus 2.5.10 rootcoord](https://github.com/milvus-io/milvus/blob/v2.5.10/internal/rootcoord/root_coord.go)、[ES 8.12 安全配置](https://www.elastic.co/guide/en/elasticsearch/reference/8.12/security-minimal-setup.html)。源码结论不等于私有镜像实测。

## 6. 对外契约与依赖

### 6.1 Outgoing

| 契约 | 消费方 | 影响 |
| --- | --- | --- |
| 无新增 HTTP API | 现有用户与前端 | 权限和业务接口不变；非空坏沙箱 token 不再静默改身份 |
| `BS_SECRET_KEYS_FILE` 与密钥环 | 所有 Python 进程/部署方式 | 未挂载即失败，变更覆盖全部进程 |
| encrypt_token/decrypt_token 签名 | DB、Redis、org_sync、sandbox | 类型不变，密钥来源与错误行为改变 |
| 密文与物化 !env 规则 | 客户配置/自动化 | 明文旧配置先显式迁移，无源码固定 key 兼容 |
| 原安装命令 / CLI / bundle | 运维/安装器 | 正常安装内部自动准备/激活；CLI单独prepare仍未激活，子检查不代表整体完成 |
| backup/journal | 维护与恢复 | 与 DB 状态配对，不能只换镜像/文件 |

### 6.2 Incoming

| 依赖 | 用法 | 风险与处理 |
| --- | --- | --- |
| cryptography | 已有 Fernet/MultiFernet | 全部 key 丢失不可逆，不承诺新 key 恢复旧密文 |
| YAML/!env/Settings | 同源读取和模型 | 局部 loader；缺 env/多源冲突拒绝；不重复解析出不同结果 |
| SQLModel/MySQL/DM | 独立维护 | 事务/行锁/大文本验证双 DB，不写专属 JSON SQL |
| config/org_sync 模型 | 精确字段维护 | 保留租户及未知字段；停写核对，不扩展通用密码扫描 |
| Redis 指定实例/DB | 精确缓存失效 | 不硬编码 /1，不清队列 |
| 镜像与 SDK | 锁定组合 | 入口、UID/GID、原生加载不符则阻止交付，不猜测路径 |
| Bash/Docker/env.awk及stty | 宿主机包装和隐藏终端输入 | 无宿主机 Python；不 source .env，不执行秘密内容 |
| 管理身份/维护窗口/备份 | 真实改密与恢复 | 缺有效管理身份不保证恢复；改密前先验证 |

### 6.3 安全异常与启动

统一 `CredentialConfigurationError` 只提供组件、字段、阶段、版本和原因类别；不向用户输出原始秘密异常链。相关 Pydantic 模型启用 hide_input_in_errors，秘密字段不参与 repr；禁记整份 model_dump/SDK 参数。第三方 URL 错误脱敏后记录类型和阶段。

移除相关入口 xtrace。ConfigService 完整运行配置一律要求显式 database_url，缺少即停止，不用 environment 默认 dev 绕过。显式 SQLite 开发/测试配置不等于缺配置回退，也不能拿来绕过外置密钥检查。

## 7. 测试与可观测

### 7.1 验证分层

- 无中间件：文件权限/密钥环、旧格式、损坏密文、特殊字符、来源冲突、保留自定义配置、无网络 prepare、无秘密 argv/log、幂等与 journal、Compose/Helm 渲染。
- 构建门禁：确认本地配置/秘密不进入构建上下文，扫描最终文件与各镜像层，不把覆盖或删除上层文件当作秘密已消失。
- 组件集成：锁定镜像认证、原生文件和权限、新旧密码实际状态、独立连接、回滚；重加密用 MySQL/DM 相同夹具验证。
- API/E2E：迁移/API/OpenFGA、Celery/Beat/Linsight/Gateway、上传下载/签名、知识库入库及 ES/Milvus 查询、组织同步/沙箱实际令牌。写入验收使用专用数据和隔离环境，不混进只读 check。
- 故障注入：DB 部分提交、journal 落后、缓存失败、错误 key、遗漏节点、Milvus 不确定结果。不得通过删数据或盲目重复业务任务恢复。

### 7.2 已实现维护入口

源码在 `src/backend/` 执行，配置与服务一致；容器使用包装器转发。示例仅含路径，不含真实秘密：

```bash
python -m bisheng.core.config.credential_tool keygen --out /secure/bisheng/keys.json
python -m bisheng.core.config.credential_tool prepare --mode fresh --config /secure/bisheng/base.yaml --inputs /secure/bisheng/inputs.yaml --key-file /secure/bisheng/keys.json --out-dir /secure/bisheng/revision-a
python -m bisheng.core.config.credential_tool check --bundle /secure/bisheng/revision-a --key-file /secure/bisheng/keys.json
# 原生初始化/改密完成后，以下 online 仍只读
python -m bisheng.core.config.credential_tool check --bundle /secure/bisheng/revision-a --key-file /secure/bisheng/keys.json --online --enforce

# config 与外置密钥环境提前设置，默认仅预检
python scripts/rewrap_credentials.py --backup-dir /secure/bisheng/migration-a --all-tenants
python scripts/rewrap_credentials.py --backup-dir /secure/bisheng/migration-a --all-tenants --apply
python scripts/rewrap_credentials.py --resume /secure/bisheng/migration-a --all-tenants --apply
python scripts/rewrap_credentials.py --verify-primary-only --all-tenants
```

原生改密、ACL、重启和恢复命令在锁定镜像门禁通过后写入运维手册。本文不把未经确认的二进制路径作为可运行命令；若镜像不支持选择的原生机制，先修订设计，不带着猜测部署。

### 7.3 可观测与证据

只记录非秘密配置版本、组件、阶段、行数、成功/失败/未验证。明确区分静态失败、认证失败、DB 已提交但缓存待处理、业务未验证。各进程输出非秘密配置版本以定位遗漏节点；不输出秘密或其摘要。

### 7.4 AC 追溯

| 完整 AC-ID | 设计位置 |
| --- | --- |
| AC-01、AC-02、AC-03、AC-04、AC-05、AC-06 | §4.3、§4.4、§4.11、§6.3 |
| AC-07、AC-08、AC-09、AC-10、AC-11 | §4.4、§4.5、§4.6 |
| AC-12、AC-13、AC-14 | §4.7 MySQL/OpenFGA/Gateway |
| AC-15、AC-16、AC-17 | §4.7 Redis、§5、§7.1 |
| AC-18、AC-19、AC-20 | §4.7 MinIO、§5、§7.1 |
| AC-21、AC-22、AC-23 | §4.4 ES、§4.7 ES、§6.2 |
| AC-24、AC-25、AC-26、AC-27 | §4.4 Milvus、§4.7 Milvus、§5 |
| AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36 | §3 D5、§4.8、§6、§7 |
| AC-37、AC-38、AC-39、AC-40、AC-41、AC-42 | §4.5、§4.6、§4.9、§7 |
| AC-43、AC-44、AC-45、AC-46、AC-47 | §0、D6、§4.6.1、原入口/PTY回归 |
| AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56 | §4.13 |
| AC-57、AC-58、AC-60、AC-62、AC-66、AC-67、AC-70 | §4.14 选项 C、§4.3、§6.3 |
| AC-59、AC-61、AC-63、AC-64、AC-65、AC-68、AC-69 | §4.14.2～4.14.6；原生文件明文，应用字段密文 |
| AC-71、AC-72、AC-73、AC-74、AC-75、AC-76 | §4.15 |

上游 ES password-file、Milvus user.yaml、OpenFGA 配置加载已按锁定镜像核查。Helm 渲染不再计入本次通过，见 verification.md 2026-11-16。私有发布镜像、DM、完整故障矩阵和 L2 审查未关闭，不标记交付完成。

### 7.5 已有证据与仍开放的范围

数字以 verification.md 为准。HTML 方案里的「213 项专项回归、无跳过」是 2026-11-14 的聚焦集，不是其后的最新全量。其后记录过密码规则调整后的 240 项，以及 ES 路径扩大后的 250 passed、1 skipped、0 failed；那 1 项跳过是当时缺 Helm 可执行文件。Helm 随后移出本次范围，这项跳过不能当成 Helm 通过，也不能再拿来要求 Chart 验收。

192.168.106.166 上，UID 1000、已有 Docker 授权的隔离项目做过新装、五组件改密恢复、受管 v1 转换和旧文件清理。清理必须让工具看见完整源目录；容器内目录为空不能当成删除成功。单项 MinIO 改密，以及数据、业务、worker 复验和当次扫描，在 verification.md 2026-11-14 记为通过。这些运行使用本地覆盖镜像。业务探针用确定性嵌入，并带仅限夹具的对象下载路由。它们不代表最终成对发布镜像、真实模型质量或完整业务流程已经验收。

仍开放：完整故障矩阵、L2 审查、正式发布镜像、DM。Gateway、rootless 和未经验证的原生旧布局明确拒绝，或不在本轮通过范围。不能据此说所有部署形态都已支持。

运维步骤见 [中间件凭据运维手册](../../../docker/中间件凭据运维手册.html)。增量验收报告已清理，剩余证据以 verification.md 为准。

## 8. 后续改进与不实施项

- Vault/KMS：不强制引入。应用字段密文与外置密钥仍按 §4.14；原生中间件文件按选项 C 明文挂载。不再把「禁止一切受限明文原生文件」当作交付条件。
- 账号最小权限：先盘点 MinIO bucket/policy、ES 索引及 DB 迁移权限后另做，不与认证同时收紧。
- 无停机/热更新：需要跨进程凭据版本与连接协议，本次维护窗口满足已确认规格。
- Sentinel 支持差异和 Redis Cluster broker：不扩大支持范围，按已验证组合交付。
- HTML 保留为已认可输入；正式 How 的维护入口为本文。实现推翻已确认决策按 SDD 重新确认，纯细节更新本文，不维护多份互相漂移的技术真相。

## 修订历史

| 日期 | 改动 | 原因 |
| --- | --- | --- |
| 2026-11-11 | 初版正式设计，明确文件/CLI/配置包/部署/迁移/恢复/门禁 | 用户确认 42 条规格；业务代码未实施 |
| 2026-11-11 | 用户确认设计；完成独立密钥基础与 34 项安全回归，尚未接入运行时 | T001/T002；§4.3 记录真实实现边界 |
| 2026-11-11 | 接入外置 key/字段解密、CLI、Compose/Helm、分批重加密与运维手册；补全 Redis ACL/既有配置接线 | 实施 tasks，真实私有镜像/双 DB/业务与恢复验收仍待执行 |

| 2026-11-12 | 原入口自动管理输入/key/配置版本/挂载；维护授权与旧身份导入、断点续跑；修复stdin、终端回显和Bash3.2空数组 | 用户确认运维无感返工；真实镜像/双DB门禁仍待执行 |
| 2026-11-14 | §4.14新增普通宿主账号、全量持久密码加密、逐容器内存加载、旧材料迁移及真实验收方案；当前v1与拟实现v2明确区分 | 用户已确认AC-57～AC-70及设计，实施中；原生消息持久密码问题阻塞，补充设计待确认 |
| 2026-11-15 | §4.14收窄为选项 C：原生明文挂载，拆除 Go 垫片；§4.15补旧 ES 无认证升级 | 用户确认选项 C 与 AC-71～AC-76 |
| 2026-11-16 | 将 HTML 方案 v2.1 并入本文，并以当前代码校正密封启动、明文原生文件、ES 设密路径和验收数字 | HTML 与选项 C、verification.md 不一致；Helm 移出本次范围 |

## 本地真实验收补充：MySQL原生初始化（2026-11-13）

使用本地隔离Colima、项目原Dockerfile构建的当前代码镜像及锁定CR中间件镜像执行原命令，发现CR MySQL8.0.43入口将包含单引号的客户密码直接插入SQL，初始化报1064后遗留部分数据；密码未设置、无密码socket root仍可连接、TCP健康检查1130失败，应用未启动。该行为不能以拒绝合法字符、降低断言或仅改客户端配置掩盖。

新增`docker/mysql/credential-entrypoint.sh`只替换bootstrap SQL和临时客户端CNF的序列化：SQL转义反斜杠/单引号，标识符双写反引号，CNF转义反斜杠/双引号；设置仅限bootstrap连接的SQL mode以保持字面量语义。复用vendor的配置检查、目录准备、初始化/临时服务器及正式mysqld生命周期；降权后重新进入本wrapper，保留mysql用户运行，不升级为root。拒绝随机/空密码初始化，不改变现有数据账户、不执行启动时自动改密。

首次失败的测试MySQL数据被停止并改名留存，只重建本次可销毁MySQL数据目录；原用户数据卷、旧容器及数据未改动。这是修复后的新装重测，不能据此声称已实现半初始化数据库的自动修复。正式运行遇到未知半初始化状态仍须安全停止和配套恢复，不自动重置已有账号。

配对回归：`test/deploy/test_mysql_credential_entrypoint.py`与Compose挂载断言；真实密码包含单引号的相同输入重新验证，最终状态以local验收报告为准。私有镜像内部函数契约由本次锁定版本验证，其他MySQL镜像仍需配套验证。

## 本地真实验收补充：迁移缓存生命周期（2026-11-13）

真实旧版镜像（提交285bfde44d）与同一套MySQL/Redis数据验证发现：`clear_sandbox_cache`初始化并关闭全局应用上下文，连同既有数据库上下文一同关闭；即使Redis恢复正常，随后的`store.records()`也会抛`ContextStateError`，续跑一直停在`DB_COMPLETE_CACHE_PENDING`。

维护脚本改用独立`RedisClient(settings.redis_url)`，只删除`config:sandbox_endpoint`，并在finally关闭自身异步客户端；不接管全局上下文、不关闭数据库/其他服务。删除失败继续传播，已提交DB仍保持待处理状态，原计划可续跑。成功/失败两条回归都验证既有数据库消费者仍可读取。真实MySQL复检、原命令续跑和密文幂等性结果见本轮验收报告。

## 本地真实验收补充：维护工具挂载合并（2026-11-13）

真实password-change准备发现输入清单和输出配置包共用父目录时，原wrapper同时提交只读和可写的相同目标挂载，Docker报Duplicate mount point。现以精确目标路径合并，相同目标只保留一个挂载；显式输出父目录需可写，不随参数顺序重新降为只读。其他输入/key仍只读，容器根文件系统仍只读，不引入宿主Python或secret环境透传。原部署入口不变。

2026-11-13修订：用户确认AC-48～AC-56；原入口选择改密设计草案见§4.13，替换D2人工协调决策，用户已确认，进入实施阶段。


2026-11-13实施细化：内部入口并入 credential_tool rotation，原生独立SDK位于core/config，不新增scripts下需要初始化全应用上下文的脚本；部分维护身份不一致时全应用上下文不可用。Native编排以实际容器的挂载、环境和命令为准，原镜像ID生成本地固定别名；保留原网络和数据，未知归属拒绝。策略校验显式只读挂载整个受限凭据根以读取历史基线，当前计划另以精确可写挂载保存状态。

实际SDK适配：MySQL8.0.43的SHOW GRANTS可能展开所有权限，允许明确CREATE USER+SYSTEM_USER；MinIO冻结S3Error需使用类式资源管理，避免contextmanager改写traceback掩盖签名拒绝；pymilvus2.6.15的重试装饰器在timeout存在时忽略retry_times上限，改密使用原准备RPC实现的单次调用、同一认证通道和状态检查。认证探测仍有5秒超时，原生写入不盲目重试。

当前运行额外Gateway/独立消费者、独立统计ES、外部端点、Redis非default账号、Milvus无认证/身份未知均在写入前UNSUPPORTED。配对回退只支持被密封原计划绑定且旧密码符合现有输入规则的原账号，旧弱密码不自动恢复；保留停写和续跑计划，交付负责人处理。支持范围的完整验证仍以verification.md为准。


## 4.15 旧 ES 无认证升级（AC-71～AC-76）

纳入原部署脚本，不新增部署命令，也不另建运行栈。范围是原标准 Compose 的 Bitnami ES 8.12.0 单节点。`security_state` 遇到其他版本或节点数不是 1 时直接失败，不套用本节流程。

HTML 方案写过「密码不落明文文件、设密走 tmpfs」。当前代码不是这条路径：原生 `elasticsearch.password` 按选项 C 明文挂到 `/run/secrets/elasticsearch.password`；容器内 `set +x` 后从该文件读出，经 stdin 传给官方 `elasticsearch-reset-password --username elastic --interactive --batch`。密码不进 argv，也不进 Docker Env。诊断输出经 `seal-stream` 加密。宿主交换分区和 coredump 策略不再作为本流程的拒绝门禁；该次 exec 只把自己的 core rlimit 设为 0。

### 入口与识别

`credential_es_select` 在 `credential_sealed_migration_prepare` 里、`migrate-prepare` 落盘之前执行。v1 包先选择再转换；已经是 v2 且后端缺少 ES 认证时，也在同一入口选择。首次安装直接返回，沿用现有初始化。有 ES 迁移会话时，`install.sh` 把 `credential_rotation_select` 推迟到 ES 迁移完成之后。

识别不看 `config.yaml` 里有没有 `basic_auth`。`discover` 走原项目网络，读 xpack security 开关和认证结果：

- 安全开关为 false，记为 `DISABLED`。
- 安全开启且当前身份不是匿名，记为 `AUTHENTICATED`。
- 安全开启但 `authentication_type=anonymous` 或用户名是 `_anonymous`，失败，不能当成安全关闭。
- 客户端认证被拒，记为 `AUTH_REQUIRED`。
- 网络失败、权限不足、安全开关类型不明，失败且不写账号。

归属用 Compose 项目标签、服务名、数据挂载 `/bitnami/elasticsearch/data`、网络别名和配置里的主机名交叉核对。配置主机名对不上捕获到的容器时拒绝。新代码目录可以和原数据目录不同。源 bundle 不在凭据存储内时加 `--allow-external-source`，只读导入，不改旧 3.0.0 目录。

`DISABLED` 时交互询问是否开启认证，默认保留。保留则去掉 `basic_auth`，`pending` 带上 elasticsearch，普通部署不强制改密。开启则隐藏输入 elastic 密码；用户名不是 elastic、或输入里还有别的组件，都拒绝。`AUTH_REQUIRED` 时在同一入口导入现用 elastic 密码，校验后保存，不重置未知账号。后端已配置且服务端已认证，则跳过本节，普通改密仍走 §4.13。非交互且尚未选择时停止。

### 准备、执行与状态

ES 子状态是 `PREPARED → FROZEN → PASSWORD_INTENT → PASSWORD_SET → VERIFIED`。外层是 `SEALED → VERIFIED → CONSUMERS_SWITCHED → COMPLETE`。跨服务写入前先落盘：`reset_intent` 在调用设密工具前写成 `PASSWORD_INTENT`；探针索引创建前先把名称和 token 写入加密会话。

会话状态用外置密钥加密保存，并带 `key_identity`。索引基线、容器 inspect 和回退材料各自密封，另存密文文件的 sha256。`deployment-policy.json` 用密钥计算 MAC。集群 UUID 在密封基线里，原镜像 ID 在密封的运行配置里。这些记录不公开密码或单密码摘要。应用 `config.yaml` 仍是字段密文；给 ES 进程挂的密码文件是明文。

`FROZEN` 之前刷新索引，记录业务索引的 UUID、文档数和别名，并核对同端点统计客户端的集群 UUID。只跳过 `index_baseline` 正则命中的系统索引（`.security`、`.security-<数字>`、`.security-tokens-<数字>`、`.security-profile-<数字>`）以及 `.ds-*` 数据流。名称只是以 `.security-` 开头、但不符合该正则的客户索引仍要计入。不删除索引，不重建数据目录。原 data 挂载和自定义配置保留，编排里的镜像钉死为捕获到的镜像 ID。配置备份不是数据备份。

`ELASTICSEARCH_ENABLE_SECURITY` 和存量 elastic 密码是两步。开启安全后先 `observe_target`。目标身份已经可用（`READY`）且阶段已是 `PASSWORD_SET` 或 `VERIFIED` 时，不再设密。尚未设成目标密码且观察结果为 `DENIED` 时，才在该容器里跑官方 reset-password。`persist_password` 再用 `change_password` 确认；只完成 bootstrap 登录不能写成 `PASSWORD_SET`。不能假定 Bitnami 看见已有 data 会重新初始化密码。工具不适配时保持停写，不改成带密码的命令行。

HTTP 端点才会走启用流程。URL 已是 HTTPS，或捕获配置里 REST TLS 已开启却与 HTTP 端点冲突，直接失败，不为了套用单节点流程去关 TLS。传输层 TLS 按捕获到的 elasticsearch.yml 保留，对应设置 `ELASTICSEARCH_SKIP_TRANSPORT_TLS`。

同端点的统计 ES 同步同一目标身份。端点不同且统计侧没有可用凭据时拒绝，避免改到外部集群。adopt-key 且没有原生文件时，在进程内按目标身份生成原生文件，再由 `write_bundle_native` 写成明文；非密码运行配置来自 `docker inspect`。

结果未知时不生成新密码。阶段仍是 `PREPARED` 或 `FROZEN` 时继续原计划。已经越过 `FROZEN` 时，原命令提供「继续」或「配对回退」。上次停在 `PASSWORD_INTENT` 时，必须再输入 `yes` 才用已保存的同一目标密码重试。就绪等待只认 Java 为 PID 1 之后的 `READY` / `KEEP` / `DENIED`；`UNKNOWN` 会继续等到超时，然后失败并保持应用暂停，不在超时当次重置账号。

### 完成与失败恢复

`verify` 同时检查：目标安全状态、匿名搜索业务索引被 401/403 拒绝、冻结基线里的集群 UUID、索引 UUID、文档数和别名。启用模式下，停在 `FROZEN` 不能通过，因为 bootstrap 登录还不等于密码已持久化。然后创建带 `_meta.bisheng_credential_probe` 的临时索引，写读删一条探针文档，不写客户业务文档。探针名称和 token 先写入加密会话；续跑只删除元数据 token 一致的索引。统计消费者还要再次核对集群 UUID。消费者切换后，`migrate-bindings` 确认没有容器再挂旧明文，才按 §4.14.6 清理。完成后再次执行原命令不重复设密。

开启认证前失败：保留原服务、原配置和数据。停写后失败：应用保持暂停，重跑原命令。已经开启认证后失败：默认继续同一目标，不自动退回无认证。配对回退只在模式仍是 `enable`、阶段已冻结或更后、外层尚未 `COMPLETE` 时准备。交互里选 2 并再输入 `yes` 后，用密封的原配置和原镜像恢复安全关闭及原消费者配置，把 `BISHENG_ES_SECURITY_ENABLED` 设为 false，并重新检查索引与连接。不恢复、不删除数据目录。安全索引里如果已经有目标密码，回退只表示恢复安全关闭，不表示清掉安全索引；下一次开启仍以原生账号现状为准。保留选择不允许走这条回退去关闭认证。

### 影响与边界

影响 ES 容器，以及使用它的 API、worker 和统计客户端。维护期间搜索和写入会短暂停。MySQL、Redis、MinIO、Milvus 的密码不在这次操作里改变。多节点、已有 TLS、file realm 不可用的环境保持现状。改动留在凭据模块和原入口，不改业务表，也不改双数据库逻辑。C1、C2、C3、C4 无变化。C6 靠外置密钥保护应用密文和迁移会话；原生 ES 密码文件按选项 C 明文挂载，不把「会话密封」说成原生文件也已密封。

证据要分开看。verification.md 记录：本地 Bitnami ES 8.12.0 单节点做过启用、匿名拒绝、索引身份保留、重启和显式配对回退；开发侧没有在 192.168.106.166 上代为安装或改 ES 账号，此前只读检查只证明后端缺少 `basic_auth`。HTML 方案写明用户已在 166 执行原命令并选择开启认证，同时写明这一次不能把验收矩阵改成全部通过。本仓库不能复核 166 现场。开发侧不因此再启动隔离栈或代操作原生账号。

参考：[官方最小安全配置](https://www.elastic.co/docs/deploy-manage/security/set-up-minimal-security)，[官方设密工具](https://www.elastic.co/docs/reference/elasticsearch/command-line-tools/reset-password)。锁定版本的行为以实际测试为准。

### 开发验收矩阵

下表是设计门禁。本地主路径通过，或 166 上的一次原命令，都不把未执行的行记成通过。环境不可用时记未执行。真实集成只用已授权的本地或 CI 环境。

| 优先级 | 风险 | 场景 | 预期结果 | 验证层级 | 当前证据 |
| --- | --- | --- | --- | --- | --- |
| P0 | 服务端识别 | 安全关闭、已开认证、匿名角色、网络失败 | 只有明确的安全关闭算无认证；未知状态不写账号 | SDK 边界与协议测试 | 识别规则有单测；166 原状态不能用「后端无 basic_auth」代替 |
| P0 | 选择保留 | 旧无认证 ES，选择不启用 | 保持安全关闭，报告待治理，普通部署不被全量强度检查误挡 | 原命令 PTY 与迁移集成 | 代码路径已接；不把启用主路径的通过记到本行 |
| P0 | 首次启用 | 单节点已有索引，用户选择启用 | 原镜像与数据卷不变；目标密码可用；匿名业务访问被拒绝 | 锁定版本集成 | 本地 8.12.0 单节点已做，见 verification.md；不是 166 的 AMD64 正式部署 |
| P0 | 配置同步 | 主 ES 与同端点统计消费者 | 只更新对应凭据；后端和 worker 使用同一目标密码；外部端点不改 | 配置与业务集成 | 同端点判断在 `shared_endpoint`；业务调用链未随本地 ES 协议测试关闭 |
| P0 | 写入前失败 | 预检或加密备份失败 | 没有原生账号和数据变更，不输出秘密 | 故障注入 | 未作为完整矩阵关闭 |
| P0 | 设密后断线 | `PASSWORD_INTENT` 之后响应丢失 | 先验证已保存目标身份；成功则续跑；不能验证时须显式确认才用同一密码重试 | 故障注入与原命令恢复 | 状态机有单测；不把一次成功启用记成断线恢复已验 |
| P0 | 配对回退 | 认证已开启、后端激活失败 | 原入口默认识续跑；回退要明确确认，并验证旧配置和索引；不能自动降级 | 状态机与真实集成 | 本地显式回退后原索引仍在；自动降级拒绝有代码约束 |
| P0 | 数据与泄露 | 旧索引、别名、特殊字符、短密码 | 冻结后的 UUID 和文档数保留；探针写读删成功；密码不进 argv、Docker Env 或普通日志 | 扫描、索引及业务集成 | 本地索引与探针已覆盖。原生密码文件按选项 C 允许在宿主受限明文存在，不再把「无明文文件」当失败 |
| P1 | 重复执行 | 已完成计划再次部署 | 读取已验证状态，不重复设密，不再要求录入相同密码 | 幂等与 PTY | 阶段判断会跳过已 `PASSWORD_SET` 的重置；未单列成交付通过 |
| P0 | 不适配拓扑 | 多节点、已有 TLS、file realm 不可用 | 保持现状；不能关闭 TLS 或套用单节点 HTTP | 拒绝路径 | 版本、节点数、HTTPS 和 REST TLS 冲突会在改账号前失败。file realm 不可用没有单独预检；官方工具失败后保持停写，不能写成已经适配 |

## 附录 A：已废止的 sealed-files-v2 / Go credential-runtime 设计（选项 C 前）

> **状态：废止（2026-11-15 选项 C）**。仅作历史对照与导入兼容说明；新实现、验收与任务不得再依赖下列目录布局、Go 静态工具、tmpfs 物化或 `sealed-files-v2` 交付门禁。

#### 4.14.2 持久目录和格式契约

```text
credential-security/
  keys/keys.json                    主keyring（外置、受限，已有部署继续原路径）
  keys/runtime/<role>.json          派生子keyring（受限，逐文件只读挂载）
  tools/<image-id>/credential-runtime  无秘密静态工具
  revisions/<revision>/
    config.yaml                    后端字段加密配置
    manifest.json                  v2版本、revision、角色和密文摘要
    native/<role>.sealed.json      该角色完整文件payload的认证密文
  rotations/<run-id>/
    plan.json / journal.json       非敏感阶段、关联标识与密文摘要
    sensitive/*.sealed.json       输入、inventory、env.before等敏感完整内容
    stages/<component>/            完整v2加密配置包，用于恢复
  migrations/<run-id>/             旧格式转换的加密备份与非敏感进度
```

- 主/子keyring格式均沿用源码中的`{"version":1,"keys":["<primary>","<retiring>..."]}`，首项加密、全有序列表解密；没有名为primary/retiring的新JSON字段。不在.env/argv/Docker Config.Env保存key原文。子key派生角色为固定allowlist，HKDF-SHA256输入为各主key的原始32字节，salt为UTF-8字节串`bisheng/credential-runtime/v2`，info为`role:`拼接固定角色ASCII名，输出32字节经base64url作为Fernet key，不使用密码或明文摘要。常量必须通过首个协议测试，发布后不可悄改。
- 初始角色allowlist为`mysql`、`mysql-init`、`openfga-migrate`、`openfga`、`redis`、`minio`、`elasticsearch`、`milvus`、`gateway-db-init`、`gateway`；未启用角色不生成文件或挂载。独立统计ES/外部服务不借用知识ES角色，缺适配时仍先拒绝。一次性的迁移/改密敏感状态使用独立`maintenance`角色，该key不挂载给常驻中间件。
- `sealed.json`外层只有`format="bisheng.credentials.v2"`、`role`、`revision`和`token`。token解密后再次包含相同format/role/revision、deployment_id及files；内外字段必须一致，且匹配启动器收到的预期部署/角色/版本，防止跨服务和跨阶段替换。JSON重复字段与未知协议字段均拒绝，不能让不同语言对同一对象有不同解释。静态部署token不设短TTL，避免机器重启后合法配置过期；旧版本拒绝依靠明确激活状态和预期revision。
- files使用`{name, content_base64, mode}`列表，base64只在密文内部编码任意文件内容。每个角色的相对路径、目标UID/GID和模式有硬编码allowlist；禁止绝对路径、`..`、重复项、硬链接/软链接穿越及设备文件。默认总明文上限8MiB，超过拒绝，不截断后启动。元数据不写密码原文或单密码可离线猜测摘要。
- 安装器用部署账号创建目录0700；主key/子key按读取主体0600或0640，所有者为部署账号，组为该账号已拥有的部署GID。只读挂载单个key/payload文件，不为了容器访问开放宿主整个父目录。容器内tmpfs按角色读者设置0700/0750及文件0400/0440；启动器可写，原生进程只读认证文件。
- 新版本输出到临时密文目录，fsync、校验和改名后才更新.env中的bundle/key/revision路径；不得先写明文再加密。最终版本由最后一个已验证阶段复制密文并生成新的受校验manifest，角色payload内revision与最终版本一致后才发布；无需运行时解密到磁盘。

#### 4.14.3 从输入到启动的数据流

1. 原安装器获取部署锁，核对Docker权限、目录可写性、原配置状态、工具版本与环境条件。首装在收集密码前生成外置key；已有环境先使用或恢复有效key，不替换旧key。
2. 交互仍逐项选择，read -s得到的密码经stdin管道交离线工具直接加密，写入的临时文件也只能是密文；禁用xtrace，禁止把秘密放env/argv。输入取消只留下可识别并可清理的密文残件。
3. 自动化输入默认不配置，交互不被旧测试请求抢占。新自动化模式读取密文清单或stdin受控通道；v1明文文件只能走明确的旧版导入分支，原文件归属单独记录，不作为新格式长期支持或复制成新明文输入。
4. 工具在内存渲染原生文件并按角色加密。`check`和真实SDK管理均在工具进程内解密；捕获文件、完整container inspect、私有诊断若含凭据，进入sealed payload或先结构脱敏，不直接落.json/.log。
5. Compose给每个原生容器挂只读静态工具、自己的密文/子keyring及独立tmpfs。工具每次启动均验证环境、key权限、token完整性、role/revision、路径allowlist和tmpfs类型，再把完整内容原子物化到内存。
6. 静态工具完成后exec实际镜像入口，保持原参数、信号、退出码与初始化/降权生命周期；不会持有Docker权限。普通容器restart也重新经过解密入口，不依赖安装器再次运行或上次内存仍存在。
7. SDK新旧身份和依赖消费者验证成功后，按现有顺序恢复后端、Worker、前端。后端/Worker读取原字段密文，新增共享组确保其实际UID能读取主key；应用进程不增加本地明文配置文件。

启动器固定内部接口：`credential-runtime run --role <role> --bundle <sealed-path> --key-file <role-keyring> --deployment <id> --revision <id> -- <trusted-vendor-argv>`。参数均为路径/标识和可信原生命令，不包含密码。没有把任意payload内的字符串当Shell求值的入口。online写账号仍由现有独立SDK模块承担。

#### 4.14.4 逐组件适配和副作用边界

| 角色 | 内存恢复内容 | 保持的原生行为与必须检查的回写 |
| --- | --- | --- |
| MySQL | mysql.password、客户端CNF；/tmp与socket目录为受控内存 | 复用现有安全bootstrap wrapper和mysql用户降权；SQL stdin/process substitution不转持久脚本；检查general/audit/binlog配置和实际写入，不让bootstrap/ALTER明文进入受管持久日志 |
| mysql-init / Gateway初始化 | 仅该消费者需要的客户端CNF和配置 | 保持原完成依赖；不用带密码DSN argv或GATEWAY_DATABASE_PASSWORD创建环境。Gateway真实部署仍需有效许可及独立适配验收，否则预检拒绝 |
| OpenFGA迁移与服务 | 各自OpenFGA配置 | 镜像可无shell；静态工具直接exec已有原生二进制，使用内存配置路径；迁移与run均覆盖，数据卷不改 |
| Redis | 完整ACL、健康检查密码、经过核实的配置 | 保持redis UID/GID与显式补充组；aclfile/config位于内存，ACL SAVE/CONFIG REWRITE不得回写密码到宿主配置/数据路径；RDB/AOF仅保持原业务数据 |
| MinIO | root账号/密码文件 | `_FILE`仅指内存路径，保持vendor入口与原data路径；扫描`.minio.sys`与日志核实没有实际root密码原文；已有凭据元数据的密码哈希不等同明文 |
| ES | 密码文件与可写配置/keystore目录 | Bitnami setup可能写配置和keystore，整个敏感配置输出路径须在tmpfs；默认模板从精确镜像的独立未启动容器通过archive stdin送入工具内存封装，保留TLS和用户设置，不能先落宿主模板副本；仍等最终Java PID1就绪 |
| Milvus | 默认配置及user.yaml等受管敏感配置 | 保留既有完整参数、root初始化字段和MinIO对象凭据；对被tmpfs遮蔽的基础配置从原镜像受控提取，禁止因只写user.yaml而丢默认文件；检查etcd和Milvus数据卷不留root/MinIO实际密码原文 |
| Gateway | 加密完整Spring配置的内存恢复 | 去掉受管密码创建环境，保留许可与路由契约；没有合法镜像/许可/端到端证据时明确不支持，不能退回原明文配置 |
| 后端/Worker/工具 | 不物化明文业务config | 原字段解密及SDK参数保持进程内；共享组只赋予必要消费者。后端不装Docker客户端、不使用运行时编排SDK |

适配必须以锁定的实际私有镜像为准，自动捕获原入口/命令、环境、网络和数据挂载。对敏感配置路径以外的自定义include、未知镜像回写或已有外部消费者不能证明符合时，在任何账号写入前拒绝，而不是套标准参数覆盖客户配置。默认镜像里不可用的示例字符串不是本次实际客户密码，但检查报告必须区分，不把SDK源码常量误报为当前凭据。

#### 4.14.5 环境预检、权限和重启

- 部署前用同一工具镜像只读核实Docker daemon所在Linux环境。先尝试读取owner/GID和实际挂载访问，再做无秘密的密文/子key/tmpfs探针；宿主账号`id -u != 0`必须可通过。Docker已授权不等于无任何管理权限，安装器不自动追加docker组、不授予sudo。
- 第一版严格接受无活动swap、无磁盘休眠入口、可关闭进程core输出且无未经核实管道式dump收集器的环境；容器core rlimit硬/软均为0，工具还检查`core_pattern`和`suid_dumpable`。无法核实的远程daemon、虚拟机内存快照、rootless或交换/转储策略不能谎报符合，说明限制并在变更前停止；不自动swapoff或改宿主sysctl。
- 这不是防御拥有宿主root权限的主动攻击者或管理员外部快照的承诺；企业有受控加密swap/KMS时另行增加可证明适配，不用一个“我已确认”标志跳过安全检查。
- 每次原生启动工具重复运行预检，不能只在安装当天检查。tmpfs自身不跨容器共享，普通/tmp是否tmpfs必须测fstatfs，不能按目录名猜测；空间限额明确设置，写失败不执行vendor进程。
- 宿主部署目录不得要求`/root`。默认文件归属为调用者；对已由root创建的目录，在修改账号前报告路径和UID/GID，管理员一次性移交不属于普通账号能自行完成的操作。脚本不递归chown客户业务数据。
- 子key与加密版本可重建运行态；静态工具、key/payload读取及健康检查不依赖网络。服务单独restart、整栈重建都必须通过；166上不得为验证主机重启而重启共享机器，主机重启门禁使用独立虚拟机，缺该环境则明确待验证。

2026-11-14的166只读检查：无swap，core_pattern为`core`，suid_dumpable为0，电源state只有`freeze`，无UID1000～65533可登录普通账号，Docker非rootless。这些仅为环境可行性输入，不是v2验收通过。实施时由已授权管理员一次性建立隔离普通验收账号及其目录/Docker访问；之后真实部署日志证明操作UID非0且没有sudo。

#### 4.14.6 旧格式转换、历史材料和恢复

旧格式转换不是静默接受永久明文。新增内部格式版本门禁与`migration.active`，复用部署锁，顺序为DISCOVERED→SEALED→VERIFIED→CONSUMERS_SWITCHED→PLAINTEXT_CLEANED→COMPLETE；具体原生改密状态仍沿用§4.13，不合并成一条不透明成功标志。

1. 只读发现当前引用、旧inputs/source/captured-base/stages、inventory/env.before及日志；按明确目录所有权建立清单，不递归收集任意业务数据。发现不可读项在服务端写入前停止，不能遗漏后仍宣告无明文。
2. 直接从旧文件流到工具内存并写加密备份/完整v2版本，校验内存中内容等价及主key/子key可读。备份也必须加密；临时输出采用fsync+原子改名。对未知token或丢key不生成新key补救。
3. 进入明确维护窗口，暂停必要消费者，以同一真实密码切换v2内存入口并实际验证；成功前不执行运维选定的真实改密。中断后原命令识别migration.active，从加密备份恢复；不能再次生成明文目录作为应急方案。
4. 校验通过后，对脚本标记自有的旧明文副本逐项unlink并记录非敏感进度，再进行已选真实改密；外部客户输入/备份只提示归属及清理路径，需明确授权，不擅自删除。
5. 若部分切换/清理失败，保留加密备份及未完成状态、保持必要停写并提示原命令续跑。已发生的账号变化必须通过旧/新身份探测核实，不执行盲目反向SQL或整库回滚。v2配对回退只使用加密保存的强旧身份。

历史计划整体的密码/完整inspect/hash等敏感信息也封装，journal只保留非秘密阶段；禁止单密码SHA256泄露弱密码猜测面。对v1快照中曾含的任意秘密摘要，不按“已经是哈希”直接公开保留，应迁入加密payload或删除自有记录。

输入/阶段密文可按恢复保留策略管理，不以删完所有历史作为首次交付前提。普通unlink不能证明SSD/快照/旧备份安全擦除：旧密码是否失效按用户选择的真实改密验证，不自动强迫修改未选组件。报告严格区分“当前受管文件无明文”与“旧介质不可能恢复”。

#### 4.14.7 模块职责和契约影响

| 模块 | 增量职责 | 不承担 |
| --- | --- | --- |
| `secret_crypto.py` + 新`credential_artifacts.py` | 主/角色key、Fernet封装、固定身份上下文及密文检查 | Docker生命周期、业务上下文初始化 |
| `credential_inputs.py` / `credential_bundle.py` | stdin/密文输入，内存渲染与v2完整加密产物 | 生成持久明文临时文件 |
| `credential_rotation*.py` / CLI | 敏感状态sealed读写、原SDK认证/单次写及恢复 | 在后端进程导入Docker SDK；自动猜管理身份 |
| `tools/credential-runtime/` | 跨架构静态解密、环境/路径/tmpfs检查、固定适配和exec | 容器编排、在线账号改密、HTTP服务 |
| `docker/lib/credential-runtime.sh` | 公共工具提取、无秘密兼容探针、原生入口挂载 | 把密钥/密码传argv/env、安装宿主依赖 |
| `credential-install.sh` / `credential-rotate.sh` / 新迁移模块 | 原入口交互、v1迁移和v2激活，所有者/GID检查 | 系统级提权、无条件递归改数据归属 |
| Compose / 构建 / Helm检查 | 固定角色、最小文件挂载、tmpfs、core限制及产物版本检查 | 对外部明文Secret或未适配的集群宣称v2支持 |

格式是内部维护CLI的破坏性变更：v1仍有只读导入器，v2运行时拒绝v1明文；能力标识`sealed-files-v2`与既有rotation-v1并列。正式镜像必须有同架构静态工具及源码/依赖描述，旧镜像不能接新配置。`--prepare-only`不接收密码、不发起服务变更；发现v2所需能力不匹配时在改账号前停止并按原入口引导配套镜像。

已有Helm/source/systemd产物不能因为后端字段已加密就标记符合本增量。第一批实际执行以标准Linux单机Compose为主；其他入口必须增加显式v2能力校验、拒绝未经证明的明文密码挂载，并把未验证模式列为门禁，不自动套用Docker内存目录设计。DM和完整交付仍保留原门禁。

#### 4.14.8 验收与观测

| 层次 | 覆盖 | 失败判定 |
| --- | --- | --- |
| 协议单元 | 官方Fernet向量、Python↔Go互通、角色/版本替换、错key/损坏token、路径穿越、同一明文产生随机密文 | 任一认证/身份/路径约束被绕过即P0 |
| 离线集成 | 从stdin开始跟踪所有持久写入；v1输入及完整计划转换、原子激活、派生key权限、取消/中断 | 生成任何受管明文临时副本或无密钥覆盖都失败 |
| 单组件真实 | 原镜像入口、降权、初始化/改密/健康检查、tmpfs和重启、原生回写及卷扫描 | 初始化成功但改密或重启失败、不明文扫描即不得通过 |
| 非root全栈 | 新普通账号的可写隔离目录、无sudo的原命令；全保留/单项/组合/全选，重建后业务和数据保留 | 日志UID0、手工chmod/解密救场或偷偷提权均失败 |
| 故障恢复 | 原生写后/配置激活前中断、迁移切换中断、清理中断；原命令从密文续跑和配对回退 | 依赖旧明文、重复已验证写入或丢身份判P0 |
| 泄露与业务E2E | 当前/历史目录、受管卷、导出容器层、所有镜像层、日志与Docker创建元数据，匹配已知密码及定义编码；真实登录、ReBAC、知识检索和Worker | 只检查HTTP200、只检查宿主当前目录或跳过历史视为未验 |

真实166仅使用新隔离普通账号和独立项目，不在原`/root`目录强行验证非root，不改客户原部署、Docker daemon或整机电源状态。最终普通账号的手工验证仍为进入拥有权限的项目根目录执行`bash docker/install.sh`；选择与维护确认沿用现有SOP，页面URL按隔离端口实际记录。账号由夹具明确标识，不在文档写测试密码；不把自动化输入路径留作手工部署默认值。

日志只输出部署/计划标识、角色、阶段、结果及错误类别；错误不输出token/key或密码摘要。每个测试保存执行UID/GID、镜像ID、工具协议版本、tmpfs证据、扫描对象范围和通过/未运行原因。发布镜像必须重新全层扫描；166局部覆盖镜像不等同最终交付，主机重启/DM/真实K8s缺证据仍待验。

参考：[Fernet格式](https://github.com/fernet/spec/blob/master/Spec.md)、[fernet-go](https://github.com/fernet/fernet-go)、[Docker tmpfs](https://docs.docker.com/engine/storage/tmpfs/)、[Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)，已于2026-11-14核查。资料只支持协议/机制，不证明私有镜像适配成功。用户已确认本节，QA参考已补14项，新增任务T084～T117。

