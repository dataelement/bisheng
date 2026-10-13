# 给客户 K8s agent 的执行说明

修复版 v2：只读取表字段，不读取索引/外键元数据，避开达梦驱动修改
SQLAlchemy 只读 `Row._data` 的兼容性问题。不要仅替换 `dict(row)`。
已在 105 达梦环境完成只读预检查（0 条历史，退出码 0）；真实删除仍需执行以下备份与检查步骤。

任务：清理当前客户测试环境**所有租户、所有 E+ 机器人**的历史轮次，避免旧版本历史影响上下文。
用户已授权本范围；无需再分析实现或修改脚本。只操作当前确认的测试环境。
清理对象仅为 `eplus_turn`；保留机器人配置、绑定空间、会话映射、序号和入站去重记录。
不是清空全部数据库，也不会清除客户 App 界面聊天消息或内部助手历史。

## 操作约束

- 目标 namespace：`bisheng`。先确认当前 kubectl context 是客户测试环境，否则停止。
- 总计最多 5 分钟；每次脚本最多 60 秒。失败立即报告，不进行全仓搜索、重试循环或安装依赖。
- 不改代码、配置、镜像、数据库结构；不清 Redis、MinIO 或其他表。
- 全程请用户暂停给所有机器人发消息。记录所有 E+ Worker Deployment 原副本数。
- 在现有 backend-api Pod 中执行，继承服务环境及配置文件；不能连接另一套数据库。
- 出错也必须恢复刚才停止的 Worker 到原副本数，并报告；不要遗留 Worker 下线。
- 不输出 Secret、连接密码或问答正文。

## 具体步骤

1. 解压包。用 `sha256sum -c SHA256SUMS` 验证文件。
2. 用 `kubectl get pods,deploy -n bisheng` 确认 API Pod 和全部 E+ Worker Deployment。
   通常 Worker 名称是 `backend-worker-eplus`。多副本全部纳入，不能只停一个 Pod。
   如果 E+ 不是独立 Deployment，而和其他 Worker 共用容器，停止并报告，不擅自停其他服务。
3. 将 `clear_eplus_history.py` 复制到 API Pod 的 `/tmp/clear_eplus_history.py`。
   如 Pod 多容器，所有 cp/exec 指定 API 容器。确认后端目录通常为 `/app`，解释器通常为
   `/app/.venv/bin/python`；确认真实路径及 API 的 `config` 环境，不猜测配置、不显示配置内容。
4. 暂停用户发送消息。先执行一次只读预览/备份确认没有非终态轮次。
   使用独一无二的路径，如 `/tmp/eplus-history-precheck-<时间>.json`：

   ```bash
   kubectl exec -n bisheng <API_POD> -- sh -lc 'cd /app && PYTHONPATH=/app .venv/bin/python /tmp/clear_eplus_history.py --all-tenants --backup /tmp/eplus-history-precheck-<时间>.json --timeout 60'
   ```

   `non-terminal` 表示仍有排队/运行中的消息，立即停止清理并报告，不删队列、不改状态。
5. 记录 E+ Worker 原副本数，scale 所有对应 Deployment 到 0。确认原 Pod 已终止；最多等 60 秒。
   不停止 API、其他 Worker 或中间件。
6. 使用新的唯一文件路径执行正式备份。此命令**不删除数据**：

   ```bash
   kubectl exec -n bisheng <API_POD> -- sh -lc 'cd /app && PYTHONPATH=/app .venv/bin/python /tmp/clear_eplus_history.py --all-tenants --backup /tmp/eplus-history-backup-<时间>.json --timeout 60'
   ```

7. **删除前**用 kubectl cp 把正式备份拷到服务器持久目录（不是 Pod 内），文件设为 600。
   对比 Pod 和服务器副本 SHA256，必须一致。备份包含全部待删除记录，不能输出正文。
   路径和校验不成功就停止，不执行 apply。
8. 使用相同 API Pod、同一份正式备份执行删除：

   ```bash
   kubectl exec -n bisheng <API_POD> -- sh -lc 'cd /app && PYTHONPATH=/app .venv/bin/python /tmp/clear_eplus_history.py --all-tenants --backup /tmp/eplus-history-backup-<时间>.json --timeout 60 --apply --workers-stopped --confirm CLEAR_ALL_EPLUS_HISTORY'
   ```

   脚本核对数据库目标、范围和完整记录与备份相同后，才事务删除。
   `mode=deleted` 表示提交成功。任何异常立即停止，不修改脚本绕过检查。
   如发生超时/连接中断，结果可能不确定：不能宣称全部回滚，恢复 Worker 后报告待核实。
9. 无论成功与否，恢复所有 E+ Worker 到各自原副本数，确认启动。
   没有数据迁移；不重启 API。请用户发新消息验证，新首轮应没有历史上下文。

## 最终报告

只报告：目标环境、备份服务器路径和 SHA256、删除轮次数、退出码、Worker 是否恢复、首轮验证情况。
失败则附最短错误摘要；不要再长时间排查。保留备份，不自动删除。

## 恢复说明

备份是完整 `eplus_turn` 行数据，日期、decimal、bytes 使用带类型的 JSON 标记。
需要恢复时停止 Worker，由维护人员解码类型并按原 ID 回插，不覆盖新记录。
当前任务不包含恢复，不自行导入或改变任何其他表。
