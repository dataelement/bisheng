# Design: 商业授权统一到期提醒（F070）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**
> - `design.md`（本文）回答 **为什么这么实现**、三路怎么写入、聚合怎么读
>
> **关联**: [spec.md](./spec.md) · PRD《3.0 beta2》§5.3
> **版本**: v3.0.0-beta1
> **最后更新**: 2026-09-14

---

## 1. 目标与非目标

- **目标**：把 Gateway / ETL / 商业版看板三路授权收成平台级 `license_info` 的当前状态，管理后台超管 Banner 只读聚合接口，文案点名授权对象。
- **非目标**：见 [spec.md](./spec.md) 范围边界。实现上额外钉死：
  - **不反向调用 Gateway**（前端先读 Gateway，再上报后端）。
  - **不向商业看板拉授权**（看板服务自己更新对应行）。
  - **不新增过期降级**（不在 `DashboardService` / ETL 解析路径上新加拦截）。
  - **表里不存密文 / 私钥 / 设备指纹**。

---

## 2. 关键约束

遵循 `docs/constitution.md` C1–C7。本功能特有：

- **授权是部署级的，不是租户级的。** `license_info` 不得带 `tenant_id`，否则租户过滤器会让超管在子租户上下文里读不到行。
- **三路写入主体已经裁定，不能合并成「后端去拉三源」：**
  - ETL：BISHENG 调 `GET {etl_origin}/api/license_info`（ETL4LM 2.1.0-beta1 §7）后 upsert。
  - 看板：商业看板服务定期更新 `license_code='dashboard'` 那一行。
  - Gateway：前端 `GET /api/license/status`，再 `POST` 给 BISHENG 落库。
- **ETL 配置地址不是 origin。** `knowledges.etl4lm.url` 形如 `http://host:port/v1/etl4llm/predict`。授权查询必须剥到 origin 再拼 `/api/license_info`。
- **后端调不到 Gateway。** 商业版拓扑是 `浏览器 → Gateway → Backend`。F037 已否决后端 HMAC 上报；本期仍由前端转发状态。
- **展示阈值与 F037 的 severity 分档不同。** 本期只保留 `normal / expiring / expired / unknown`，30 天一条线，不再向前端下发 `warning / critical`。
- **新表走 SQLModel `table=True` + 启动 `create_all`。** 不必为整表创建单独 Alembic revision；`update_time` 用项目统一 server default。实现时错误码模块号登记 **270**（11x 是灵思；11001 是 Gateway 业务码，不是 BISHENG 模块号）。

---

## 3. 方案对比与选定

### 决策 1：授权真相放在 `license_info` 表，不放内存聚合

- **备选**：
  - A. Banner 请求时并行拉 Gateway / ETL / 看板，不落库。实现快，重启即丢，看板没有可拉的 HTTP。
  - B.（选定）平台级表做当前状态；三路按各自合同写入；聚合接口只读表（读时按到期日重算剩余天数）。
- **选定**：B
- **原因**：用户已裁定必须有 `license_info`。看板只保证写表，不保证提供查询接口。表还能让 ETL Beat 与超管刷新解耦。
- **何时该重新考虑**：三源都提供稳定只读 HTTP，且产品不再要求持久化。

### 决策 2：Gateway 由前端上报，后端不反调

- **备选**：
  - A. 后端配置 `gateway.internal_url` 自己打 `/api/license/status`。
  - B.（选定）前端已能打到 Gateway；把 `data` 原样 POST 给后端 upsert。
- **选定**：B
- **原因**：用户已裁定该路径。A 要新配内部地址，开源 / 配错都会静默失败，且是反向调用。
- **何时该重新考虑**：出现「无浏览器也要刷新 Gateway 行」的运维需求。

### 决策 3：看板只写表，BISHENG 不拉

- **备选**：
  - A. 为看板再做一个类似 ETL 的 HTTP 适配器。
  - B.（选定）看板服务定期 upsert `dashboard` 行；BISHENG 只读。本期不提供看板专用 HTTP 写入口（与用户裁定一致）。
- **选定**：B
- **原因**：本仓看板在 `telemetry_search` 进程内，但商业授权由看板侧持有，本仓没有到期字段。写表是已确认合同。
- **何时该重新考虑**：看板无法直连同一 MySQL/DM8，再补内部 HMAC upsert，复用同一 `upsert` 服务。

### 决策 4：读时按 `expire_date` 重算剩余天数和 `display_state`

- **备选**：
  - A. 展示源写入的 `days_remaining` / `display_state`。看板一天写一次时，剩余天数会停住。
  - B.（选定）有 `expire_date` 则按「今天」重算；没有则回退到存下来的 `days_remaining`。永久授权（无到期日且无剩余天数）→ `normal`，Banner 不出现。
- **选定**：B
- **原因**：阈值是日期事实，不该取决于谁最后写了一次整数。
- **何时该重新考虑**：产品改成「以源系统当时计算为准、不允许平台重算」。

### 决策 5：取源失败不把成功行改成 expired

- **备选**：
  - A. 失败则把该行 `display_state=unknown` 并清空到期日。一次 ETL 抖动，超管会看不到本仍有效或已过期的提醒。
  - B.（选定）失败只打日志，保留上次成功写入；从未成功则无行，聚合视为未取得。
- **选定**：B
- **原因**：AC-05 禁止把未取得展示成已过期；也不该因为一次超时抹掉仍可用的到期日。
- **何时该重新考虑**：产品要求「超过 N 小时未成功检查即视为未知并隐藏」，再加 `checked_at` 过期窗口。

### 决策 6：ETL 用 Beat 小时级刷新，聚合接口可补拉过期行

- **备选**：
  - A. 只在超管打开 Banner 时拉 ETL。
  - B. 只靠 Beat。
  - C.（选定）Beat 每小时拉一次（部署级，不按租户循环）；超管聚合查询时若 `etl` 行不存在或 `checked_at` 超过 1 小时，同步补拉，单源超时 2–3s。
- **选定**：C
- **原因**：Banner 不轮询；只靠 Beat 时，刚配上 ETL 的环境可能要等一小时。补拉失败不得拖垮聚合。
- **何时该重新考虑**：ETL 授权查询成为计费接口或明显变慢。

### 决策 7：Banner 可见人用平台超级管理员，不是 `role === "admin"`

- **备选**：
  - A. 维持 F037 的 `user.role === "admin"`。
  - B.（选定）前端闸门与聚合接口都用 `is_global_super`；非超管聚合返回空列表（200）。
- **选定**：B
- **原因**：PRD 写的是平台超级管理员。`role === "admin"` 在多租户里可能把 Child Admin 算进去。空列表而不是 403，避免刷新刷出错误 Toast。
- **何时该重新考虑**：产品明确要求子租户管理员也看全局授权。

### 决策 8：推翻 F037「前端只直连 Gateway 画 Banner」

- **备选**：
  - A. 保留 `LicenseBanner` 只读 `/api/license/status`，另做 ETL / 看板。
  - B.（选定）Banner 改为：先（能拿到就）上报 Gateway，再读聚合接口画统一文案。`GET /api/license/status` 仍留给 Gateway 自己的降级链路，Banner 不再单独渲染它。
- **选定**：B
- **原因**：F037 决策 1 成立的前提是「只有 Gateway 一项」。本期三项必须走同一文案和同一阈值。
- **何时该重新考虑**：无。这是对本期目标的必要推翻。

---

## 4. 系统现状（接手必读）

### 4.1 今天（缺口）

```
超管进入 platform MainLayout
  → LicenseBanner 挂载（role === "admin"）
  → GET /api/license/status          ← Gateway 自处理，BISHENG 不参与
  → severity ∈ {warning, critical, expired} 才渲染
  → 文案：「软件授权将在 N 天后到期 / 已过期」
     黄 / 红分档，不写授权名，不写到期日

ETL：knowledges.etl4lm.url 只给 Etl4lmLoader POST 解析，无 license 查询
看板：BISHENG_DASHBOARD_PRO 只是功能开关，telemetry_search 无到期字段
```

锚点：`LicenseBanner.tsx`、`controllers/API/license.ts`、`MainLayout.tsx`、F037 `GET /api/license/status`。

### 4.2 改造后数据流

```
写入① ETL
  Beat 每小时 / 聚合补拉
    剥 etl4lm.url → origin
    GET {origin}/api/license_info
    映射 → upsert license_code='etl'

写入② 看板服务
  定期 UPDATE/INSERT license_code='dashboard'
  BISHENG 不发起

写入③ Gateway
  LicenseBanner 挂载
    GET /api/license/status（silent）
    有 data → POST /api/v1/commercial-licenses/gateway
      映射 → upsert license_code='gateway'

读取
  GET /api/v1/commercial-licenses/status
    读 license_info（最多 3 行）
    按 expire_date 重算 days_remaining / display_state
    超管返回列表；非超管 []
    LicenseBanner 只渲染 expiring / expired
```

### 4.3 表与对外字段

**`license_info`（平台级，无 `tenant_id`）**

| 列 | 类型 | 说明 |
|---|---|---|
| `license_code` | varchar(32) PK | `gateway` / `etl` / `dashboard` |
| `expire_date` | date NULL | 当地日期；永久为 NULL |
| `days_remaining` | int NULL | 源返回值，读时优先用到期日重算 |
| `display_state` | varchar(16) | 写入时带上；读时重算。`normal` / `expiring` / `expired` / `unknown` |
| `source_status` | varchar(32) NULL | Gateway `severity` 或 ETL `license_type` |
| `checked_at` | datetime NOT NULL | 最近一次成功写入 |
| `extra` | JSON | 源字段子集（`version`、`usable`、`expired`…），不含密文 |
| `create_time` / `update_time` | datetime | `update_time` 用统一 server default |

一行一个模块。upsert 键 = `license_code`。看板不得改其它 code。

**读时映射**

| 条件 | `display_state` | Banner |
|---|---|---|
| 无行；或到期日与剩余天数都空（永久 / 未取得） | `unknown` 或 `normal` | 隐藏 |
| 剩余 > 30 | `normal` | 隐藏 |
| 剩余 1–30 | `expiring` | 展示即将到期 |
| 剩余 ≤ 0 | `expired` | 展示已过期 |

**ETL `GET /api/license_info` → 行**

| ETL | 表 |
|---|---|
| `expiration_time`（Unix 秒） | `expire_date` |
| `remaining_days`（已到期为 0，永久为 null） | `days_remaining` |
| `license_type` | `source_status` |
| `expired` / `usable` / `disabled` / `license_type` | `extra` |
| `perpetual` / `execution` 或 `expiration_time=null` | 到期日空，`display_state=normal` |

**Gateway `data` → 行**

| Gateway | 表 |
|---|---|
| `expire_day` | `expire_date` |
| `days_remaining`（可为负） | `days_remaining` |
| `severity` | `source_status` |
| `version` / `expired` / `checked_at` | `extra` |
| `version=pro` 且无到期日 | `display_state=normal` |

Gateway 请求/响应示例（已核实）：

```json
{
  "status_code": 200,
  "data": {
    "version": "trial",
    "expire_day": "2026-07-02",
    "days_remaining": -74,
    "severity": "expired",
    "expired": true,
    "checked_at": "2026-09-14T10:00:00.025346068+08:00"
  }
}
```

**聚合 `GET /api/v1/commercial-licenses/status`**

```json
{
  "licenses": [
    {
      "license_code": "etl",
      "license_name": "etl",
      "display_state": "expiring",
      "expire_date": "2026-09-30",
      "days_remaining": 16,
      "checked_at": "2026-09-14T10:00:00+08:00"
    }
  ],
  "checked_at": "2026-09-14T10:05:00+08:00"
}
```

`license_name` 与 code 相同，展示名走 i18n。未部署且无行的源不出现。

**上报 `POST /api/v1/commercial-licenses/gateway`**

- 需登录且 `is_global_super`
- body = Gateway `data`（上表字段）
- 只 upsert `gateway`

### 4.4 模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `bisheng/commercial_license/` 新领域模块 | 模型、upsert、ETL 同步、聚合、Gateway 上报 | 不解密、不拦业务、不写看板行 |
| Beat `refresh_etl_license` | 小时级拉 ETL | 不按租户循环 |
| 看板服务（仓外） | 写 `dashboard` 行 | 不改 `gateway` / `etl` |
| `LicenseBanner` + `license.ts` | 上报 Gateway → 读聚合 → 统一文案 | 不再按 Gateway severity 分色 |
| `MainLayout` | 仅 `is_global_super` 挂 Banner | — |
| Gateway 仓 | 保持 `/api/license/status` 与 11001 | 不负责 ETL / 看板 |

建议目录：

```
commercial_license/
  api/endpoints/status.py
  api/endpoints/gateway_report.py
  domain/models/license_info.py
  domain/repositories/...
  domain/services/upsert.py
  domain/services/aggregator.py
  domain/services/etl_sync.py
  domain/mappers.py
```

路由挂 `/api/v1/commercial-licenses`。

### 4.5 前端文案

统一样式（不再分黄/红）。多项用 `；` 连接，最后追加续期句。建议 key：

```json
{
  "license": {
    "name": {
      "gateway": "Gateway 授权",
      "etl": "ETL 授权",
      "dashboard": "商业版看板授权"
    },
    "expiring": "{{name}}将于 {{date}} 到期，剩余 {{days}} 天",
    "expired": "{{name}}已过期",
    "renewHint": "请联系授权提供方续期。",
    "businessExpired": {
      "gateway": "Gateway 授权已过期，当前无法使用该能力",
      "etl": "ETL 授权已过期，当前无法解析该文件",
      "dashboard": "商业版看板授权已过期，当前无法访问该看板"
    }
  }
}
```

去掉 `FORCE_DEBUG_VISIBLE`。11001 拦截器改为使用服务端文案或 `businessExpired.gateway`，不再写死「软件授权已过期」。`api_errors.11001` 源文件同步点名 Gateway（改 `packages/locales`，不手改 gen）。

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `etl4lm.url` 是 predict 全路径，不是 origin | 在后面拼 `/api/license_info` 会 404，`etl` 行永远不出现 | `etl_sync` 剥 origin |
| 2 | 租户过滤器会拦截所有带 `tenant_id` 的 SELECT | 给授权表加 `tenant_id` 后，子租户上下文读不到全局行 | 表不加该列 |
| 3 | F037 Banner 直连 Gateway，开源 404 | 继续只读 Gateway，ETL / 看板永远不上 Banner；开源可能打出噪声 | Banner 改聚合；Gateway 用 `silent` |
| 4 | platform 11001 拦截器丢弃 `status_message`，强制 `t('license.expired')` | Gateway 改了文案也仍显示「软件授权」 | 拦截器走点名文案 |
| 5 | ETL 已到期是 `remaining_days=0`，Gateway 可以是负数 | 按「只有负数才过期」会漏掉 ETL | `<= 0` 均为 expired |
| 6 | 看板若写错 `license_code` 会覆盖其它源 | Gateway 行被看板刷掉 | 文档钉死枚举；本仓 upsert 校验 code |
| 7 | Beat 默认按租户扫是本仓常见写法 | 授权被扫成「每个租户拉一次 ETL」 | 部署级一次，必要时 `bypass_tenant_filter` |
| 8 | `role === "admin"` ≠ 平台超管 | 子租户管理员看到全局授权 Banner | 决策 7 |
| 9 | 架构文档 11-gateway §9.1 仍写过期 `System.exit` | 按旧文档会以为进程已死、状态接口不存在 | 以 F037 + 现网 `/api/license/status` 为准 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `license_info` 表 | MySQL/DM8，一行一个 `license_code` | 看板服务写 `dashboard`；BISHENG 写 `etl` / `gateway` 并读聚合 |
| `GET /api/v1/commercial-licenses/status` | HTTP | platform `LicenseBanner` |
| `POST /api/v1/commercial-licenses/gateway` | HTTP，body = Gateway `data` | platform `LicenseBanner` |
| 错误码模块 270 | `common/errcode/`，实现时写入 constitution C5 | 上报校验失败等 |

看板写表示例：

```sql
INSERT INTO license_info
  (license_code, expire_date, days_remaining, display_state, source_status, checked_at, extra)
VALUES
  ('dashboard', '2026-09-30', 20, 'expiring', NULL, NOW(), '{}')
ON DUPLICATE KEY UPDATE
  expire_date = VALUES(expire_date),
  days_remaining = VALUES(days_remaining),
  display_state = VALUES(display_state),
  checked_at = VALUES(checked_at),
  extra = VALUES(extra);
```

看板可以只写 `expire_date` + `checked_at`，其余由读时重算。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| Gateway `GET /api/license/status` | 前端经网关访问 | 字段改名会破坏上报映射；开源 404 必须静默 |
| ETL4LM 2.1.0-beta1 `GET /api/license_info` | BISHENG 服务端访问 | 旧 ETL 无此接口 → 失败不覆盖；url 必须能剥 origin |
| 看板服务定期写表 | 同库 upsert | 看板未上线则无 `dashboard` 行，属正常 |
| `knowledges.etl4lm.url` | DB/YAML 知识库配置 | 空 = 不拉 ETL |
| `UserPayload.is_global_super` | 登录身份 | 闸门不得退回 `role === "admin"` |

`GET /api/license/status` 保留，供 Gateway 降级与本期上报；Banner 不再单独渲染它。

---

## 7. 测试与可观测

- **映射单测**：Gateway 31/30/1/0/-74；ETL `remaining_days=0`、永久 `expiration_time=null`；失败不覆盖已有行；剥 origin。
- **API**：超管看到临期 / 过期项；非超管 `licenses=[]`；无行不出现对应 code。
- **前端**：单项 / 多项文案；unknown 不展示；开源无 Banner、无 Toast。
- **手动**：构造 Gateway trial 过期 → 上报后 Banner 写「Gateway 授权已过期」；mock ETL `remaining_days=16` → 出现 ETL 即将到期句；向表写入 `dashboard` 过期行 → 同一 Banner 逐项列出；停 ETL 再刷，不得变成「ETL 已过期」（除非上次到期日已过）。
- **日志**：ETL 拉取失败、上报非法 code、剥 origin 失败打 INFO/WARNING，带 `license_code`，不含密文。

---

## 8. 后续改进 / 不打算做的事

- 看板无法直连库时的内部 HMAC upsert：等部署形态出现再补，复用 `upsert.py`。
- `checked_at` 过期窗口（久未检查视为 unknown）：本期按决策 5 保留上次成功行。
- 订阅信息服务授权、续期入口、邮件 / 飞书、看板 / ETL 新降级：PRD 排除。
- 后端反调 Gateway：与决策 2 相反，除非出现无浏览器刷新需求。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-14 | 初版 | 《3.0 beta2》§5.3 + 用户裁定：`license_info` 表、ETL 拉接口写入、看板写表、Gateway 前端上报、后端聚合查询 |
