# F059 模型与镜像发行阶段证据

状态：**部分完成，T071仍待验收**。逐项来源和校验和见 [model-release-validation.json](./model-release-validation.json)。

模型租户默认值使用None等待上下文，数据库仍非空且带索引；显式租户不覆盖，要求上下文但缺失时拒绝写入。租户/DM8方言静态组合64通过、模型与审批隔离44通过；Alembic仅f059_resource_phases单head。按用户确认没有连接真实DM8。

固定7e720073b的原生arm64九镜像构建、隔离resolver/nginx/许可证烟测及完整Engine应用包验证通过。随机SQLite哨兵跨升级保留，实际目录与DB身份不变，两份下载备份核对同值；原有容器/网络清单不变。amd64同源九镜像原生构建、隔离烟测与串行完整Engine烟测均已通过；随机SQLite哨兵、相同目录/DB身份及两次实际备份下载均验证，原有116个非本轮容器和完整网络清单不变。两个架构分别在原生引擎运行，没有以模拟替代。

这些是本地原生验证；镜像config ID不能写成仓库manifest digest。当前没有授权新的公共push/tag/DockerHub发行，正式CI发行未执行，不声明T071或全部F059通过。单节点结果不证明跨节点恢复。
