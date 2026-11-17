# F004 整体验收记录（T062）

**结论**：T062 **没有完成**。本地的自动化验证已执行并通过；T062 要求的五项（`/e2e-test`、两节点、DM8、`prep` 复测、额度拒绝的环境验证）**都没有执行**，因为它们需要已部署本分支的环境与界面登录。在这些项完成之前，`unified_runtime_enabled` 不能对真实用户打开。

## 1. 已执行的验证（本地，2026-11-18，Wave 3 与 Wave 4 的代码）

这些测试用脚本化模型、fakeredis 与内存对象存储，没有连接真实的 MySQL、Redis、MinIO、代码执行器与模型。

| 项 | 方法 | 结果 |
|---|---|---|
| 后端回归 | 选择集 `test/linsight test/workstation test/open_api test/api/test_route_path_naming.py test/memory test/citation`，与 Wave 2 提交（db8d30a845）后的结果逐用例对比 | 无新增失败，见第 5 节 |
| `direct` 运行的工作区、技能、延迟建目录、跨节点恢复文件 | `test/workstation/test_direct_workspace_and_skills.py`（5 个） | 通过 |
| 本地缓存清理、部门并发名额、输出侧内容安全 | `test/workstation/test_direct_run_guards.py`（12 个） | 通过 |
| 文件事件、访问控制、`resync` 的 `ended` | `test/linsight/test_file_events.py`（16 个）、`test/linsight/test_resync_lifecycle.py`（6 个） | 通过 |
| 工具显示数据与完整结果 | `test/workstation/test_direct_tool_display.py`（3 个） | 通过 |
| 附件按需读取与进度帧 | `test/workstation/test_attachment_on_demand.py`（14 个）、`test_attachment_progress_event.py`（5 个） | 通过 |
| 引用、读图、记忆 | `test/linsight/test_unified_citation_image_memory.py`（15 个） | 通过 |
| 开放 API 应答在开关开与关时相同 | `test/open_api/test_task_mode_contract_unchanged.py`（15 个） | 通过 |
| 前端：工作区实时文件、工具行展开、会话页移除旧通道、`resync` 结束状态 | jest：`src/hooks src/components/Chat src/components/Linsight src/store src/api src/pages/appChat`（155 个套件） | 149 个套件通过。6 个套件失败（`useAiChat.test.ts`、`importFailureContract.test.tsx`、`conversationShare.test.tsx`、`appStreamStop.test.tsx`、`knowledgeUpload.test.ts`、`__tests__/memory.test.ts`）。在改动前的树（f3fc90c1fd）上跑同样 6 个套件，失败的用例名单逐行相同 |
| 改动的前端文件 | eslint（带 suppressions）、tsc-strict（1976 个文件） | 无报错 |

## 2. T062 要求但没有执行的验证

| T062 的步骤 | 状态 | 没执行的原因 | 需要 |
|---|---|---|---|
| ① `/e2e-test features/v3.1.0-beta2/004-unified-agent-runtime` | 未执行 | API 层端到端测试要连一个已部署本分支、开关已打开的后端 | 部署 + 测试账号 |
| ② 两节点环境执行 TC-UAR-022、TC-UAR-023 | 未执行 | 没有部署本分支的两节点环境 | 两节点环境 |
| ③ DM8 环境执行 TC-UAR-033，长运行期间会话页无 500 | 未执行 | 105 未部署本分支 | DM8 环境 |
| ④ 用 `s5_first_char_timing_from_logs.py` 复测 `prep`，与 AC-34 比较 | 未执行 | 依赖真实运行产生的 `BS_METRIC domain=agent_run` 日志 | 114 部署 + 真实请求 |
| ⑤ 额度不足时两种方式都在运行开始前被拒绝 | 仅单元测试 | `test_direct_run.py` 用替身准入函数断言“拒绝发生在模型调用之前”；真实 DSH 额度没有验证 | 开启 `dsh.enabled` 的环境 |

T039（P1 等价性）与 T051（P2 界面）的未执行项见 verification-p1.md 与 verification-p2.md，它们同样是本验收的前置。

## 3. 界面没有在浏览器里运行过

Wave 2 至 Wave 4 的全部前端改动只经过 jest。以下场景必须人工在浏览器里走一遍（对照 `prototype/index.html`）：

1. 直接回答：流式出字、工具行、“查看代码和输出”、生成文件在运行中即出现在工作区并能预览下载。
2. 打开「深度研究」：计划出现并立即执行；运行中发消息，显示“已发送，排队处理中”，读取后文案消失，计划条目被改写。
3. 提问卡片：回答后运行继续。
4. 停止：5 秒内停下，已有内容保留。
5. 重新打开仍在运行的会话：内容补齐，无重复文字；网络面板里没有 `task-message-stream` 的 WebSocket。
6. 升级前的旧会话：历史任务回合能回看。
7. 开关关闭的租户：界面与今天完全相同。

## 4. 人工执行步骤（待执行）

1. 查 114 无进行中的深度研究，同步虚拟环境（`uv sync --frozen`，本分支把 deepagents 升到 0.7.39），部署本分支，重启 backend、linsight worker。
2. 对测试租户调用 `POST /api/v1/workstation/config/daily`，带 `unified_runtime_enabled: true`。
3. 按第 3 节的 7 个场景与 test-cases.md 逐项执行，记录差异。
4. `grep "BS_METRIC domain=agent_run"` 取 `prep_ms`，填下表。
5. 用几个不同大小的附件实测内联阈值（design §7 待定事项 14）。

| 场景 | 样本数 | prep 中位数 | prep 90 分位 | AC-34 阈值 | 是否达标 |
|---|---|---|---|---|---|
| 直接回答（不带附件） | 未测 | 未测 | 未测 | 见 spec AC-34 | 未测 |
| 直接回答（带附件） | 未测 | 未测 | 未测 | 见 spec AC-35 | 未测 |

## 5. 回归结果

后端选择集：4185 通过、120 失败、10 错误、18 跳过。与 Wave 2 提交后的结果逐用例对比：**无新增失败**，新增 72 个测试，去掉 2 个（附件默认读取器的测试随该读取器删除，另一个改名）。120 个失败与 10 个错误在改动前同样存在（本地没有 MySQL、MinIO 等中间件）。
