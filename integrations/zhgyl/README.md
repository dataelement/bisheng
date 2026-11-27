# 中航 3.0.2 本地集成候选

平台基线：官方 `v3.0.2` / `hotfix/3.0.2`，提交
`81071da7ec5a30c1528a111db12bcf175af84471`。
公司定制源：`feat/zhgyl-3.0.0`，提交
`46b8c93d9e67de8ca663464698d5a45f2cccc6b0`。
D 代码交接源：`AlexLiu0130/aviation-ai-workspace` 的
`5eae5b47505b6b3ce4254884a9258cc055d9b523`；首页素材和导航补入 2026-11-26 已发布增量。

已吸收 2026-11-26“中航采购场景”交接的五模块范围收口。隔离本地平台、六个业务服务和双代码沙箱已运行；当前仍是待评审源码，登录后的真实模型/Skill、三条上传链和完整界面对照尚未验收。没有提交、推送或创建远端分支，未改 D。

## 内容与归属

| 内容 | 位置 |
| --- | --- |
| 公司 DocFlow / ZIP / 安全 / 部署前缀 | 保留在原平台源码；见 `docs/zhgyl-merge-playbook.md` |
| D 三参谋、示例、订单与预测入口 | `src/frontend/client/src/components/zhgyl/` 及现有组件接线 |
| 最新首页素材、无业务数据的订单视图 | `src/frontend/client/public/zhgyl/` |
| 固定工具、回执落盘、续期和终态修复 | `src/backend/bisheng/linsight/` 与 OpenAPI 参数处理源码 |
| 独立服务 / Skill / 预测 / 源测试 | 本目录 `services/`、`skills/`、`forecast/`、`tests/` |

未加入旧前端编译包或 JS 字节偏移补丁。订单视图默认空数据；真实订单、名录、客户库、凭据、令牌缓存和运行目录不在源码内。预测样例由 `forecast/seed_fixtures.py` 显式生成，生成结果被忽略。

未纳入报关未发布分页候选、正式数据库改造或旧航空主题设置面板。当前 D 固定浅色航空主题及重播动效、13份原 CSS、7张原图、28处行为改动已适配到源码；原生事件驱动业务过程与受校验历史回顾，不修改全局 DOM/WebSocket/XHR 原型。源码迁移不等于视觉验收，见根目录 `design-qa.md`。

最新业务边界：采购和报关普通历史不自动推荐，明确选商/询价继续可用；运输按毛重/尺寸和主分单查询、按费用单原币去重，撤回模拟报价/开票日；报关仅显示单项报关费，缺省与零值区分；预测独立 API 量价缺误差指标时不填假值；订单只显示计划交付日、付款截止日、结算日期与倒计时，切换失效订单不借旧上下文。

工具列表另补最小权限修复：有使用权限而无编辑权限的主体不能取得已保存 API 密钥；管理编辑/测试和执行器从数据库读取密钥的合同保留。

## 上传修复

- **知识库和附件解析：**保留 3.0.2 已有的无图片文档媒体目录检查。真实纯文字 DOCX / Pandoc 对照中，旧方法抛 `FileNotFoundError`，新版成功；尚不能证明这就是原现场错误。
- **日常聊天：**散文件改走现有 `/workstation/files`。该接口生成唯一对象键并写属主、租户元数据，与受保护的 `/workstation/files/share-url` 一致。没有放宽续签权限。
- **工作流：**上传助手不再把异常转换为空字符串；单文件和批量文件选择经已有 `showApiError` 提示，保留原值并允许重试。

## 可重复本地检查

使用 Python 3.11，安装仓库已有依赖及 pytest。隔离检查明确替换基础设施，不能证明生产认证、中间件或完整上传成功。

```sh
# From repository root; each group runs in a separate process.
src/backend/.venv/bin/python integrations/zhgyl/tests/run_backend_contracts.py core
src/backend/.venv/bin/python integrations/zhgyl/tests/run_backend_contracts.py archive
src/backend/.venv/bin/python integrations/zhgyl/tests/run_backend_contracts.py d-adapters

cd integrations/zhgyl
python3 tests/procurement/test_mock_api.py
python3 services/transport-native/test_service.py
python3 -m unittest discover -s forecast -q
```

前端按 `src/frontend/package.json` 的 pnpm 9.15.9 锁文件安装。API 检查无需原生 canvas：

```sh
cd src/frontend/client
pnpm exec jest --config ../../../integrations/zhgyl/tests/jest-upload.config.cjs src/api/apps.upload.test.ts --runInBand
NODE_OPTIONS=--require=../../../integrations/zhgyl/tests/no-native-canvas.cjs pnpm exec jest src/pages/appChat/components/InputFileComponent.test.tsx src/components/zhgyl/useAdvisorEntry.test.tsx --runInBand --coverage=false
pnpm exec tsc-strict
pnpm exec vite build
```

canvas 预加载脚本只用于不画图的 DOM 测试，沿用仓库的 `jest-canvas-mock`；它不验证原生 canvas 功能，不参与产品运行。

## 真正运行前的依赖

1. API、所有 Worker 和前端使用同一构建版本；公司 DocFlow 配置及部署前缀按原合并手册保留，授权模型发布仍按原手册执行。
2. 将独立服务部署在获准私网，合并 `forecast/bisheng-nginx.conf` 的代理位置；预测服务首页是 `/`。先注册真实工具、Skill 和模型，再设置 `FORECAST_NATIVE_TOOL_KEY` / `FORECAST_NATIVE_MODEL_ID` 等现有环境变量。
3. 采购工具按正常平台注册的新 child ID / key 设置可信部署变量 `PROCUREMENT_NATIVE_TOOL_ID` / `PROCUREMENT_NATIVE_TOOL_KEY`（兼容默认 D 的44/key），并与固定调用路径、POST方法和 `PROCUREMENT_API_ORIGIN` 同时匹配。不得伪造数据库 ID 或移除校验。
4. 运输和报关固定工具依赖各自 `/app/*-runtime/platform_fetch.py` 与私有配置。部署侧按现有合同挂载源码和配置；不要把运行数据或凭据复制进本目录。
5. D 已有的多个固定 Skill 混选限制仍保留。三参谋入口选定单场景；不要将单助手检查外推成任意 Skill 组合已验证。
6. 订单提醒仍是该页面的 `sessionStorage` 行为，尚无正式提醒服务；空订单视图不能证明正式数据已接通。

本轮未在 D 上传测试文件、修改数据、重启服务或部署；D 用于页面、源码、镜像及经批准模型连接参数的只读取证。

本地完整接线、合成资产生成器及真实 HTTP 检查见 `platform/LOCAL-ACCEPTANCE.md`。平台生成器 `platform/prepare_local_platform.py` 仅创建仓库外新目录，复用与发布镜像逐字节一致的依赖锁并叠加当前源码。用户另已批准本地复用 D 模型连接参数；该私密配置不入源码、补丁或交付包。首次原生注册/登录仍需人工验证码，未绕过验证。
