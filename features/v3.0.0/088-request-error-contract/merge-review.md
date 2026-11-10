# F088 rebase 冲突精准复核

**结论：PASS。** 在指定冲突范围内，未发现阻断合并的语义丢失。此结论是冲突解决内容审查，不替代父任务正在执行的全量与双端构建。

工作区：`/Users/shanghang/.codex/worktrees/request-error-contract/bisheng`。逐项对照当前source、incoming `origin/feat/3.0.0`（`4bb923a43`）及原F088 `12be71949`。仅执行只读Git/文件检查，写此临时报告；未改产品、未运行测试/全量、未执行Git写入或发其他线程消息。

| 项目 | 核实结果 |
| --- | --- |
| SkillUploadDialog incoming配额 | 50MiB限制、非空/格式校验、quotaBlocked阻止校验、11061/11062单条配额提示、drop传播控制与格式说明均保留。与incoming差异仅为F088标准错误模型适配，没有删除配额逻辑。 |
| SkillUploadDialog F088完整错误 | isApiError/status_code/status_message/data均保留；11055重名恢复继续读取skill_id/content_hash；errorCode从标准status_code设置，使incoming quotaBlocked提示去重继续生效。保存仍await请求、catch保留错误、finally解锁，成功后才关闭。定位：SkillUploadDialog.tsx:27、:46、:72、:95、:126、:137、:149。 |
| SkillUploadDialog测试 | 两侧全部既有测试均保留；incoming的50MiB、count cap、server quota去重与package drop均有原行为断言；F088输入改为normalizeApiError，英文fixture与断言同步，不是删断言迁就实现。 |
| SkillCenterPage测试 | incoming两条updatedAt时间戳保留；原F088英文fixtures、标准错误测试与全部12条行为测试保留。相对12be71949仅增加两条updatedAt。定位：SkillCenterPage.test.tsx:11、:15、:225。 |
| SpeechToText incoming取消锁 | attemptRef/armedRef/seenStop、dropAttempt、stopSignal变化、disabled取消、启动中点击暂停、await后的attempt guard、finally仅清当前attempt、Tooltip/aria状态均保留；相对incoming仅新增标准错误传递适配。定位：SpeechToText.tsx:38—:98、:125—:147。 |
| SpeechToText F088错误 | errorRef接收原unknown；标准ApiError交showApiError；VoiceSession.onError原error继续透传；getVoiceModels catch仅当前attempt展示，并将同一error传给errorRef。本地错误仍原文案，无部分字段重建。定位：SpeechToText.tsx:43、:119、:129。 |
| SpeechToText测试类型 | incoming全部取消/立即暂停状态测试及原参数化用例保留；相对incoming仅两处Promise resolver使用Awaited<ReturnType<typeof getVoiceModels>>，不改变运行行为。 |
| platform suppression | 按JSON叶子逐项对比incoming：当前754项、incoming772项；无新增键或计数增长。incoming所有hook文件键（controllers/hooks/knowledge、BuildPage/hook、Dashboard/hook、util/hook）均保留；未误用冲突一侧整文件覆盖。 |

检查：上述6文件无冲突标记；`git diff --check 4bb923a43 -- <上述路径>`通过。逐一对比三份test文件的既有测试名称，无两侧测试丢失，并读了配额/时间戳/取消锁的关键断言。

测试证据：父任务报告5 focused suites/37 tests通过；本reviewer没有重复运行，亦未把父任务结果冒充独立执行。全量、严格类型、双端build结果由父任务最终记录。

审查时仍处于rebase，冲突文件index显示UU（内容已解决但尚未标记）；这是父任务后续stage/continue步骤，不是本报告发现的代码阻断。本reviewer未修改index或执行rebase操作。
