# 看板 component/query 对拍

对比 171 当前接口和更新后的 `bisheng-backend`。不改看板配置，不改 MySQL / Elasticsearch 业务数据。

## 前提

- 本机 `src/backend/bisheng/config.yaml` 指向 171 的 MySQL，用来给 `user_id=1` 签短期 token
- 接口地址用 171 后端 `http://192.168.106.171:7860`。平台入口 `10.171.0.30:30335` 会把这张短期 cookie 判成 400。

## 命令

在 `src/backend` 下执行。

采集当前线上基线：

```bash
PYTHONPATH=/Users/lkk/workplace/bisheng/src/backend \
config=config.yaml BISHENG_E2E=1 DASHBOARD_QUERY_MODE=capture \
  .venv/bin/python -m pytest ../../e2e/dashboard-component-query/test_query_parity.py::test_component_query_parity -q --tb=short
```

更新 `bisheng-backend` 后再重放：

```bash
PYTHONPATH=/Users/lkk/workplace/bisheng/src/backend \
config=config.yaml BISHENG_E2E=1 DASHBOARD_QUERY_MODE=compare \
  .venv/bin/python -m pytest ../../e2e/dashboard-component-query/test_query_parity.py -q --tb=short
```

基线写在本目录 `baseline.json`。当前已经 502 的图，新版本必须返回 200，且 `value` 是列表。其余请求的状态码、维度、数值、合计和展示名必须一致。
