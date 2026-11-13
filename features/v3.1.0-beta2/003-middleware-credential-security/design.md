# Design：中间件密码与配置加密治理

**关联**：[已确认 spec](./spec.md) · [HTML 方案](../../../docs/中间件密码与配置加密治理方案.html) · [版本契约](../release-contract.md)
**版本**：v3.1.0-beta2 / F003。**更新**：2026-11-12。
**状态**：正式设计已确认；运行时、配置包/CLI、Compose/Helm 和存量维护代码已实施。本地验证通过，真实私有镜像、双 DB 和业务/恢复验收待执行；任务状态以 tasks.md 为准。保持当前分支与工作区。
**核查基线**：`feat/3.1-beta2` / `285bfde44d`。当前获准只读检查部分缓存上游镜像；Docker daemon 不共享本机 bind 路径，隔离容器创建随后超时并已清理。未执行客户实际改密或部署，不将源码/上游支持当成交付验收。

## 0. 当前最高优先级修正：部署无感（2026-11-12）

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

在现有配置与部署链路中增加客户独立外置密钥、统一密码解密、凭据配置准备/检查，以及可恢复的存量迁移。实际账号改密由显式运维步骤执行，应用加载配套配置后重建连接。

不新增业务 HTTP API，不改变账号权限、业务及租户归属，不强制 Vault/KMS，不提供密码热更新或零停机保证，不通过关闭认证、删数据恢复连接。只迁移当前共用加密工具保护的数据。

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
- **重新考虑条件**：客户要求所有部署秘密静态加密或已有统一 KMS，再替换密钥提供层，不改业务密码契约。

### D2：配置准备与实际改密分离

- **备选**：安装时自动改所有账号；人工重复修改每个消费者；生成配置包并显式切换。
- **选定**：离线生成未激活配置包，检查只读，真实改密走原生管理 runbook。
- **原因**：初始化不等于存量改密，Milvus 失败响应还可能已写入密码。配置包减少 OpenFGA、Gateway、Milvus 对象存储等联动遗漏。
- **重新考虑条件**：具有经过验证的独立管理身份、幂等改密和协调协议，再评估自动控制面。

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

真实账号改密、独立密钥轮换是维护变更；底层CLI生成产物仍不会自行激活，也不代替组件管理接口。


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

密码文件最多去掉一个结尾 LF/CRLF，保留前后空格；拒绝空值、内嵌换行/NUL、占位符、已知默认弱值以及超对应组件限制的输入。合法特殊字符交给各格式序列化，不用统一 Shell 转义或 percent-encoding 代替。长度按锁定版本验证，不猜测统一密码长度政策。

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

### 4.9 Helm、源码与多节点

- Helm 使用 `credentials.existingSecret` 与 `credentials.configRevision`。客户在集群外准备 Secret 的 `fernet-keys.json`、`config.yaml`；三个 Python Deployment 只读挂载同 Secret，YAML 挂载到原默认路径，key 指向 /run/secrets/bisheng-fernet-keys.json。
- 旧 middleware/config values 拒绝并提示迁移；连接参数集中在外部 Secret 的 YAML，Nginx 非秘密地址移到 frontend.objectStorageEndpoint/objectStorageSharepoint。本次 MinIO 密码不再由 values 生成，Milvus/ES 密码不进入普通 env。发现旧秘密 values 时渲染报迁移错误，不默认继续生成明文 Secret。
- 未纳入范围的 Gateway HMAC、独立 sandbox token 模板等不顺带迁移，不因名字相近就混进共用 Fernet 环。
- configRevision 不含秘密，用于显式 rollout；external Secret 不能假设 Helm 自动 hash 内容。改 Secret 后更新 revision 并重建全部相关 Deployment。
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
| Compose/install/credentials.sh + lib/credential-install.sh / credential-migrate.sh | 原入口引导、锁/状态恢复、新装编排、授权存量迁移及路径挂载 | 不source客户文件，不自动改真实账号；不停止未知节点 |
| Helm | external Secret 和 revision rollout | 不生成客户 key，不修改外部中间件 |

### 4.11 构建产物与密钥隔离

在后端构建目录新增 .dockerignore，至少排除本地 `bisheng/config.yaml`、`.env`、`.env.*`、`secrets/` 和 `.generated/` 等非发布输入；秘密文件仍必须放在构建上下文外，不能只依赖文件名匹配。离线准备产物不复制到 src/backend，镜像仅包含配置模板与工具代码。

发布检查同时扫描交付源码、最终容器文件系统和镜像各层；不因新 COPY 覆盖了路径就认为下层内容消失。若基础镜像包含旧固定密钥或真实客户配置，重建干净基础镜像后才能交付；不能仅在上层删除文件。扫描只报告文件/层位置及类别，不输出秘密内容，不将待匹配的真实 key 写入测试源码。

### 4.12 实现补充与边界

- 测试 conftest 在业务 premock 导入前提供临时测试配置/key，与生产引导隔离；旧数据库环境来源缺字段时也校验，YAML和运行环境冲突拒绝；prepare物化后目标检查不沿用旧源覆盖。外部DM配置包不强制要求MySQL原生文件。

- `credentials.sh --image IMAGE [--network NETWORK] <命令>` 只使用本地工具镜像；输入清单/密码文件放同一安全目录，输出父目录独立。离线 network none，online 必须显式网络；远程 daemon 必须拥有所引用宿主路径。CLI 可直接在源码/配套镜像中运行。TLS 证书路径要额外显式挂载，标准安装器面向当前单机 HTTP 拓扑，不自动套用客户集群/TLS override。
- 新装需要配套镜像先可获得；正式安装先以离线help探测工具入口，发现旧镜像时原入口引导填写配套镜像地址，非交互明确停止；prepare-only 不拉取。正式安装先获得工具镜像并静态校验，再启动原生组件；等待 liveness 后只做一次认证检查，避免启动阶段反复尝试错误密码。API/Worker 显式 force-recreate，Worker 中的 Beat/Linsight 一并重建。
- 标准 Compose 使用 default Redis 原有全权限语义。增量 Redis 改密保留旧 ACL 的命令/key/channel 权限及其他用户，仅换目标密码；带引号/转义的复杂 ACL 拒绝自动转换。Gateway Redis 配置从旧包保留后只替换密码。外部 Sentinel/Cluster/自定义初始 ACL 仍需专项适配验收。
- Milvus override 挂载 `/milvus/configs/user.yaml`，增量 MinIO 只改其中对象凭据，增量 Milvus 只改登录安全字段，保留其他原生参数。token 与 user/password 冲突拒绝，真实账号不随改密变更。
- 缓存上游 Bitnami ES8.12 支持 ELASTICSEARCH_PASSWORD_FILE；单机 HTTP 模板显式启认证及对应 TLS 开关，客户请求 TLS 时不自动关闭。MySQL 原生客户端继承 pool SSL 的 CA/cert/key 与校验模式；OpenFGA tls=true 使用 Go 信任根，私有 CA/双向 TLS 必须另外提供并验证，不能推断它与 Python 的文件挂载自动相同。
- `check` 同时比较 MySQL client/OpenFGA、Redis ACL、MinIO user/password 与 Milvus对象凭据、Milvus native登录、Gateway Redis等已知消费者的配置一致性；不会用这些静态比较宣告服务器已实际改密。
- `adopt-key`/`key-rotation` 不接受新密码 inputs。adopt 记录 pending，不通过普通安装器的全量 enforce 激活原生认证；在停写窗口完成静态/DB密文迁移与缓存清理后，以 --no-deps 重建现有应用，真实组件治理另做。
- 构建扫描覆盖源码、镜像元数据和每层内容，识别 lower-layer 残留；真实交付镜像档案缺失时保持发布门禁未完成。
- 直接维护脚本默认 dry-run，精确目标/跨租户显式授权。前向 resume 已实现；反向恢复由 DBA 按备份、租户与当前字段值核对执行，不提供盲目整库恢复。

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

本地自动化、Compose 静态渲染与 Helm 实际渲染已执行。上游 ES password-file/原生脚本、Milvus user.yaml、OpenFGA 配置加载机制已核查；私有镜像、双 DB、真实业务及回滚未完成，不标记交付完成。镜像机制验证是实现早期的放行门禁，业务写入与恢复演练是交付门禁。

## 8. 后续改进与不实施项

- Vault/KMS 或全持久化秘密加密：客户明确要求/已有基础设施时另行接入，本次接受受控明文 Secret。
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
