# 专家问答搜索与组合筛选设计

Feature ID: F083-qa-search-filters
Status: VERIFIED_LOCAL
Related requirements: [requirements.md](./requirements.md)

## 现状与依据

- 门户 `frontend/src/pages/ExpertQAPage.tsx` 维护业务域、状态、排序和分页，通过 `frontend/src/api/expertQa.ts::fetchExpertQuestions` 请求 `/workspace/api/v1/qa_experts/questions`。
- `bisheng/qa_expert/api/endpoints.py::list_questions` → `QuestionService.list_questions` → `QuestionRepository.list_all`；当前 `keyword` 只对 `Question.title` 模糊匹配。
- `qa_question_invite` 有 `question_id/expert_id/user_id`。邀请关系是人员筛选的来源，不要求存在回答；不使用回答计数或榜单前 8 人替代邀请关系。
- `ExpertService.list_filter_options` 和专家列表已处理主部门向公司/部门展示组织归并，以及职业字典编码/显示文本兼容；复用该口径，避免重新按组织名称猜测。
- 门户已有固定三栏和独立滚动，左侧业务域标题、右侧榜单标题在内容滚动容器外。

## 接口与查询

保留 GET `/qa_experts/questions` 及既有响应，增量可选参数：

| 参数 | 含义 |
|---|---|
| `keyword` | 问题标题/描述、有效回答内容、可展示专家姓名的关键词 |
| `invited_expert_id` | 被邀请专家档案 ID |
| `department_id` | 受邀专家所属展示部门 ID |
| `major` / `position` | 岗位 / 职务字典编码，沿用门户管理页映射 |
| `job_family` / `job_category` | 职位族 / 职位类字典编码 |
| `asked_from` / `asked_to` | ISO 日期，按北京时间包含起止日 |

既有 `domain/display_status/filter/sort_by/page/page_size` 保留；新字段未传时维持原行为。状态文案“已回答未解决”映射 `display_status=pending_adopt`，不增加新状态枚举。

服务层复用专家部门及职业字段解析，得到符合全部人员条件的专家集合；仓储通过邀请关系子查询限制问题，空集合明确返回无匹配。关键词采用 OR，结构化条件采用 AND，全部在分页前生效。计数复用同一条件，返回每问题一行；禁止取一页后前端过滤或取全量问题再分页。

有效回答正文检索不匹配 `status=ANSWER_STATUS_DELETED`。专家姓名检索包括已显示的受邀专家及回答专家；回答姓名部分沿用身份展示规则，普通用户不得使用被匿名隐藏的真实姓名命中。定向可见性和自动租户条件仍应用在完整查询上，不以搜索为由放宽。

日期转为北京时间的起日零点与止日次日零点，使用 `created_at >= start` 和 `created_at < end`；只填写一端时只应用对应边界。前后端都验证顺序。

专家选项按接口分页读取完整候选范围，包含历史停用专家，不能仅用专家榜单或任意前 500 条截断冒充完整选项。职业/部门下拉复用 `experts/filter-options`；失败时展示重试，不能使用占位选项伪装成功。

## 前端交互与布局

详细页面结构、组件 Props、条件联动、浮层及窄屏设计见 [frontend-design.md](./frontend-design.md)。用户审阅页面稿后确认开始实施，正式前后端接口已在本地接入。

- 在横幅和三栏之间增加独立的 `ExpertQaSearchFilters` 组件。搜索行包含关键词输入、搜索、清空及“我要提问”；原横幅中的提问按钮移动到搜索行，避免重复占用高度。
- 筛选行包含业务域、状态、受邀专家、起止日期、部门、岗位、职务、职位族、职位类；使用可访问的标签和下拉控件，长选项可搜索。业务域与左侧选项保持同步。
- 搜索文本区分草稿与已提交关键词；回车/按钮提交。结构化条件即时生效，日期非法时阻止提交并显示提示。
- 左侧“我提问的/邀请我的”作为独立个人范围，与上方状态及人员条件组合；不再让状态和个人范围互斥。
- 筛选修改同时重置 `page=1`；问题滚动容器的重置键包含完整生效条件，旧请求继续使用 AbortController 和 active 标记隔离。
- 搜索筛选组件占固定区域，三栏容器使用剩余高度；采用紧凑横幅和控件间距，窄屏控件横向滚动或折叠更多筛选，避免固定区域吃完列表空间。保留既有业务域、榜单标题固定行为。
- 空结果显示“未找到符合条件的问题”和清空入口；请求失败显示重试，不自动清空用户条件。

## 文件计划 File Structure Plan

后端相对于 `src/backend/`，前端相对于门户仓库根目录：

| Path | Action | Responsibility | Requirement |
|---|---|---|---|
| `bisheng/qa_expert/domain/schemas.py` | modify | 新查询字段与日期验证 | REQ-002, REQ-003 |
| `bisheng/qa_expert/api/endpoints.py` | modify | 查询条件透传 | REQ-001, REQ-002, REQ-003 |
| `bisheng/qa_expert/domain/services.py` | modify | 专家字段解析与身份查询上下文 | REQ-002, REQ-006 |
| `bisheng/qa_expert/domain/repositories.py` | modify | 内容搜索、邀请条件、时间和分页计数 | REQ-001, REQ-002, REQ-003, REQ-006 |
| `test/qa_expert/test_question_search_filters.py` | create | 组合查询、日期、计数和拒绝路径 | REQ-001, REQ-002, REQ-003, REQ-006 |
| `test/qa_expert/test_question_api.py` | modify | 参数透传及非法参数 | REQ-003, REQ-004 |
| `frontend/src/api/expertQa.ts` | modify | 参数类型、序列化及选项读取 | REQ-002, REQ-004 |
| `frontend/src/components/ExpertQaSearchFilters.tsx` / `.module.css` | create | 搜索筛选控件与响应式布局 | REQ-004, REQ-005 |
| `frontend/src/utils/expertQaSearch.ts` | create | 查询类型和真实筛选选项的展示映射 | REQ-002, REQ-004 |
| `frontend/src/pages/ExpertQAPage.tsx` / `.module.css` | modify | 列表状态、条件组合、固定布局 | REQ-004, REQ-005, REQ-006 |
| `frontend/scripts/expertQaScroll.browser.test.mjs` | modify | 固定布局、请求行为、筛选清空与失败回归 | REQ-004, REQ-005, REQ-006 |

不新增依赖、数据库表或权限策略，不改课程页、手册、问答附件、其他工作区改动。后端实际 API 条件和受控浏览器接口都使用同一参数契约。

实现说明：子查询和计数使用既有 `build_tenant_filter_clause`，与统一租户事件保持同一规则，避免子查询内部表未被外层事件识别。前端更多筛选的五个字段都使用可搜索单选浮层，替代页面稿的少量原生示例选项。加载/失败提示放在操作区间隙，保持控件加载期间的列表顶部位置。

## 验证和交付

| Evidence | Scope | Target |
|---|---|---|
| V-QUERY | 查询行为 | AC-001, AC-002, AC-004 |
| V-FIELDS | 组织及职业字段解析 | AC-003 |
| V-API | 参数契约和非法日期 | AC-004 |
| V-ACCESS | 可见性、匿名、租户条件 | AC-007 |
| V-BROWSER | 真实页面的搜索筛选操作、清空、分页、加载失败、三种桌面/窄屏视口和截图 | AC-005, AC-006 |

复用 `test/qa_expert` 现有夹具和门户 Vite/Playwright 脚本。后端选择能执行真实 ORM 查询的隔离夹具；若本地数据库依赖不可用，记录限制，不能把 Mock 透传称为数据库验证。执行受影响范围的 pytest、ruff、前端构建和浏览器测试，记录 `verification.md`；实际 DM8 和线上性能联调单列未验证项。

发布顺序为后端后门户。回退本次源代码并重新发布即可；不涉及数据回退。最终只交付本地修改与证据，提交、推送和部署另按用户要求执行。
