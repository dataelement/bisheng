# ID 检索开发计划

> 执行方式：使用 superpowers:executing-plans 在当前会话按任务顺序执行。项目 SDD 的 spec/design 确认已完成，tasks 自动评审，不增加新的规格或设计确认关卡。

**Goal**：现有授权与用户检索入口支持 ID 完整值和前缀，同时保留已有名称检索性能优化。
**Architecture**：直接扩展既有接口，沿原业务服务与范围约束查询；名称和 ID 分支在数据库合并去重、排序后分页。权限经已有主体目录端口取数，查询归所属 Repository；不新增目录子系统、版本协商或授权复检机制。
**Tech Stack**：现有 FastAPI、SQLAlchemy/SQLModel、pytest、MySQL/DM8、两端 React/TypeScript 与原组件库。
**Spec**：[spec.md](./spec.md) · [design.md](./design.md)。当前分支 `feat/cofco-1021-3.0.0-beta1`。

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已确认 | 已同步本轮完整 ID＋前缀口径 |
| design.md | ✅ 已确认 | 第三版；用户回复“OK，列计划开发” |
| tasks.md | ✅ 已拆解 | 评审见 tasks-review.md |
| 实现 | ✅ T001–T015 已实现 | 已完成代码审查及本地后端回归；实际文件落点见 design §8 |
| 验收 | 部分完成 | T016 真实 API/页面、T017 双库性能及前端 CI 仍待执行 |

## 全局约束

- 用户/部门检索 external_id，用户组检索原数字 ID 的文本前缀；完整 ID 优先，内部稳定 ID 才是提交身份。
- 原名称前缀不改包含，原名称包含不缩成前缀；不新增全量组织加载、长 IN 集合、GROUP BY 或逐行补部门查询。
- 所有范围和隐藏/禁用状态遵守原入口，不将资源管理权限替换为组织管理权限。
- 空候选约束与不限定候选必须区分；空 ID 可按名称查找，不回填业务数据。
- Endpoint → Service → Repository；不新增 DAO 或权限域的业务 ORM 查询。
- 不增加查询模式、能力接口、响应标记、开关、check 接口、写入语义或新前端依赖。
- 前后端同版更新；仅在必要时补查询索引，无业务数据迁移。
- 用户后续明确要求“开发完统一测试”，覆盖原测试先行顺序；后端实现后统一回归；前端遵照用户约定，默认不本地运行测试、lint、typecheck、构建，依靠手动清单及镜像/CI 验证，不能宣称未执行项通过。
- 保留工作区已有其他文档改动，不自动合并、部署或提交无关文件。实现期间小步记录完成证据，合并/部署不在当前计划内。

## Review Focus

1. `jia` 命中 `jia0100`，`0100` 不凭中段命中；`JIA` 不凭 ID 命中小写 ID，但名称按原大小写规则判断。由 T001/T003 验证。
2. 同一 external_id 在不同来源属于不同稳定用户；同一用户命中名称和 ID 只能出现一次。由 T003/T008 验证。
3. 空的允许用户集合不能退化为无限制查询；没有组织管理角色的资源管理员仍按资源候选范围选人。由 T003/T008 验证。
4. ID 精确命中不能被分页/树种子截断挤掉；越界页不返回伪 total=0。由 T003/T008 验证。
5. 前端取消请求不等于数据库停止扫描；既有索引、去分组、窗口计数与完整请求性能必须实测。由 T017 验证。

## Wave 1：先验证基础规则与查询

### T001 — 后端：纯规则失败测试

- [ ] 新建 `src/backend/test/common/test_subject_search.py`，覆盖规范化、255 code point 边界、非 BMP、换行、字面通配符、用户组数字前缀区间。测试只导入未来的纯函数，不模拟返回业务结果。
- [ ] 用 `uv run pytest test/common/test_subject_search.py -q` 观察缺失实现的失败。

接口约定：`normalize_keyword(value: str) -> str`、`escape_like(value: str) -> str`、`numeric_prefix_ranges(value: str, max_value: int) -> list[tuple[int, int]]`。数值区间只接受规范十进制前缀，不把 `01` 转成 `1`。

```python
def test_numeric_prefix_does_not_drop_leading_zero():
    assert numeric_prefix_ranges("01", max_value=2147483647) == []

def test_newline_and_outer_space():
    assert normalize_keyword("  jia\r\n0100  ") == "jia 0100"
```

覆盖 AC: AC-03, AC-04, AC-11, AC-12。
依赖：无。预期：因生产函数缺失失败，不允许因测试框架或配置错误冒充红灯。

### T002 — 后端：实现纯函数与方言表达式

- [ ] 新建 `src/backend/bisheng/common/subject_search.py` 实现 T001 接口；不引用 domain。
- [ ] 在 `src/backend/test/database/test_dm_dialect_helpers.py` 先补精确/前缀比较的 MySQL/DM SQL 编译失败测试，再扩展 `src/backend/bisheng/core/database/dialect_helpers.py`。
- [ ] 保留可索引的原列前缀条件，大小写精确判断只做残余筛选；所有值使用绑定参数，转义符显式声明。
- [ ] 运行 T001 及方言测试至通过，随后对这两个改动 Python 文件执行 ruff。

输出：纯函数，以及 `case_sensitive_prefix(column, keyword)`、`case_sensitive_equals(column, keyword)` SQLAlchemy 表达式，供 Repository 使用。
依赖：T001。预期：规则/编译测试通过；编译通过不等同 DM 实际执行通过。

### T003 — 后端：用户/部门候选查询失败测试

- [ ] 新建 `src/backend/test/user/test_subject_search_repository.py`、`src/backend/test/department/test_subject_search_repository.py`。
- [ ] 复用现有 `test_global_members_search.py` 的 SQLite 真实 SQL fixture 思路，仅替换会话/鉴权依赖；验证最终结果而不是只断言 mock 被调用。
- [ ] 数据包括同名不同 ID、跨来源同业务 ID、空 ID、大小写、前导零、特殊字符、跨租户、空允许集合、用户主/次部门、完整命中位于截断边界后、空页。
- [ ] 先运行两份测试观察正确失败，再进入 T004。

覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-10, AC-16, AC-17, AC-23。
依赖：T002。预期：因新查询缺失而失败。

### T004 — 后端：最小用户/部门查询实现

- [ ] 在 `src/backend/bisheng/user/domain/repositories/subject_search_repository.py` 与 `src/backend/bisheng/department/domain/repositories/subject_search_repository.py` 实现 T003 需要的查询。
- [ ] 保持范围由调用方服务提供，不在 Repository 做鉴权；参数中的允许集合以 None 表示不额外限定、空集合表示零候选。
- [ ] 名称/ID 两路共享同一冻结范围，按稳定 ID 合并去重后排序/分页；主属部门可放置过滤早于树种子截断，精确命中优先。
- [ ] 保留原页面输出结构、排序与窗口计数；空页必要计数，不恢复冗余 GROUP BY。
- [ ] 运行 T003 测试至通过；保存 SQL 编译输出用于索引计划核对。

输出：由现有用户/部门业务 Service 调用的查询方法，不在 endpoint 直接调用；具体方法按现有 Repository 注入方式落地，不增加通用目录框架。
依赖：T003。预期：候选语义测试通过。

### T005 — 后端：索引检查与必要 DDL

- [ ] 核对 `User`、`Department` 模型与目标库索引，记录原名称/ID 查询执行计划；不能把 `(source, external_id)` 当成 external_id 前导索引。
- [ ] 仅在需要时为相应模型增加非唯一查询索引，并通过当前 Alembic 单 head 创建 DDL revision；不得猜 down_revision，不改已发布 migration。
- [ ] 索引子步骤分别限制为模型声明、migration、迁移测试小改动；执行既有单 head 与 schema 对齐测试。新增测试文件放 `test/database/`。
- [ ] 在 `verification.md` 记录是否需要 DDL、双库适用性、发布执行顺序与删除新增索引的回滚方式；无业务数据回填。

依赖：T004。预期：确认有可用 ID 前缀访问路径；没有目标库时标待实测，不以本地 SQL 编译替代。

## Wave 2：接入现有业务接口

### T006 — 后端：管理用户检索失败测试

- [ ] 扩展 `test/user/test_user_list_department_path.py`、`test/department/test_global_members_search.py`、`test/tenant/test_tenant_users_query_source.py`，每份作为一个独立小步，先跑红灯。
- [ ] /user/list simple 应补 external_id；普通响应不泄露敏感列；global-members 名称前缀/禁用用户及 root 约束不变；租户用户仍以主属部门挂载子树为准。
- [ ] 验证现有排序、分页、空关键词与名称行为，并新增 ID 前缀、精确优先与越界页。

覆盖 AC: AC-01, AC-02, AC-03, AC-05, AC-10, AC-16, AC-17, AC-20, AC-21, AC-23。
依赖：T004。预期：新 ID 用例失败，原名称用例保持通过。

### T007 — 后端：用户列表、组织、租户接口接入

- [ ] 子步骤 A：`user/api/user.py` → 用户业务 Service（`user/domain/services/user.py`）→ T004 Repository；保留范围编排，endpoint 不直接查 Repository，不扩大公共 UserDao 过滤器的全部消费者。
- [ ] 子步骤 B：`department/domain/services/department_service.py` 接 T004，保留前缀、主属部门 JOIN、去 GROUP BY、窗口计数、空页计数与批量部门信息。
- [ ] 子步骤 C：`tenant/domain/services/tenant_service.py` 接既有主属部门语义的 T004 查询。
- [ ] 子步骤分别执行对应 T006 回归至通过，再进行下一个；不将三套范围归并为全局目录。

依赖：T006。预期：三类接口均可按人员 ID 查找，原范围与响应结构保持，仅补可空显示字段。

### T008 — 后端：授权和创建候选失败测试

- [ ] 扩展 `test/permission/test_f048_grant_subjects.py` 与 `test/permission/test_prospective_grant_application.py`，先写新增查询用例并跑失败。
- [ ] 验证资源管理者没有组织管理角色仍可按原资源范围查候选；拒绝无 manage_permission、跨租户和部门空间越界对象。
- [ ] 验证创建授权路径、用户组 ID 数值前缀/规范文本、部门使用 external_id 而非 dept_id、真实 total、深层树精确命中路径。

覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-16, AC-17, AC-18, AC-21, AC-23。
依赖：T004。预期：新增用例因候选查询未接入而失败。

### T009 — 后端：授权候选接入与用户组查询

- [ ] 在 `tenant/domain/services/f048_permission_subject.py` 及已有 application 目录端口中接入 T004；资源与 prospective 创建两路保留原鉴权/范围。
- [ ] 用户组查询放租户所属 Repository（`tenant/domain/repositories/subject_search_repository.py`），使用 T002 数值区间查现有主键，名称沿用原规则；不新增 user_group 子系统。
- [ ] 按接口、适配器、Repository 分三个小步接入，每步限相关 1–2 文件并跑 T008；permission endpoint 不导入业务 ORM/Repository，不直接实例化 tenant Service。
- [ ] 部门序列化补 external_id，授权用户树保留 matched/path、limit/truncated；新总数准确。不改 grants:mutate 或创建授权的写入合同。

依赖：T008。预期：T008 通过，原资源权限与创建授权测试通过。

## Wave 3：两端逐入口接入

### T010 — Client：API 类型、显示 ID 与候选查询

- [ ] 小步 A：`client/src/api/permission.ts` 保留原路径和参数，支持用户组分页搜索及可空 external_id；已选结构仅增加可空显示值，不改变 type/id。
- [ ] 小步 B：`SubjectSearchUser.tsx`、`SubjectSearchDepartment.tsx` 补字段名/ID/路径，保留树懒加载与选择规则。
- [ ] 小步 C：`SubjectSearchUserGroup.tsx` 改服务端搜索/分页，清除只在前 200 条本地过滤的限制。
- [ ] 小步 D：`PermissionDraftPickerDialog.tsx` 及其实际已选数据转发处保留 externalId；每步限 1–2 文件。

手动验证：用户/部门/组均可查完整或前缀 ID；完整 ID 可复制且复制不勾选；第 201 个之后的组可查；切类型/关闭清词，已选按原合同保留。
覆盖 AC: AC-01, AC-06, AC-07, AC-08, AC-09, AC-10, AC-15, AC-18, AC-19。
依赖：T009。

### T011 — Client：输入与请求状态、三语文案

- [ ] 在 client 现有查询 hooks 增补规范化、255 code point 校验、IME 完成触发及请求代次；沿原 debounce，不引入新状态管理。
- [ ] 三语键分别更新 `client/src/locales/{zh-Hans,en,ja}/translation.json`；只改原始翻译，不碰生成错误码文件。
- [ ] 状态与 i18n 分步，每步限制 1–3 文件；复用已落地组件，不加视觉新规范。

手动验证：超限输入保留且不查询、纠正恢复；延迟旧响应不覆盖新词；失败/超时保留关键词和选择并可重试；加载中旧候选不可选；三种语言文本正确。
覆盖 AC: AC-04, AC-11, AC-12, AC-13, AC-14, AC-15。
依赖：T010。

### T012 — Platform：共享选人组件与 API

- [ ] 小步 A：`controllers/API/user.ts`、`controllers/API/department.ts` 保持原参数与路径，只补响应字段；租户 API 独立小步核对。
- [ ] 小步 B：`selectComponent/DepartmentUsersSelect.tsx`、`Users.tsx` 保留 externalId 转发与原单/多选、锁定项、root 范围。
- [ ] 共享规范化/IME/请求代次放组件旁小型 hook；每步只改 1–2 文件，不创建全局目录状态或跨 SPA 组件。

手动验证：用户组成员、标注任务成员、服务账号所有者与部门管理员选择均能按 ID 搜到；原单选/多选/已选保持；新建/挂载租户仍只看到原允许子树。
覆盖 AC: AC-01, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-18。
依赖：T007。

### T013 — Platform：授权弹窗

- [ ] 分别修改 `bs-comp/permission/SubjectSearchUser.tsx`、`SubjectSearchDepartment.tsx`，随后独立小步修改 `SubjectSearchUserGroup.tsx` 与已选信息的实际转发处。
- [ ] `controllers/API/permission.ts` 独立小步补可空 ID 与用户组查询参数；沿现有 request 包装。
- [ ] 保留选中、禁选与授权模型语义，不改已授权列表；查询/复制操作不产生写请求。

手动验证：与 Client 同一数据按名称/ID 搜到相同可授权范围；搜索、分页、删词不丢已选；提交仍为原稳定 ID，原事务/失败提示不变。
覆盖 AC: AC-01, AC-06, AC-07, AC-08, AC-09, AC-10, AC-18, AC-19。
依赖：T009, T012。

### T014 — Platform：独立列表、审批及日志入口

- [ ] 按入口顺序独立小步：`SystemPage/components/Users.tsx`；`DepartmentPage/components/AddMemberDialog.tsx`；`TenantPage/components/CreateTenantDialog.tsx` 与 `TenantUserDialog.tsx`。
- [ ] 审批两处选择逻辑抽到 `ApprovalPage/components/ApproverUserPicker.tsx`（实际落点保持命名一致），在原 index 接入；按 approval-module 约束不改审批流程保存合同。
- [ ] `filterTableDataComponent/FilterByUser.tsx` 只增加搜索显示 ID，保留 user_id value；日志页原稳定 ID 过滤不动。
- [ ] 逐步复核 `CreateDepartmentDialog`、`DepartmentSettings`、`MountTenantDialog`、`ServiceAccount/CreateServiceAccountDialog` 已通过共享选择器覆盖，显式覆盖搜索提示词的调用点同步更新。每步限 1–2 文件。

手动验证：各入口原触发方式不变；审批保存、服务账号所有者、标注成员和日志请求 payload 仍用内部 ID；挂载 root 限制不丢；已有失败流程保留选择。
覆盖 AC: AC-01, AC-07, AC-08, AC-10, AC-13, AC-14, AC-16, AC-18, AC-19, AC-20, AC-23。
依赖：T012, T013。

### T015 — Platform：三语及触及文件历史 i18n

- [ ] 按现有命名空间分别更新 `platform/public/locales/{zh-Hans,en-US,ja}/bs.json`；授权独立 permission 命名空间按实际使用分别更新，一次只处理一个命名空间的三语文件。
- [ ] 按 i18n-localizer 提取本期触及文件的冻结中文，翻译中明确 ID 为完整值/前缀可检索，不能继续暗示中段包含。
- [ ] 不手改 suppressions，不新增 any、默认导出或 ts-strict-ignore；无关页面和组件视觉不改。

手动验证：三语 placeholder、空态、重试、超限及 ID 字段名称；有正常 ID 时结果和已选都可核对。
覆盖 AC: AC-07, AC-11, AC-12, AC-14, AC-15。
依赖：T014。

## Wave 4：验收与性能回归

### T016 — E2E 及页面验收

- [ ] 按 e2e-test 技能新建 `test/e2e/test_e2e_subject_id_search.py`，复用 auth/api/cleanup helpers，测试专用租户、e2e-subject-id- 前缀及双 cleanup，允许与拒绝成对。
- [ ] 新建本 feature `e2e-checklist.md`，逐项覆盖两个 SPA 及全部登记入口；未执行页面检查保留未勾选。
- [ ] 执行相关后端回归及可运行 API E2E，保存命令与结果；无真实依赖时记录阻塞，不以 mock 替代真实通过。

覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24。
依赖：T011, T015。预期：可运行 API 用例通过；UI 与环境缺口据实报告。

### T017 — 双库性能与最终评审

- [ ] 在专用性能数据集准备 ≥15 万用户、≥3 万部门，禁止给真实客户库造数据；取改动前基线和新版本，记录硬件、并发、关键词分布、样本量、缓存状态、P50/P95 与 SQL 执行计划。
- [ ] 同时测试名称、ID、短前缀、无结果、越界页、最宽范围、受限部门及大组管理员；不把浏览器取消算作数据库取消。
- [ ] 目标为各入口服务端 P95≤500ms，MySQL/DM8 均满足，原名称检索保持同环境基线。失败先定位分支/排序/计数/索引并修正重测；不引入功能开关掩盖失败。
- [ ] 保存 `verification.md`；运行 arch-guard 及针对改动的后端格式/静态检查，完成最终 code-review，并把实际状态回写 design/tasks。前端镜像/CI 未跑则明确保留待验证。

覆盖 AC: AC-21, AC-22, AC-23, AC-24, AC-25。
依赖：T005, T016。预期：有真实证据才标性能验收通过；合并、发布和环境部署不包含在本任务授权中。

## 任务粒度与执行记录约定

T005/T007/T009/T010/T012/T013/T014/T015 为同一交付物的编号任务，每个已列子步骤必须单独执行、核对及记录；不把整个入口波次作为一次大改。完成记录格式：`任务/子步骤；改动文件；测试命令或手动路径；结果；未完成项`。

## 实际偏差记录

用户要求先开发后统一测试，故 T001/T003/T006/T008 中的先红后绿步骤不再执行；不将其记为已完成的红灯证据。ID 匹配、范围及写入合同未变。下方原计划子项保留作为计划文本，实际状态以本表和验证报告为准。

| 任务 | 实际结果与证据 |
|---|---|
| T001–T004 | 规则、双库 SQL 编译、真实 SQLite 查询覆盖完成；实际测试合并于 common/test_subject_search、user/test_management_subject_search、tenant/test_grant_subject_search_repository，落点见 design §8 |
| T005 | 模型和 Alembic 索引已加；单 head、SQLite 重复升级/降级与数据保留测试通过；目标库执行计划待测 |
| T006–T009 | 管理和授权接口均接入；范围、原名称行为、精确优先、分页计数及树路径纳入聚焦回归 |
| T010–T015 | 两端入口、已选信息、IME/规范化/状态及三语完成；代码审查问题已修复，页面及前端 CI 未验证 |
| T016 | API E2E 文件和页面清单已编写；本地后端回归已执行；无专用服务夹具，4 项真实 API E2E 跳过；页面未执行 |
| T017 | 后端检查和最终代码审查已做；双库真实执行及 ≥15 万用户/3 万部门性能未执行；详见 verification.md |
