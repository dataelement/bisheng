# 专家问答搜索筛选验证记录

Date: 2026-10-14
Design status: VERIFIED_LOCAL
Feature implementation status: VERIFIED_LOCAL

## 本轮验证范围

用户已审阅页面稿并明确要求开始实施、接入真实接口。T001/T002 已完成本地实现；以下记录先列正式实现证据，保留之前设计阶段的历史证据。

## 正式实现结果

| Evidence | Result | 命令 / 实际结果 | 覆盖 |
|---|---|---|---|
| E-QUERY-API | PASS | 后端 `.venv/bin/python -m pytest test/qa_expert/test_question_search_filters.py test/qa_expert/test_question_api.py test/qa_expert/test_question_service.py test/qa_expert/test_expert_management_list.py test/qa_expert/test_dictionary_options.py test/qa_expert/test_anonymous_alias.py test/qa_expert/test_negative_guards.py -q --disable-warnings`：72 passed | AC-001/002/003/004/007 |
| E-BROWSER | PASS | 前端 Node v24.19.0 运行 `scripts/expertQaScroll.browser.test.mjs`：四种视口、三栏独立滚动、搜索提交、真实契约参数、五项职业条件、日期、清空、分页及失败重试通过 | AC-005/006 |
| E-BUILD | PASS | 前端 `npm run build` 成功，2377 个模块，1.62 秒；含现有大包提示 | 正式页面及组件类型/构建 |
| E-STATIC | PASS | 前端定向 ESLint 和相关 diff 空白检查通过；新增后端测试及 endpoints/services 的 Ruff 检查通过 | 新增代码质量 |
| E-STATIC-BASELINE | BASELINE_UNCHANGED | `repositories.py` 原有 1 项、`schemas.py` 原有 31 项 Ruff 问题；与 HEAD 对照，无新增问题 | 不顺手改无关旧代码 |

E-QUERY-API 在独立内存 SQLite 执行真实 ORM 查询；`test_http_search_filters_query_real_database` 通过真实 FastAPI 路由、QuestionService 和 QuestionRepository 验证查询和分页。身份展示的外部账号依赖被隔离，不连接业务数据库；不是用 Mock 返回问题查询结果。

E-BROWSER 加载正式 `ExpertQAPage`、PageShell 和搜索组件，通过受控响应验证真实 API 参数。专家候选跨 6 页读取到第 503 个停用档案；下拉不截断在前 500 个。验证了同一请求携带部门/岗位/职务/职位族/职位类、个人范围与状态组合、嵌套浮层在窄屏不裁切；慢旧请求迟到不会覆盖新结果。

正式页面浏览器截图：`/tmp/expert-qa-search-live.png`、`/tmp/expert-qa-search-live-mobile.png`。已查看桌面截图，搜索筛选区与三栏保持对齐。

## 未验证和部署边界

- 尚未部署、提交或推送。本地门户现在调用真实 `/workspace/api/v1/qa_experts/questions` 和专家选项接口，不使用页面稿示例数据。
- 上线必须先更新 BiSheng 后端，再更新门户前端；旧后端不支持本次新增参数，不能只发布前端。
- SQLite 的查询/接口验证不替代真实 MySQL/DM8 方言运行及业务数据规模性能验证；这些需部署环境联调。本轮无数据库表迁移和线上数据修改。
- 原有开发环境 Ruff 问题和构建大包提示保留，未扩大修复范围。

## 设计阶段历史证据

页面稿路径：`/Users/wenruli/code/project/bisheng/shougang-group-knowledge-portal/frontend/designs/expert-qa-search/`。

执行目录为门户 `frontend/`，使用 Node v24.19.0：

```sh
node node_modules/typescript/bin/tsc -p designs/expert-qa-search/tsconfig.json
node node_modules/vite/bin/vite.js build --config designs/expert-qa-search/vite.config.mjs
node node_modules/eslint/bin/eslint.js designs/expert-qa-search/App.tsx designs/expert-qa-search/main.tsx designs/expert-qa-search/components.tsx designs/expert-qa-search/model.ts designs/expert-qa-search/verify.mjs designs/expert-qa-search/vite.config.mjs
node designs/expert-qa-search/verify.mjs
```

## 实际结果

| Evidence | Result | 已获得的证据 | 限制 |
|---|---|---|---|
| V-DESIGN-TYPES | PASS | 页面稿 TypeScript 检查及定向 ESLint 无错误 | 不等于正式接口类型已接入 |
| V-DESIGN-BUILD | PASS | Vite 页面稿构建成功，1726 个模块 | 构建产物在 `/tmp/expert-qa-search-design-build`，未发布 |
| V-DESIGN-LAYOUT | PASS | 1920×900、1280×720、800×600、390×844，搜索/排序/两侧标题保持原位，正文与侧栏独立滚动；更多浮层在视口内，展开及标签出现不增加列表顶部偏移 | Chrome 本地设计预览 |
| V-DESIGN-INTERACTION | PASS | 关键词草稿与提交分离、答案命中、受邀未回答、业务域双向同步、同一专家条件、单标签删除、日期错误/端点、清空、个人范围、分页归零、冲突状态处理、Escape 返回焦点 | 仅示例查询，不证明后端权限/租户/分页正确 |
| V-QUERY / V-FIELDS / V-API / V-ACCESS | PASS | 当前正式实现证据见 E-QUERY-API | SQLite + 真实 API 链路，业务库未联调 |

## 视觉检查

已打开检查桌面默认图、更多筛选展开图及手机展开图：保留门户蓝色视觉和三栏结构，固定区采用两行；手机“更多筛选”独立固定在该行右侧，可直接点击。

页面稿 `previews/` 输出：`desktop.png`、`compact.png`、`tablet.png`、`mobile.png`、`desktop-more-filters.png`、`mobile-more-filters.png`、`selected-filters.png`。

本地预览服务：`http://127.0.0.1:3008/`。设计说明见 [frontend-design.md](./frontend-design.md)。

页面稿仍保留示例数据作为设计评审材料。正式组件已经使用可搜索下拉并接入真实参数；T001/T002 的完成状态以本轮实现证据为准。
