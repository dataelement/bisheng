# Verification — 默认部署调整

日期：2026-11-17。源码基线 `0e975096fe`（开始实施前远端最新 beta1），实现分支 `codex/beta1-deployment-defaults-20261116`。没有变更主工作区、线上服务或发行镜像。

## 已完成

| 层次 | 结果 | 覆盖与边界 |
| --- | --- | --- |
| 后端组合回归 | 182 passed、2 skipped、5 deselected | 配置新旧键/空块/空地址；真实API授权与撤销；两种地址模式下SQLite+PKCE+密码学换票/续期/退出；Chat协议；真实MCP SDK并发工具/技能访问、来源拒绝；YAML与Compose环境接线 |
| 安装器 | 18项通过 | 模拟Docker CLI记录调用，不启动容器；首次默认runtime、身份独立密钥与合法Fernet key、重复运行保留、已有明确关闭、Gateway/FT组合与失败路径 |
| Helm/发行打包门禁 | 47 passed | 真实helm template与schema、默认三功能、新旧key整块优先、headless代理peer、边缘协议清理、Python wheel与npm下载策略、私有源无公网回退、原升级密钥保留和发行元数据门禁；镜像为既有测试用fixture，不是真实发布 |
| runtime-manager | 100 passed、8 skipped | 既有egress/build/Kubernetes诊断合同；真实回环出口代理与真实上游，构建测试仍按原套件跳过真实Docker阶段 |
| 真实Nginx代理套件 | 8 skipped | 新增request-origin/fixed-origin两种模式，缺少NGINX_BIN未执行；覆盖模板已准备，不能记为代理实机通过 |
| Compose真实解析 | PASS | 使用实际Docker Compose v5.5.0执行install.sh --prepare-only和verify-app-runtime-compose.sh；插值、13/17服务形态、环境变量读取点、内部网络、数据根映射及出口/编排边界全部通过；未启动容器 |
| 静态检查 | PASS | ruff format/check、bash -n、git diff --check；arch-guard无VIOLATION，有settings.py既有Fernet常量导致的RULE-7 WARNING，本次未新增该常量 |

## 后端组合选择与基线对照

在 src/backend 中运行下列选择（Python使用主工作区既有.venv，config环境变量显式指向已有本地测试配置，不复制或打印凭据）：

```bash
python -m pytest test/dsh/test_config_contracts.py test/dsh/test_optional_public_origin.py test/dsh/test_public_origin.py test/dsh/test_identity_api.py test/dsh/test_browser_config_admission.py test/dsh/test_self_service.py test/dsh/test_work_capabilities.py test/dsh/test_native_access.py test/dsh/test_native_responses.py test/dsh/test_foundation.py test/common/test_yaml_settings_loading.py -q -k 'not external and not session_pages_remain_exactly'
```

未过滤的原选择发现以下两类问题，已在干净同提交基线 `/private/tmp/bisheng-deployment-defaults-baseline-20261117` 运行相同既有文件组合对照（基线143 passed、1 skipped、1 failed、1 error）：

- `test_session_pages_remain_exactly_tenant_scoped_even_when_root_is_visible` 在基线同样失败；本次增加两种地址参数后两种均有相同基线现象。未改动其会话查询实现，不将该项记为通过。
- `test_primary_department_is_display_only_and_missing_is_null[external]` 缺少 `DSH_TEST_DATABASE_URL`，基线同样在fixture报错。过滤external与上述既有会话用例后执行本地组合。
- 2项Desktop解析器用例按原套件因缺少指定Desktop源码路径跳过；完整Desktop客户端验收未执行。

## 尚未验证的真实环境

未执行Docker拉取/启动、真实PyPI/npm下载后应用安装、宿主隔离、真实Gateway与Nginx/TLS反代、Kubernetes/CNI/CSI、MySQL/DM8中间件、浏览器/Desktop普通用户业务验收。默认开关和源码测试不替代上述运行条件。已提供QA八列参考表与e2e-checklist；安装需包含本变更的新发行镜像，修改tag不表示已构建或推送。

本地源代码验证完成；E2E整体为PARTIAL，部署/发行验收仍待环境准备。
