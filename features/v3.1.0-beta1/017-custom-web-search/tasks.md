# 自定义联网搜索任务

**规格**：[spec.md](./spec.md)；**设计**：[design.md](./design.md)；**版本**：v3.0.0，正式编号待分配。

## 状态与执行规则

规格和设计方向已获用户确认；设计独立评审问题尚需关闭。下列任务以依赖顺序执行；后端先写配对测试（红），再实现（绿）。已有实现和测试不代表任务已完成：每项须核对全部断言、记录具体实现文件、测试命令及结果并完成对应 /task-review 才能勾选。已有局部自动化测试执行，但各任务的断言和结果尚未逐项核对、对应 /task-review 尚未完成，真实环境验证仍未完成，因此不预先勾选。测试任务只写测试，标明覆盖 AC；实现任务只在对应测试后执行。共享文件修改须检查旧服务商、读取工具及调用方的回归，遵守版本契约对象归属。

## Wave 0：基础设施与决策

- [ ] **T001** 基础设施：核对 `src/backend/bisheng/tool/domain/models/gpts_tools.py` 中 WebSearchSecret 的 owner tenant/category/provider 唯一键、密文版本与审计字段，确保 MySQL/DM8 可建表；回滚采用停用 custom、备份后由运维单独移除新增表，不能把数据迁移放入 Alembic。依赖：无。
- [x] **T002** 基础设施：原环境变量方案由 P1 修复替代；直接复用平台 encrypt_token/decrypt_token，不创建搜索 keyring 或数据库配置项，损坏数据 fail closed。32 项相关回归及 115 API/worker 解密验证通过；旧 provider 不变。
- [ ] **T003** 决策与登记：功能编号已收纳为 F017 并登记 v3.1.0-beta1 release-contract；继续确认新密钥对象归属及共享工具写入影响；确认历史子项覆盖处理、私网 CIDR/端口授权、HTTP 内网策略、网络限制值及平台加密恢复责任。依赖：无。登记需走项目正常流程；本次只记录待办。
- [ ] **T004** 安全评审：按用户已确认决定保留通用原文预览，对已知秘密及可识别编码脱敏；按已修订 AC-12 评审并记录上游任意变形、拆分或未知秘密无法识别的已接受残余风险；不得将有限脱敏描述为绝对保证。依赖：无。

## Wave 1：后端 Domain（测试先于实现）

- [ ] **T005** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 覆盖 OpenAPI 3.0 单 server、GET/POST、query/JSON 顶层标量选择，固定参数类型及不支持外部引用、路径参数、嵌套必填/文件的拒绝。**覆盖 AC: AC-02, AC-06, AC-13**。依赖：T003。
- [ ] **T006** 实现：复用 `src/backend/bisheng/tool/domain/services/openapi.py` 解析，在 `web_search.py` 应用搜索限制并输出可选操作与规范化参数，拒绝 T005 的不支持输入；运行 T005。依赖：T005。
- [ ] **T007** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 覆盖根数组/属性路径、必填 title/url/snippet、可选 source/icon/date、无效链接、空数组与非数组/缺失字段错误。**覆盖 AC: AC-03, AC-04, AC-06, AC-09, AC-10**。依赖：无。
- [ ] **T008** 实现：在 `src/backend/bisheng_langchain/gpts/tools/web_search/custom.py` 完成对象属性映射，不执行表达式，错误不得伪装为空数组；运行 T007。依赖：T007。
- [ ] **T009** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 覆盖公网、授权/未授权私网、IPv4/IPv6/mapped、混合或空 DNS、重绑定、peer 不匹配、代理、重定向、TLS、超时及压缩前后上限。**覆盖 AC: AC-02, AC-06, AC-08, AC-12**。依赖：T003。
- [ ] **T010** 实现：在 `src/backend/bisheng_langchain/gpts/tools/web_search/custom.py` （包含隔离传输入口） 核对并补齐经授权 origin、DNS 全地址检查、固定 IP、Host/SNI 与 peer 校验，禁代理和重定向及有限资源；导入/测试/运行统一调用，运行 T009。验证 `BS_CUSTOM_SEARCH_CA_FILE` 指定私有 CA、默认信任源、无效 CA 与证书域名不匹配及各进程部署分发。依赖：T009。
- [ ] **T011** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 覆盖加解密、错 owner/category、篡改、未知版本/缺钥、替换及旧 provider 不受影响。**覆盖 AC: AC-07, AC-08, AC-12**。依赖：T001, T002。
- [ ] **T012** 实现：在 `src/backend/bisheng/tool/domain/services/web_search.py` 完成带域及 owner/category 绑定的认证加密和 fail-closed 解密；运行 T011。依赖：T011。
- [ ] **T013** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 覆盖 keep/replace/clear、离线保存、旧 provider 合并、60 KiB 限制、子项覆盖拒绝、事务回滚和 revision 冲突。**覆盖 AC: AC-06, AC-07, AC-11, AC-12**。依赖：T001, T006, T012。
- [ ] **T014** 实现：在 `src/backend/bisheng/tool/domain/services/web_search.py` 完成校验、行锁加 CAS、配置与密钥原子写入及白名单 DTO；运行 T013。依赖：T013。
- [ ] **T015** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 验证草稿测试不持久化、请求共用固定参数、预览与结果对已知密钥直接/嵌套及 URL/Base64 编码脱敏，错误和响应头不泄露；记录分片及未知变形风险。**覆盖 AC: AC-05, AC-06, AC-12, AC-13**。依赖：T004, T008, T010。
- [ ] **T016** 实现：在 `src/backend/bisheng/tool/domain/services/web_search.py` 实现 T015 约定的测试和有限脱敏；运行 T015，不把有限脱敏表述成绝对保证。依赖：T015。

- [x] **T040（beta2 替代）** 测试：覆盖无 proof 导入/保存/测试/执行，以及旧或失效 proof 的读取和目标租户兼容；继续验证越权拒绝和凭据范围。原 proof 绑定任务被 2026-11-24 用户决定替代。
- [x] **T041（beta2 替代）** 实现：移除 proof 的签发及校验；custom DTO 为 `{operation, mapping}`，旧 proof 兼容忽略，继续执行请求结构、参数、认证和映射校验。决策见 design.md §3.4。

## Wave 2：后端 API 与执行

- [ ] **T017** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 覆盖匿名、普通用户、租户管理员、global super、错误 preset/tool_key/已删除及跨租户目标；settings GET/PUT、schema 和 test 均 fail closed，未知字段拒绝。**覆盖 AC: AC-02, AC-05, AC-07, AC-12**。依赖：T014, T016。
- [ ] **T018** 实现：在 `src/backend/bisheng/tool/api/tool.py` 接入 `/{tool_type_id}/web-search/settings`、`/schema`、`/test`；服务端检查 global super 和真实目标，委派领域服务，运行 T017。依赖：T017。
- [ ] **T019** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 验证旧列表/详情不泄密，旧写入无 revision 被拒或同等 CAS；跨租户子项不可批量清空，双管理员冲突不丢其他 provider。**覆盖 AC: AC-07, AC-11, AC-12**。依赖：T014。
- [ ] **T020** 实现：在 `src/backend/bisheng/tool/domain/models/gpts_tools.py` 收紧旧写入口并保护其他工具原有行为；运行 T019。依赖：T019。
- [ ] **T021** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 验证搜索词和固定参数进入 GET/POST 请求，成功映射为现有 JSON 结果，空结果与失败区分，网页来源保留且无效 URL 不产生引用。**覆盖 AC: AC-04, AC-08, AC-09, AC-10, AC-13**。依赖：T008, T010。
- [ ] **T022** 实现：在实际 `bisheng_langchain` 搜索 provider 模块完成 custom 适配，复用 T010 传输与 T008 映射，不反向导入 `bisheng`；运行 T021。依赖：T021。
- [ ] **T023** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 验证 tool/use 授权后从实际 owner/category 解密并仅向工具初始化注入内存副本，不写 ORM、缓存、队列或日志；缺钥或错租户失败。**覆盖 AC: AC-08, AC-12**。依赖：T012, T022。
- [ ] **T024** 实现：在 `src/backend/bisheng/tool` 中实际 ToolExecutor 初始化模块接入受权密钥注入；保持子项优先规则和旧 provider 行为，运行 T023。依赖：T023。

## Wave 3：前端 Platform（Client 无新增设置页）

- [ ] **T025** 测试：在 `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/CustomWebSearch.test.tsx` 验证导入、操作/搜索词和固定参数选择、映射、无认证/API Key、测试原始及映射结果、错误提示。**覆盖 AC: AC-02, AC-03, AC-04, AC-05, AC-06, AC-13**。依赖：T018。
- [ ] **T026** 实现：在 `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/CustomWebSearch.tsx` 实现 T025 交互及临时密钥状态；手动验证导入、测试错误和重试，运行 T025。依赖：T025。
- [ ] **T027** 测试：在 `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/WebSearchFrom.test.tsx` 覆盖 provider 选项、未知 provider 保留、密钥保留/替换、保存失败或 409 草稿保留、成功关闭。**覆盖 AC: AC-01, AC-06, AC-07, AC-11, AC-12**。依赖：T018。
- [ ] **T028** 实现：在 `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/WebSearchFrom.tsx` 与 `src/frontend/platform/src/controllers/API/webSearch.ts` 接入 revision 和专用 API，不在持久状态留明文，运行 T027。依赖：T027。
- [ ] **T029** 实现：在 `src/frontend/platform/src/pages/BuildPage/tools/ToolSet.tsx` 接入专用设置，移除配置日志；手动检查成功关闭、409 保留草稿和网页读取设置不变。依赖：T028。
- [ ] **T030** 实现：在 `src/frontend/platform/src/pages/BuildPage/bench/Subscribe.tsx` 接入同一专用设置；手动检查保存、重开、冲突保留草稿及其他 provider 不变。依赖：T028。
- [ ] **T031** 实现：在 Platform 三语言资源中补齐对应文案（分文件逐一修改）；检查中、英、日文无缺失或溢出，保持既有设计组件。依赖：T026, T028。
- [ ] **T032** 测试：在 Platform 对应入口测试文件中验证 T029 与 T030 两条实际提交链路、失败不关闭及读取工具不变。**覆盖 AC: AC-01, AC-07, AC-11**。依赖：T029, T030。

## Wave 4：Worker、集成与交付

- [ ] **T033** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 验证 API、Celery、Linsight 进程使用平台加密封装正确解密，密钥缺失 fail closed、实例重初始化生效；Celery tenant_id 从消息 headers 恢复 ContextVar，验证两租户和共享资源 use 授权。**覆盖 AC: AC-08, AC-09, AC-12**。依赖：T024。
- [ ] **T034** 实现：在实际 Worker 初始化/部署注入入口补齐 T033 所需配置和租户传播，不把密钥写入消息；保持已有调用方授权，运行 T033。依赖：T033。
- [ ] **T035** 测试：在 `src/backend/test/tool/test_custom_web_search.py` 用 MySQL 和 DM8 分别验证原子回滚、两个管理员 CAS、tenant 范围与建表；记录 CI 运行结果。**覆盖 AC: AC-07, AC-11, AC-12**。依赖：T014, T020。
- [ ] **T036** 运维演练：验证旧密文迁移、备份恢复和回滚边界；记录操作与结果，不输出密钥。依赖：T003, T034。
- [ ] **T037** E2E：在隔离部署和受控上游运行 `src/backend/test/e2e/test_e2e_custom_web_search.py` 并补足真实写入及执行覆盖：两入口导入、固定参数、测试、离线保存、重开、切换、错误/空结果，工作台、工作流、Linsight 引用及历史回放；覆盖双租户授权。**覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13**。原 opt-in 只读权限检查占位测试已按用户要求删除，真实部署 E2E 仍未完成。依赖：T032, T034, T035。
- [ ] **T038** 评审：执行 /sdd-review 本目录 tasks，逐条解决 checklist 问题；独立关闭 design 评审及 Constitution Check，确认安全残余风险、运维决定和版本归属。依赖：T003, T004。
- [ ] **T039** 评审：每项实现按项目流程执行 /task-review 并记录结果；全任务及 E2E 完成后执行 /sdd-code-review --base 对应发版线，修复问题并记录结果。依赖：T036, T037, T038。

## 核心测试对应关系（按用户要求收敛，未完成任务评审）

新增功能的测试及 fixture/helper 统一放在 `src/backend/test/tool/test_custom_web_search.py`，保留 21 个功能用例（含参数化展开）。原有 provider 和通用工具回归文件保持原位。前端两个组件测试已按用户要求删除。上方任务是待审查计划；实际自动化范围以本节为准，未覆盖的计划断言不视为完成。

- 共用解析：自定义工具与搜索的 JSON/YAML 导入、嵌套 body 兼容与搜索子集限制。
- 配置管理：保存及密钥替换/保留/清除、旧 revision、操作篡改、旧 provider 数据保留、跨租户/子项覆盖拒绝、通用响应脱敏和明文凭据拒绝。
- 试搜及执行：预览脱敏且不落库、POST 参数与结果映射、空/无效响应、代表性旧 provider 初始化与权限检查。
- 实际 HTTP 主链路：URL 导入 Schema → 保存配置 → ToolExecutor → 隔离传输 → 标准结果；Schema 下载不携带搜索凭据。
- 管理接口授权保留参数化核心检查；不再单独保留密码学、TLS 和网络输入变体矩阵。
- 组合测试命令、结果与验证边界见 [本地验证记录](./verification-local.md)。

## 实际偏差记录

- 入口审查：`/build/tools` 的 `ToolSet` 为活跃入口；`Subscribe` 中的对话框目前没有打开触发器，不能据此认定第二入口已实现。spec 未要求新增工作台配置入口；T030/T032 的范围须经需求确认和评审，T037 的两入口 E2E 清单须相应核对，以上任务均未完成。
- 保存不要求在线测试；见 spec AC-06。
- 用户已接受原文预览与已知秘密脱敏的残余风险，AC-12 已同步；见 design §4.8，待 T004 评审记录。
- 没有任何历史子记录的 preset 因无法安全识别类型而 fail closed：普通列表隐藏 `extra`、旧配置写入被拒，包括实际非搜索 preset；有历史子记录且可识别的非搜索 preset 保持原行为。实际影响与迁移策略待部署核实，见 [运维指南](./operations.md)。

- 按用户要求复用自定义工具现有 OpenAPI 输入及解析：前端共用 `OpenApiSchemaInput`，后端共用 `ToolServices.load_openapi_schema` / `OpenApiSchema`，删除独立 `web_search_schema.py`。功能测试收敛为一个文件，不据此勾选 SDD 任务。

- 按用户要求将 preview/proof/secret/settings 合并到 `web_search.py`，运行侧 worker 合并到 `custom.py`；继续保持 `bisheng` 管理服务与 `bisheng_langchain` 执行包边界，以及隔离子进程传输。

- [x] P1：去除专用密钥环境变量依赖，平台 encrypt-token 密文迁移；保留旧 ID 的迁移及无环境变量回归。

- 2026-11-24：用户明确要求 beta2 移除 proof，前后端契约、旧配置兼容和验证同步更新，见 design.md §3.4。
