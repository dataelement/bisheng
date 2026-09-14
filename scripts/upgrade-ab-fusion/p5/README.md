# P5 A 知识空间迁入 B

一个空间是一致性单元（元数据 + MinIO 原文件 + 在 B 重建解析/向量/全文 + 成员 + 新 OpenFGA tuple）。  
**禁止拷 A 的 Milvus collection、ES index、OpenFGA store、A 自增 ID。B 保持共享存储关闭。**

默认 `APPLY=0`，不落库。Agent 不代跑。

## 脚本

| 步骤 | 命令 | 说明 |
|---|---|---|
| 导出 | `bash p5/00-export-a-space.sh --space-id <A空间id>` | 只读 SSH A，JSON 在 `logs/p5/` |
| 盘点 | `bash p5/10-inventory.sh` | 数量 + B 同名 + 抽出 `fusion_user_map` |
| dry-run | `bash p5/20-dry-run.sh` | 所有者映不上则阻断该空间 |
| apply | `APPLY=0 bash p5/30-apply.sh --space-id <id>` 再 `APPLY=1 ...` | B 容器内 Service 建空间；拷 MinIO；入队重解析 |
| verify | `bash p5/40-verify.sh` | 数量、对象抽样、版本链、解析状态。入队成功 ≠ 解析完成 |
| 回滚 | `APPLY=0 bash p5/90-rollback.sh <manifest>` | 只删 manifest 里的本批新 ID/对象 |

续跑：已有 `fusion_file_map.b_file_id` 的跳过拷贝。批次清单：`logs/p5/batch.txt`（每行一个 A `space_id`）。

## 本批明确跳过

A 传统库 type=0、工作流、会话、共享存储 migrate、打开首钢同步。部门树走 P4 `02/03/04`，按 `external_id` bind/create；部门作用域映不上 **阻断该空间**，禁止降级 personal。

收藏/置顶/订阅：`p5/50-export-a-relations.sh` + `51-apply-relations.sh`（映不上跳过）。积分：`p4/10-export-a-points.sh` + `11-apply-points.sh`（`point_rule` 用 A 覆盖）。全量编排：`bash ../full-migrate.sh`（默认 APPLY=0）。

VIOLATION 文件进例外清单、不入解析队列。SUCCESS/FAILED/TIMEOUT 拷原文件后在 B 重新解析。MinIO 拉取失败或入队脚本缺失即停。
