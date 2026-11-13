# F119 Code Review Report

日期：2026-11-03。范围：当前独立工作区全部Feature修改（含此前未提交的清单/官方示例/入口改动），对照已确认42条spec/design/tasks。代码基线HEAD `463d6fc20`；`feat/3.0.0...HEAD`混有此前上游交付，本Feature尚无提交，故用`git diff HEAD`加逐个未跟踪文件作为实际审查范围，不将已有提交归入本Feature。

**结论：本地代码预审完成；最终交付门 NEEDS_FIX（原生镜像/真实E2E证据待补）。** 本报告不表示部署验收通过，也不将43任务全部勾选。用户在获知这些限制后明确要求先合并到feat/3.0.0并推送，按本轮指令交付代码，原生镜像/真实E2E待验保留。本审查由同一代理完成，无独立第二审查者。

| 维度 | 代码审查结果 | 证据/限制 |
| --- | --- | --- |
| 边界条件 | PASS | 新旧清单分开；未知版本/JSON/入口/链接拒绝；静态build前后区别；未知版本序号为空；checker输入、字节/行数/时间限制与过期检查 |
| 权限与认证 | PASS（本地） | 公开tail重走log_read→edit；publish-only不读失败；app/tenant/version/deployment关联；F114非owner普通主体测试；K8s固定目标hash、独立registry来源和检查目的；真实普通账号待验 |
| 并发安全 | PASS（本地） | 原operation/epoch/UID/lease围栏；清理重试保留第一失败；检查Pod终态仅由可信status确认，保留finalizer至原cleanup；不新增本地共享主数据 |
| 信息泄漏 | PASS | 脱敏后40行/16KiB；无法解封/缺敏感上下文不公开输出；公开查询不describe/unseal；发布失败和审计递归去tail；安全image_role/ref格式限制 |
| 测试覆盖 | NEEDS_FIX（交付门） | 本地167 backend/100 CLI/4 proxy通过；manager863通过、20个已对照复现的基线失败、6跳过；真实E2E3跳过；新服务镜像尚未原生构建/部署 |
| 风格/分层 | PASS | ruff/arch-guard通过；backend无Docker/K8s编排入口；纯默认块和静态selector复用；跨进程检查文档用实际manager子进程12模式组合核对 |
| 文档同步 | PASS | design实施落点、任务/Owner、编号F119、发行单元、验收清单与限制已同步；release-contract/索引已更新 |

## 审查中已修复

- 将诊断从长期发布失败/审计中移除，只在原保留期内的合法公开读时补充；runtime management同样查询时过期。
- 保留主失败原因，日志读取异常不会替换它；终态重试保留原安全镜像上下文，不复活到期tail。
- Docker在source/material准备前核对runtime/preparer，维护前及启动时再核对固定运行镜像；兼容构建FROM采用已检查Image ID。
- K8s检查用途在模板、backend意图与admission基线同时收紧；无业务/源码挂载；HTTP私有registry只沿用安装侧明确来源，其他源TLS不变；bundle不被额外assembler配置阻断。
- CLI实际wheel更新post2，并完成空venv和fresh login shell验证，SDK分发未变；16227文案和三语生成产物一致。
- 最新发版线F118编号已被项目内新建对话占用，改为F119并扫引用；功能和AC未变。

## 未关闭项

1. T042：原生服务镜像build/发行、真实registry检查时延与116整条发布/审批/写库/停启/权限/清理验收。当前本机orbstack socket不存在；未替换任何环境服务。完整步骤与授权边界见deployment-plan.md、e2e-checklist.md。
2. T043最终门：原生镜像/E2E证据到位后重核；本轮已整合最新远端a65f130cf4并复核源码，提交/推送结果记录于verification.md。

预期交付范围与剩余限制已写明；没有发现仍需修改的已知本地业务逻辑缺陷。原有测试夹具/导入顺序/中间件依赖失败单独留证，不通过削弱授权或删除断言关闭。

## 本轮合并授权

用户明确指令：“合并到feat/3.0.0分支并推送远端”。此指令在已披露41/43任务、原生服务镜像/116真实E2E待验与20项manager基线失败后给出，允许本轮代码合入及推送；不把待验项改为通过，不替换环境服务。合并时使用最新远端，并保留F118项目内新建对话等后续增强。

## 合并后源码复核

`03d8d82c8`整合最新远端`a65f130cf4`及Feature提交`4a91ec61d`；91个Feature变更文件的范围与预审一致，唯一索引冲突保留双方条目。合并后backend 167通过/3 E2E跳过、CLI 100通过、manager定向400通过，i18n/生成检查通过。用户要求先交付代码，原生服务镜像/真实部署验收仍未关闭，不将NEEDS_FIX交付证据状态改成全部通过。
