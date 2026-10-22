# F059 模型与镜像发行阶段证据

状态：**原生双架构通过，正式CI发行未执行，T071保留未完成**。逐项来源、config ID和校验和见 [model-release-validation.json](./model-release-validation.json)。

模型租户默认None等待上下文，数据库非空且保留索引；显式租户不覆盖，缺上下文拒绝。租户/DM8方言静态组合64、模型审批隔离44通过，Alembic单head f059_resource_phases；没有真实DM8测试。

候选54b3ea2c1在原生amd64、arm64分别完成九镜像构建、隔离resolver/nginx/许可证检查及完整应用包Engine验证。随机SQLite哨兵跨升级保留，实际目录与DB身份不变，两次真实下载备份核验通过。两轮非本次容器/网络清单不变。arm64另10项WAL回归全部通过，含三种真实Docker布局、最新提交可见、SQL只读拒写和并发事务一致性。

Go公网metadata等待、首轮取消及官方材料恢复分别保留，未计为源代码失败或伪造成功。amd64首次classic下载构建由操作者停止，最终使用同源已通过native脚本的镜像。未删除无关镜像或修改daemon代理。

本地config ID不是仓库manifest digest；部署控制镜像另记录LAN固定digest。没有授权新的公共push/tag/DockerHub发行，正式CI未执行；单节点结果不证明跨节点恢复。

## 后续候选 9e7e86cab

189真实业务暴露profile引用与对象混用，已修复并完整runtime1217/13skip通过。前述双架构原生证据仍准确对应54b，不能转标为新候选；9e7同SHA原生重建及烟测正在补验，正式公共CI仍未授权。

候选更新为`0e493c07a`：另修精确无分配404观察语义，完整runtime1259/13skip通过；双架构原生按同SHA重新构建中。9e7不作为已完成的原生证据；54b历史证据保留。

## 候选 0e493c07a 实际补验完成

同SHA原生amd64和arm64均完成9镜像build、isolated smoke、full bundle smoke，全部exit0；arm64实际WAL 10/0skip、三种Docker布局通过。镜像config ID、工具/许可与物料SHA见JSON。amd64非本次容器57个、arm64为2个，前后及网络均保持；不得将旧54b的87个计数移用。54b与9e7过程仍保留于Git和私有日志，9e7未单独完成原生验收。

189仅向专用LAN仓库推送manager固定manifest `b17045eb…`，Helm11升级控制三服务，明确保留原实际能力报告；未发布DockerHub。四个无分配失败draft经owner API正常删除。新六场景prepare暴露空闲租约过期后永久renew409，尚未创建业务Pod，登记T198/T199，不据原生结果声明K8s业务通过。

## 当前amd64验收候选与arm优先级

709821ecb在189原生九镜像构建/隔离烟测及bundle/SQLite数据哨兵通过；d86e66a2d只修改K8s日志容器白名单，另原生manager构建/导入通过，未重复未改helper应用镜像或重标其来源。固定private digest/组件SHA详见JSON，非正式Docker Hub/CI发行。用户已要求先跑通K8s，暂停新的arm验证；此前e405的附加WAL 20秒超时仍未解决，不以旧0e绿色记录覆盖。
