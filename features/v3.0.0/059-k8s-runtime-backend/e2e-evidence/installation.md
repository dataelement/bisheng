# F059 189 安装验收阶段证据

状态：**部分通过，T068仍未完成**。源码、镜像和逐check记录见 [installation.json](./installation.json)。

第三轮真实执行15项必需检查及registry-push全部成功，正常cleanup完成，exit0。覆盖受限RBAC/exec、PSA、同UID删除与binding拒绝、CNI/状态来源、网络隔离、SQLite锁/fsync与镜像实际启动。此前两轮失败保存在189专用evidence目录，没有用后续成功覆盖历史。

Helm revision9把manager/egress/admission统一到7e720073b候选，升级原样保留canary计划UID与字节；动态probe_report被清空，故重新执行完整第四轮，报告有效前拒绝新部署。第三轮不能代替最终候选复验。

先前失败进程留下的资源仅按自然到期、同UID和实际binding停止证明恢复；旧dryRun的UID空计划不能直接假定为资源已停止。其清理、最终报告失效配对和业务故障验收仍待完成。单节点结果不证明跨节点恢复；DM8按用户确认仅静态检查。
