# F070 Points — Playwright Gates

Headless Chromium acceptance for milestones **G-M1 … G-M5**.

## Environment

| Item | Value |
|------|--------|
| Middleware | `192.168.106.171` (MySQL/Redis/Milvus/ES/MinIO) — do **not** start local docker middleware for points 联调 |
| Apps (local) | Backend `:7860`, Portal BFF `:8010`, Portal `:5173`, Platform `:3001`, Client `:4001` |
| Admin user | `E2E_POINTS_ADMIN` (default `admin`) |
| Normal user | `E2E_POINTS_USER` (default `gzx01`) |
| Password | `E2E_POINTS_PASSWORD` (required; local shared password via env only) |

## Setup

```bash
cd src/backend/test/e2e_ui/points
npm install
npm run install:browsers
npm run test:list
```

## Run a Gate

```bash
export E2E_POINTS_RUN_GATES=1
export E2E_PORTAL_BASE_URL=http://127.0.0.1:5173
export E2E_POINTS_PASSWORD='…'   # local shared password
npm run test:gm1
npm run test:gm2   # needs points.enabled=true + G7 rule
npm run test:gm3   # Platform :3001 + Portal 首页榜 / 我的积分排名
npm run test:gm4   # beneficiary + R* deduct + rules modal
npm run test:gm5   # 串行 gm1–gm4 + 对账/开关负例/入口冒烟（发布前）
npm run test:gm5:only  # 仅 G-M5 本文件
```

统一数据工厂：`helpers/factory_trigger.py`（`runFactory`）覆盖 G2/G3/G4/G7 造数、对账、`enabled=false`、schema 检查。

G-M2 uses `helpers/gm2_trigger.py`（经 AwardFacade hooks 造数）+ Portal「我的积分」UI 断言。

G-M3 uses `helpers/gm3_trigger.py`（排行快照刷新 + org_level 只读级联校验）+ Platform「设为公司根」入口可见性 + Portal 三 Tab 榜 / 排名。

**共享库安全**：`set-company-root` 会清空整租户 `org_level` 再级联。默认 Gate **不调用**；仅当同时设置：

```bash
export E2E_POINTS_ALLOW_ORG_MUTATE=1
export E2E_POINTS_COMPANY_DEPT_ID='<dept_id>'   # 业务 dept_id 或内部 id
```

才会跑可选打标用例。可选环境变量：`E2E_PLATFORM_BASE_URL`（默认 `http://127.0.0.1:3001`）。

Failures keep screenshot/trace under `test-results/`. **Gate red → do not start the next milestone.**
