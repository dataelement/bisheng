# F088 集成授权与合入前验证

日期：2026-10-22。用户明确要求：停止Vite，合并到3.0.0，提交推送，删除开发分支。保留此前披露的基线失败与未执行真实业务E2E，不将集成授权改写为验收全部通过。

## 集成范围

原开发提交12be71949，以bc6ca25ba为实施基线；重放至最新origin/feat/3.0.0的4bb923a43，保留发版线依赖清理、技能配额/更新时间与语音防竞态修复。主检出原有未跟踪计划文件不纳入提交。

冲突逐块解决，没有整文件采用冲突一侧。SkillUploadDialog标准ApiError继续保留errorCode供配额去重；技能时间戳字段保留；语音attempt/armed/stopSignal及Tooltip与原错误传递同时保留。抑制元数据经lint:prune生成，逐项比较发版线无新增键或计数增长。两个语音Promise解析器夹具仅修正类型；新增排序测试改用当前展示接口mock，全部原拖拽断言保留。

## 合并结果验证

- 独立精准冲突复核PASS，见merge-review.md。
- client冲突相关5套37测试通过；平台排序/选择器/提交刷新/全局兼容4文件18测试通过。
- platform最终完整198文件：197通过/1失败，963测试：961通过/2失败；仅剩原knowledgeSpaceGrantSubjects两项旧断言。
- client完整113套：82通过/31失败，718测试：698通过/20失败；与合入前F088相比新增失败suite为0，均为已有记录的失败。
- 两端生产构建通过。
- client1494个strict文件全部通过；platform801个strict文件仅原clientVoiceDraft旧测试参数错误1项。
- check-i18n通过；platform85项既有lint、client29项既有lint/2警告保留。client新增一项来自发版线原SkillList测试，非F088新增源码。抑制阈值没有扩大。
- git diff --check通过。两端Vite进程已停止；真实浏览器业务E2E仍未执行，T006不伪装为已完成。

日志：/private/tmp/f088-merge-platform-verified.log、f088-merge-client-full.log、f088-merge-platform-build.log、f088-merge-client-build.log、f088-merge-client-focus.log、f088-merge-platform-focus.log、f088-merge-client-types.log、f088-merge-platform-types.log、f088-merge-i18n.log。远端最终提交以feat/3.0.0的Git记录为准。
