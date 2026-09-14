# Tasks: 商业授权统一到期提醒

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认（2026-09-14） |
| design.md | ✅ 已评审 | 用户确认；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 6 Wave / 20 项 |
| 实现 | ✅ 已完成 | 20 / 20 完成。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3–§4 |

---

## 开发模式

按 Wave 组织。后端映射 / upsert / ETL / 聚合 / API **先写测试再写实现**。前端 Banner 文案抽出纯函数：先测后写。Celery 任务是部署级授权刷新，**不按租户循环、不传 tenant_id**（INV-35；偏离模板「headers → ContextVar」，论证见 design 坑 7）。

---

## Tasks

### Wave 1 — 基础设施

- [x] **T001**: `license_info` ORM
  **文件**: `src/backend/bisheng/commercial_license/domain/models/license_info.py`
  **逻辑**: 继承 `SQLModelSerializable`，`table=True`，`__tablename__='license_info'`。列按 design §4.3：`license_code` PK（`gateway`/`etl`/`dashboard`）、`expire_date`、`days_remaining`、`display_state`、`source_status`、`checked_at`、`extra` JSON、`create_time`/`update_time`（统一 server default）。**禁止 `tenant_id`**。整表新建靠启动 `create_all`，不写 create-table Alembic；模型须能被启动路径 import（T012 注册路由时带上），否则 `create_all` 建不出表。回滚：删模型后 `DROP TABLE license_info`。
  **依赖**: 无

- [x] **T002**: 错误码 270 + C5 登记
  **文件**: `src/backend/bisheng/common/errcode/commercial_license.py`,
           `docs/constitution.md`
  **逻辑**: `BaseErrorCode` 子类，模块号 270（上报体非法 27001）。在 constitution C5 表**只追加一行** `270 commercial_license`，不改其它模块号。不占用 11x，不把 Gateway 11001 收进本模块。release-contract 已预登记 270。
  **依赖**: 无

### Wave 2 — 映射与落库

- [x] **T003**: 状态映射单测
  **文件**: `src/backend/test/commercial_license/test_mappers.py`
  **逻辑**: 只测纯函数，不写 mapper 实现。剩余 31→normal 不展示；30 与 1→expiring；0 与 Gateway `-74`→expired；无到期日且无剩余天数（永久 / pro）→normal。ETL `expiration_time` Unix 秒→日期；`remaining_days=0`→expired；`license_type=perpetual` 且 `expiration_time=null`→normal。映射结果不含密文/私钥/指纹字段。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-15
  **依赖**: 无

- [x] **T004**: Gateway / ETL mapper
  **文件**: `src/backend/bisheng/commercial_license/domain/mappers.py`
  **逻辑**: `map_gateway_payload` / `map_etl_payload` / `compute_display_state(expire_date, days_remaining, today)`。实现 T003 断言。论证见 design 决策 4。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-15
  **依赖**: T003

- [x] **T005**: upsert 单测
  **文件**: `src/backend/test/commercial_license/test_upsert.py`
  **逻辑**: 只测，不写 repository。mock repository。同 `license_code` 第二次写入覆盖；非法 code 拒绝；失败路径调用「保留旧行」助手时不得把 `display_state` 改成 expired、不得清空 `expire_date`。
  **覆盖 AC**: AC-05, AC-14, AC-16
  **依赖**: T001, T004

- [x] **T006**: repository + upsert
  **文件**: `src/backend/bisheng/commercial_license/domain/repositories/license_info_repository.py`,
           `src/backend/bisheng/commercial_license/domain/services/upsert.py`
  **逻辑**: `get_all` / `get_by_code` / `upsert`。`upsert_mapped` 只接受三个枚举 code。`keep_previous_on_fetch_failure(code)` 不写库。无 `tenant_id` 过滤。
  **覆盖 AC**: AC-14, AC-15, AC-16
  **依赖**: T001, T002, T005

### Wave 3 — ETL 同步与聚合

- [x] **T007**: ETL 同步单测
  **文件**: `src/backend/test/commercial_license/test_etl_sync.py`
  **逻辑**: 只测，不写 etl_sync。`http://host:8000/v1/etl4llm/predict` → `GET http://host:8000/api/license_info`。url 空不请求、不 insert。HTTP 500 / `status=fail` / 超时调用 `keep_previous_on_fetch_failure`，已有行保持。成功体按 T004 映射后 upsert `etl`。
  **覆盖 AC**: AC-05, AC-16
  **依赖**: T004, T006

- [x] **T008**: ETL 同步实现
  **文件**: `src/backend/bisheng/commercial_license/domain/services/etl_sync.py`
  **逻辑**: 读 `settings.get_knowledge().etl4lm.url`，剥 origin（design 坑 1），超时 2–3s，用项目 HTTP 客户端。不根据 url 是否存在推断授权有效。
  **覆盖 AC**: AC-05, AC-16
  **依赖**: T007

- [x] **T009**: 聚合单测
  **文件**: `src/backend/test/commercial_license/test_aggregator.py`
  **逻辑**: 只测，不写 aggregator。读表三行，按今天重算；只输出 `gateway`/`etl`/`dashboard`。无行不出现。`dashboard` 已在表中则原样纳入，**禁止**任何拉看板 HTTP 的 mock 被调用。`checked_at` 超过 1 小时的 `etl` 触发一次 `etl_sync`；sync 失败仍返回旧行重算结果。
  **覆盖 AC**: AC-01, AC-17, AC-19
  **依赖**: T006, T008

- [x] **T010**: 聚合服务
  **文件**: `src/backend/bisheng/commercial_license/domain/services/aggregator.py`
  **逻辑**: `list_license_status(now)` 实现 T009。返回字段：`license_code`、`license_name`（=code）、`display_state`、`expire_date`、`days_remaining`、`checked_at`。不新增看板/ETL 过期拦截。
  **覆盖 AC**: AC-01, AC-17, AC-19, AC-22
  **依赖**: T009

### Wave 4 — HTTP + Beat

- [x] **T011**: 聚合与 Gateway 上报 API 测试
  **文件**: `src/backend/test/commercial_license/test_license_api.py`
  **逻辑**: 只测，不写路由。超管 `GET /api/v1/commercial-licenses/status` 返回 design §4.3 字段，`display_state` 仅四档。非超管 200 且 `licenses=[]`，不 403。表空 + 无 ETL url 时超管 GET 也是 `licenses=[]`，且测试过程不发起看板 HTTP。`POST /api/v1/commercial-licenses/gateway` 超管写入 `gateway` 行；非法 body → 27001。未登录按现有鉴权失败。
  **覆盖 AC**: AC-18, AC-19, AC-20, AC-23
  **依赖**: T006, T010

- [x] **T012**: 端点 + 路由注册
  **文件**: `src/backend/bisheng/commercial_license/api/router.py`,
           `src/backend/bisheng/api/router.py`
  **逻辑**: 本模块 `router.py` 内写 `GET /status`、`POST /gateway`（`resp_200`；登录用户 + `is_global_super`）。GET 委托 `list_license_status`（含 ETL 补拉）；POST 只 `upsert` gateway。在 `bisheng/api/router.py` **只追加** `include_router`，不改其它路由。本仓不改 Gateway Java 降级白名单（AC-24）。
  **覆盖 AC**: AC-18, AC-19, AC-20, AC-24
  **依赖**: T002, T011

- [x] **T013**: ETL Beat 任务
  **文件**: `src/backend/bisheng/worker/commercial_license/tasks.py`,
           `src/backend/bisheng/worker/__init__.py`,
           `src/backend/bisheng/core/config/settings.py`
  **逻辑**: 定义 `refresh_etl_license`，任务体直接调 `etl_sync`。在 `worker/__init__.py` **只追加**该任务 import（Celery `include=["bisheng.worker"]` 靠这里注册）。在 `CeleryTask.beat_schedule` 默认补 `refresh_etl_license`，`schedule=3600.0`，task 路径 `bisheng.worker.commercial_license.tasks.refresh_etl_license`。**不传 tenant_id，不遍历租户，不恢复租户 ContextVar**（INV-35 / design 坑 7）。默认 `celery` 队列。
  **覆盖 AC**: AC-16
  **依赖**: T008

### Wave 5 — Platform Banner

- [x] **T014**: Banner / 业务错误 i18n
  **文件**: `src/frontend/platform/public/locales/zh-Hans/bs.json`,
           `src/frontend/platform/public/locales/en-US/bs.json`,
           `src/frontend/platform/public/locales/ja/bs.json`
  **逻辑**: 三语同一批 key（i18n 硬约束，故本任务 3 个文件）。按 design §4.5 增加 `license.name.*`、`license.expiring`、`license.expired`、`license.renewHint`、`license.businessExpired.*`。删除或停用「软件授权将在…」旧 warning/critical 文案，避免再被引用。
  **覆盖 AC**: AC-12, AC-13
  **依赖**: 无

- [x] **T015**: Banner 文案纯函数测试
  **文件**: `src/frontend/platform/src/test/f066LicenseBannerCopy.test.ts`
  **逻辑**: 只测，不写 `licenseBannerCopy.ts`。输入聚合 `licenses[]`，过滤 `expiring`/`expired`，单项完整句（含业务名、日期、天数），多项 `；` 拼接且无「共 N 项」，末尾续期句。`unknown`/`normal` 不进结果。名称用 `gateway`/`etl`/`dashboard` 对应业务词，不得出现「软件授权」。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-10, AC-11, AC-12
  **依赖**: T014

- [x] **T016**: Banner 文案纯函数
  **文件**: `src/frontend/platform/src/layout/licenseBannerCopy.ts`
  **逻辑**: 实现 T015 断言。输入聚合列表，输出 Banner 字符串或空（无临期/过期项）。论证见 design §4.5。
  **覆盖 AC**: AC-10, AC-11
  **依赖**: T015

- [x] **T017**: 聚合 API 客户端 + Banner + 超管闸门
  **文件**: `src/frontend/platform/src/controllers/API/license.ts`,
           `src/frontend/platform/src/layout/LicenseBanner.tsx`,
           `src/frontend/platform/src/layout/MainLayout.tsx`
  **逻辑**: 3 个文件是同一条挂载链路，不宜再拆。挂载时（无轮询）：`GET /api/license/status` `silent` → 有 data 则 `POST /api/v1/commercial-licenses/gateway` → `GET /api/v1/commercial-licenses/status`。用 T016 拼文案；统一一种样式；无关闭按钮；保留 `--license-banner-h`；去掉 `FORCE_DEBUG_VISIBLE`。`MainLayout` **只改** Banner 闸门为 `user.is_global_super`。Gateway 404 不上报、不 toast。
  **覆盖 AC**: AC-06, AC-07, AC-08, AC-09, AC-18, AC-23
  **手动验证**:
  - 超管刷新管理后台：临期/过期项出现，文案含名称+日期+天数，黄/红不再分档
  - 非超管 / 开源无 Gateway：无 Banner、无错误弹窗
  - 停留页面数分钟：网络面板无第二次聚合轮询
  - Banner 无关闭按钮
  **依赖**: T012, T016

### Wave 6 — 业务错误点名

- [x] **T018**: platform 11001 拦截器
  **文件**: `src/frontend/platform/src/controllers/request.ts`
  **逻辑**: **只改** 11001 分支。不再强制 `t('license.expired')`（「软件授权」）。优先 `status_message`，否则 `license.businessExpired.gateway`。不新增看板/ETL 拦截，不改其它 status_code 分支。
  **覆盖 AC**: AC-12, AC-21, AC-22
  **手动验证**:
  - 触发既有 Gateway 11001：toast 点名 Gateway，不再出现「软件授权」
  **依赖**: T014

- [x] **T019**: `api_errors.11001` 点名 Gateway
  **文件**: `src/frontend/packages/locales/src/api_errors/zh-Hans.json`,
           `src/frontend/packages/locales/src/api_errors/en.json`,
           `src/frontend/packages/locales/src/api_errors/ja.json`
  **逻辑**: 三语同一批改 11001。改为 Gateway 点名文案。只改 locales 源，不手改 gen / `platform/public/locales/*/api_errors.json`；改完按仓库流程生成（`pnpm --filter @bisheng/locales` 的 build / 现有 pre-script）。
  **覆盖 AC**: AC-12, AC-21
  **依赖**: 无

- [x] **T020**: client 11001 拦截器
  **文件**: `src/frontend/client/src/api/request.ts`
  **逻辑**: 继续用 `translateApiErrorMessage` / `status_message`；确认生成后的 11001 已是 Gateway 点名。不新增 client Banner，不改其它错误码分支。
  **覆盖 AC**: AC-12, AC-21, AC-23
  **手动验证**:
  - client 触发 11001：文案点名 Gateway；开源无 Gateway 时不因状态接口弹出错误
  **依赖**: T019

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策时先停下再改。

（实现中如有偏离，在此追加。）
