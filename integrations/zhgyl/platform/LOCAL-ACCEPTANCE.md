# 本地五场景运行与验收接线

以下为隔离合成验收配置，不迁移 D 业务数据或业务服务凭据；获准模型配置单独保存在仓库外私密目录。五模块最新交接源码已纳入本仓库并重新生成运行包。当前 API 直测与直接运行固定 Skill 脚本，不等于真实平台 Agent 已选中、读取并执行 Skill。

## 当前运行入口

- 活动源码：本仓库 `integrations/zhgyl/`。
- 当前业务运行目录：`/Volumes/SSD/zhgyl302/business-20261126-final`；私有目录 0700、凭据 0600，不进源码包。六服务已切换，最新真实 HTTP 及订单同源代理复测通过；工具/模型注册、Skill 导入和真实 Chat 仍待原生登录。
- 本地平台：`http://127.0.0.1:13001`，API health 为 OK；独立 Celery/Beat、Linsight 消费进程与双沙箱已起。两个沙箱实际 copy-in→UID10000执行→产物下载→释放通过，子进程无服务令牌，释放后 exec/files 返回404。
- Docker daemon：`colima-zhgyl302`，socket `unix:///Volumes/SSD/zhgyl302/colima/zhgyl302/docker.sock`。不要全局切换 context。
- 独立网络 `zhgyl302_isolated`，主平台也加入此网。
- 生成器拒绝覆盖已有目录。生成随机本地凭据、合成快照、合成名录、Skill 资产和五个 zip；不读任何 D snapshot/private 文件。

```sh
python3 integrations/zhgyl/platform/seed_local_acceptance.py --runtime /your/new/private/runtime
# Registry login config has no contexts; use explicit host. Standalone compose
# binary avoids plugin discovery being affected by the isolated DOCKER_CONFIG.
ZHGYL_RUNTIME=/your/new/private/runtime \
DOCKER_CONFIG=/Volumes/SSD/zhgyl302/registry \
DOCKER_HOST=unix:///Volumes/SSD/zhgyl302/colima/zhgyl302/docker.sock \
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose -p zhgyl302-business \
-f integrations/zhgyl/platform/local-business.compose.yaml up -d
```

| 服务 | 宿主 loopback | 容器地址/挂载 |
|---|---|---|
| 采购 Mock API | `28768` | `http://procurement-api:18768`；采购快照和随机凭据只读 |
| 运输历史 | `28769` | `http://transport-api:8080`，别名 `bs-d-transport-api`；revision4 合成快照只读 |
| 报关历史 | `28770` | `http://customs-api:8080`，别名 `bs-d-customs-api`；revision4 合成快照只读 |
| 运输原生 API | `28771` | `http://transport-native-api:8080`；独立可写 `/state` |
| 预测 v0.8.0 | `28786` | `http://procurement-forecast:8786`；源码及合成 assets 只读，可写 `/runtime` |
| 订单数据 | 不发布 | `http://orders-data:8080/api/zhgyl/orders`；与订单 Skill 共用合成 `orders.json` |

运输/报关历史服务的兼容 DNS alias 只存在于本隔离网络；现有取数器仍校验固定 private origin。没有放宽任意 URL 访问。订单 API 需要本地随机 `X-Zhgyl-Data-Key`，不支持写入；将运行目录 `orders-nginx.conf` 合入本地前端 Nginx，代理负责注入，前端不获取该 key。整个前端宿主入口也必须只绑定 loopback。该接线只用于合成验收，不构成生产用户鉴权方案。

## 平台注册和 Worker 必需项

1. 使用新平台管理员会话，通过 `POST /api/v1/skill` multipart 字段 `file` 依次上传运行目录 `skill-bundles/*.zip`，用 `PATCH /api/v1/skill/{name}/status`、JSON `{"enabled":true}` 启用。五个名称为 `procurement-history`、`transport-native-api`、`customs-history`、`order-tracking`、`procurement-forecast-fast`。它们均将 `SKILL.md` 放在 zip 根部；采购、订单和预测包只带生成的合成 assets。`check_skill_bundles.py` 使用实际 3.0.2 纯函数验证解包、名称、frontmatter 和内容哈希；HTTP 权限、MinIO 存储与发布仍需在平台实际验证。
2. API 工具先 `POST /api/v1/tool/schema`，body 的 `file_content` 为对应 OpenAPI JSON 字符串；将返回结构补齐鉴权后 `POST /api/v1/tool` 正常注册，不直接改 SQL ID。新平台会分配新 ID 和 `tool_type_{groupId}_{md5(operationName)}` key。
3. 采购工具 `operationId=query_procurement_history`，服务根 `http://procurement-api:18768`，固定 POST 路径 `/openapi/tic-definition/integrationInterface/call?functionCode=mock_procurement_history_v1`。Worker ENV 设置 `PROCUREMENT_API_ORIGIN`、`PROCUREMENT_NATIVE_TOOL_ID`、`PROCUREMENT_NATIVE_TOOL_KEY` 为可信部署注册结果；后两个默认 D 的 44/key，仅为兼容。ID/key/origin/path/POST 任一不匹配仍拒绝，原 `ToolExecutor` 的 ACL/账号检查保留。前端按 operationName 在权限目录发现工具，不能照搬 group21。
4. Worker 将外置 `private/procurement/` 整目录挂到 `/app/data/procurement-private`，仅该目录允许本地 token cache 写入。父目录 0700、client.json 0600，所有者 UID 必须与 Worker 一致。不能通过放宽检查解决挂载属主错误。
5. 报关 Worker 只读挂载本仓库 `services/customs-history/` 到 `/app/customs-runtime`、外置 `private/customs/client.json` 到 `/app/customs-private/client.json`；Skill 选择 `customs-history` 并绑定实际可用的代码执行器。当前运输主路径不需要旧 `transport-history` Skill 或代码执行器。
6. 运输原生工具 `operationId=transport_execute`，根 `http://transport-native-api:8080`，POST `/transport/execute`，仅 `request_json` 和 `context_id` 两字符串参数；API Key 配置为 `Authorization: Bearer <本地随机运输token>`，与运行目录 transport-native.env 一致。工具须加入前台可选范围。Skill 返回完整 `answer`，详情沿当前 `context_id`。
7. 预测工具 `operationId=forecast_execute`，根 `http://procurement-forecast:8786`，POST `/api/skill-execute`，唯一参数 `request_json` 字符串。注册后把实际 key/model ID 写外置 `forecast.env` 中 `FORECAST_NATIVE_TOOL_KEY`、`FORECAST_NATIVE_MODEL_ID`，仅重建本地预测容器。`FORECAST_PLATFORM_BASE` 必须为预测容器能访问的本地主平台地址；`FORECAST_AGENT_BASE_URL` 为平台工具能访问的预测地址。合并交接 `forecast/bisheng-nginx.conf` 的两个同源代理路由。预测 source/Skill 哈希与导入版本要一致。
8. 模型和沙箱由主平台接线。采购/报关/订单依赖真实隔离代码执行器，模型不能访问私有凭据。`GET /api/v1/tool/sandbox_conf`、`POST /api/v1/tool/sandbox_conf` 可配置沙箱；前台模型与工具范围分别通过工作台配置 API 管理。D 预测专用模型关闭长推理、max_tokens4096；新平台用用户授权迁移的真实模型配置，不复制 D 数字 ID。

## 可直接发送的场景输入及预期

| 场景 | 完整用户输入 | 合成验收预期 |
|---|---|---|
| 采购 QPL | `DEMO-QPL-001有哪些历史供应商？本次甲方空客，按历史最低单价升序展示。` | 2条历史、合成QPL甲100与乙120 CNY/件；显示合成名录来源，不声称真实QPL资格 |
| 采购 QSL | `DEMO-QSL-001有哪些历史供应商？本次甲方商飞，按历史最低单价升序展示。` | 2条历史、合成QSL甲80与乙90；不混入QPL主体 |
| 采购确认/撤销 | 上轮后发 `将合成QPL供应商甲记录为本次询价对象。`，再 `查看本对话确认记录。`，最后 `撤销确认记录<刚返回的完整记录号>。` | 只写该Chat确认台账；撤销追加事件；不下单、不发送 |
| 采购近似 | `查询DEMO-NEAR-999的采购历史。`，核对提示后 `型号确认无误，请查近似型号。` | 精确0条须先核对；限定正则召回001/002，选择后分别展示，不跨型号比价 |
| 运输历史 | `查分单 DEMO-TRN-001 的历史运输费用。` | USD1500共享账单、完整2分单覆盖、金额只计一次不分摊；普通历史不附推荐 |
| 运输询价 | `为一票运输推荐运输方案：JFK到TFU，型号683-3-2/X-310A，毛重120KG，包装长107CM、宽61CM、高61CM，空运，危化品。请给出推荐排序、首选方案和历史费用参考。` | 甲/乙两个候选与费用依据；历史参考不等于正式报价 |
| 运输续问/错误 | 原Chat发 `查看F01详情。`；新Chat单独发 `查看F01详情。`；另发 `推荐运输方案，起点JFK。` | 原Chat正确详情；无context拒绝且结束；缺字段最少澄清且结束，不生成费用 |
| 报关历史 | `查分单DEMO-CUS-001以前谁办的报关、花了多少。` | CNY1305单一报关费、1/2明细、2分单覆盖；费用只计一次；普通历史不附推荐 |
| 报关询价 | `推荐报关代理：目的港PVG，型号BMS10-146 TYPE I，毛重100KG，包装100×80×60CM，数量1，危化品。` | 合成代理甲/乙；毛重口径、完整共享范围，不分摊 |
| 报关续问/缺条件 | 原Chat发 `查看F01详情。`；新Chat发 `推荐报关代理，目的港PVG。` | 详情包括DEMO-CUS-002、单一报关费1305；缺条件澄清，不算无历史 |
| 预测正常 | 在预测页明确选择 `189A1002-1，全部客户，2026-12起，2个月`，确认生成分析 | predicted；真实Agent读取Skill并prepare/finalize；后台独立核验后才生成HTML/MD/JSON |
| 预测稀疏/无历史/有效零 | 分别选择 `BACB30YP8K9`、`DEMO-NO-HISTORY`、`ZERO-PRED-001`，其余同上 | unpredictable保留历史；no_history不伪造需求；有效零仍predicted且数量0 |
| 订单 | `查看订单DEMO-ORDER-001的物料、金额与付款交付结算日期，以2026-11-26为基准。` | 1000CNY、1条物料、三节点2026-11-29；不能把日期已过说成未付款 |
| 订单提醒 | 同Chat发 `将这单的交付提醒改为7天后。` | 生成待确认链接，未保存/未发送；页面人工保存仅该标签页sessionStorage |

## 最新合成数据覆盖

- 运输保留 `DEMO-TRN-001..003` 原身份、关联和金额，新增 `ELC24018561`，合计4明细/3账单。ELC为2024年合成运输，覆盖旧快捷历史示例；所有记录有毛重120KG、尺寸与主分单。净重100KG、包装数量及开票日期只为旧表合同兼容，禁止用作本期询价条件；新增记录没有模拟报价时间。
- 报关保留 `DEMO-CUS-001..003` 身份、共享范围与1305/1600金额，改为单一 `customs_fee_amount`，不再生成旧20项费用拆分。新增 `DFS26080009`（420）、`DEMO-CUS-ZERO`（0）、`DEMO-CUS-MISSING`（字段缺失），合计6明细/5费用单。0是有效金额，缺值显示未提供，不能互相替代；普通历史不自动推荐代理。
- 订单保留 `DEMO-ORDER-001..003` 所有原值，扩展为24条、4个合成供应商，新增型号 `26DMAC`/`ZDA601US`。以2026-11-26为显式验收基准，覆盖过去/当天/7天内/30天内/更远/缺失日期，多物料、多发票、多结算日期与明确订单切换后的上下文清理；页面和Skill读取同一文件。
- 上述标识只用于命中已有首页示例，全部业务内容均由生成器构造；不代表D历史记录、供应商资质或真实客户订单。

## 验证命令与证据边界

```sh
src/backend/.venv/bin/python integrations/zhgyl/platform/check_skill_bundles.py --runtime /your/runtime
src/backend/.venv/bin/python integrations/zhgyl/platform/verify_local_business.py --runtime /your/runtime --output /your/runtime/http-results.json
docker --context colima-zhgyl302 exec zhgyl302-business-orders-data-1 python /service/check_http.py
# Once the real native run is independently verified, append
# --verified-report-id <actual 32-hex run id> to download all three report formats.
```

HTTP 驱动验证采购 token、精确/正则/空结果、QPL/QSL固定脚本确认撤销、运输和报关共享账单/询价/详情/失败反馈、预测四分支和503。未经真实原生回执核验的预测报告必须404；驱动不会伪造原生任务或调用 verify 来冒充已生成报告。订单容器内真实HTTP检查403/200/405；同源代理完成后再传 `--orders-proxy-base http://127.0.0.1:<前端端口>` 校验页面与Skill共享数据。

首次本地容器验收中，上述四组API检查及订单容器HTTP检查通过；真实平台注册、模型与沙箱、五场景Chat、预测真实报告和浏览器仍由主 Agent 继续。最新 Runtime 已按新合同生成后仍须重跑 HTTP、平台注册、原生 Chat 与浏览器；旧 runtime 的通过记录不能外推。

## D 只读核验记录（2026-11-26，范围收口前的交接基线）

范围收口前核对的 D 运输历史/报关历史 server.py与contract.py、运输原生service.py与交接基线逐字节相同。D预测Skill.md SHA256 `bc00f498432869c9758b8149543b9c2a4a063d09f39f615348ab41dd4a124803` 与交接基线相同；server.py当时差异只在去掉D硬地址、由环境变量派生本地地址。之后已吸收用户批准的五模块业务改动，不能据这些旧hash宣称当前引擎仍与D完全相同。采购API是D宿主Python进程18768，其他业务为独立容器；也不能把交接源码hash说成D对象存储完整包hash。

项目已发布证据：采购2026-11-20发布回执为Skill5/content_hash `35fd71d3a26388ba6ce542e4c0bae3a7ca2b515496c4cd42a7b2362324da9379`；订单2026-11-19为Skill8/content_hash `8617f1fd893007d1303093aa00375ef9bf9b5f478270fd9c7878e2c83b9ee266`，订单Skill.md逐字节一致。运输原生2026-11-19已发布，旧干净平台参数schema缺陷由本轮OpenAPI properties修复覆盖。报关2026-11-20文件夹虽有“发布”字样，README明确publish_D.py未执行，因此未纳入其分页候选。

没有复制D数据库、运行目录、业务快照或名录；当前运行仅用生成器的合成资产。获准模型连接参数留在仓库外私密目录，未进入源码、补丁或交付包；没有复制D业务服务凭据。
