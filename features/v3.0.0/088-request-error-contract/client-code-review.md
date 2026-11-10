# F088 client 最终独立审查

工作区：`/Users/shanghang/.codex/worktrees/request-error-contract/bisheng`；基线 `bc6ca25ba`。对象为共享工作区的未提交实现；只读产品代码、运行精准回归并写报告，未安装依赖、修改产品、执行批量脚本、Git 写入或派生 agent。

**Spec verdict：PASS（本报告明确列出的活跃迁移链）。Quality verdict：PASS（相同范围的代码审查与精准回归）。本轮没有未关闭的代码阻断。** 这是限定范围的独立审查结论，不能替代整个 F088 的全量、构建或真实后端 E2E 发布验收；后者仍未验证。

## 范围与证据

使用 requesting-code-review 的调用链审查，并按仓库 sdd-code-review 七维框架记录。对照 feature 的 spec/design/tasks、`/private/tmp/f088-client-consumer-review.md` 的 R1/R2/R3 及本轮 `task-1-report.md`。不重接不可达 UI，不将 stub 视为真实 API，不把未勾选任务本身当产品缺陷。

| 域 | 已核实的活跃链 |
| --- | --- |
| request/auth/binary/identity | client 原认证/refresh队列 → 新末端错误规范化；独立解码视图不改原response.data；共享错误身份/cause/response/Blob证据；模板参数；真实提示的WeakMap/presentation归属 |
| Skills | skillCenter → useSkillCenter / SkillUploadDialog / SkillCenterPage / SkillDetails；11053、11055命名恢复、详情文件query、乐观回滚、失败保留窗口及输入 |
| upload/rename/delete | 上传 → 文件登记 → useFileUpload；19403参数/早停；文件/文件夹行与卡片 → useInlineRename → await保存/失败保留输入；删除成功后才成功提示 |
| export/citation | daily/appChat当前ChatView → 消息toolbar/移动格式sheet/导入选择 → messageExport；引用resolve → 当前引用UI reason/404恢复，保留同一标准错误与原始证据 |
| query/cache | App默认retry + 原QueryCache；空间/频道列表hook → 页面/sidebar；RunCode有限网络重试；保留RQ4.44.0、成功结构、缓存键、原加载含义 |
| history/clear | daily、订阅assistant、文件、文章、文件夹/空间dock → 四history hooks → 失败/重试、禁发、cleanup、资源归属clear及失败保留消息 |
| approval/share | ApprovalPane列表/详情/动作revision与错误重试，详情与选择一致性；菜单申请；share404/普通失败重试；sharedLink mutateAsync终点 |
| voice/artifacts | ASR/TTS → VoiceSession保留原cause → UI；artifact下载/另存知识空间 → API错误去重，本地错误保留文案、finally恢复锁 |
| remaining default lists | app/standalone会话列表 → sidebar；SourceManager列表/搜索/分页 → picker；文章page1/loadmore → useArticleList/ArticleList；Nav正常历史与搜索结果独立 |

明确排除SSE/WebSocket/原生fetch传输、后端、platform终审；旧不可达LibreChat管理UI及固定成功stub。保留guest26401/26402/26403、不可用附件链接、可选标题、徽标零值、权限惰性探测等已有命名恢复，不机械删除。

## 最后两族修复：已关闭

### 消息导出/导入提示终点

核实位置：`src/frontend/client/src/components/Chat/MessageSelection/MessageSelectionToolbar.tsx:105`、`ExportFormatSheet.tsx:98`；`src/frontend/client/src/components/Chat/ChatView.tsx:286`、`src/frontend/client/src/pages/appChat/ChatView.tsx:137`。

四个真实UI catch现在将标准ApiError原样传给showApiError，同一对象的status_code/data/response/cause/kind/presentation全部保留，不再重建只含码/消息的对象。global、已提示、canceled由共同helper处理；本地浏览器下载错误仍使用原localized fallback。导出finally复位按钮，sheet仅成功下载后关闭；导入失败保留选择和窗口，只有成功后退出选择。新增真实组件回归覆盖这些终点及成功继续执行；原AC-07、AC-09、AC-10、AC-15缺口关闭。

### 上传聚合、登记与附带终点

核实位置：`src/frontend/client/src/pages/knowledge/hooks/useFileUpload.ts:152`、`:354`、`:380`、`:407`、`:528`、`:603`、`:610`。

uploadFilesSequential收到global/canceled即原样reject、停止后续文件，不加入普通失败汇总；普通每文件失败在现有展示信息外保留error原对象，19403参数/早停/计数恢复保留。file/folder最外层catch有明确终点，finally清占位、folder reentry锁并刷新已尝试上传的配额；部分body成功后遇global/cancel不继续登记。folder重名precheck保留既有普通失败fall-through，global/cancel停止该流程。

登记只保留一次标准HTTP/network/timeout重试；business/global/canceled/invalid-response/local Error不触发新增重试，也不重传文件body。同文件获授权的duplicate overwrite与single-delete catch也按标准错误归属提示；原duplicate清理、delete回滚与成功后提示保留。原AC-07、AC-08、AC-10、AC-15缺口关闭。

本轮只核实上述五生产文件及三新增测试、原quota测试，不扩大到其他CRUD或非统一HTTP通道。未发现本轮新增阻断。

## 本轮发现并已关闭

1. 历史失败无重试且遮住后续新消息：四hooks返回retryHistory，五消费者连接onRetry，error/loading禁发；history cleanup忽略过期完成。folder重试重新获取session/list/history，旧history完成会被cleanup丢弃。
2. 跨资源clear晚完成误清当前资源：file/article资源token，folder资源token+activeChatRef守卫；失败保留消息。
3. 同资源clear pending可发新消息：clearingRef即时锁/isClearing、UI禁发、重复clear及regenerate守卫；资源effect复位锁，旧operation不释放新操作锁。
4. app sidebar retry旧闭包：A初始失败→新建B→retry曾重新插A；现从conversationIdRef/localizeRef读取当前值，不把不稳定localize加进初始化effect。精准回归已通过。
5. R1/R2/R3其余已修项已核实：分享失效/重试、WeChat恢复、菜单申请、版本/关联query与mutation、sharedLink Promise、审批详情错配、voice cause、artifact去重、AppChat权限探测失败、空间/频道主列表、inline rename、删除成功提示、Nav/Source/Article/sidebar假空成功。本轮未发现这些链的额外阻断，不重复旧缺陷。

## 七维 SDD

| 维度 | 结论 | 说明 |
| --- | --- | --- |
| Boundary Conditions | PASS（范围内） | export/import标准错误身份与展示归属保留；upload global/cancel停止并恢复，普通配额恢复保留；核心模板/二进制已核实 |
| Permission & Auth | PASS（范围内） | 原session/refresh队列保留；全局动作先执行再规范化；旧不可达resolved403删除而非重接；无新增业务层403策略 |
| Concurrency Safety | PASS（范围内） | history资源cleanup、clear资源token/锁、sidebar最新路由闭包；独立13项精准回归通过 |
| Information Leakage | PASS（增量范围） | 原始证据保留未变成新UI/日志全量输出；不是全仓日志安全审计 |
| Test Coverage | PASS（精准范围） | 本reviewer前轮13项、本轮41项独立通过；实际hooks/components与失败后UI状态均有断言；全量/E2E不由本报告替代 |
| Code Style | PASS（静态范围） | 共享错误模型、原组件/RQ4.44、ArticleList控制器拆出满足600行；最终lint/typecheck须另验 |
| Docs Sync | PASS（审查范围） | 已核实design移除未实施过期文本，并同步二阶段解码/WeakMap、history重试和clear归属锁、验证与修订记录；未执行浏览器验收明确保留未勾选 |

## 验证与范围限制

本reviewer独立执行：client cwd，`JEST_JUNIT_OUTPUT_DIR=/private/tmp/f088-final-review pnpm exec jest src/hooks/chatHistoryErrors.test.tsx src/pages/appChat/hooks/sidebarRequestErrors.test.tsx --runInBand --coverage=false --forceExit`。结果：**2 suites /13 tests PASS，exit0，2.243s**。包含跨资源late clear不影响B且锁复位、同资源pending禁发/重复clear、失败保留消息、重试成功、sidebar当前路由与auth/guest草稿恢复。

读取他方证据（不冒充独立执行）：consumer `task-1-report.md`为4 suites/16 tests通过、guest命名恢复9项通过、client1490 strict files typecheck通过、9生产+4测试scoped ESLint无诊断（suppression缩小由父任务prune）。父任务另有request binary/global、11053/11055、审批/分享/rename/配额/voice回归。

没有运行浏览器/真实后端E2E、全client测试、全frontend lint/typecheck/check-i18n/build；这些由T006负责，不能给无证据的发布PASS。没有穷尽所有文件预览局部元数据、树导航每层竞态、任务模式内部SSE/WS对账及文章所有辅助分享/收藏/反馈按钮。对这些不作全覆盖声明。

### 精准最终复核（第二轮）

阅读实施报告 `.superpowers/sdd/client-final-migration-plan/fix-round-2-report.md`、五个生产文件与三新增测试。生产控制流和测试证据一致；测试虽然隔离共同提示helper，但明确断言传递同一ApiError对象及无额外普通toast，helper自身的presentation/canceled策略已在此前请求契约审查中核实。

本reviewer本轮仅执行一次聚焦命令（client cwd）：

```sh
JEST_JUNIT_OUTPUT_DIR=/private/tmp/f088-final-review-round2 pnpm exec jest src/components/Chat/MessageSelection/exportFailureContract.test.tsx src/components/Chat/importFailureContract.test.tsx src/pages/knowledge/hooks/uploadTerminalErrors.test.tsx src/pages/knowledge/hooks/uploadFailureContract.test.ts --runInBand --coverage=false --forceExit
```

结果：**4 suites /41 tests PASS，exit0，11.145s**。未重跑history/clear/closure或全量。实施agent的changed-file ESLint exit0/no diagnostics与diff-check为读取报告所得，不冒充本reviewer独立执行。

最终scope verdict：**Spec PASS / Quality PASS；无本范围内待修代码问题。全量门禁、构建与真实后端E2E尚未由本reviewer验证。** 父任务已生成E2E清单，真实后端不可达，故不能把清单或本轮单测视为已执行E2E。
