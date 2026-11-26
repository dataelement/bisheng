# 开发者 Token 同步记录 — 研发验证用例

| 项 | 值 |
|---|---|
| 文档版本 | `0.2.0` |
| 日期 | `2026-11-24` |
| 用途 | 研发开发期验证 |
| 需求 | `requirements.md` v0.2.0（Q2=A） |
| 设计 | `design.md` v0.2.0 |
| 定义状态 | 业务用例已按 Q2=A 更新；契约细节待设计确认后锁定 |
| 岗位 | 研发 → `src/backend/test/`；Platform vitest（非浏览器） |

## 1. 覆盖概览

| 功能 | REQ/AC | 用例 |
|---|---|---|
| 入口权限 | REQ-001 AC-01 | TC-DTSR-01, 02 |
| 接口列 | REQ-002/006 AC-02 | TC-DTSR-03 |
| 错误 16KB／脱敏 | REQ-003 AC-03 | TC-DTSR-04, 05, 06 |
| 仅同步类写入 | REQ-004 AC-04 | TC-DTSR-07, 08 |
| 汽车板 | REQ-004/005 AC-05/06 | TC-DTSR-09, 12 |
| 写失败不阻断 | INV-4 | TC-DTSR-10 |
| MCP | — | **删除**（Q2=A 不适用） |

## 2. 用例清单

| ID | 标题 | 优先级 | 类型 | 关联 | 前置 | 步骤 | 数据 | 预期 |
|---|---|---|---|---|---|---|---|---|
| TC-DTSR-01 | 有权 list 仅本 Token | P0 | 功能 | AC-01 | Prep-Token T + 记录 | list(T) | page=1,limit=5 | 仅 T；倒序 |
| TC-DTSR-02 | 跨租户 list 拒绝 | P0 | 安全 | INV-2 | Token 他租户 | list(T) | — | 拒绝无泄露 |
| TC-DTSR-03 | file/sync 与汽车板 interface 可区分 | P0 | 功能 | AC-02 | 两类各 1 条 | list(T) | — | interface 不同 |
| TC-DTSR-04 | 短错误全文且未截断标记 | P0 | 功能 | AC-03 | failed 100 字 | list | — | 全文；truncated=false |
| TC-DTSR-05 | 16385 字节截断 | P0 | 边界 | AC-03 | 超长错误 | record_finished | 16385B | ≤16384；truncated=true |
| TC-DTSR-06 | Token 头值脱敏 | P0 | 安全 | REQ-003 | 含伪密钥 | record_finished | — | 库无明文 |
| TC-DTSR-07 | file/sync 失败落库 trigger=api | P0 | 功能 | AC-04 | mock sync 失败 | 跑 sync 收尾 | — | 有 failed 行 |
| TC-DTSR-08 | retrieve 失败不落库 | P0 | 异常 | AC-04 | 同 T 调 retrieve 失败 | 断言表 | — | 无新增同步记录 |
| TC-DTSR-09 | 汽车板手动失败归关联 T | P0 | 功能 | AC-05 | 关联 T | 测试同步失败 | — | trigger=manual |
| TC-DTSR-10 | record 抛错不改 sync 结果 | P0 | 异常 | INV-4 | repo raise | sync 收尾 | — | 业务结果不变 |
| TC-DTSR-12 | 汽车板前端无 runs 区块 | P0 | 功能 | AC-06 | 组件源码/快照 | 检查 | — | 无最近执行表 |

## 3. 异常边界专项

空列表、超长、重复各一次一条、权限、写库失败：见上表。MCP／弱网：不适用。并发两同步 → 两行：待补 TC-DTSR-13（设计确认后）。

## 4. 自动化

TC-DTSR-01～10：pytest 可自动化。TC-DTSR-12：源码断言或 vitest。UI 点选与真实环境 → 独立验收。
