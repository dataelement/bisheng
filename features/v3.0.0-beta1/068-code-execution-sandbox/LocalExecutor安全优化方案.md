# LocalExecutor 安全优化方案

状态：已拆成两步，本文保留为原始设想，不再作为实现依据。第一步已实现，是当前依据。第二步 chroot 暂时不做，文档保留但不排期。

- [第一步：普通 uid + 私有运行目录](./LocalExecutor安全优化方案-第一步-uid隔离.md)（已实现）
- [第二步：chroot 监狱](./LocalExecutor安全优化方案-第二步-chroot监狱.md)（暂时不做）

评审后被替换的设计：会话目录直接交给临时 uid（改为每次调用复制进私有目录）；用硬链接让 venv 只存一份（对当前 Dockerfile 不成立，改为允许列表复制）；以 `pip` / `python ` / `bash` 开头来判断拒绝 shell（改为在 `lang` 层统一拒绝）。

`LocalExecutor` 的安全边界做成一棵共用的 `chroot` 监狱：虚拟环境只留一份，每次调用用临时 uid，可写目录按会话分开。监狱缺失、进程不是 root、或 `chroot` 失败时直接失败，不再退回现在这种跟 worker 同用户的子进程。

这只加固 `type=local`。代码节点继续用 `/opt/code-root`（只有标准库、全程只读）。`type=container` 继续走独立的 sandbox 镜像，不把这套监狱塞进后端镜像去替代它。

## 现状缺口

`LocalExecutor` 用 `sys.executable` 拉起子进程，用户和 worker 相同。镜像里 worker 是 root，权限位挡不住写。环境是 `os.environ.copy()`，数据库、Redis、MinIO 的密钥会进子进程。`communicate()` 把标准输出全部读进 worker。`workspace_escape_guard` 只检查脚本文本。`insert_set_font_code` 每次运行都删掉进程共享的 matplotlib 字体缓存。

## 监狱里有什么

监狱根目录固定为 `/opt/local-root`，所有调用进入同一棵树。

- 解释器、`/app/.venv`、动态链接器和 `libpython` 按原绝对路径放进监狱。虚拟环境在构建它的同一步里硬链接，镜像只存一份。系统动态库在更早的镜像层里，后面这一层会多存几十 MB。跨镜像层硬链接会在写入时复制出第二份，所以不能在后面的 `RUN` 里再链一次 `/app/.venv`。
- 这些路径属 root，目录 `555`、文件 `444` / `555`。子进程已换成普通 uid，写不进去。
- 监狱内生成 `/etc/ld.so.cache`，不设置 `LD_LIBRARY_PATH`。
- `/work` 属 root，权限 `755`。会话目录在运行时建在这里，不打进镜像。

默认 Docker 能力集有 `CAP_SYS_CHROOT`、`CAP_SETUID`、`CAP_SETGID`，没有 `CAP_SYS_ADMIN`。worker 不能在运行时把活的虚拟环境挂进监狱，必须在镜像构建时放好。

LibreOffice、pandoc 不放进这棵树。子进程若再调它们，调用失败。需要这些程序时走 `type=container`。

## 谁可以写哪里

uid 从 `30000`–`39999` 临时领取，和代码节点的 `20000`–`29999` 分开。占用标记放在监狱外的 `/var/run/bisheng-local-uids`。跑完并确认该 uid 下没有残留进程后，标记才删除。

可写目录按会话分，不按 uid 分：

- 灵思任务用 `/opt/local-root/work/<会话 id>/`。同一次任务的多次调用共用它，上次的 `output/`、`scratch/` 还在。
- 没有会话时，每次调用用 `/opt/local-root/work/<随机 id>/`，父进程收完文件就删。

执行前父进程把该目录交给当前 uid（`0700`），并把 `cwd`、`HOME`、`TMPDIR`、`TEMP`、`TMP`、`MPLCONFIGDIR` 都指到这下面。子进程写的交付物、临时文件和字体缓存都落在这里。脚本由父进程事先写入同一目录。

其他会话目录保持 root、`0700`。当前 uid 能穿过 `/work`，打不开别的会话，也不能在 `/work` 下新建目录。调用结束后所有权收回 root，这个 uid 再被领走时也进不了上一份目录。

父进程不进入 `chroot`。子进程看到的 `/work/<id>`，父进程打开 `/opt/local-root/work/<id>`。收文件时每一级都不跟随符号链接，只读普通文件；把目录收回 root 时同样不跟随。收完后按现有逻辑上传 MinIO，并同步回灵思的 `local_sync_path`。

## 子进程约束

环境只保留 `PATH`、`LANG`、`TZ`、`HOME`、`TMPDIR`、`TEMP`、`TMP`、`MPLCONFIGDIR`。Python 加 `-B`。不再把父进程环境整份拷进去，也不再删除共享字体缓存。

只执行 Python。以 `pip`、`python `、`bash` 开头而被当成 shell 的输入直接拒绝。

资源上限加在这个独立 uid 上：地址空间、CPU、可写文件大小、打开文件数、进程数。进程数上限不能加在与 Celery worker 相同的 root 上，否则会打断 `-P threads` 的 worker。墙钟超时保持现有的 600 秒，超时后按进程组杀掉，再按 uid 清残留。标准输出在读取时截断，避免把 worker 撑满。

## 明确不做

- 不给每个 uid 复制一棵 `chroot`。
- 不把完整虚拟环境再拷一份进镜像，也不把它链进 `/opt/code-root`。
- 不做网络隔离。`chroot` 之后子进程仍使用容器的网络，这是剩余风险。
- 不在非 Linux、非 root 的开发机上模拟这套监狱；那种环境直接拒绝执行。
