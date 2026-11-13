# 验证记录

- Feature ID: `085-canonical-version-link`
- Date: `2026-11-13`
- Overall: `PASS (local)`；真实环境 `MANUAL_REQUIRED`
- Code State: 正式分支 `feat/2.5.0-sg` 的 `c348f906b99d37ad87512e35785ff087ec23248e` 基础上的本任务未提交工作区。
- 仓库：`/Users/wenruli/code/project/bisheng/bisheng`

## 复现与证据

| Evidence | 结果 | 对应范围 |
|---|---|---|
| E-001 | 初次fixture发现SQLite建表遗漏现有组织字段，补齐测试DDL后稳定复现18094；新增批次6失败、5通过 | V-001 / AC-01至AC-03；`/tmp/canonical-version-link-red.log` |
| E-002 | 反向merge旧实现没有迁移manager身份；补充边界批次2失败、5通过，修复后通过 | V-001、V-003；`/tmp/canonical-version-boundary-red.log` |
| E-003 | 真实最终清理器在还有一个入口时误删invalid文档；删除最后墓碑后又遗留空文档。两个预期失败均观察到，修正判断后通过 | V-002 / AC-04；`/tmp/canonical-version-cleanup-red.log`及初次投影集成输出 |
| E-004 | 最终相关回归 **132 passed, exit 0, 10.97秒**，无排除或跳过；其中新用例21项 | V-001至V-003 / AC-01至AC-05；`/tmp/canonical-version-final.log` |
| E-005 | 新测试Ruff及格式检查通过；6个业务文件相对HEAD没有新增Ruff诊断；py_compile、架构守卫及git diff --check通过 | 静态检查；保留既有诊断，不全文件格式化 |

工作目录 `src/backend`，最终命令：

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_canonical_version_link.py \
  test/knowledge/test_knowledge_version_service_link.py \
  test/knowledge/test_knowledge_version_service_set_primary.py \
  test/knowledge/test_knowledge_version_service_delete.py \
  test/knowledge/test_knowledge_version_service_read.py \
  test/knowledge/test_knowledge_version_endpoint.py \
  test/knowledge/test_shared_space_projection.py \
  test/knowledge/test_knowledge_document_projection_service.py \
  test/knowledge/test_knowledge_document_entry_resolver.py \
  test/knowledge/test_document_projection_batch_worker.py \
  test/knowledge/test_favorite_notification_versions.py \
  test/knowledge/fulltext/test_fulltext_lifecycle_hook.py \
  -q --disable-warnings --tb=short
```

## 覆盖与边界

| Acceptance | 本地状态 | 可观察证据 |
|---|---|---|
| AC-01 | PASS | 两个独立manager关联，目标有/无历史版本均正确；唯一版本行迁移，原对象、上传人、路径保留，原始来源和组织继承 |
| AC-02 | PASS | 双方权限分别拒绝；额外分享入口、租约、删除状态、发布前驱、多版本源、重复MD5、跨库/租户和损坏主版本拒绝，无关系写入；权限服务本身另复用入口解析器回归 |
| AC-03 | PASS | 提交前注入失败后恢复原两文档和manager；重复请求没有额外版本/墓碑/代次；权限校验后代次漂移拒绝 |
| AC-04 | PASS (isolated) | 真正的投影服务在存储失败后持久化failed并可重试，成功写入新主内容；真正的worker最终清理器删除旧canonical墓碑及空文档，保留两个原物理对象；仍有其他入口或物理版本时不删文档；消息派发失败仍保留可被扫描的两条工作 |
| AC-05 | PASS | 原版本关联、主版本切换、删除、列表读取、API、收藏通知、全文事务及投影回归通过；反向manager merge复用同一生命周期 |

所有数据库操作使用测试夹具的隔离内存SQLite。OpenFGA权限读取、Celery发布和共享存储使用替身；数据库仓储、生命周期、入口解析器、投影器、最终清理器和全文outbox真实执行。未运行无关全项目测试或覆盖率统计；本地行为证据不等同真实ES/Milvus读写、MySQL/DM8锁竞争或线上问答验收。最终运行有835项SQLModel等依赖弃用警告，无失败。空文档检查还补充了 `/tmp/canonical-version-empty-document-red.log` 的失败证据：即使没有入口，仍有物理版本时也不得删除文档。

Ruff原业务文件基线诊断数依次为：版本仓储实现11、接口11、schema 0、分发服务3、版本服务9、worker 2，修复后各项数量与诊断内容相同。新增测试完整检查通过。仅格式化新增方法及测试，保留旧代码格式。

## 发布与人工验收

1. 需更新API后端和执行投影的默认worker代码；无新增Schema或历史数据脚本。现有投影扫描补偿保持运行。
2. 在3562库重新关联131060→37753，确认目标版本链保留原V1且新增唯一V2，新文件成为唯一manager。此步骤尚未执行。
3. 等待新manager投影ready，核对旧源37755的墓碑和空文档清理完成；两个原物理文件仍存在。核对默认搜索/单文档问答命中新主版本、历史版本可通过版本记录查看。
4. 核对后台失败重试、实际租户隔离和并发关联锁竞争。生产ES/Milvus/OpenFGA及MySQL/DM8均为 `MANUAL_REQUIRED`。

回退代码前暂停新增关联，先让已提交pending投影收敛；不通过直接改关系表撤销成功关联。本次没有提交、推送、部署生产或执行手工业务数据修复；测试容器应用记录见下。

## 镜像仓库历史源码摘要（迁移前）

- 版本仓储：`3bffbfe014dc8d59d27f411449747fc588a41c565cfb6a796928a0aec90524d3`
- 版本服务：`03afbb3509a300e3a1a3ed95aaecb164656be9a33ef8e77e3abf3067f6d46b71`
- 清理worker：`0a490cedf0d181f36d542a7c1364f70e8cf7f8e0daf68783986a962e09e93078`
- 新回归测试：`77560cb97dbb0916c65120ea54d488c771efaba5cfae01cfa50b3f2f7209a425`

## 开发分支纠正（2026-11-13）

此前E-001至E-005与源码摘要来自首钢镜像仓库main，仅作为迁移前历史证据。本次迁移到正式开发仓库 `/Users/wenruli/code/project/bisheng/bisheng` 的 `feat/2.5.0-sg`，基线 `c348f906b9`。保留分支已有统计刷新与MCP等变更；测试表已有组织列，不再追加。原078编号已被MCP占用，改用085。未提交或推送；此前main来源镜像不作为最终交付。

- E-006：正式仓库自带虚拟环境为Python 3.14，与项目依赖不兼容，首次执行出现mock及LangChain导入失败；没有修改该虚拟环境。
- E-007：在正式仓库 `src/backend` 下使用镜像仓库现有的Python 3.10解释器执行上述同一批回归，**132 passed, exit 0, 13.32秒**。实际测试源码来自正式仓库；日志 `/tmp/canonical-version-feat-py310-final.log`。解释器绝对路径为 `/Users/wenruli/code/project/bisheng/首钢股份git/bisheng-feat-2.5.0-sg/src/backend/.venv/bin/python`。
- E-008：正式分支6个业务文件py_compile、架构守卫、git diff --check、新测试Ruff及格式检查全部通过。
- E-009：镜像仓库main中本次8个已跟踪文件逐一校验SHA256并备份后精确还原；新测试和规格原件已移至备份目录，镜像仓库工作区确认干净。转移回执及完整补丁保存在 `/Users/wenruli/code/project/bisheng/首钢项目/outputs/version-link-branch-correction-20261113-d3e4ecce`。

## 测试环境容器应用（2026-11-13）

用户授权将本次修复应用到 `10.171.0.50` 的容器并重启，随后确认新启动的worker为 `b15e38c1a1d1`。

- E-010：`bisheng-backend` 与 `bisheng-backend-worker` 的六个文件均与正式分支HEAD基线相同；备份并校验后平滑停止，仅替换本次六个文件再启动。两个容器应用后SHA256均与正式分支工作区一致，四个关键模块在两侧均成功导入。
- E-011：API容器 `healthy`，`http://127.0.0.1:7860/health` 返回 `{"status":"OK"}`；Celery控制检查确认 `celery`、`knowledge_celery`、`knowledge_pdf_celery`、`workflow_celery` 四个队列在线。未执行真实文件关联，也未手工修改业务数据；此记录不替代生产业务验收。
- 宿主仅有Python 2，首个Python 3备份脚本在写入前因解释器不存在停止；改为Shell执行备份、应用及重启，Python语法检查使用容器原有解释器，未安装依赖。
- 测试机原文件、回退脚本及回执：`/home/Oper1/sg-version-link-backup-20261113-f345100a`。回退脚本要求先平滑停止两个容器，仅还原六个原文件。容器重建会丢失此次热修复。
- 本地回执：`/Users/wenruli/code/project/bisheng/首钢项目/outputs/test-container-version-link-20261113/deployment-receipt.json`。正式分支镜像已另行构建并校验2199个源码文件及关键模块，尚未推送或用于替换测试容器镜像。
