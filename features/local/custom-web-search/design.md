# 自定义联网搜索设计

**状态**：用户已确认设计方向并同意进入实现；独立评审问题须在实现及验证中关闭，功能尚未完成。

**规格**：[spec.md](./spec.md)

**版本**：v3.0.0；功能编号待分配
**日期**：2026-11-05

## 1. 目标与边界

在既有联网搜索工具中增加一个可通过 OpenAPI 配置的搜索服务，将请求和结果转换为现有搜索契约。首版支持一个所选操作、JSON 搜索结果、固定参数和 API Key 认证；不承诺兼容任意 OpenAPI 或多服务并行。

## 2. 约束

遵循 [架构宪章](../../../docs/constitution.md) C1–C8 和 [v3.0.0 版本契约](../../v3.0.0/release-contract.md)；联网搜索与网页读取设置互不影响。

首版接口范围：OpenAPI 3.0，单一 server，GET/POST，查询参数或 JSON body 的顶层标量字段；其他必填参数支持字符串、数字、布尔固定值，按 Schema 校验类型。拒绝无法表达的必填参数、外部引用、路径参数、文件上传及复杂嵌套请求；不静默忽略。响应必须为 JSON，结果路径定位数组，字段路径相对于数组元素，路径仅支持对象属性，不执行表达式或脚本。空路径表示响应根数组；映射字段的空路径不作为有效字段。结果需有可用 HTTP(S) 链接才能生成引用。

## 3. 决策

### 3.1 输入与输出

- 选定：OpenAPI 描述请求，管理员选择操作、搜索词参数，补充固定参数并配置结果字段路径；适配器统一转换输出。
- 备选：要求供应商实现固定毕昇协议，配置简单但无法直接接入普通搜索服务；仅导入 OpenAPI 自动识别结果，缺乏确定的语义映射。
- 依据：现有 `SearchTool.normalize_result_item` 固定输出字段，而现有 OpenAPI 解析器只处理请求参数，并不提供搜索结果语义。供应商需要更复杂参数或非 JSON 响应时重新评估范围。

### 3.2 执行和验证

- 选定：保存前校验 Schema、操作、参数和映射配置；测试和生产调用共用请求构造和响应映射逻辑。测试保留原始响应查看交互，响应先按 §4.8 进行可验证的密钥脱敏，同时展示转换结果；空数组是成功，非数组或必填映射错误是失败。保存不强制连接上游，测试不写入已保存配置。
- 备选：完全复用 `/tool/test`，但该接口执行普通工具且不做搜索结果转换；要求每次保存前在线测试会让临时断网阻止保存。将来若普通工具执行器支持等价安全边界及映射，可以重新评估复用。

### 3.3 配置与密钥

- 选定：延续联网搜索 `type` + `config` 的单服务商选择，新增 `custom` 配置；密钥在服务端加密保存，读接口只返回是否已配置，更新时区分保留、替换与清除。固定参数中不得包含密钥；认证单独配置。切换服务商保留其他配置。
- 备选：沿用现有 `extra` 中明文回传的习惯，会违反本功能密钥不回显的要求。若项目提供统一密钥服务，优先接入并重新评估存储方式。

## 4. 系统现状与拟议数据流

### 4.1 现状

`WebSearchFrom.tsx` 用于内置工具设置；`/build/tools` 的 `ToolSet` 是现有活跃入口。`bench/Subscribe.tsx` 保留历史设置对话框，但目前没有打开触发器，不能视为第二个活跃入口，也不表示已新增打开按钮。原设计的两入口范围与这一现状存在偏差，T030/T032 和 T037 的两入口验证范围待评审和用户确认；确认前不改变已确认需求。`load_tools._get_web_search` 按 `type` 取得对应配置，`SearchTool.init_search_tool` 从固定注册表构造 provider；各 provider 返回统一字段列表，`SearchTool.invoke` 序列化为 JSON。工作台、工作流及 Linsight 的网页引用处理依赖搜索结果中的链接和内容。OpenAPI 自定义工具由 `OpenApiSchema` 解析，现有 `/tool/schema` 和 `/tool/test` 处理通用工具；其能力与本设计不完全相同。

### 4.2 拟议流程

管理端选择自定义 → 粘贴或导入 Schema → 服务端解析受支持操作 → 选择操作和搜索词参数 → 配置固定参数、认证和结果路径 → 可选测试 → 校验并保存。执行时，从受权限保护的配置读取并解密凭据 → 将 `query` 和固定参数按选择位置构造请求 → 限制时间和响应大小 → 解析 JSON → 以相同路径映射并调用 `normalize_result_item` → 返回现有 `web_search` JSON 数组和引用链。

### 4.3 契约与职责

OpenAPI 输入和解析复用自定义工具现有能力：前端 `EditTool` 与 `CustomWebSearch` 共用 `OpenApiSchemaInput`；后端共用 `ToolServices.load_openapi_schema` 和 `OpenApiSchema` 的 JSON/YAML、本地引用及参数发现。搜索侧仅保留操作子集限制、搜索词选择和结果映射；URL 下载通过注入下载函数保留搜索网络策略，不另建 Schema 解析器。

| 项目 | 拟议契约与职责 |
|---|---|
| 配置 | `type: custom`，`config.custom` 保存所选 operation 的受限规范化描述、搜索词参数、固定参数、认证设置和结果映射，不保存完整 Schema；持久化前限制整个分类 extra 的 UTF-8 大小以适配 MySQL TEXT（上限 60 KiB），超限明确报错。密钥在专用表中以外部配置的专用 Fernet 密钥加密持久化，extra 和前端只见状态。原有 provider 数据结构不迁移。 |
| 运行输入 | `web_search` 的 `query: string`，保持现有调用方不变。 |
| 运行输出 | JSON 数组，每项包含 `id`、`title`、`snippet`、`url`、`source`、`siteIcon`、`datePublished`；URL 无效的结果不作为网页引用，映射错误不能伪装为空数组。 |
| 管理 API | 采用 §4.4 的专用 settings、schema 和 test 契约；原两入口提案及现状见 §4.1、§4.4。仅全局超管可管理，校验目标联网搜索预置工具及其归属，不复用仅验证登录的通用入口。 |
| 服务端适配器 | 负责受限 Schema 验证、请求构造、超时/大小限制、响应转换；不改变引用注册规则。 |
| 管理端 | 沿用现有 OpenAPI 编辑的导入、认证与测试交互及现有组件；下拉增加自定义，展示选择、固定参数、映射和测试结果。遵循三语言及设计系统规范。 |

### 4.4 专用管理 API 和 DTO（提案，路径相对 /api/v1/tool）

以下均需已登录且服务端重新检查 global super；不可仅依赖前端隐藏或通用 /schema、/test 的登录检查。服务端从可信租户上下文加载目标分类及子工具，校验 preset、未删除、真实子项 tool_key=web_search、分类归属和当前操作者权限；错误 ID、不匹配、越权 fail closed，不通过 ID 或异常泄露其他租户资源。设置类路径遵守现有 route 命名约束。请求和响应均有尺寸上限，未知字段拒绝；不接受客户端声明的 tenant_id、权限、密文或 key_id 作为可信依据。

- `GET /{tool_type_id}/web-search/settings`：返回 `{revision, enabled, type, prompt, providers, custom_secret_configured}`；providers 是该用户可管理设置的白名单化配置 DTO，custom 内是规范化 operation、query 参数、固定参数、auth 位置/名称及 mapping，不含 API Key 明文、API Key 存储密文或 Schema 中的示例 secret；另含操作声明 proof（见下方实现对照）。旧服务商字段维持原兼容语义，自定义密钥仅返回存在标志。revision 是服务端生成的 opaque 版本，非时间戳。
- `PUT /{tool_type_id}/web-search/settings`：请求 `{revision, enabled, type, prompt, providers, custom_secret: {action: keep|replace|clear, value?: string}}`；仅 replace 必须提交非空 value，keep/clear 禁止提交 value；密钥存在标志不参与写入。服务端全量静态校验后原子保存，返回新 revision 和脱敏 DTO；不进行在线测试。原 provider 配置使用现有兼容字段合并规则，不能凭前端固定枚举删未知 provider；任何失败不得部分写入。无认证配置可以 clear；需要 key 而无有效密钥的配置不得保存。冲突返回稳定的冲突码/HTTP 409，提示重新加载，禁止静默覆盖。
- `POST /{tool_type_id}/web-search/schema`：互斥的 `{content}` 或 `{url}`；使用 §4.7 安全网络策略导入、受限解析 OpenAPI 3.0，返回操作/参数候选及受限规范化描述，不读取或写入保存密钥；拒绝外部 $ref、认证内嵌、超限和不支持操作。URL 不得含 userinfo、fragment 或秘密查询参数。
- `POST /{tool_type_id}/web-search/test`：`{draft, query, secret: {action: keep|replace, value?: string}}`；keep 仅可由有权管理同一目标者使用已存 key，replace 使用一次性提交的值、不写库。服务端验证草稿并按 §4.7 访问，返回 `{status, preview, results}` 或脱敏错误。preview 保留原始响应交互并进行已知凭据脱敏，剩余风险见 §4.8；不因测试成功隐式保存或启用。

原两入口提案（范围待评审和用户确认）：`ToolSet.tsx` 的父级提交和历史 `bench/Subscribe.tsx` 对话框的 isApi 提交统一改用专用 settings 的读写与 revision；目前仅前者有活跃打开入口，后者没有打开触发器。成功才关闭，冲突/失败保留草稿并允许用户显式重载。现有 `WebSearchFrom.tsx` 白名单重建配置会丢新 provider，需取消这一丢弃行为；`ToolSet.tsx` 的配置 console.log 必须移除，状态管理不得留存明文 secret。旧 `/tool/config`、旧列表/详情及其他写入口不能绕过白名单、脱敏、版本和验证：对 web_search 必须委派同一服务及 CAS 或拒绝旧写；必须验证升级前客户端兼容性，不能保留一条无版本覆盖通路。

**实现对照（未完成独立评审）**：`web_search.py` 为每个 schema operation 生成 `proof`，实际 custom DTO 为 `{operation, mapping, proof}`；proof 为 `{key_id, ciphertext}` 的操作声明认证密封值，不是 API Key 的密文。`web_search.py` 使用独立域标签并绑定 tenant/category，测试、custom 保存和执行初始化校验 operation 的 server/method/path、参数、类型与 security。导入依赖已配置的 keyring，密钥轮换须考虑已保存 proof 的可解密性；相关兼容性与轮换仍待测试。settings DTO 可返回操作 proof，但不得返回 API Key 明文或其存储密文。API 成功响应经 `resp_200(data=...)` 包装；schema 的 content/url 互斥且当前实现拒绝所有 URL 查询串，test 的 data 为 `{status, preview, results}`。上述为源代码观察，不代表安全、兼容性或端到端验证通过。

**设置实现边界**：`web_search.py` 使用非 custom provider 字段白名单；历史未知 provider 和字段在读取视图隐藏但保存时保留，新增或修改未知项被拒绝。旧 custom 凭据无法解密时，选择 custom 失败；选择其他 provider 仅在 prompt 和非 custom 配置不变等条件下允许，默认值也可能使配置变化而触发 409。详情及恢复条件见 [运维指南](./operations.md#保存时的凭据检查)。

### 4.5 作用域、授权与并发（待确认提案）

现状是分类/工具各有 tenant_id 和共享标志，列表基于当前租户及权限；不能从 global-super 写入权限推断配置全局唯一。现行 `ToolExecutor.parse_preset_extra` 采用子工具 extra 非空优先、否则分类 extra；现行 `update_tools_extra` 按分类 ID 写分类并批量清空子项，UPDATE 不自动获得 SELECT 的租户过滤。上述是现状，不作为安全契约。

配置和密文绑定现有实际工具分类的 tenant_id 和 category ID，沿用现有当前租户工具加载和 tool/use 授权，不新建跨租户共享机制或从其他租户回退查找配置；管理员切换租户后只管理该作用域中可管理的预置分类。不能由客户端指定 owner tenant 或凭据引用；服务端从已授权实际分类确定密钥归属。现有共享工具行为不因该功能扩权或重新定义；实际共享引用能否使用独立密钥需按既有授权路径做双租户验证，不能绕过授权。

事务中按目标实际 owner + category ID 的授权范围读取并锁定分类，检查 revision 后更新配置和密钥；版本必须覆盖 enabled/type/prompt、所有 provider、密钥操作及影响执行的子项状态。比较失败则整事务回滚并返回冲突；加行锁后仍须比较版本。所有旧写路径同样经过检查；对无 revision 的旧客户端，显式拒绝并给升级提示或采用同一事务可证明的兼容协议，不得无条件覆盖。不得清空跨租户子项；历史非空子项及其密钥迁移/覆盖处置未定，先检测并拒绝该分类修改、提示管理员处理，直到明确迁移策略；对无覆盖的目标不做无范围 bulk 更新。不同 provider 的修改以最新版本为基底局部合并，仅更新明确提交字段，不会丢其他 provider，两个管理员并发有一方冲突而非最后写入胜出。

**现有兼容限制**：`gpts_tools.py` 对没有任何历史子记录（包括已删除记录）的 preset 无法安全识别类型，普通列表隐藏其 `extra`、旧配置写入拒绝，即使实际为非搜索 preset 也受影响；可识别的非搜索 preset 保持原行为。部署影响和迁移策略待核实，见 [运维指南](./operations.md#已知未解决事项)。

### 4.6 密钥存储、分发与轮换（待确认提案）

在工具域新增专用 secret 表/仓储，唯一键为 (owner tenant, category ID, provider=custom)，存密文、key_id、版本及审计元数据，不将明文或密文放在任何 category/child extra、通用 DTO 或日志。使用具域标签及 owner/category 绑定的认证加密信封，参考 `app_publish/domain/secret_security.py` 的 Fernet 模式而不直接复用其 app 专用类；切勿使用 `core/config/settings.py` 中源码固定密钥。新表由现有模型发现/建表机制处理，架构与双库兼容遵循项目规范；事务内配置、密钥和 revision 一起提交。

从部署侧提供独立 keyring（key_id → Fernet key）及 active key_id，通过部署密钥管理注入 API、Celery、Linsight 所有实例，不写入仓库、普通配置文件、日志或备份明文；配置名、部署注入机制及密钥托管运维负责人待实施前确认。密文含版本和 key_id，解密后验证信封域及 owner/category 绑定；未知版本/key、缺钥、错钥和校验失败均 fail closed，不回退其他 provider 或用空密钥。执行于 `ToolExecutor._init_preset_tool` 中在受权、选定实际有效 extra 之后、调用 `load_tools` 之前注入深拷贝内存参数，不写回 ORM、缓存、队列或日志；独立的 `bisheng_langchain` 包不得反向导入 `bisheng`。长运行实例可能持有旧密钥，只承诺下次初始化生效，失效强制终止需另议。

轮换提案：先将新旧 keyring 发至全部进程验证可解密，再切 active key；新写用新 key，使用可审计、限速、可重试的运维任务逐条重加密并与配置 revision 作原子 CAS，冲突重读重试，不输出密文或明文；完成并验证所有记录和备份恢复后，按保留期移除旧 key。备份密文数据库的同时通过独立安全渠道备份必要 keyring/版本，不同存储域、限制访问并演练恢复；密钥丢失不可恢复，需重新配置上游 key。是否已有统一 KMS、具体回滚窗口及值班机制待运维确认，不声称现有部署已支持。

**轮换现状**：上述 CAS 批量重加密任务尚未实现；`web_search.py` 和 `web_search.py` 的 `keep` 不重加密，受控流程可逐分类显式替换凭据。替换不会更新既有 operation proof，旧 proof 和保留期内备份仍可能需要旧 key；不要提前移除，演练及恢复仍待验证。具体流程见 [运维指南](./operations.md#轮换备份和恢复)。

### 4.7 内外网出站约束（待确认提案）

支持公网及企业内网，不等于任意地址：部署运维显式配置允许的私网 CIDR（IPv4/IPv6）和允许端口；初始空集合即私网不可用，部署完成授权后内网可用；由全局超管配置的搜索 origin 与导入 origin 分别授权，运行仅访问保存的搜索 origin，模型 query/上游响应不能改变目标。用户已要求公网和内网均可用，私网 allowlist 的运维入口和默认值需用户/运维确认，不能悄然只支持公网。禁止 userinfo、非 HTTP(S)、环回、链路本地、组播、未指定、保留/元数据地址，包含 IPv4-mapped IPv6 与 DNS CNAME 多地址；公网上的非全局地址若不在明确的允许私网 CIDR 中则拒绝。域名解析失败、答案为空或任何地址不合规即全拒，IP 字面量采用相同分类；使用经过审查的固定 IP 拨号、原始 Host 和 TLS SNI/证书域名验证、核对实际 peer，关闭代理环境和连接复用。禁止重定向（包括 3xx，不转发认证），每次连接重新解析、重新审批和固定；拒绝不一致和重绑定。TLS 不降级、不关闭证书验证；HTTP 内网明文是否接受需运维确认。

参考 `bisheng/open_mcp/upload.py` 的固定 IP、Host/SNI、peer 校验、禁代理及流式大小限制，不直接复用其仅对 MinIO 的私网例外；共用无反向包依赖的传输层，不能只调用 URL 形式验证，也不能复用现有 requests 默认重定向/异常正文逻辑。导入、测试、执行分别限制连接、读取、总时间及压缩后/解压后字节上限，限制 JSON 深度、结果条数和字段长度，禁止压缩炸弹。上限具体数值须在实现前按部署基线确认并写入测试；日志不含 query、URL 查询串、认证头或上游内容。

**实现对照（待验证）**：`bisheng_langchain/gpts/tools/web_search/custom.py` 将请求与分别配置的 `BS_CUSTOM_SCHEMA_ORIGINS` / `BS_CUSTOM_SEARCH_ORIGINS`、`BS_CUSTOM_SEARCH_PORTS`、`BS_CUSTOM_SEARCH_PRIVATE_CIDRS` 传入以同一 `custom.py` 为入口的隔离子进程；未配置 origin 或端口则失败。子进程以固定 IP 连接、检查 peer，并使用原主机名作 TLS SNI；拒绝非 2xx 与非 identity 编码。`BS_CUSTOM_SEARCH_CA_FILE` 显式指定 CA 文件，否则使用 Python 默认信任源；进程环境清空，不依赖代理环境。实际限制为 1 MiB 响应、5 秒 socket 超时及 20 秒子进程总超时。须验证私有 CA、无效 CA、证书域名不匹配及部署分发，不将源码存在等同于通过安全评审。

### 4.8 测试响应、敏感信息与残余风险

用户要求与现有通用工具一致，保留原始响应查看交互；服务端在返回前递归检查 JSON 的键和值及嵌套字符串，对当前请求中已知的明文密钥及 URL 编码、Base64 等可明确生成的常见编码形式做精确替换；对响应预览和映射结果都执行相同脱敏并限定体积，响应头、错误正文、请求 URL 查询串和密钥不写日志、不返回。测试覆盖直接和嵌套回显、常见编码、错误和响应头。与现有通用工具一致是交互要求，不代表现有工具已具备上述脱敏能力。

**剩余风险**：不可信上游可以拆分、任意变形或不可逆变换密钥，或回显服务端不知道的其他秘密，有限规则无法识别全部形式。用户已接受保留原文预览和已知秘密脱敏的残余风险；AC-12 已按此限定，不能宣称绝对不泄密。实现只能证明经测试覆盖的直接值及指定编码被脱敏；评审和交付须记录风险。固定参数、Schema 示例和 URL 不应包含秘密；这些约束也无法自动证明不存在未知秘密。

### 4.9 验证矩阵

- 权限：匿名、普通用户、租户管理员、global super，错误 preset/tool_key/已删除对象；两个租户各自/共享分类的列表、详情、配置、测试及 use；不越权读取 secret、导入 URL 或跨租户更新。
- 数据与并发：两入口读写与切换保留其他 provider；密钥 keep/replace/clear 与失败原子回滚；两人并发配置及密钥替换冲突；旧客户端无 revision、子项覆盖、事务失败和双库 MySQL/DM8。检查所有列表、详情、子项、日志、前端状态无自定义密钥和密文。
- 密钥：缺失/错误/被篡改/错 owner 错 category、不同进程及已初始化工具生命周期，演练滚动轮换、中断重试、备份恢复与旧钥移除；未配置密钥时受影响功能 fail closed、其他 provider 不受影响。
- 网络：IPv4/IPv6、IPv4-mapped、IP 字面量、混合 DNS、空结果、解析重绑定、真实 socket peer 不匹配、代理环境、重定向、超时、压缩与响应上限、TLS 证书和公网/授权私网/未授权私网/元数据，导入和生产共测。
- 测试预览：嵌套、URL/Base64/Unicode 编码及分片回显 secret、异常/重定向/响应头回显，验证指定可识别形式脱敏并记录无法识别任意变形的残余风险；测试失败不保存，离线保存成功，真实响应映射失败不得伪装为空结果。端到端覆盖两入口、工作台、工作流与 Linsight 的配置、执行和引用。

## 5. 已知风险

| 事实 | 影响及处理 |
|---|---|
| 现有 `OpenApiSchema` 不是完整 OpenAPI 实现，且 body 和 query 处理受限。 | 不能宣称支持任意 Schema；保存前严格判定受支持子集。 |
| `validate_destination` 只验证 URL 形式，并不证明目标地址公网安全。 | 导入、测试和正式调用都要应用一致的目标地址策略、重定向与 DNS 校验；需保留企业内网部署的可配置能力，不能简单假设该函数已防 SSRF。 |
| `ToolSet.tsx` 是活跃入口，`bench/Subscribe.tsx` 的历史对话框目前无打开触发器。 | 不得将历史代码视为已实现的第二入口；原两入口提案和验证范围待评审及用户确认，见 §4.1。 |
| 上游错误、原始响应或 Schema 中可能包含密钥。 | 对测试响应、错误和日志进行密钥脱敏；不记录认证头或完整带密钥 URL；固定参数不用于存储秘密。 |
| 现有调用方读取规范化的网页结果。 | 原样返回上游数据会破坏引用；测试及运行必须通过同一转换函数。 |

## 6. 对外契约与依赖

- 提供：不改变 `web_search(query)` 及其结果数组契约；管理侧新增或扩展解析、测试和脱敏配置能力。
- 依赖：上游服务遵守所选 OpenAPI 操作、返回可映射 JSON；配置存储需在 API、Celery 和 Linsight 进程均可读取；使用外部提供且各进程一致的专用加密密钥，缺失或解密失败时明确报错。后端 ToolExecutor 在调用独立 bisheng_langchain 包前解析密钥并注入内存，禁止反向 import 或持久化明文；不能依赖本地文件保存共享状态。
- 权限和租户：当前预置工具配置保存仅允许全局超管；新增导入、测试和写入也仅允许全局超管，并校验目标确为联网搜索预置工具。执行保留 ToolExecutor 的 tool/use 授权，沿用现有子工具配置优先于分类配置的选择规则；不新增未经验证的跨租户配置读取。读写作用域须以实际预置工具数据模型及业务授权测试确认，批量写入不能依赖 SELECT 租户过滤。
- 网络：用户确认支持公网和企业内网；仅全局超管配置的明确服务地址可被访问，禁止自动重定向及代理环境变量，禁止访问环回、链路本地和云元数据地址。连接前校验全部解析地址，固定连接 IP 并保留原 Host/TLS SNI、校验对端地址；域名解析变化后重新校验。Schema 导入、测试和运行共用同一策略；测试覆盖 IPv4/IPv6、重绑定、混合 DNS 和敏感地址。出站采用有限超时和响应体大小，错误不回传 URL 查询串、上游正文或凭据。

## 7. 验证与可观测

单元测试覆盖 Schema 子集、参数类型、映射、空结果、错误和脱敏；接口测试覆盖授权、配置更新与密钥保留；覆盖两种 UI 入口和切换；工作台、工作流、Linsight 覆盖规范化结果与引用。人工验证使用受控的 OpenAPI 搜索服务，依次导入、填写固定参数、测试、保存、重新打开、搜索及检查引用；错误、超时和空结果分别验证。日志只记录失败类别和耗时，不记录查询词、凭据及原始响应。

本地测试入口及部署验收步骤见 [运维指南](./operations.md#上线验证)；已报告的命令选择与结果及其局限见 [本地验证记录](./verification-local.md)。SQLite、mock 和局部测试不能代替 MySQL/DM8、真实跨进程授权、网络、证书、部署及完整 E2E 验证；本次文档同步未重跑测试。

## 8. 待落定

- 正式功能编号及发版线登记。
- 历史子项覆盖处理及企业内网授权网段的运维配置需按 §4.5 和 §4.7 落实；用户已接受的预览脱敏残余风险见 §4.8，仍需评审和交付记录；不能使用源码中的固定 Fernet 密钥作为安全凭据。
- 不支持复杂请求体、分页、非 JSON、任意脚本和多搜索服务并行；有明确服务需求再扩展。
