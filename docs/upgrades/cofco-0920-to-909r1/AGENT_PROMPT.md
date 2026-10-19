# 中粮0920到909r1升级执行指引

你负责客户生产BiSheng从`v3.0.0-cofco-0920`升级到`v3.0.0-cofco-909r1`。解压离线说明包后，先阅读同目录`UPGRADE.md`和`preflight.sql`，校验`SHA256SUMS`；若直接在仓库执行，正文在`docs/cofco-upgrade-0920-to-909r1.md`。目标Git提交`2113fc2108af5921cd3e170f798c86ce40684886`，ARM镜像标签为`v3.0.0-cofco-909r1-arm64`，前后端都要更新。

## 本轮先做只读预检

在负责人明确批准生产变更前，不执行scale、配置更新、DDL、权限apply或任何数据修复。先输出以下结果，缺项即停止进入写阶段：

1. 实际namespace、节点架构、运行镜像及digest、API/所有Worker/Beat/Linsight/调试进程清单、原副本数，以及控制它们的HPA/CronJob/GitOps。不能只查一个API Pod。
2. 数据库实际连接目标和`alembic_version`，不得展示数据库密码、模型Key或机器人Secret。预期0920迁移头为`f059_merge_cofco_909_f058_heads`。出现未知revision、多头、923/f068或额外热改时报告偏差，不擅自downgrade/stamp。
3. 模型服务商表是`llm_server`，检查与`llm_model.server_id`的关联；验证助手模型和创建助手的系统模型可用，不从日志401直接猜“密钥过期”。
4. SQL唯一CURRENT Catalog、ACTIVE授权模型release、Store/model/checksum、在途权限投影；用909r1镜像独立维护Job跑权限发布dry-run，不启动API/Worker。
5. 新镜像实际linux/arm64、r1离线包SHA256、所有调度节点的CRI镜像库存；Docker load成功不能代替containerd导入证据。不能把本地909h6旧包当r1使用。
6. 所有ConfigMap Python热补丁、entrypoint挂载和正常配置挂载。逐项报告，不清空volumeMounts。`entrypoint.sh`需支持eplus，普通配置/证书挂载保留。
7. 完整业务DM库与OpenFGA实际数据库备份方案、Pod外存储位置、恢复演练结果、旧镜像可用性、生产E+参数和OCR/模型/索引连通条件。

预检最后只给“可以开始/被哪项阻断”、数据迁移差异、预计维护范围和待确认项。不要重新研究已经在UPGRADE.md写明的迁移路径，不创建另一套数据库/权限Store试图绕开错误。

## 获得升级批准后的严格顺序

1. 入口维护、停止新任务投递，排空在途业务；保存副本数，停止所有业务API/Worker/E+/调试进程，暂停可重新拉起它们的控制器。中间件和OpenFGA继续运行。
2. 取得并核验停写后的业务库/OpenFGA一致恢复点，备份移出Pod；无备份不做迁移。等待F048心跳消失，不能通过删Redis键绕过门禁。
3. 同一909r1镜像/生产配置的独立Job中执行Alembic正向升级。预期最终唯一head为`f061_merge_cofco_909_f066_heads`，核对5张E+表及PAT列/默认值，保留执行日志。
4. 权限发布dry-run→人工核对Store和target checksum→按该次输出执行`publish_authorization_model_change.py --apply`。需真实管理员operator-id。0退出且marker校验成功才继续；已经current也不能跳过apply。3/4退出保持维护并定位，不重复首次F048迁移，不改Grant，不强行改CURRENT指针。
5. 逐项更新启动ConfigMap、909r1前后端镜像和已有Worker，移除已被正式代码替代的Python补丁挂载。维护Job复用实际API env/config/网络，但不能继承会被API Service选中的label。
6. 首次新建E+独立Worker，复用已有后端配置，`sh /app/entrypoint.sh eplus`，1副本，不能用Celery或HTTP探针。不上线临时机器人debug服务；不复制测试Bot凭据。
7. 先1个API并验证迁移/权限→普通Worker/前端→E+ Worker及生产助手上线→业务验收→恢复原副本、调度和入口写入。API健康200只是必要条件，不代表权限/E+验收通过。

## 禁止事项

- 不运行downgrade、stamp、删除alembic版本记录、生产临时merge revision。
- 不删除模型服务商、用户、历史、知识库，不清空Redis/索引，不无条件重解析所有文件。
- 不关闭TLS校验，不写死测试密钥、模型ID、Store ID或管理员ID。
- 不重新跑`migrate_f048_permission_data.py`补标记；不默认执行全量可见投影/孤儿tuple清理。
- 不只回滚镜像或只恢复业务库。发生权限切换后回退，必须保证业务SQL、OpenFGA和旧版配置/镜像一致；恢复写入后回退须另行确认增量数据处理。

失败时保留日志并给出“步骤、首个异常、哪些数据已改、是否仍停写、下一步需谁确认”。不要反复长时间搜索无关机器人消息日志来定位DDL或权限发布错误。

## 完成报告

报告新前后端digest/架构、各Deployment镜像和副本、迁移头和新表/列、权限发布成功事件与marker校验、原有功能/普通用户授权/新API/E+文字图片知识流式验收、补丁移除、备份位置及回退条件。未做的验收明确标注，不把“Pod Running”写成全链路成功。
