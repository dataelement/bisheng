# F059 模型与镜像发行阶段证据

状态：**原生双架构通过，正式CI发行未执行，T071保留未完成**。逐项来源、config ID和校验和见 [model-release-validation.json](./model-release-validation.json)。

模型租户默认None等待上下文，数据库非空且保留索引；显式租户不覆盖，缺上下文拒绝。租户/DM8方言静态组合64、模型审批隔离44通过，Alembic单head f059_resource_phases；没有真实DM8测试。

候选54b3ea2c1在原生amd64、arm64分别完成九镜像构建、隔离resolver/nginx/许可证检查及完整应用包Engine验证。随机SQLite哨兵跨升级保留，实际目录与DB身份不变，两次真实下载备份核验通过。两轮非本次容器/网络清单不变。arm64另10项WAL回归全部通过，含三种真实Docker布局、最新提交可见、SQL只读拒写和并发事务一致性。

Go公网metadata等待、首轮取消及官方材料恢复分别保留，未计为源代码失败或伪造成功。amd64首次classic下载构建由操作者停止，最终使用同源已通过native脚本的镜像。未删除无关镜像或修改daemon代理。

本地config ID不是仓库manifest digest；部署控制镜像另记录LAN固定digest。没有授权新的公共push/tag/DockerHub发行，正式CI未执行；单节点结果不证明跨节点恢复。

## 后续候选 9e7e86cab

189真实业务暴露profile引用与对象混用，已修复并完整runtime1217/13skip通过。前述双架构原生证据仍准确对应54b，不能转标为新候选；9e7同SHA原生重建及烟测正在补验，正式公共CI仍未授权。
