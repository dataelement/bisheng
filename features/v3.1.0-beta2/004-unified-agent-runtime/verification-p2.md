# F004 P2 验证记录（T051）

**结论**：自动化部分通过；114 上按 test-cases.md TC-UAR-005 至 TC-UAR-012、TC-UAR-020 的界面执行**没有做**。原因与 verification-p1.md 相同：需要在 114 登录并部署本分支。

## 已执行（本地，2026-11-18）

| 项 | 方法 | 结果 |
|---|---|---|
| 收件箱消息在下一次模型调用前注入、顺序与恰好一次、`steer_read`、迟到消息留在收件箱、子代理与无人值守不挂载、`direct` 档生效 | `test/linsight/test_inbox_middleware.py`（14 个，脚本化模型 + fakeredis） | 通过 |
| 入箱即写提问行、`steer_accepted`、读取后清除排队标记 | `test/workstation/test_steer_message_persist.py` | 通过 |
| 统一停止接口；挂起运行被停止后会话回到空闲 | `test/workstation/test_unified_stop.py` | 通过 |
| 过期 `direct` 运行与接力运行的回答行 | `test/workstation/test_direct_answer_recovery.py` | 通过 |
| 规划提示词；开关关闭时逐字节不变 | `test/linsight/test_planning_prompt.py`（7 个） | 通过 |
| 后端回归选择集与 P1 提交后逐用例对比 | `regress.sh` | 无新增失败，新增 65 个通过 |
| 前端 store、订阅、输入框、计划面板、提问卡片 | jest：`src/store/runStore.test.ts`、`src/hooks`、`src/components/Chat`、`src/components/Linsight/Execution` | 658 通过；13 个失败集中在 `useAiChat.test.ts` 与 `importFailureContract.test.tsx`，在改动前的树上同样失败 |
| 改动的前端文件 | eslint、tsc-strict | 无报错 |

## 未执行

| 项 | 需要 |
|---|---|
| TC-UAR-005 至 TC-UAR-012（运行中发送、排队标记、改计划、提问、停止） | 114 部署 + 界面登录 |
| TC-UAR-020（两个标签页） | 同上 |
| 断网 10 秒后内容补齐、无重复文字 | 同上 |
| 真实模型在新规划提示词下收到插话后改写计划的成功率（design 决策 6 要求 P2 后重测） | 114 + 真实模型，脚本 `scripts/spike_unified_runtime/s3c_steer_real_model.py` 需改用现行提示词 |

界面部分没有在浏览器里运行过一次。上表的 jest 用例只覆盖组件在给定 store 状态下的渲染与纯函数。
