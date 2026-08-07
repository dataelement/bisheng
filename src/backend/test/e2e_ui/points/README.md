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
```

G-M2 uses `helpers/gm2_trigger.py`（经 AwardFacade hooks 造数）+ Portal「我的积分」UI 断言。

Failures keep screenshot/trace under `test-results/`. **Gate red → do not start the next milestone.**
