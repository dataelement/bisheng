# F119 待部署交付清单

用户已明确要求本轮代码合并并推送feat/3.0.0；提交/推送结果见verification.md。本清单仍不表示已发行服务镜像或已获得替换116服务的授权。

## 需要一起交付的组件

| 单元 | 本次内容 | 验证要求 |
| --- | --- | --- |
| backend + Celery workers | 新输入默认2/bundle；固定runtime/health；准备/启动分类；公开edit诊断与保留期；K8s image-check冻结文档/registry来源策略 | 同一代码版本，无数据库迁移/历史回填 |
| runtime-manager | 公共环境、入口、静态产物、清理前诊断、Docker及K8s镜像检查 | 目标平台原生构建；本地合同通过不代替Engine/registry |
| trusted helper | 同版manager包、image_check、既有crane v0.22.1与许可证 | `scripts/build_runtime_images.sh`的原生工具/隔离/许可证烟测 |
| assembler | 继承同版helper，静态规范产物消费 | source-image需要；bundle不要求配置assembler |
| CLI/官方skills/locale | post2 wheel、manifest/hash、三份2/bundle示例和路径要求；16227三语 | 实际平台下载、skills sync、空venv安装后复核 |

无需重建Python/Node/static runtime镜像来实现运行变量与入口修复；不主动重建现存正式应用，不改现有profile/材料归属、image pull/offline/运行网络策略。

## 交付次序

1. 审查本工作区diff及未跟踪文件；本轮已整合最新发版线a65f130cf4，保留其增强，F118编号冲突已由本任务顺延F119解决。按用户指令提交/推送代码后，CI发行需记录确切source revision，按新唯一发行标识运行原生构建；不覆盖已发行tag。
2. 在CI/原生构建机验证脚本并取得不可变镜像digest/Image ID、目标架构及许可证证据。当前本机Docker daemon不可用，服务镜像尚无这些证据。
3. 核对116原服务/应用/profile/策略摘要。另行明确本次环境更新授权后，按现有部署方式更新同提交backend/worker/manager；K8s helper/assembler仅在对应环境另行授权后更新，116验收不扩大为189变更。
4. 按e2e-checklist新建专用e2e-f119资源/普通身份，实际CLI预检→真实审批→上线→写库→停启保留，验证Node/static与权限拒绝；记录并清理本次精确资源。
5. 复核原业务资源/网络策略不变，更新verification和最终L2；目前T042/T043未关闭。

## 回退

保留更新前镜像/部署说明与原固定交付，不迁移数据或历史清单；若旧代码不识别新发行合同，停止新提交并按原受控流程回退平台组件，不自动重建正式应用或把新固定版本改写为旧语义。失败日志始终只有原RuntimeOperation保留来源，不从发布历史复活。
