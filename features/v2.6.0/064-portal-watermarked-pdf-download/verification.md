# 验证记录 Verification：门户带水印 PDF 下载与知识预览水印

## 阅读摘要

- F064 的代码实施与自动化任务 T001-T029、T031-T092 已完成；仅 T030 发布环境人工门禁尚未执行。
- 最终两行水印口径已完成：下载与预览均显示“主部门-姓名--用户账号-YYYY/MM/DD / 首钢股份内部资料，严禁外传，违者必究”，无主部门时首行为“姓名--用户账号-YYYY/MM/DD”；账号优先当前用户 `external_id`，为空时回退登录账号。
- 按需 PDF 扩展已完成：有效引用零生成；缺失/非成功/源过期在当前请求生成并持久化；损坏、对象丢失、size/SHA 不一致只强制修复一次；API/Celery 共用文件级 Redis ownership lock。
- 下载阶段采用 PDF 就绪 300 秒 + 水印 60 秒，Portal BFF 下载专用超时为 370 秒；Portal 与 BiSheng client 都展示脱敏的生成失败/超时文案。
- 最新 PDF 自适应水印与下载服务目标矩阵为 `58 passed`；目标 Ruff 和 compileall 通过。引擎使用最终黑体测量两行文字，以旋转包围盒加留白计算步长；活动最小值为 `180pt × 135pt`、安全留白为 `36pt/27pt`，长身份仍自动扩展。
- Portal BFF 既有分享/预览/下载目标矩阵保持；Portal 全尺寸 SVG 目标 `4 passed`，目标 ESLint 和 `2234 modules transformed` 生产构建通过。预览活动最小单元为 `240px × 180px`、安全留白为 `48px/36px`，使用 `ResizeObserver` 按正文 surface 尺寸生成独立水印坐标，不再使用 SVG pattern。
- BiSheng client 全尺寸 SVG 与正文 surface 目标 `2 passed`；导入检查和 `6087 modules transformed` 生产构建通过，同样按实际 surface 尺寸逐坐标绘制。
- 最终代码生成普通与较长身份 A4 PDF 并由 Poppler 以 120 DPI 渲染：普通身份旋转包围盒 `194.14pt × 148.47pt`、实际步长 `230.14pt × 175.47pt`、13 个锚点；较长身份实际步长 `411.31pt × 302.32pt`、显示 5 个锚点。两者方向向量均为 `(0.819, -0.574)`，即最终左下向右上 `/`，日期为 `YYYY/MM/DD`，且无重叠、奇偶行错位、正文可读；真实 Portal/BiSheng 完整入口目检仍属于 T030。
- 预览边界回归新增两端红灯并完成修复：Portal `3 passed`、目标 ESLint 与 `2230 modules transformed` build 通过；BiSheng 水印+独立预览 `3 passed`、import check 与 `6086 modules transformed` build 通过。两端源码扫描确认完整 viewer 只提供 Provider，overlay 仅存在于 `data-preview-watermark-surface` 正文容器。
- pattern 切片回归已完成：旧实现因错位行跨越 pattern tile 边界而周期性裁剪；两端现改为全尺寸 SVG 独立 `<g>/<text>`。本地浏览器在普通身份 1500×720 和长身份 1500×500 surface 上分别生成 15 组和 5 组水印，pattern 数为 0，每组均保留两行，正文内部不再残缺，只有真实正文外边缘按预期裁剪。
- 智能写作展示时机与透明度漂移回归已修复：`/apps` 模板初始态不再挂载水印，进入会话后才按 `hasConversation` 挂载；下载 PDF 默认透明度由漂移值 `0.31` 恢复为全端统一的 `0.11`，其余字号、角度、间距与颜色保持不变。
- 最新透明度需求已覆盖上一轮视觉基准：PDF、Worker、Portal 预览/问答和 BiSheng 预览/问答当前统一为 `0.31`；显示时机及其他视觉 token 保持不变。
- 全量仓库仍存在实施前已登记的无关失败；下载/预览视觉、播放器/文档交互、50 MB、真实并发、浏览器断连与发布环境权限验收未执行，因此 Feature 状态为 `MANUAL_REQUIRED`，不是 `VERIFIED`。

## 元信息 Metadata

- Feature ID: `064-portal-watermarked-pdf-download`
- Status: `manual_required`
- Related requirements: `features/v2.6.0/064-portal-watermarked-pdf-download/requirements.md`
- Related tasks: `features/v2.6.0/064-portal-watermarked-pdf-download/tasks.md`
- Created: `2026-07-21`
- Updated: `2026-07-23`

## 验证摘要 Verification Summary

- Overall status: `MANUAL_REQUIRED`
- Completed tasks: `T001-T029, T031-T097, T099-T101, T103-T105`
- Remaining tasks: `T030, T098, T102`
- Blocked tasks: `无`
- Automated conclusion: F064 下载、按需 PDF 修复、最终两行水印、自适应无重叠 PDF、约 25% 间距缩短、全端透明度 `0.31`、`YYYY/MM/DD`、最终 `/` 方向、全尺寸 SVG 逐坐标预览、Portal/BiSheng 登录态问答正文水印接线、目标测试、静态检查、生产构建、PDF/浏览器样本渲染、匿名 API/问答水印门禁及范围源码审计通过。
- Release conclusion: 必须完成 T030/T098 的真实文件、登录态完整入口、浏览器交互、并发和断连人工门禁后，才可标记 Feature 级 `VERIFIED`。

## 已执行命令 Commands Run

| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| 两端全尺寸 SVG 目标测试（实现前） | Test-First 红灯确认旧 pattern 实现缺少 surface 坐标生成与独立节点契约 | `1 / 2` | `EXPECTED_FAIL` | BiSheng `1 failed, 1 passed`，失败为缺少 `calculateKnowledgePreviewWatermarkPositions`；Portal 目标类型编译缺少 `calculatePortalPreviewWatermarkPositions`，并保留既有 QA 模板字段与旧 `fetchHomeContent` 基线错误 |
| BiSheng `npx jest ...KnowledgePreviewWatermark.test.tsx --runInBand --coverage=false` + `npm run check-imports` + `npm run build:ci` | 全尺寸 SVG 坐标、resize 重铺、无 pattern、正文 surface 与生产构建 | `0` | `PASS` | `2 passed`；800×640 生成 14 个独立锚点，奇数行半步错位，高度增大后锚点增加；每组固定两行、无 `<pattern>/<rect>`；导入检查通过，`6087 modules transformed` |
| Portal `node --test .test-dist/tests/previewWatermark.test.js` + 目标 ESLint + `npm run build` | Portal 全尺寸 SVG 坐标、ResizeObserver、无 pattern 与生产构建 | `0` | `PASS` | `4 passed`；800×640 生成 14 个独立锚点，尺寸增长后重铺；源码契约包含 `ResizeObserver`/`positions.map` 且无 `<pattern>`；ESLint 无输出，`2234 modules transformed` |
| 本地浏览器 1500×720 普通身份与 1500×500 长身份 visual fixture | 验证独立文字节点不会在正文内部被周期性切片 | `0` | `PASS` | 普通身份 15 组、长身份 5 组，pattern 数均为 0，每个 `<g>` 均有两行 `<text>`；正文内部水印完整，仅真实 surface 外边缘发生裁剪 |
| 两仓生产源码 pattern 名称扫描 + `git diff --check` | 确认移除 pattern 路径并检查差异卫生 | `0` | `PASS` | 生产组件与布局工具不再包含 pattern 相关名称；Portal/BiSheng 两仓 diff 均无空白错误 |
| 三端新口径目标测试（实现前） | Test-First 红灯确认旧日期、间距和 PDF 方向不满足新规格 | `1 / 1 / 1` | `EXPECTED_FAIL` | 后端 `7 failed, 31 passed`，BiSheng `2 failed`，Portal `3 failed, 1 passed`；分别命中 PDF 方向/步长/日期、BiSheng 日期及 Portal 日期/单元 |
| BiSheng backend `.venv/bin/python -m pytest test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py test/knowledge/pdf/test_portal_pdf_download_service.py test/knowledge/test_portal_pdf_download_contract.py -q` + 目标 Ruff/compileall | 新间距、斜杠日期、PDF `/` 方向、自适应长文字和下载回归 | `0` | `PASS` | `57 passed`；Ruff `All checks passed!`，compileall 无输出；文本方向向量断言 `x>0,y<0` |
| BiSheng client 目标 Jest + `npm run check-imports` + `npm run build:ci` | `240px × 180px`、`48px/36px`、`YYYY/MM/DD`、SVG `/` 方向及构建 | `0` | `PASS` | `2 passed`；导入检查通过，`6087 modules transformed`，仅既有资源/chunk/PWA 警告 |
| Portal frontend 目标 `tsc` 产物 + Node test + 目标 ESLint + `npm run build` | Portal 新间距、斜杠日期、SVG `/` 方向及构建 | `2 / 0 / 0 / 0` | `TARGET_PASS` | 目标 `4 passed`、ESLint 无输出、`2232 modules transformed`；test 类型编译仍仅被既有 QA 模板夹具和旧 `fetchHomeContent` 引用阻断 |
| PyMuPDF 样本生成 + Poppler 120 DPI 渲染 + 图像目检 | 普通/较长身份的日期、方向、密度和不重叠视觉验证 | `0` | `PASS` | 普通 13 个锚点、较长 5 个锚点；方向向量 `(0.819,-0.574)`，日期斜杠、最终 `/`、无重叠；Poppler 仅有既有 Fontconfig 默认配置提示 |
| 后端/两端预览中等增密定向测试（实现前） | Test-First 红灯确认轻度增密常量不满足新规格 | `1 / 1 / 1` | `EXPECTED_FAIL` | 后端 `2 failed, 6 passed`，BiSheng `1 failed, 1 passed`，Portal 目标 `1 failed, 3 passed`；失败分别明确显示 `288 != 240`、`384 != 320` |
| BiSheng backend `.venv/bin/python -m pytest test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py test/knowledge/pdf/test_portal_pdf_download_service.py test/knowledge/test_portal_pdf_download_contract.py -q` + 目标 Ruff/compileall | 中等增密、自适应旋转包围盒、长字段扩展、错位锚点与下载回归 | `0` | `PASS` | `57 passed`；Ruff `All checks passed!`，compileall 无输出；覆盖 `240pt × 180pt` 最小步长、普通 A4 12 至 14 个锚点、长身份扩展、多页/横向/旋转和正文保持 |
| BiSheng client 目标 Jest + `npm run check-imports` + `npm run build` | `320px × 240px` 单 SVG pattern、身份文案、正文边界与生产构建 | `0` | `PASS` | `2 passed`；pattern `320px × 480px`、半步错位 `160px`、长身份扩展；导入检查通过，`6065 modules transformed`，仅既有资源/chunk/PWA 警告 |
| Portal frontend 目标 `tsc` 产物 + `node --test .test-dist/tests/previewWatermark.test.js` + 目标 ESLint + `npm run build` | Portal `320px × 240px` 自适应布局、SVG 源码契约、静态检查和构建 | `2 / 0 / 0 / 0` | `TARGET_PASS` | 目标 `4 passed`、ESLint 无输出、`2232 modules transformed`；全量 test 类型编译仍仅被既有 QA template 字段和旧 `fetchHomeContent` 引用阻断，应用 TypeScript/Vite build 通过 |
| 普通/长身份 PDF + `pdftoppm -png -r 120 -singlefile ...` + `pdfinfo` + 图片目检 | 中等增密、错位、长文本扩距、重叠和正文可读视觉回归 | `0` | `PASS` | 普通 A4 包围盒 `194.14 × 148.47pt`、步长 `242.14 × 184.47pt`、13 个锚点；长身份包围盒 `343.81 × 253.27pt`、步长 `391.81 × 289.27pt`、5 个锚点；PNG 均无相邻重叠，正文可读 |
| 三端最小单元源码扫描 + 两仓 `git diff --check` | 参数一致性、差异卫生、范围和安全边界 | `0` | `PASS` | PDF/worker 均为 `240/180`，Portal/BiSheng 均为 `320/240`；未改 Compose、Docker、schema、依赖、队列或身份来源；两仓 diff 无空白错误 |
| 后端/两端预览轻度增密定向测试（实现前） | Test-First 红灯确认旧最小单元不满足新规格 | `1 / 1 / 1` | `EXPECTED_FAIL` | 后端 `2 failed, 6 passed`，BiSheng `1 failed, 1 passed`，Portal 目标 `1 failed, 3 passed`；失败分别明确显示 `320 != 288`、`427 != 384` |
| BiSheng backend `.venv/bin/python -m pytest test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py test/knowledge/pdf/test_portal_pdf_download_service.py test/knowledge/test_portal_pdf_download_contract.py -q` + 目标 Ruff/compileall | 轻度增密、自适应旋转包围盒、长字段扩展、错位锚点与下载回归 | `0` | `PASS` | `57 passed`；Ruff `All checks passed!`，compileall 无输出；覆盖 `288pt × 200pt` 最小步长、普通 A4 8 至 10 个锚点、长身份扩展、多页/横向/旋转和正文保持 |
| BiSheng client 目标 Jest + `npm run check-imports` + `npm run build` | `384px × 267px` 单 SVG pattern、身份文案、正文边界与生产构建 | `0` | `PASS` | `2 passed`；pattern `384px × 534px`、半步错位 `192px`、长身份扩展、无 `ResizeObserver`/tile 数组；导入检查通过，`6064 modules transformed`，仅既有资源/chunk/PWA 警告 |
| Portal frontend 目标 `tsc` 产物 + `node --test .test-dist/tests/previewWatermark.test.js` + 目标 ESLint + `npm run build` | Portal `384px × 267px` 自适应布局、SVG 源码契约、静态检查和构建 | `2 / 0 / 0 / 0` | `TARGET_PASS` | 目标 `4 passed`、ESLint 无输出、`2232 modules transformed`；全量 test 类型编译仍仅被既有 QA template 字段和旧 `fetchHomeContent` 引用阻断，应用 TypeScript/Vite build 通过 |
| 普通/长身份 PDF + `pdftoppm -png -r 144 -singlefile ...` + `pdfinfo` + 图片目检 | 下载密度、错位、长文本扩距、重叠和正文可读视觉回归 | `0` | `PASS` | 普通 A4 包围盒 `194.14 × 148.47pt`、步长 `288 × 200pt`、10 个锚点；长身份包围盒 `459.45 × 334.24pt`、步长 `507.45 × 370.24pt`、5 个锚点；PNG 均无相邻重叠，正文可读 |
| 三端最小单元源码扫描 + 两仓 `git diff --check` | 参数一致性、差异卫生、范围和安全边界 | `0` | `PASS` | PDF/worker 均为 `288/200`，Portal/BiSheng 均为 `384/267`；未改 Compose、Docker、schema、依赖、队列或身份来源；两仓 diff 无空白错误 |
| BiSheng backend `.venv/bin/python -m pytest test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py test/knowledge/pdf/test_portal_pdf_download_service.py -q` + 目标 Ruff/format/compileall | 最终两行 PDF spec、`external_id`/账号回退、主部门、黑体候选与下载服务回归 | `0` | `PASS` | `41 passed`；Ruff `All checks passed`，5 个文件格式通过，compileall 无输出；覆盖固定两行、双连字符、无部门格式、PDF 视觉 token、可靠字体解析和不可用时明确失败 |
| BiSheng client `npx jest ...KnowledgePreviewWatermark.test.tsx --runInBand --coverage=false` + `npm run check-imports` + `npm run build:ci` | 两行预览、动态密度、账号映射、正文裁剪与构建 | `0` | `PASS` | `2 passed`；mock `ResizeObserver` 从初始 4 个单元调整为 800×640 的 25 个并覆盖 2400px 长文档；导入检查通过，`6086 modules transformed` |
| Portal frontend 目标 `tsc` + `node --test .test-dist/tests/previewWatermark.test.js` + 目标 ESLint + `npm run build` | Portal 两行 formatter、按 surface 尺寸铺设、PDF 等效样式和生产构建 | `0` | `PASS` | `4 passed`；800×640 为 25 个单元，长文档数量增加；`16px`、`-35°`、`0.16`、`#737373`、`240px × 160px`、首锚点 `27px × 48px` 契约通过；ESLint 无输出，`2230 modules transformed` |
| 最终代码生成代表 PDF + `pdftoppm -png -r 144 -singlefile ...` + 图片目检 | 长中文身份两行黑体 PDF 视觉回归 | `0` | `PASS` | Poppler 成功渲染；正文完整可读，首行“炼钢制造部-张三丰--SG-LONG-00192837-2026-07-22”、固定第二行、顺序、倾斜、透明度和铺设密度符合基准；仅有本机 Fontconfig 配置提示 |
| BiSheng backend `./.venv/bin/python -m pytest -q test/user/test_user_primary_department_contract.py test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py test/knowledge/pdf/test_portal_pdf_download_service.py` | 历史三行阶段的主部门查询、PDF spec、worker 与统一下载文案 | `0` | `HISTORICAL_PASS` | 当时 `43 passed`；三行文案证据已由本表上方最终两行 `41 passed` 证据替代，主部门与 worker 边界仍有效 |
| Portal BFF `./.venv/bin/python -m pytest -q tests/test_auth_api.py tests/test_auth_unified_api.py` | Portal 登录/统一认证会话主部门字段透传 | `0` | `PASS` | `34 passed`；`department_name` 随当前用户会话返回，旧 role/external_id 契约保持 |
| BiSheng client `npx jest ...KnowledgePreviewWatermark.test.tsx ...FilePreviewPage.download.test.tsx --runInBand --coverage=false` | 历史三行阶段的 BiSheng 预览水印与下载回归 | `0` | `HISTORICAL_PASS` | 当时 `3 passed`；三行文案证据已由本表上方最终两行 `2 passed` 替代，正文 surface 与下载行为仍有效 |
| Portal frontend `npx tsc -p tsconfig.tests.json --noEmitOnError false` + `node --test .test-dist/tests/previewWatermark.test.js` | 历史三行阶段的 Portal formatter、auth 映射和正文 surface 契约 | `2` / `0` | `HISTORICAL_TARGET_PASS` | 当时目标 `3 passed`；三行文案证据已由本表上方最终两行 `4 passed` 替代；该轮全量测试类型仍仅有既有 QA template 字段与旧 `fetchHomeContent` 错误 |
| Portal frontend `npx eslint src/utils/previewWatermark.ts src/components/PreviewWatermark.tsx tests/previewWatermark.test.ts` | Portal 水印目标静态检查 | `0` | `PASS` | 无输出；包含 `src/api/auth.ts` 时仅命中既有 `no-control-regex` 基线 |
| BiSheng client `npm run check-imports` + `npm run build:ci`；Portal frontend `npm run build` | 两端导入与生产构建 | `0` | `PASS` | BiSheng `6086 modules transformed`，Portal `2230 modules transformed`；仅既有资源/chunk/PWA/Browserslist 与 Node 版本提示 |
| BiSheng backend `compileall` + 目标 `ruff --select E,F,I` + 两仓旧文案/secret/diff 扫描 | 语法、静态质量、安全与差异卫生 | `0` | `PASS` | 新增/目标模块检查通过，无硬编码 secret，无生产源码旧四行字段前缀，`git diff --check` 通过；legacy `user.py` 全文件仍有既有 F841/格式基线 |
| BiSheng `.venv/bin/python -m pytest ...test_pdf_artifact_worker.py ...test_pdf_artifact_on_demand_service.py ...test_pdf_artifact_repository.py ...test_portal_pdf_download_service.py ...test_portal_pdf_download_contract.py ...test_knowledge_space_download_endpoint.py ...test_shougang_portal_endpoint.py -q` | 按需 Artifact、共享 processor、single-flight、统一下载与两个 endpoint fresh 回归 | `0` | `PASS` | `107 passed`；覆盖 generation 复用/重启/强制修复、锁 owner/waiter/TTL/延迟释放、有效引用零生成、损坏产物一次修复、最终失败脱敏、资源清理与旧 endpoint |
| BiSheng `.venv/bin/ruff check --ignore RUF001,RUF003`（本扩展后端文件与测试） | Python 静态检查 | `0` | `PASS` | `All checks passed!`；两项仅忽略仓库既有中文标点规则，未忽略业务或类型错误 |
| Portal BFF `backend/.venv/bin/python -m pytest backend/tests/test_knowledge_api.py backend/tests/test_bisheng_client.py -k download -q` | 370 秒代理、流式关闭与安全错误映射 | `0` | `PASS` | `12 passed, 113 deselected`；下载专用 timeout=370、500 上游细节不透传、409/504 与流式生命周期通过 |
| Portal frontend `./node_modules/.bin/tsc -b --pretty false` + `node --test .test-dist/tests/fileDownload.test.js` | Portal 下载类型检查与最终提示 | `0` | `PASS` | TypeScript build 通过；`5 passed`，覆盖 409 JSON、500/504 非 JSON 稳定文案与成功 Blob |
| BiSheng client `./node_modules/.bin/jest src/api/knowledge.test.ts -t downloadWatermarkedKnowledgeFileApi --runInBand --coverage=false --silent` | BiSheng 下载 helper 最终提示 | `0` | `PASS` | `4 passed, 33 skipped`；新增 504 PDF 生成超时稳定提示，既有成功/文件名/Blob 错误行为保持 |
| 两仓 `git diff --check` + 下载旧调用/部署文件源码扫描 | 差异卫生、无回退与部署边界 | `0` | `PASS` | diff 无空白错误；未新增原文件/预览 URL fallback；本扩展未改 Compose、Dockerfile、entrypoint、schema、依赖或 Celery queue |
| `git status --short`（BiSheng、Portal） | 记录实施前工作树并建立避让边界 | `0` | `PASS` | 已登记 BiSheng 的 portal config、Celery DB、entrypoint、F063 deployment test 等既有脏文件，以及 Portal 既有 `docker-compose.yaml`；本 Feature 未覆盖这些改动 |
| Portal BFF `.venv/bin/python -m pytest -q tests/test_knowledge_api.py tests/test_bisheng_client.py`（实施前） | 全量相关文件基线 | `1` | `BASELINE` | `104 passed, 9 failed`；失败集中于既有首页统计、聊天代理和搜索断言 |
| BiSheng `.venv/bin/python -m pytest -q test/knowledge/pdf/test_pdf_artifact_service.py test/test_shougang_portal_endpoint.py test/knowledge/test_public_space_file_permissions.py test/test_permission_public_space_download.py`（实施前） | F063 accessor、门户 endpoint 与权限基线 | `0` | `PASS` | `32 passed` |
| BiSheng `.venv/bin/python -m pytest -q test/knowledge/test_portal_pdf_download_contract.py`（实现前/后） | 配置、DTO、入口和错误码 Test-First | `2 → 0` | `PASS` | 红灯为缺少 `KnowledgePdfWatermarkConf`；实现后 `12 passed` |
| BiSheng `.venv/bin/python -m pytest -q test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py` | 水印核心与隔离 Worker | `0` | `PASS` | `9 passed`；页数/尺寸/源 SHA、中文、多 tile、旋转、损坏/加密输入、stdin 脱敏及 terminate/kill/reap 通过 |
| BiSheng `.venv/bin/python -m pytest -q test/test_shougang_portal_endpoint.py test/knowledge/test_portal_share_download_grant.py test/knowledge/pdf/test_portal_pdf_download_service.py test/knowledge/test_portal_pdf_download_contract.py test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py` | BiSheng F064 最终目标矩阵 | `0` | `PASS` | `87 passed`；包含 grant 到期不晚于分享链接、真实签名 grant 下载组合、权限/租户/IDOR、三类 Artifact、60 秒 deadline、生成取消、并发/锁、清理、遥测和 HTTP 状态 |
| BiSheng `.venv/bin/python -m pytest -q test/knowledge/pdf/test_pdf_watermark.py test/knowledge/pdf/test_pdf_watermark_worker.py test/knowledge/pdf/test_portal_pdf_download_service.py test/knowledge/test_knowledge_space_download_endpoint.py test/knowledge/test_portal_pdf_download_contract.py test/test_shougang_portal_endpoint.py` | 旧单文件 endpoint 收口与共享响应扩展矩阵 | `0` | `PASS` | `78 passed`；两个 endpoint 均返回 PDF 二进制和安全 headers，错误状态、清理、13 个入口、水印核心/服务回归通过 |
| BiSheng `.venv/bin/ruff check`（F064 新增模块及测试） | Python 静态检查 | `0` | `PASS` | `All checks passed!` |
| BiSheng `bash scripts/arch-guard.sh` | 后端架构边界守卫 | `0` | `PASS` | 无违规输出，旧 endpoint 仅复用领域下载服务与共享响应适配器 |
| BiSheng `.venv/bin/python -m pytest -q test/knowledge/pdf/test_pdf_artifact_service.py test/knowledge/test_public_space_file_permissions.py test/test_permission_public_space_download.py` | F063 与既有权限兼容回归 | `0` | `PASS` | `19 passed` |
| Portal BFF `.venv/bin/python -m pytest -q tests/test_portal_share_access_store.py` | Redis v2 分享会话 | `0` | `PASS` | `13 passed`；含跨实例、绑定、匿名 view、Redis fail closed、开发回退与不足一秒 TTL 向上取整 |
| Portal BFF `.venv/bin/python -m pytest -q tests/test_portal_share_access_store.py tests/test_bisheng_client.py tests/test_knowledge_api.py -k 'share or preview or chunks or download'` | BFF 分享、预览、下载目标矩阵 | `0` | `PASS` | `41 passed, 96 deselected`；匿名分享 detail/摘要可见，preview/content/chunks 401 且无上游；登录预览、Range、grant、流式响应与下载回归通过 |
| Portal BFF `.venv/bin/python -m pytest -q --tb=no` | BFF 全量回归 | `1` | `BASELINE_FAILURES` | `397 passed, 16 failed`；失败为既有 admin config、首页统计、聊天/搜索及缺少 async pytest 插件的 favorite 测试，F064 目标矩阵全绿 |
| Portal BFF `.venv/bin/python -m compileall -q ...` | 修改模块语法编译 | `0` | `PASS` | 所有 F064 BFF 修改模块编译通过 |
| Portal frontend `npx tsc -p tsconfig.tests.json --noEmitOnError false` | 生成 Node 目标测试产物并检查全量测试类型 | `2` | `BASELINE_FAILURES` | 既有 `adminQaTemplates.test.ts` 缺字段及 `portalContentConfig.test.ts` 引用已不存在的 `fetchHomeContent`；仍按参数生成目标 JS |
| Portal frontend `node --test .test-dist/tests/fileDownload.test.js .test-dist/tests/guestDownloadAccess.test.js .test-dist/tests/portalDocumentSources.test.js .test-dist/tests/fileListItem.test.js` | 统一下载、权限显示、入口来源和 loading | `0` | `PASS` | `14 passed` |
| Portal frontend `npx eslint src/api/content.ts src/utils/fileDownload.ts tests/fileDownload.test.ts tests/guestDownloadAccess.test.ts tests/portalDocumentSources.test.ts tests/fileListItem.test.ts` | F064 核心前端文件静态检查 | `0` | `PASS` | 无错误或警告 |
| Portal frontend `npm run lint` | 前端全量 lint | `1` | `BASELINE_FAILURES` | `13 errors, 6 warnings`；均位于既有 auth、审批/问答组件、Expert QA 历史行、adminDomains 和既有测试；本次新增的文件名正则 lint 错误已修复 |
| Portal frontend `npm run build` | TypeScript/Vite 生产构建 | `0` | `PASS` | `2227 modules transformed`；仅提示本机 Node 20.13.1 低于 Vite 推荐 20.19+ 及既有 chunk size 警告 |
| Portal frontend 定向 `tsc` + `node --test`：`filePreview.test.ts`、`previewWatermark.test.ts` | 预览 manifest、身份/时钟、CSS 属性和匿名请求短路 | `0` | `PASS` | 历史 `11 passed`；该轮身份/时间与四行文本证据已由本次三行主部门目标测试替代，其他匿名门禁和 CSS 契约保持有效 |
| Portal frontend `npx eslint`（DetailPage、PreviewWatermark、formatter 与目标测试） | 预览扩展静态检查 | `0` | `PASS` | 无错误或警告 |
| Portal frontend `npm test`（预览扩展后全量） | 全量 Node test 类型门 | `2` | `BASELINE_FAILURES` | 仍只被既有 `adminQaTemplates.test.ts` 缺 `homeIcon/description` 与 `portalContentConfig.test.ts` 旧 `fetchHomeContent` 引用阻断；新增目标测试可独立编译运行 |
| Portal frontend `npm run build`（预览扩展后） | 预览扩展生产构建 | `0` | `PASS` | `2230 modules transformed`；Node 版本与 chunk 警告同既有基线 |
| BiSheng client `npm run test:ci -- --runInBand src/api/knowledge.test.ts -t downloadWatermarkedKnowledgeFileApi --coverage=false --silent` | 水印 Blob helper 契约 | `0` | `PASS` | `3 passed, 33 skipped`；Axios Blob、entry point、RFC 5987/安全 fallback 文件名、JSON Blob 错误和 Object URL 释放通过 |
| BiSheng client `npm run test:ci -- --runInBand ...PortalKnowledgeWorkbench.test.tsx -t ... --coverage=false --silent` | BiSheng 门户入口接线与文件夹能力收缩 | `0` | `PASS` | `5 passed, 100 skipped`；表格/卡片文件夹无下载，文件列表、预览、收藏源空间 entry point 正确，loading 防重复与错误恢复通过 |
| BiSheng client `npm run test:ci -- --runInBand src/pages/knowledge/FilePreview/FilePreviewPage.download.test.tsx src/pages/knowledge/SpaceDetail/VersionHistorySheet.download.test.tsx --coverage=false --silent` | 独立预览与版本历史下载 | `0` | `PASS` | 两个目标文件各 `1 passed`；独立预览使用 `bisheng_preview`，版本历史传实际历史 `knowledge_file_id`，均阻止重复提交并恢复按钮 |
| BiSheng client `npm run test:ci -- --runInBand src/api/knowledge.test.ts -t batchDownloadApi --coverage=false` | 非门户批量 API 契约 | `0` | `PASS` | `1 passed, 32 skipped` |
| BiSheng client `npm run build:ci` | BiSheng client 生产构建 | `0` | `PASS` | `6084 modules transformed`，生产构建通过；仅既有资源、chunk、PWA glob 和 Browserslist 警告 |
| BiSheng client `npm run check-imports` | 大小写敏感导入检查 | `0` | `PASS` | `All import paths match git index casing` |
| BiSheng client `npx jest ...KnowledgePreviewWatermark.test.tsx ...FilePreviewPage.download.test.tsx --runInBand --coverage=false` | 知识预览水印与独立预览下载回归 | `0` | `PASS` | 历史 `3 passed`；该轮姓名/账号与四行文本证据已由本次三行主部门目标测试替代，可访问性、基础层接线与下载行为保持有效 |
| Portal frontend `node --test .test-dist/tests/previewWatermark.test.js` + 目标 ESLint + `npm run build` | 预览水印正文边界回归 | `0` | `PASS` | `3 passed`；Provider/overlay 分离、7 类非 PDF 正文 surface、PDF 单页 surface、交互隔离和匿名门禁源码契约通过；ESLint 无输出；`2230 modules transformed`。Node 20.13.1 版本提示与既有 chunk warning 保留 |
| BiSheng client 目标 Jest + `npm run check-imports` + `npm run build:ci` | 预览水印正文边界与独立预览回归 | `0` | `PASS` | `3 passed`；完整 FilePreview/RichKnowledgePreview 仅提供 Provider，各格式 viewer 在 `relative overflow-hidden` 正文 surface 内渲染 overlay；导入检查通过，`6086 modules transformed` |
| 两端 `rg data-preview-watermark-surface/PreviewWatermarkOverlay/KnowledgePreviewWatermarkProvider` + `git diff --check` | 正文边界接线与差异卫生 | `0` | `PASS` | Portal PDF 画布与 7 类非 PDF surface、BiSheng 7 类普通 viewer 及富媒体正文均有显式边界；外层 viewer 不再直接覆盖水印；两仓 diff 无空白错误 |
| BiSheng client `npx jest ...PortalKnowledgeWorkbench.test.tsx -t 'keeps...|wires...'` | 门户预览/下载源码契约 | `0` | `PASS` | `2 passed, 103 skipped`；既有门户预览和下载接线契约保持 |
| BiSheng client `npm run check-imports && npm run build:ci`（预览扩展后） | 导入与生产构建 | `0` | `PASS` | 大小写检查通过，`6086 modules transformed`；仅既有资源/chunk/PWA/Browserslist 警告 |
| BiSheng client 全量 `PortalKnowledgeWorkbench.test.tsx` 联合运行 | 既有工作台整文件基线 | `1` | `BASELINE_FAILURES` | `95 failed, 10 passed`（联合三文件总计为 `95 failed, 13 passed`）；失败统一为既有测试未提供新 `useAuthContext` 所需 `AuthProvider`，目标水印与独立预览文件通过 |
| 两端 `rg KnowledgePreviewWatermark/PreviewWatermark` + import graph | 入口覆盖与非知识范围隔离 | `0` | `PASS` | Portal 仅 DetailPage 接线；BiSheng 仅 `FilePreview`/`RichKnowledgePreview` 接线，并由独立、门户、收藏、版本对比和知识引用复用；SOP、聊天上传、Artifact 无新增接线 |
| F064 diff 敏感信息模式扫描 | 防止凭据进入本次变更 | `0` | `PASS` | 未发现 token、API key、secret、password 或 Authorization bearer 字面量 |
| `rg` 下载旧调用扫描 + 两仓 `git diff --check`/`git diff --name-only` | 下载口径、部署边界和空白检查 | `0` | `PASS` | BiSheng 知识下载源码不再引用 `getFileDownloadApi` 或从 `original_url/preview_url` 下载；Portal source 仍无重复下载事件；本扩展未修改依赖 lock、Compose、Dockerfile、entrypoint、Celery 或数据库 schema；diff 无空白错误 |
| Portal/BiSheng 问答水印目标测试（实现前） | Test-First 红灯确认问答正文、URL iframe、默认关闭/显式开启和单一透明度来源尚未实现 | `1 / 1` | `EXPECTED_FAIL` | Portal `3 failed`；BiSheng `4 failed`，失败均命中新 Provider/surface/入口接线契约 |
| Portal `node --test .test-dist/tests/chatWatermark.test.js .test-dist/tests/previewWatermark.test.js` + `npx tsc -b` | 本地 QA、第三方 URL iframe、workflow 单层责任、匿名排除、复用 formatter/layout 与生产类型检查 | `0` | `PASS` | `7 passed`；应用 TypeScript build 无输出；透明度由 layout `0.11` 单一注入 SVG，CSS 不再重复定义 |
| BiSheng `jest ...ChatWatermark.test.tsx ...KnowledgePreviewWatermark.test.tsx --ci --runInBand --coverage=false` + import check | 默认关闭的通用 surface、空/加载/消息正文、主问答/AppChat/知识/单文档/订阅入口和 guest/share/readOnly 排除 | `0` | `PASS` | `7 passed`；运行时验证 disabled 不创建 surface、enabled 且有当前用户时创建 SVG；大小写敏感导入检查通过 |
| Portal/BiSheng `npm run build` + 两仓 `git diff --check` | 两端生产构建与差异卫生 | `0 / 0 / 0 / 0` | `PASS` | Portal `2234 modules transformed`，BiSheng `6065 modules transformed`；仅既有 Node/Vite、Browserslist、字体运行时解析、eval/chunk 告警；两仓无空白错误 |
| 本地 Portal 浏览器 `/apps` 匿名态 DOM/几何审计 | 问答正文边界、输入框排除、匿名无实际水印和运行时错误 | `0` | `PARTIAL_PASS` | surface 为 `position:relative; overflow:hidden; isolation:isolate`，尺寸 `985×422`；composer 不在 surface 内；匿名 direct overlay/canvas/水印文字均为 0；控制台无 error/warning。当前浏览器无登录态且本机 Chrome 会话不可用，登录态全入口视觉保留给 T098/T030 |
| T100 实施前 Portal `chatWatermark.test.js` + backend `test_pdf_watermark.py` | 智能写作展示条件与 PDF 透明度失败回归 | `1 / 1` | `EXPECTED_FAIL` | Portal `1 failed, 2 passed`，命中无条件 overlay；backend `2 failed, 6 passed`，命中默认/实际 trace 透明度 `0.31` |
| Backend `pytest`：PDF 水印、worker、Portal 下载服务与下载 contract | 下载水印及关联链路回归 | `0` | `PASS` | `57 passed`；默认 spec 和实际 PDF trace 均精确为 `0.11` |
| Backend 目标 Ruff + compileall | 修改模块与回归测试静态/语法检查 | `0` | `PASS` | `All checks passed`；目标模块编译通过 |
| Portal `chatWatermark.test.js` + `previewWatermark.test.js` + `npm run build` | 智能写作模板/会话边界、预览样式复用和生产构建 | `0` | `PASS` | `7 passed`；生产构建 `2234 modules transformed`；仅保留既有 Node 版本与 chunk 警告 |
| BiSheng `ChatWatermark.test.tsx` + `KnowledgePreviewWatermark.test.tsx` + import check + `npm run build` | BiSheng 问答/预览统一样式回归 | `0` | `PASS` | `7 passed`；大小写敏感导入检查与生产构建通过，仅保留既有资源/chunk/PWA/Browserslist 告警 |
| 本地 Portal 浏览器 `/apps` 初始态 DOM 审计 | 智能写作进入页面不显示水印 | `0` | `PARTIAL_PASS` | 实际页面 overlay 数量为 `0`；当前会话无登录态，无法通过 UI 发送问题验证“进入会话后显示”，该视觉项保留给 T102/T098 |
| T104 实施前 backend/Portal/BiSheng 透明度目标测试 | 新口径 `0.31` 失败回归 | `1 / 1 / 1` | `EXPECTED_FAIL` | backend `2 failed, 6 passed`；Portal `1 failed, 3 passed`；BiSheng `1 failed, 2 passed`，均明确命中实际值 `0.11` |
| Backend PDF/worker/Portal download 关联 pytest + Ruff + compileall | PDF 与 Worker `0.31` 及下载链路回归 | `0` | `PASS` | `58 passed`；Ruff `All checks passed`；目标模块编译通过 |
| Portal preview/chat Node test + `npm run build` | Portal 预览/问答单一透明度来源与生产构建 | `0` | `PASS` | `7 passed`；`2237 modules transformed`，仅保留既有 Node 版本与 chunk 告警 |
| BiSheng preview/chat Jest + import check + `npm run build` | BiSheng 预览/问答单一透明度来源与生产构建 | `0` | `PASS` | `7 passed`；导入检查通过，`6066 modules transformed`，仅保留既有资源/chunk/PWA/Browserslist 告警 |

## 验收覆盖 Acceptance Coverage

| Acceptance ID | Requirement | Automated Evidence | Status |
|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | 前端统一工具/三入口源码测试 + BFF PDF 流 | `PASS` |
| AC-REQ-001-02 | REQ-001 | 首页、相关推荐、专家问答结构化文档、QA 引用来源测试；普通附件 fallback 保留 | `PASS` |
| AC-REQ-001-03 | REQ-001 | RFC 5987、ASCII、中文、扩展名替换、特殊/控制字符清理测试 | `PASS` |
| AC-REQ-001-04 | REQ-001 | 旧下载 URL 源码扫描；BFF preview 始终清空下载字段；viewer/chunks 目标回归 | `PASS` |
| AC-REQ-002-01 | REQ-002 | 有效引用直接读取并验证 PDF/size/SHA；按需服务 generation/lock 调用为零 | `PASS` |
| AC-REQ-002-02 | REQ-002 | Repository/按需服务覆盖无记录、WAITING/PROCESSING/FAILED、源变化并在当前请求持久化；无原文件 fallback | `PASS` |
| AC-REQ-002-03 | REQ-002 | 共享 processor 回归证明 ORIGINAL/PARSE_PREVIEW 只登记引用，GENERATED 只上传并登记一次 | `PASS` |
| AC-REQ-002-04 | REQ-002 | 对象损坏/读取失败/元数据不匹配触发一次新 generation；第二次无效即脱敏失败且不回退 | `PASS` |
| AC-REQ-002-05 | REQ-002 | 文件级 ownership lock、非 owner 等待复用、invalid generation 防重复 bump 与延迟线程释放锁测试 | `PASS` |
| AC-REQ-003-01 | REQ-003 | 单元测试验证每页两行目标文字、最终黑体度量、旋转包围盒、`180pt × 135pt` 最小值、`36pt/27pt` 留白、长字段扩展、奇偶行错位、`0.31` 和最终 `/` 方向；普通/长身份 PDF 已用 Poppler 渲染且无重叠，最新透明度仍待发布代表集目检 | `MANUAL_REQUIRED` |
| AC-REQ-003-02 | REQ-003 | Repository/下载服务验证 DB 当前用户姓名、`external_id` 与主部门；无主部门和账号回退均有测试；浏览器不提交身份文本 | `PASS` |
| AC-REQ-003-03 | REQ-003 | Asia/Shanghai 固定日期 `YYYY/MM/DD` 与单次 spec 复用测试 | `PASS` |
| AC-REQ-003-04 | REQ-003 | 多页/横向/旋转、页数/尺寸/源 SHA/validator 自动化通过；缺发布代表集 smoke | `MANUAL_REQUIRED` |
| AC-REQ-004-01..04 | REQ-004 | BFF 登录 gate、BiSheng permission/tenant/file/space/换用户矩阵和 UI `canDownload` 契约 | `PASS` |
| AC-REQ-005-01 | REQ-005 | 匿名分享可查看文件元数据/摘要但无 grant；下载及 preview/content/chunks 要求登录，切换登录不可重放 | `PASS` |
| AC-REQ-005-02 | REQ-005 | claims/domain key/用户租户目标绑定；TTL 有界且 `exp <= share expiry` | `PASS` |
| AC-REQ-005-03 | REQ-005 | 撤销、到期、view-only、部门变化实时复核 | `PASS` |
| AC-REQ-005-04 | REQ-005 | Redis 跨 Worker store；公开 DTO/URL/frontend 无 grant；生产 Redis fail closed | `PASS` |
| AC-REQ-005-05 | REQ-005 | 篡改、wrong-purpose、跨用户/租户/分享/文件、过期和 anonymous-to-login replay 拒绝 | `PASS` |
| AC-REQ-006-01 | REQ-006 | Portal Search/List/Detail 与 BiSheng 文件行/预览/版本历史 loading、disabled、防重复、错误恢复、Blob anchor/revoke | `PASS` |
| AC-REQ-006-02 | REQ-006 | PDF 就绪 300 秒与水印 60 秒分阶段 deadline/504；超时线程结束前保持文件锁 | `PASS` |
| AC-REQ-006-03 | REQ-006 | success/error/timeout/disconnect cleanup 与 MinIO 只读测试；缺真实浏览器断连观察 | `MANUAL_REQUIRED` |
| AC-REQ-006-04 | REQ-006 | 进程并发 2、同用户 Redis ownership lock、429 和 TTL 恢复测试；缺发布环境真实并发压测 | `MANUAL_REQUIRED` |
| AC-REQ-006-05 | REQ-006 | BFF 370 秒专用 timeout、chunked 转发、取消/错误路径 `aclose()` | `PASS` |
| AC-REQ-007-01..04 | REQ-007 | 两个二进制 endpoint、安全 header/中文文件名、错误矩阵、首块一次遥测、前端无重复事件、13 入口归一 | `PASS` |
| AC-REQ-008-01..04 | REQ-008 | 依赖/部署 diff、旧单文件路径二进制收口、非门户批量契约、release contract、F063 只读和脏文件避让 | `PASS` |
| AC-REQ-009-01..04 | REQ-009 | 门户表格/卡片文件夹下载隐藏，批量下载继续隐藏；共享组件默认 `hideFolderDownload=false`，非门户能力保持 | `PASS` |
| AC-REQ-010-01..04 | REQ-010 | 文件列表、门户原地预览、收藏源空间、独立预览、版本历史 ID、Blob 文件名/错误、pending 和旧 URL 源码扫描 | `PASS` |
| AC-REQ-011-01 | REQ-011 | Portal 唯一 DetailPage 预览层接入；搜索/列表 iframe 复用；formatter/source/build 通过；各 viewer 实际视觉待验 | `MANUAL_REQUIRED` |
| AC-REQ-011-02 | REQ-011 | BiSheng `FilePreview`/`RichKnowledgePreview` 基础层接入，五类知识入口 import graph 覆盖；实际普通/富媒体视觉待验 | `MANUAL_REQUIRED` |
| AC-REQ-011-03 | REQ-011 | `/user/info`、Portal auth 与两端 deterministic formatter 验证独立主部门、姓名、`external_id`、账号回退、有/无主部门、Asia/Shanghai 固定日期、两行内容及旧文案缺失；CSS/DOM 交互隔离保持 | `PASS` |
| AC-REQ-011-04 | REQ-011 | 匿名分享 meta/access/detail/摘要 200；preview/content/chunks 401、统一提示且 BiSheng 上游调用为零；Portal 源码契约不发正文请求 | `PASS` |
| AC-REQ-011-05 | REQ-011 | 下载/预览目标回归与生产构建通过；接线仅限知识预览基础层；CSS 绕过能力边界已写入 requirements/design/security review | `PASS` |
| AC-REQ-011-06 | REQ-011 | 两端 Provider/overlay 分离、PDF 单页/画布与其他格式正文 surface 源码契约、定向测试、静态检查和生产构建通过；真实浏览器边界目检待执行 | `MANUAL_REQUIRED` |
| AC-REQ-011-07 | REQ-011 | 两端旋转包围盒纯函数、`240px × 180px` 最小单元、`48px/36px` 留白、长字段扩展、奇偶行半步错位、全尺寸 SVG 独立坐标、等效字体/字号/最终 `/` 方向/`0.31`/颜色与生产构建均通过；真实完整入口视觉对比待执行 | `MANUAL_REQUIRED` |
| AC-REQ-011-08 | REQ-011 | 两端目标测试验证 surface 坐标、ResizeObserver 重铺、无 `<pattern>/<rect>` 且每组固定两行；本地浏览器普通/长身份 visual fixture 验证正文内部无切片、仅真实外边缘裁剪；真实 Portal/BiSheng 完整入口仍待 T030 | `MANUAL_REQUIRED` |
| AC-REQ-012-01 | REQ-012 | Portal 条件 `!isSmartAppsMode || hasConversation` 源码/目标测试、`/apps` 初始态浏览器 overlay=0 与生产构建；登录会话态视觉仍待验 | `MANUAL_REQUIRED` |
| AC-REQ-012-02 | REQ-012 | Portal URL iframe 宿主单层 overlay、workflow iframe 宿主无 overlay 的源码测试；真实登录态 iframe 视觉待验 | `MANUAL_REQUIRED` |
| AC-REQ-012-03 | REQ-012 | BiSheng 通用 surface 运行时测试；主问答、App/Agent、知识空间、单文档、订阅入口源码接线与生产构建 | `PASS` |
| AC-REQ-012-04 | REQ-012 | AiChatMessages 空/加载/消息三分支、Landing/ChatEmptyState 欢迎态与错误消息同正文 surface 接线测试 | `PASS` |
| AC-REQ-012-05 | REQ-012 | header/input/history/citation 处于 surface 外的结构测试与源码审计；真实交互视觉待验 | `MANUAL_REQUIRED` |
| AC-REQ-012-06 | REQ-012 | `user && !shareToken`、`user && !isGuestMode && !readOnly`、ShareView 默认关闭及 Portal `user=null` 无 overlay 测试/浏览器审计 | `PASS` |
| AC-REQ-012-07 | REQ-012 | 复用两端现有身份/date/layout，SVG `fillOpacity={layout.opacity}` 且唯一值 `0.31`，目标预览回归通过 | `PASS` |
| AC-REQ-012-08 | REQ-012 | overlay `pointer-events:none/user-select:none/aria-hidden`、surface `overflow-hidden`、ResizeObserver 与生产构建通过；真实长会话滚动/resize 待验 | `MANUAL_REQUIRED` |

## 安全复核 Security Review

- grant 使用从现有 JWT secret 域分离派生的签名 key，限制算法、audience、purpose、版本、用户、租户、分享、空间、文件、下载权限、过期时间与 jti。
- grant 仅由 BiSheng 返回给 Portal BFF，并保存在 Redis v2 服务端会话；浏览器只持有 HttpOnly share session cookie，公开 JSON、URL、frontend 类型和日志均不包含 grant。
- 分享下载先校验当前门户登录 session 与 Redis session 绑定，再由 BiSheng 验签，并实时检查分享链接状态、到期、下载权限和部门范围。
- 普通下载在 BiSheng 重新执行当前租户、文件归属和 `download_file` 权限；前端 `canDownload` 仅控制展示，不是授权终点。
- 旧 `/knowledge/space/{space_id}/files/{file_id}/download` 仅保留 URL 路径兼容性，已改为注入同一 `PortalPdfDownloadService`；路径参数由整数类型校验，入口值按枚举归一，响应不再暴露对象地址、原文件 URL 或预览 URL。
- BFF 仅转发白名单响应头，强制 `application/pdf`、`private, no-store` 和 `nosniff`；500 使用通用文案，临时路径、对象名、水印身份及 grant 不进入客户端错误。
- 水印 Worker 环境变量白名单化，身份 spec 仅通过 stdin 传递；stderr 固定为通用错误；个人水印文件只存在于隔离临时目录并在全部受测终止路径清理。
- 安全复核发现并已修复：分享 grant 原固定 TTL 未钳制到分享链接到期点；实际下载只携带 grant 时 verifier 的 `share_token` 参数误设为必填。两项均有回归测试。
- 生命周期复核发现并已修复：生成任务取消使用 `asyncio.CancelledError`，原普通异常分支无法清理；现已在保持取消传播的同时释放临时目录、用户锁和进程容量。
- Portal BFF 三条预览正文路由在分享 session 检查和 BiSheng 调用前执行登录门禁；匿名直接请求无法通过已验证 share cookie 绕过，文件 detail/摘要 endpoint 保持可用。
- 预览水印身份仅来自 Portal `PortalUser` 或 BiSheng Recoil `store.user`，不接受 URL/文件参数，不持久化、不上传且不进入日志；覆盖层 `pointer-events:none`、`user-select:none`、`aria-hidden=true`。
- 主部门只由 BiSheng 当前用户的 `user_department.is_primary=1` 关系解析；下载服务使用参数化 ORM 查询，Portal/BiSheng 前端只消费当前用户接口返回值，客户端不能提交或覆盖水印身份；未新增 secret、日志字段或跨用户组织数据接口。
- 用户账号由下载服务读取当前用户记录的 `external_id`，遗留空值仅回退当前认证账号；预览只消费当前登录会话的同源字段，URL、文件元数据和请求参数均不能覆盖水印身份。
- 自适应布局只使用当前身份文字的长度和公开视觉 token 计算单元，不记录、不上传、不输出测量文本；前端 SVG 文字由 React 转义，未引入 `innerHTML`、Canvas 位图导出或新的网络请求。
- PDF 字体只从 WQY Zen Hei/Micro Hei、Noto Sans CJK、PingFang/STHeiti 等黑体候选解析；仓库自带 Noto Sans 作为最终可靠兜底，所有候选不可用时明确失败。已移除可能静默生成缺字正文的 PyMuPDF `china-s` 内置兜底。
- CSS 水印属于可见追溯提示，不是 DRM；授权用户可通过禁用样式、删除 DOM、开发者工具或截图裁剪绕过。下载 PDF 的服务端不可编辑水印保持原安全边界；如需更强预览控制必须另立服务端栅格化/流媒体方案。
- 问答水印复用当前登录用户状态，不接受会话消息、iframe URL、query 参数或应用配置提供身份；Portal 匿名用户和 BiSheng guest/share/readOnly 入口不实例化实际水印，第三方 URL iframe 仅由 Portal 宿主覆盖，认证 workflow iframe 仅由 BiSheng 子页面覆盖。

## 人工验证 Manual Verification

| Acceptance | Manual Steps | Expected Result | Status |
|---|---|---|---|
| AC-REQ-003-01/04 | 用中文、多页、横向、旋转、复杂内容代表 PDF 在浏览器下载并逐页目检 | 两行水印为“主部门-姓名--用户账号-YYYY/MM/DD / 首钢股份内部资料，严禁外传，违者必究”，方向为左下向右上 `/`，平铺、半透明且可辨识；无主部门显示“姓名--用户账号-YYYY/MM/DD”；原内容、页数、尺寸和方向保持 | `NOT_RUN` |
| AC-REQ-004/005 | A/B 用户、view-only、公共/部门分享、撤销/到期、匿名后登录重新验证 | 无权限/跨用户/失效分享均拒绝；允许用户下载水印身份与当前登录人一致 | `NOT_RUN` |
| AC-REQ-006-02..05 | 代表性 50 MB/高页数文件；两个并发、第三个请求；慢任务；下载中断浏览器连接 | 性能可接受；容量 2 与同用户限制生效；超时 504；断连后临时目录、锁和上游连接释放 | `NOT_RUN` |
| AC-REQ-001/007/009/010 | 在首页、搜索、知识列表、详情、相关推荐、专家问答、QA 引用、分享及 BiSheng 门户列表/预览/收藏/版本历史入口下载 | 全部单文件保存为 `.pdf` 且有水印；错误中文；无重复成功事件；门户无批量下载且文件夹行/卡片不显示下载 | `NOT_RUN` |
| AC-REQ-011-01/02/03/06/07/08 | 分别在 Portal 详情/搜索/列表弹窗与 BiSheng 独立/门户/收藏/版本对比/知识引用打开 PDF、Office、表格、Markdown/HTML、文本、图片、chunks、web 和音视频预览；重点检查首页和知识库 TXT/PDF；使用有主部门/无主部门及长账号用户并拉伸窗口、滚动长文档 | 所有知识正文有两行平铺水印，身份/账号、`YYYY/MM/DD` 北京日期与固定提示正确；黑体、字号、顺序、最终 `/` 方向、`0.31` 和密度与下载 PDF 等效，长字段自动扩距且相邻水印不重叠；正文内部每组两行完整，仅真实正文边缘裁剪；水印只在白色正文、单个 PDF 页面或媒体内容内，灰色页边、滚动空白和工具栏无水印 | `NOT_RUN` |
| AC-REQ-011-02/05 | 操作文档滚动、缩放、分页、表格、链接、音视频播放/拖动；再打开聊天上传、SOP、Artifact 和非知识预览 | 所有 viewer 控件正常；非知识预览无本 Feature 水印 | `NOT_RUN` |
| AC-REQ-011-04 | 匿名完成公共分享验证后查看页面并直接请求三个正文接口，再登录重试 | 匿名仍见元数据/AI 概览与“登录后预览”；三个接口 401；登录后预览正常并显示本人水印 | `NOT_RUN` |
| AC-REQ-012-01..08 | 用有主部门、无主部门和长账号用户分别打开 Portal 智能问答/写作、URL 应用、workflow，以及 BiSheng 主问答、App、Agent、知识空间、单文档、订阅文章/频道；覆盖空、加载、生成、错误、长会话滚动、resize 和移动端；另测 guest/share/readOnly | 水印只固定覆盖可见问答正文，标题/导航/历史/输入/引用面板无水印；文本、日期、方向、密度、透明度与预览一致；URL/workflow 各仅一层；guest/share/readOnly 无水印且所有交互可用 | `NOT_RUN` |

## 失败与缺口 Failures and Gaps

- 本次 T089-T092 pattern 切片修复的 BiSheng client `2 passed`、Portal frontend `4 passed`，目标 ESLint/import、两端生产构建、本地浏览器普通/长身份渲染和 diff 审计通过；未发现本扩展目标自动化失败。
- T085-T088 新口径扩展的后端 `57 passed`、BiSheng client `2 passed`、Portal frontend `4 passed`，目标 Ruff/compileall、ESLint/import、两端生产构建和 Poppler 普通/长身份渲染通过；未发现该扩展目标自动化失败。
- 本次中等增密扩展的后端 `57 passed`、BiSheng client `2 passed`、Portal frontend `4 passed`，目标 Ruff/compileall、ESLint/import、两端生产构建、Poppler 普通/长身份 PDF 渲染均通过；未发现本扩展目标自动化失败。
- 本机 Poppler 输出一次 Fontconfig 默认配置缺失提示，但嵌入黑体后的 PNG 生成成功且中英文正文、水印均完整；部署镜像已安装/复制字体并执行 `fc-cache`，真实镜像仍由 T030 smoke 确认。
- 本轮 Portal frontend test TypeScript 编译仍被既有 QA 模板夹具缺 `homeIcon/description` 与 `portalContentConfig.test.ts` 的旧 `fetchHomeContent` 引用阻断；目标预览 Node test `4 passed`，应用 TypeScript/Vite build 通过。
- 本轮 BiSheng client `knowledge.test.ts` 整文件有 2 个既有 folder mutation 断言失败；按 `downloadWatermarkedKnowledgeFileApi` 定向运行 `4 passed, 33 skipped`。
- Portal BFF 全量结果为 `397 passed, 16 failed`；16 项均属于实施前已登记的 admin config、首页统计、聊天/搜索和 async favorite 基线问题，F064 最新 41 项目标矩阵通过。
- Portal frontend 全量 test TypeScript 编译仍被既有 QA 模板夹具字段缺失和 `fetchHomeContent` 旧引用阻断；预览扩展 11 项定向测试、既有下载 14 项目标测试、目标 ESLint 和生产构建通过。
- Portal frontend 全量 lint 为 `13 errors, 6 warnings`；F064 核心新增文件目标 lint 通过。Expert QA 文件的历史 lint 行仍存在，但本次结构化知识链接修改通过生产构建和源码目标测试。
- BiSheng client 本次联合运行中的 PortalKnowledgeWorkbench 整文件为 `95 failed, 10 passed`，失败统一源于既有测试 harness 未为新 `useAuthContext` 提供 `AuthProvider`；水印与独立预览两个目标文件 `3 passed`，源码契约定向 `2 passed`，CI 构建和 import check 通过，未扩大修复无关 harness。
- 当前本机 Node `20.13.1` 低于 Vite 推荐的 `20.19+`，但 Portal frontend 本次生产构建成功；部署环境应使用项目要求的 Node 版本。
- 本次问答扩展目标测试和两端生产构建均通过；Portal 目标 ESLint 仍命中 `AppsPage.tsx` 既有 `react-refresh/only-export-components` 错误和 `QAPage.tsx` 既有 Hook 依赖警告。本地浏览器仅具匿名 Portal 会话，已验证匿名不渲染实际水印、正文 surface 几何与输入框排除；Chrome 既有登录会话不可用，故 T098 的登录态、多入口、桌面/移动和长会话视觉未伪报完成。
- T099-T102 bugfix 的失败回归、最小修复、`57 passed` 后端矩阵、两端 `7 passed` 水印目标测试、Ruff/compileall/import check 与两端生产构建均通过；本地 `/apps` 初始态实际 overlay 为 0。浏览器没有可发送问答的登录态，因此 T102 仍保留“智能写作进入会话后显示水印”的视觉子项，未标记完成。
- T103-T105 已将四端透明度统一为 `0.31`：三端旧值失败回归、后端 `58 passed`、Portal/BiSheng 各 `7 passed`、静态检查、导入检查和两端生产构建通过；最新加深效果尚未在真实登录态完整入口和代表下载 PDF 中目检，继续由 T030/T098/T102 覆盖。
- T030 尚未执行，特别是真实缺失/损坏产物的请求内修复、完整 Portal/BiSheng 业务入口的下载/预览水印视觉与交互、匿名浏览器流程、非知识范围、50 MB、同文件并发复用、并发 2/429、300+60 秒/504、浏览器断连与发布环境权限矩阵。
- 规格目录受仓库 `.gitignore` 的 `features/` 规则忽略；文档已在工作区更新，但不会出现在普通 `git status` 中。

## 验证质量门 Verification Quality Gate

- [x] 每个验收标准均有 `PASS` 或 `MANUAL_REQUIRED` 状态。
- [x] 所有自动化完成声明都有本轮实际执行证据。
- [x] 目标测试、静态检查、构建、兼容性和安全边界均已验证。
- [x] 全量历史失败与目标测试结论分开记录，没有伪报全仓绿色。
- [ ] T030 人工门禁尚未执行，Feature 不得标记为 `VERIFIED`。
