# LocalExecutor 安全优化方案 · 第一步：普通 uid + 私有运行目录

状态：已实现，默认 `off`（Compose 默认开启，见 [沙箱配置与使用说明](./沙箱配置与使用说明.md) 3.4）。实现与本文的出入见"代码改动"表下方的说明。本机模式停在这一步。第二步（chroot 监狱）暂时不做，文档保留在 [LocalExecutor安全优化方案-第二步-chroot监狱.md](./LocalExecutor安全优化方案-第二步-chroot监狱.md)，不排期、不实现。原始设想 [LocalExecutor安全优化方案.md](./LocalExecutor安全优化方案.md) 里的"同会话目录交给临时 uid""硬链接 venv"两处设计已被本文替代。

## 目标

只改后端代码和配置，不动镜像，把 `type=local` 的子进程从"跟 worker 同为 root、继承全部环境变量、直接在任务工作区里运行"改成"换成普通 uid、环境变量白名单、只在私有运行目录里运行"。私有运行目录有两种寿命：代码节点每次调用一个、用完即删；灵思按任务保留一个，任务结束、工作区被删时一起删（见"运行目录的两种寿命"）。

解决：

- 用户代码拿不到 worker 的环境变量（数据库、Redis、MinIO 密钥）；读不到 `/root` 下的东西（`/root/.cache/bisheng/` 里有所有用户的上传缓存和各任务工作区）。
- 用户代码改不了、也换不掉任务工作区里的任何东西；写不了工作区和 `/root`。
- 输出、磁盘、进程数、内存有上限；超时后按 uid 清掉残留进程；进程被杀后遗留的运行目录会被清掉，不会被下一个拿到同一 uid 的调用读到。
- 去掉 `insert_set_font_code` 每次删除进程共享字体缓存的竞态（仅在隔离模式下）。

不解决（见"剩余风险"）：

- **对所有用户可读的文件仍然可读**。`/app/bisheng`（含挂进来的 `config.yaml`）和 `/app/data` 由"权限收紧"一节单独关上，启动时实测；其余如 `/etc`、`/usr`、`/app/.venv`、`/app/bisheng_langchain` 仍可读。
- **`/tmp`、`/var/tmp`、`/dev/shm` 这类全局可写目录**：脚本可以在里面写文件，也可以读别的运行留在那里的、权限为 `0644` 的文件。是否收紧是另一项可选加固，不在本方案内。
- 网络、内核漏洞。

这些不在本方案内。chroot 监狱暂时不做；需要挡住它们时用 `type=container`。

## 现状缺口（已对照代码核实）

| 缺口 | 位置 |
|---|---|
| 子进程与 worker 同为 root | `local_executor.py::_execute_code`，镜像没有 `USER` |
| 环境整份拷进子进程 | `_child_env`：`os.environ.copy()` |
| 子进程直接在任务工作区里运行 | `run`：`run_with_dir(dir_path=self.local_sync_path)`，灵思的 `file_dir` 是 `/root/.cache/bisheng/linsight/<svid8>`（`task_exec.py:931`） |
| 输出无上限 | `proc.communicate()` 把 stdout / stderr 全读进 worker 内存 |
| 无资源上限 | 容器模式的 runner 有 `RLIMIT_AS` / `NPROC` / `CPU`（`sandbox-runner/execute.py:34`），本机模式一个都没有 |
| 共享字体缓存被并发删除 | `insert_set_font_code`：`os.remove(fontlist*)` |
| 只有文本检查 | `workspace_escape_guard`，不是边界 |

## 核心设计：子进程从不接触任务工作区

直接把 `file_dir` 交给临时 uid 行不通：`file_dir` 在 `/root` 下，普通 uid 进不去；而且父进程还要往里写脚本、写知识库图片、收文件，这些写入都可能被用户代码事先放好的符号链接带出去。

所以改成和容器模式一样的数据流：

```text
任务工作区 W（root 独占）  --复制进来-->  私有运行目录 R（归当前 uid）  --只收普通文件-->  W
```

一次 `execute_code(work_dir=W)` 的流程。`work_dir` 为 `None` 时不进入这条流程，直接失败：原来的默认值是共享的 `extensions/` 目录，不能把它当工作区复制进去再收回来。

1. 取一个 uid（见"uid 池"）。取到之后，先删掉 `local_run_root` 下所有属主是它的目录。保留模式下，该 W 已经有 uid 和 R，直接沿用，跳过第 1、2 步。
2. 在 `local_run_root` 下 `mkdtemp` 建 R，`chown` 给该 uid，权限 `0700`。R 里再建 `.tmp/`、`.mpl/`。
3. 把 W 复制进 R（规则见下）。临时模式全量复制；保留模式只复制 W 里新增或变化的文件。两种模式都记录每个文件的 `(size, mtime_ns)`。知识库图片暂存发生在 `execute_code` 之前，已经在 W 里，会被一起带进去，`KbImageStage` 不用改。
4. 把脚本写进 R（脚本名沿用 `tmp_code_<md5>.py`，收文件时按名字排除）。
5. 以该 uid 启动子进程，`cwd=R`，限制资源，读输出直到退出或超时。
6. 无论如何都清场：以该 uid 发 `kill(-1, SIGKILL)`，确认 `/proc` 里该 uid 已无存活进程。
7. **只有第 6 步确认成功**，才把 R 里新增或改变的普通文件收回 W（规则见下）。临时模式随后 `rmtree(R)`，删标记，释放 uid；保留模式留下 R 和 uid，等工作区被删时再释放。
8. 第 6 步确认失败：不收回任何文件，不删 R，保留标记，这个 uid 不再分配，记 error 日志。R 留给后续回收（见"uid 池"）。保留模式下同时把这个 W 的登记作废，下次调用重新取 uid、重新建 R、全量复制。
9. 返回日志前，把日志里的 R 替换成 W（模型看到的路径保持一致）。

`run_with_dir` 的快照差分、`output/` 收割、`sync_to_workspace`、`sync_files_to_local` 都不动：它们看到的还是 W，只是 W 里的新文件由第 7 步写入。

### 运行目录的两种寿命

| | 临时模式 | 保留模式 |
|---|---|---|
| 谁用 | 工作流代码节点（`work_dir` 是每次新建的临时目录，没有稳定的 W） | 灵思（W 是整个任务期间不变的 `file_dir`） |
| R 的寿命 | 一次调用 | 从该 W 的第一次调用起，到该 W 被删时止 |
| 复制进来 | 全量 | 增量，只复制 W 里新增或变化的文件 |
| uid | 每次调用取、调用完还 | 第一次调用取，W 被删时还 |

**为什么能做保留**：灵思的 W 在 `task_exec.py::_cleanup_resources` 里被 `shutil.rmtree`（任务上下文的 `finally`），寿命与任务一致。R 跟着 W 走，不需要另设空闲超时和独立的会话生命周期。

**怎么选模式**：灵思在构造代码解释器时，往 `code_config["config"]["local"]` 里写 `keep_run_dir = True`（和现有的 `local_sync_path`、`workspace_prefix` 写在同一处，`workbench_impl.py`）；没有这个标记就是临时模式。

**登记表**：保留模式在 worker 进程内维护一张表，键是 `realpath(W)`，值是：

- uid 和 R（uid、R 在第一次调用时才真正领取，但**登记条目本身在构造执行器时就创建**，见"释放钩子的覆盖"第 3 点）。
- 同步索引：`{相对路径: (size, mtime_ns)}`，表示 R 与 W 此刻一致的那些文件。
- 两把锁和一个 `closing` 标记（见下面"同一个 W 的调用串行"）：外层 `asyncio.Lock` 负责排队，内层 `threading.Lock` 负责真正的互斥。
- 登记条目的句柄存在执行器上，条目有"已关闭"状态；调用看到已关闭就直接返回"任务已结束"，不会重新注册。同一个 W 的下一轮会新建句柄，不受旧条目的"已关闭"影响。

**释放钩子**：新增 `release_local_run(W)`，在 `_cleanup_resources` 里、`rmtree(W)` 之前调用（要放进线程池，因为里面有杀进程和删目录的阻塞操作；worker 进程里所有任务共用一个事件循环，阻塞会拖住同进程的其他任务）。它只碰内层 `threading.Lock` 和 `closing`，**不碰外层 `asyncio.Lock`**。放置要求：

- **放在自己的 `try` 里，排在 `_cleanup_resources` 的第一位**，不与 `_stop_termination_monitor()` 共用同一个 `try`。现有代码里后者抛异常会跳过后面的 `rmtree`，钩子不能因此被跳过。
- **按 `self.file_dir` 操作，不套用现有的 `os.path.exists` 判断**：W 目录已经不在，R 照样要释放；`file_dir` 为 `None`（驱动在初始化工作区之前就失败）时直接返回。
- **用 `asyncio.shield(asyncio.to_thread(...))` 调用**。清理阶段被再次取消（例如 worker 关闭）时，释放线程仍会跑完，不会让"调用方去删 W、释放还没做完"的顺序失控。

顺序：

1. 置 `closing = True`，对该 uid 清场并确认；这会让正在跑的那次调用提前返回。
2. 等内层锁（带超时），正在跑的那次调用发现 `closing` 后不做收回，直接返回"任务已结束"。
3. 删 R，删标记，归还 uid，从登记表里去掉。排队中的调用手里还握着这个登记条目的引用，拿到锁后看到 `closing`，同样直接返回。
4. 清场未确认时和平时一样：不删 R，不还 uid，留给启动清扫。

任务结束时不做收回，因为 W 马上就删。

#### 释放钩子的覆盖（已对照 `task_exec.py` 核实）

**已覆盖的路径**：

| 入口 | 上下文管理器 | 清理 |
|---|---|---|
| `async_run`（新任务） | `_managed_execution` | `finally` 里 `_cleanup_resources` |
| `async_resume`（回答 ask_user 后续跑） | `_managed_resume` | 同上 |
| `async_continue`（继续对话） | `_managed_resume` | 同上 |

- **停靠**：任务停靠时协程直接返回，同样走这条 `finally`，W 和 R 在停靠时就释放了。续跑、继续对话每次都重新 `_init_file_directory`、重建工具，每一轮是新的 W、新的登记。
- **谁会设 `keep_run_dir`**：`_init_bisheng_code_tool` 在生产代码里只有 `task_exec._generate_tools` 一个调用方，其余都是测试。工作站日常对话建代码工具时没有 `local_sync_path`，走临时模式，不会遗留登记，不需要钩子。
- **三处 `one.close()`**（`_execute_workflow`、`_resume_workflow`、`_continue_workflow` 的 `finally`）：`LocalExecutor.close()` 来自基类，是空操作，释放不能指望它。它们在驱动结束时先执行，早于 `_cleanup_resources`。
- **驱动在初始化工作区之前失败**（例如 `TaskAlreadyInProgressError` 在 `try` 之前抛出、或附件摄取失败）：`file_dir` 还是 `None`，也没有构造过代码执行器，钩子直接返回，不会误释放正在运行的另一个驱动的登记。

**需要补进设计的四处**：

1. **钩子独立于 `_cleanup_resources` 里现有的 `try`**，且按 `self.file_dir` 操作，不依赖 `exists`。见"释放钩子"的放置要求。
2. **终止时线程还在跑**：终止路径是 `task.cancel(); await task`。`agent_task` 如果正阻塞在 `await asyncio.to_thread(...)`，取消只让等待方返回，线程里的子进程仍在执行，驱动随后进入 `_cleanup_resources`。释放钩子的"置 `closing`、清场杀进程、等内层锁"就是为这种情况设计的；钩子的调用要用 `asyncio.shield` 包住，见上。
3. **释放之后到达的调用，不能重新建登记**：登记条目在 `_init_bisheng_code_tool` 构造执行器时创建，句柄存在执行器上；`release_local_run(W)` 把它标为已关闭，之后到达的调用直接返回"任务已结束"，不会为已删除的 W 新建 R 和 uid。
4. **启动清扫放在每个 worker 进程里**：`ScheduleCenterProcess.run` 里、进入主循环之前，每个进程各跑一次。判断依据是 uid 池标记里的 pid 加启动时间是否对应存活进程，不能一律清掉，否则会误删同一台机器上其他 worker 进程正在用的 R（`--worker_num` 默认 4 个进程同时启动）。现有的 `check_and_terminate_incomplete_tasks` 只处理数据库里的会话状态，不管磁盘，这里要新加。

**钩子覆盖不了、只能靠启动清扫的场景**：进程崩溃（`kill -9`、OOM、容器重启）时 `finally` 不会执行，W 和 R 都留下。清扫只清 R；W 目录本身没人清，这是现状，与本方案无关。

**已知但不处理的**：Redis 故障时 `_acquire_session_run_lock` 会放行，理论上同一个会话可能被两个驱动同时跑。同一进程内它们会共用一个登记条目，一个结束会连带释放另一个的 R。现有代码里 `rmtree(W)` 本来也会把另一个驱动的工作区删掉，这是已有的风险，本方案不新增也不解决，只在日志里留痕。

#### 同一个 W 的调用串行

**为什么要串**：同一个 uid 下的两个进程共用一个 R，其中一次调用结束时的清场（`kill(-1)`）会把另一次调用的进程也杀掉；两次调用对 R 的复制进来、收回也会互相踩。串行是清场安全的前提之一，详见"uid 池"里的"清场的范围与前提"。

**确实会并行**：灵思用 `create_deep_agent`，工具节点 `ToolNode._afunc` 对同一条模型回复里的全部工具调用做 `asyncio.gather`。`bisheng_code_interpreter` 不在子代理的禁用名单里，主图和研究员子代理用的是同一个工具实例，没有任何锁。所以同一条消息里的两次代码调用，或者主图与子代理的代码调用，现在会同时在 W 里运行。`--max_concurrency` 限制的是不同任务，管不到任务内部。

**不能当作"一个任务一个工具对象"来设计锁**：当前每次驱动只构造一个 `CodeInterpreterTool`（`_init_bisheng_code_tool` 构造后把工具 id 从选择列表里删掉，不会再造副本；子代理拿的是同一份列表）。但 `create_deep_agent` 会对描述被覆盖的工具做 `model_copy`，是浅拷贝，工具对象变两个而 `executor` 还是同一个。所以锁不放在工具对象上，放在按 `realpath(W)` 索引的登记条目上。

**范围**：只在 `local_isolation=uid` 的保留模式下生效。`off`、容器模式、E2B 以及代码节点的行为不变，锁不加在 `CodeInterpreterTool` 的所有路径上。

**怎么串**：`LocalExecutor` 新增 `arun`，工具的 `_arun` 只调它；`off` 下 `arun` 直接转到原来的同步 `run`。保留模式下：

```text
async with entry.queue:                       # 外层 asyncio.Lock：FIFO 排队，不占线程
    await asyncio.to_thread(run_locked)       # run_locked 里先拿内层锁再执行
# run_locked:
#   循环 inner.acquire(timeout=1)，每次失败检查 entry.closing，为真就返回"任务已结束"
#   拿到后执行：复制进来、跑子进程、清场、收回
```

- **外层 `asyncio.Lock`**：`gather` 按模型发出的顺序启动各个调用，FIFO 保持"先发出的先执行"，同一批里先写文件、后读文件的依赖大多能成立（`threading.Lock` 不保证这个顺序）。排队的调用在这里等，不占线程池线程。
- **内层 `threading.Lock`**：真正的互斥。任务被取消、`await to_thread(...)` 被打断时，外层 `async with` 会立刻释放，但线程里的子进程可能还在跑；内层锁在线程退出前一直持有，下一个调用不会进到同一个 R 里。
- **加锁顺序固定**：先外层再内层。`release_local_run` 只碰内层和 `closing`，所以不会死锁。
- **等锁时间不计入脚本的超时**，超时只从拿到内层锁后开始计。
- **等待可以被打断**：内层 `acquire` 用带超时的循环，每秒检查一次 `closing`。任务被终止时，排队的调用很快返回，不用等持锁的那次自然结束。

**为什么排队不占线程**：worker 进程只有一个事件循环，所有任务共用一个默认线程池（`min(32, CPU 核数 + 4)`），一次代码调用要占一个线程，可能占很久。排队的调用若都在线程里等 `threading.Lock`，会加剧线程池耗尽，所以排队放在 `asyncio.Lock` 上。

**代价**：同一条消息里的多个代码调用，总耗时变成各次相加；批量并行调用一般不多。

**不采用的备选**：
- 忙时退回临时模式（另开 uid、全量复制，各自跑完收回）：保留并行，但多占 uid、多一次全量复制，两次调用同时写 W 的竞态也没有解决。
- 只用 `threading.Lock`：等待者各占一个线程，也不保证调用顺序。

**崩溃**：进程被 `kill -9` 时，登记表丢了，W 和 R 都留在原地。R 靠"uid 池"里的遗留回收和上面的启动清扫清掉；同一个任务再次启动时没有登记，按第一次调用处理，全量复制。

**不跨进程**：登记表在进程内，同一个 W 不会被两个进程同时使用，灵思一个任务只在一个 worker 进程里执行。

**事件循环**（已对照 `linsight/worker.py` 核实）：每个 worker 进程只有一个事件循环，进程内所有灵思任务共用它，每个任务是这个循环上的一个 `asyncio.create_task`；`--worker_num` 个进程用 `spawn` 启动，互相独立；`asyncio.Semaphore(max_concurrency)` 按进程限制并发。因此 `asyncio.Lock` 不会遇到跨循环的问题，登记条目随 `release_local_run` 一起销毁，不会带到别的任务。任务停靠（等待用户输入）时走 `_cleanup_resources`，W 和 R 都已释放；续跑可能落在别的进程或节点上，那里没有登记，按第一次调用处理。

### 复制进来

- 只复制普通文件。跳过符号链接、套接字、FIFO、设备，以及隐藏名和 `__pycache__`（与 `_walk_regular_files` 同口径）。
- 单个文件超过 `local_copy_in_file_bytes` 就跳过，并和容器模式一样在日志末尾加一条 `[SYSTEM NOTICE]`，说明哪些文件没带进去。总量超过 `local_copy_in_total_bytes` 同样停止并提示。
- **不复用容器模式的 `max_copy_in_bytes`（默认 50MB）。** 上传的原始文件进工作区时上限本来就是 50MB（`workbench_impl.py` 的 `_RAW_KEEP_MAX_BYTES`），所以它们不会被挡住；会被挡住的是模型自己写进 `scratch/`、`output/` 的大中间文件。本机模式现在直接在工作区里读，没有这道上限，沿用 50MB 会让第二次调用读不到上一次写出的大文件。
- 用 `shutil.copy2` 保留 mtime，目标文件 `lchown` 给该 uid，权限设为 `0644`（原来有可执行位的保留 `0755`）。不用硬链接：硬链接的文件仍归 root，脚本想在原位修改上一步的产物会被拒绝。
- **临时模式**（代码节点）：每次全量复制。工作区一般很小，不做增量。
- **保留模式**（灵思）：只复制"需要复制"的文件，对每个 W 里的文件做一次 `lstat`，满足下面任一条才复制：
  - 不在同步索引里（新增）。
  - W 里的 `(size, mtime_ns)` 与索引不同（变了；以 W 为准，覆盖 R 里的同名文件）。
  - 在索引里，但 R 里已经没有了（被脚本删了；按 W 补回）。

  另外，索引里有而 W 里已经没有的文件，把 R 里的副本删掉并从索引去掉，让 R 与 W 保持一致。与容器模式相比：只用 `lstat`，不读文件内容算 md5。
- 每次复制记一条 debug 日志（文件数、字节数、耗时、是否增量），方便线上确认效果。
- `local_copy_in_total_bytes` 管的是**本次调用复制进来的字节数**；R 的总量由磁盘监视（`local_disk_limit_bytes`）兜底。保留模式下 R 与 W 各占一份磁盘。

### 收回来

只在清场确认成功之后才做（流程第 7 步）。即便如此，仍按"R 里全是不可信内容"处理：

- 逐级用 `O_NOFOLLOW` 打开（目录加 `O_DIRECTORY`，文件加 `O_NONBLOCK`），对**打开得到的这个 fd** 做 `fstat` 判断：必须是普通文件，`st_nlink == 1`，大小不超过上限。之后的读取也用这同一个 fd，不按路径重新打开。符号链接、FIFO、设备、硬链接文件一律不收。
- 只收"不在同步索引里，或 `(size, mtime_ns)` 变了"的文件（临时模式的索引就是本次复制进来的清单）；跳过隐藏名、`__pycache__` 和脚本文件。
- 写入 W 时先写同目录下的临时名，再 `os.replace`；目标文件归 root、`0644`。W 只有 root 能写，路径上若发现符号链接就放弃这个文件。
- 写完后用 `os.utime` 把 W 里这个文件的 mtime 设成和 R 里一致，并把 `(size, mtime_ns)` 写进同步索引。这样下一次调用的差分不会把它当成"W 里新变的文件"又复制一遍。（保留模式用；临时模式不需要，但做了也无妨。）
- 单文件上限用 `local_rlimit_fsize_bytes`，总量上限用 `local_disk_limit_bytes`。
- 不同步删除：脚本在 R 里删掉的文件，W 里还在。这与容器模式一致，也符合 `sync_to_workspace` 对删除的现有约定；保留模式下，下一次调用还会按 W 把它补回 R。本机模式以前脚本可以直接删 W 里的文件，这是一处行为变化。
- 无论退出码是不是 0 都收，保持本机模式现有语义（失败前写出的文件仍留在工作区）。因磁盘超限被杀的运行除外，不收。

### 绝对路径兼容

模型会在日志里看到宿主路径（`os.getcwd()`、traceback），也可能把 W 的绝对路径写进脚本。R 与 W 不同，所以：

- 脚本入库前，把代码文本里出现的 W 字面量原样替换为 R。只替换这一个精确前缀，并且要卡边界：只替换"后面是字符串结尾，或者紧跟 `/`"的那一处，`W` 是更长路径前缀的情况不动（例如 `/…/linsight/ab12cd34` 不能误伤 `/…/linsight/ab12cd34ef`）。
- 日志返回前把 R 替换回 W（第 9 步），同样卡边界。
- `workspace_escape_guard` 保留，对 W 前缀的豁免不变，仍按 W 判断。

## 子进程怎么启动

```python
subprocess.Popen(
    ["prlimit", "--as=…", "--cpu=…", "--nproc=…", "--fsize=…", "--nofile=…", "--core=0", "--",
     sys.executable, "-s", "-B", "-X", "utf8", script_name],
    cwd=R, env=env, user=uid, group=uid, extra_groups=[],
    stdin=subprocess.DEVNULL, stdout=PIPE, stderr=PIPE,
    start_new_session=True, close_fds=True,
)
```

- `user=` / `group=` / `extra_groups=` 是 `subprocess` 自带参数（3.9 起），换 uid 发生在 fork 与 exec 之间的 C 代码里，在 `-P threads` 的 worker 里是安全的。不用 `preexec_fn`，不引入 `chroot` 命令。
- `extra_groups=[]` 必须给，否则 root 的附加组会被带进子进程。
- 资源上限用 `prlimit` 命令套一层：它先以子 uid 身份给自己设上限，再 `exec` 解释器，没有引导脚本，traceback 里也没有多余的栈帧。`RLIMIT_NPROC` 按真实 uid 计数，所以必须在换 uid 之后生效，这也是不能把进程数上限加在 worker 本身的原因。
- `prlimit` 来自 util-linux。**已在 107 部署上核实**：`bisheng-backend`、`bisheng-backend-worker`（镜像 `bisheng-backend:feat_v3.0.0-beta1_068-container-sandbox`，Debian 13）里都有 `/usr/bin/prlimit`（util-linux 2.41），沙箱 runner 里也有。util-linux 是 Debian 的基础必装包，换成别的 Debian 系基础镜像也会有；但其他发行版的基础镜像或精简镜像仍要靠预检兜底。
- 保留现有的 `lang` 处理：`python*` 用 `sys.executable`，`sh` / `bash` 仍可运行，同样以该 uid 和同样的上限运行。第一步不收紧语言。

### 环境变量

只给白名单，其余全部不带：

| 变量 | 值 |
|---|---|
| `PATH` | 取父进程的值（LibreOffice 等仍可用） |
| `LANG` / `LC_ALL` | `C.UTF-8` |
| `TZ` | 父进程有则带上 |
| `HOME` | R（沿用现有设计：`~` 落在工作区内） |
| `TMPDIR` / `TEMP` / `TMP` | `R/.tmp` |
| `MPLCONFIGDIR` | `R/.mpl` |
| `USER` / `LOGNAME` | `sandbox`（`getpass.getuser()` 先读这两个变量，随机 uid 没有 passwd 条目也不会报错） |

不继承 `BS_*`、`PYTHONPATH`、`LD_*`、代理、各类密钥变量。

### 字体缓存

- 在隔离模式下不再删 `fontlist*`。`insert_set_font_code` 里那段删除只保留在 `local_isolation=off` 的路径上，这样 `off` 与现状完全一致；做法是把"删缓存"和"插入字体设置代码"拆成两步，隔离模式只做后者。
- 父进程第一次用到时（加锁，进程内一次）`import matplotlib.font_manager`，让 root 自己的缓存目录（`matplotlib.get_cachedir()`，在 `/root/.cache` 下）生成缓存；检查缓存里有 `WenQuanYi Zen Hei`，没有就强制重建一次。
- 每次运行把 `fontlist-*.json` 复制进 `R/.mpl`，归该 uid。这个文件很小，复制代价可以忽略。
- 普通 uid 读不到 `/root/.cache`，不预填充的话每次都会重建缓存，这就是要复制的原因。

### 输出读取

用 `selectors` 同时读 stdout 和 stderr，不用 `communicate()`。每个流只保留开头 512 KiB 和结尾 512 KiB，中间丢弃并插入一行提示；失败日志取 stderr 末尾（traceback 在末尾）。两个流合计超过 256 MiB 立即杀掉并报错。

## uid 池

- 区间 `30000`–`39999`，常量写在代码里，不进配置。该区间不能与容器里已有的 uid 冲突：清场的 `kill(-1)` 会杀掉这个 uid 的全部进程，若别的服务恰好用了这段 uid 会被误杀。后端容器里的服务目前都是 root，没有冲突；预检时扫一遍 `/proc/*/status`，发现区间内已有不属于池标记的进程就拒绝启用隔离并写明 uid（见"开关与失败策略"）。
- 标记目录 `/var/run/bisheng-local-uids`（root，`0700`）。标记内容是占用进程的 pid 和启动时间（`/proc/<pid>/stat` 第 22 列）。
- 发布标记：先写本线程私有的临时文件，再用 `os.link` 链成 `<uid>`。链接是原子的，目标已存在就失败，所以多线程、多进程之间只有一个能拿到，也没有别人读到半写标记的窗口。
- 发现标记时，对应进程还在就换下一个；不在了，或启动时间对不上（pid 被复用），当作残留：先清场、确认无进程，再删标记重取。
- 清场：以该 uid 起一个小进程执行 `os.kill(-1, 9)`（`Popen(user=uid, group=uid, extra_groups=[])`）。内核不会把信号发给调用者自己。随后扫 `/proc/*/status` 的 `Uid:` 行确认没有存活进程，僵尸（`State: Z`）不算。确认失败就保留标记、不再分配这个 uid，并记 error 日志；此时不收回文件、不删 R（流程第 8 步）。
- **清场的范围与前提**：`kill(-1)` 以该 uid 的身份发信号，只影响本容器、同一个 uid 的进程，不会碰别的 uid、别的任务。它安全的前提是**同一时刻只有一次调用在用这个 uid**，由两点保证：
  - uid 不跨 W 共用：每个 uid 在池里只有一个原子标记，只会被一个登记条目持有；保留模式一个 W 一个 uid，临时模式每次调用各取一个。
  - 同一个 W 内串行：见"同一个 W 的调用串行"。串行一旦被绕过，一次调用的清场会把另一次调用的进程一起杀掉，同一个 R 里还可能把另一次写到一半的文件当成完整文件收回。
- **清场会清掉后台进程**：每次调用结束都清场，脚本里用 `&`、`nohup` 拉起的后台进程不会留到下一次调用，不能靠它"启动一个服务、下一次调用再连"。现在的本机模式没有这个限制，这是一处行为变化。常见脚本用 `subprocess.run` 调 soffice、pandoc 等会等子进程结束，不受影响。
- 不用 `killpg` 代替：脚本里的子进程可以 `setsid` 或双 fork 脱离进程组，杀不干净；按 uid 清场并扫 `/proc` 确认，才能保证不留残余。
- **遗留运行目录的回收**：worker 被 `kill -9` 时，标记还在，R 也留在 `local_run_root` 下，属主就是那个 uid，下一个领到它的调用可以读到。所以：
  - 回收残留标记、或领走一个 uid 时，先删掉 `local_run_root` 下所有属主是它的目录（用 `lstat` 判断属主，`rmtree` 不跟随符号链接）。
  - 进程启动时扫一遍 `local_run_root`：没有对应存活进程标记的目录和标记一起清掉。
  - 因清场未确认而被隔离的 uid，只有在确认它名下已无进程之后，才删它的 R、释放标记。
- 保留模式下，uid 由登记表持有，直到该 W 被释放才还给池子；标记里的 pid 就是持有它的 worker 进程，进程没了，标记就按上面的规则被当作残留回收。
- 实现参照 `docs/workflow/code.py` 里的 `_acquire_uid` / `_reap_uid` / `_uid_has_live_process`，抽成独立模块 `local_uid_pool.py`。chroot 方案若以后重开，可以复用它。
- 同一台宿主机上多个后端容器会共用这段 uid，`RLIMIT_NPROC` 按 uid 在内核里合计，别的容器里同 uid 的进程会占额度。清场的 `kill(-1)` 只在本容器的 PID 命名空间内生效。

## 磁盘

运行期间每 5 秒统计一次 R 的总大小和文件数，超过 `local_disk_limit_bytes` 就杀进程并返回明确错误。`RLIMIT_FSIZE` 只限单文件，挡不住写很多文件。保留模式下 R 在任务期间一直在，统计的是整个 R，包含复制进来的部分；因超限被杀后，该 W 的登记作废、R 删掉，下次调用重新全量复制。

本方案**不限制同时运行的次数**。灵思 worker 已有 `--max_concurrency 5`，商业版网关限制了 HTTP 请求并发，这里再加一层会让原本能跑的请求被拒绝，数值也没有依据。uid 池有 10000 个，不会成为瓶颈。代价是工作流代码节点所在的 Celery worker 最多 100 个线程，最坏情况下并发占用的内存是 100 乘以 `local_rlimit_as_bytes`，这要靠部署侧控制 worker 并发。若以后在线上看到过载，再带着实测数据单独加。

## 权限收紧

换 uid 之后，子进程仍能读所有"对其他用户可读"的文件。容器里真正敏感的是三处，本节在不改镜像、不动 `/usr` 的前提下把它们对池里的 uid 关上；LibreOffice、pandoc、shell、ffmpeg 仍在原位，功能不变。

**容器里的布局**（`src/backend/Dockerfile`：`WORKDIR /app`、`COPY ./ ./`；`docker/docker-compose.yml` 的 `backend`、`backend_worker`）：

| 路径 | 来源 | 内容 |
|---|---|---|
| `/app/bisheng/` | 镜像 | 后端源码 |
| `/app/bisheng/config.yaml` | 宿主机只读挂载 `bisheng/config/config.yaml:/app/bisheng/config.yaml:ro` | 数据库、Redis、MinIO 等连接信息（密码为 Fernet 密文，密钥在源码里） |
| `/app/data/` | 宿主机读写挂载 `data/bisheng:/app/data`，`backend` 与 `backend_worker` 共用 | 助手对话历史、统计日志、性能快照等 |
| `/app/.venv/` | 镜像 | 解释器和依赖，**子进程必须能读、能执行，不能动** |

### 处理

1. **`/app/bisheng`：启动时 `chmod 0700`。**
   - 只改这一层目录，不递归。目录没有其他用户的 `x` 位，普通 uid 连路径都穿不过去，下面的源码和 `config.yaml` 挂载点一并被挡住，与 `config.yaml` 自己的权限无关。
   - `/app` 本身保持 `0755`：子进程要穿过它去用 `/app/.venv`。
   - 子进程用不到 `/app/bisheng`：`cwd=R`，脚本目录 R 在 `sys.path` 上，`/app` 不在；技能包和知识库图片由 root 先复制进 W 再进 R。
   - 这是对容器可写层的元数据修改，`docker restart` 后仍在，容器重建后丢失，所以每次启动都做（幂等）。
2. **`config.yaml`：宿主机上设为 `0600`、属主 root，作为第二道防线。**
   - 容器里改不了它：只读挂载，`chmod` 会得到 `EROFS`，而且权限本来就取自宿主机。
   - 有了第 1 条，即使宿主机上是 `0644` 也读不到；`0600` 防的是它从别的路径被访问到（另一个挂载点、宿主机上的其他用户）。部署文档写明这条要求。
3. **`/app/data`：启动时对挂载根目录 `chmod 0700`。**
   - 同样只改顶层目录，不递归。这是绑定挂载，改的是宿主机上 `data/bisheng` 目录本身的权限，部署文档要写明；该目录在宿主机上本来就属主 root。
   - 宿主机上如果有非 root 的运维脚本直接读这个目录下的日志，会受影响，需要改成 root 读或走 `filelib/download_statistic` 接口。
   - 存储不允许 root 改权限时（例如 NFS 开了 `root_squash`），`chmod` 会失败，见下面的启动检查。

**不需要处理的**：
- `/app/entrypoint.sh`：只有启动命令，没有密钥（已核对 `src/backend/entrypoint.sh`）。
- `/proc/<pid>/cmdline`：各进程的命令行是 `uvicorn …`、`celery -A bisheng.worker.main …`、`python bisheng/linsight/worker.py …`，不带密钥（同上核对）；`/proc/<pid>/environ` 是 `0400` 属主 root，子进程本来就读不到，预检会实测。
- `/app/bisheng_langchain` 等其他源码目录：没有配置和密钥，不收紧，避免扩大改动面。

### 启动检查

放在预检里（进程内一次，见"开关与失败策略"），先做上面的 `chmod`，再**以池里的一个 uid 实测**，不只看权限位（ACL、挂载选项、宿主机上的权限都会影响结果，实测才算数）：

| 检查 | 期望 | 不满足时 |
|---|---|---|
| 以 uid 打开 `/app/bisheng/config.yaml` | `PermissionError` | **拒绝启用隔离**，抛 `LocalIsolationUnavailable`，日志写明哪一步可读 |
| 以 uid 列 `/app/bisheng` | `PermissionError` | 同上 |
| 以 uid 列 `/app/data` | `PermissionError` | 只打 WARNING，不拒绝（内容是日志和历史，且有些存储改不了权限）；WARNING 写明"沙箱代码可读 `/app/data`" |
| 以 root `stat` 宿主机挂进来的 `config.yaml` | group / other 没有读位 | 只打 WARNING，提示宿主机上改成 `0600` |
| 以 uid 运行 `/app/.venv/bin/python -c "import numpy"` | 成功 | 拒绝启用隔离：收紧把解释器也挡住了 |

`chmod` 本身失败（`EPERM`、`EROFS`）时不中断，继续做实测，以实测结果决定。`local_isolation=off` 时这一节整个不做，不改任何权限。

## 开关与失败策略

`SandboxConf.local_isolation`：

| 值 | 行为 |
|---|---|
| `uid` | 上述流程。不是 Linux、不是 root、没有 `prlimit`、预检失败，都直接失败，不退回旧的同用户执行 |
| `off`（默认） | 完全保持现状，不做任何隔离。部署时在镜像或 compose 里显式设 `uid`；首次使用时打一条 WARNING |

取值容错：空串或 `off`（不分大小写、去空格）为 `off`，其余任何值都按 `uid` 处理；配置读不出来时也按 `uid`，不会因为写错值悄悄退回不隔离。

`off` 下**没有 R**：子进程仍直接以 `cwd=W` 运行，不复制进来、不收回，不换 uid，不占 uid 池、不写标记，不建登记表，`keep_run_dir` 被忽略，环境变量整份继承，也没有 `prlimit` 上限。灵思在 `_cleanup_resources` 里调用的 `release_local_run(W)` 在 `off` 下、或者该 W 没有登记时，必须是空操作，直接返回，不报错、不碰文件系统。

预检（进程内只做一次，成功后缓存）：

1. 先检查系统条件：Linux；`geteuid() == 0`；`prlimit` 可用；进程持有所需的能力。只判断 `euid == 0` 不够，丢了能力的容器会走到含糊的失败。用 `/proc/self/status` 的 `CapEff` 逐项检查，失败时日志写明缺的是哪一项：

   | 能力 | 用途 |
   |---|---|
   | `CAP_SETUID` / `CAP_SETGID` | `Popen(user=…, group=…, extra_groups=[])` 换 uid、清附加组 |
   | `CAP_CHOWN` | 把 R 和复制进去的文件交给 uid |
   | `CAP_DAC_OVERRIDE` | root 读写属主是该 uid、权限 `0700` 的 R |
   | `CAP_KILL` | 超时后向该 uid 的进程组发信号 |

   Docker 默认能力集包含这些。已在 107 部署上核实：`bisheng-backend` 与 `bisheng-backend-worker` 的 `CapEff` 都是 `0xa80425fb`（Docker 默认集），5 项都在，另有 `CAP_SYS_CHROOT`（chroot 方案需要；该方案暂时不做）。`docker/docker-compose.yml` 里沙箱 runner 显式列了 `SETUID`、`SETGID`、`CHOWN`、`DAC_OVERRIDE`，没有 `CAP_KILL`；本机隔离不在 runner 里跑，不受影响。

2. 扫 `/proc/*/status`：`30000`–`39999` 区间内如果已有进程，且不属于池标记记录的占用者，说明有别的服务在用这段 uid，清场会误杀它们，拒绝启用隔离，日志写明 uid 和进程。
3. 做"权限收紧"里的 `chmod`（`/app/bisheng`、`/app/data` 顶层目录 `0700`）。
4. 再从池里领一个 uid，在一个临时 R 里跑一小段脚本，确认：uid 非 0；读 `/proc/1/environ` 被拒；能导入 numpy、pandas、matplotlib；能在 R 里写文件；以及"权限收紧"里启动检查表的各项。**无论成败，都在 `finally` 里按清场流程收尾：清场、删临时 R、删标记、把 uid 还回池里。**

失败时抛 `LocalIsolationUnavailable`，原因写进服务端日志，给模型的文案只说"本机代码执行环境未就绪"。

`LocalExecutor.run` 捕获该异常返回 `{"exitcode": 1, "log": ..., "file_list": []}`；代码节点走 `execute_code` 直接抛出，节点按现有方式失败。

## 配置字段

加在现有的 `SandboxConf`（`settings.py`），不新增 YAML 顶层键；环境变量覆盖沿用 `BS_SANDBOX_CONF__<FIELD>`。

| 字段 | 默认 | 说明 |
|---|---|---|
| `local_isolation` | `off` | `uid` / `off`；环境变量 `BS_SANDBOX_CONF__LOCAL_ISOLATION` |
| `local_run_root` | `/tmp/bisheng-local-run` | R 的父目录。启动时建好，root，`0711`：uid 能穿过，不能列目录 |
| `local_rlimit_as_bytes` | `2 GiB` | 沿用 `sandbox-runner` 的值，两种模式行为一致。已确认够灵思里处理大表格，不再上调 |
| `local_rlimit_nproc` | `256` | 同上，给 BLAS 线程和 LibreOffice 留余量 |
| `local_rlimit_cpu_s` | `600` | 同上 |
| `local_rlimit_fsize_bytes` | `1 GiB` | 单文件 |
| `local_rlimit_nofile` | `1024` | |
| `local_disk_limit_bytes` | `2 GiB` | R 总量，包含复制进来的内容和这次新写的文件 |
| `local_copy_in_file_bytes` | `1 GiB` | 复制进来的单文件上限。不复用容器模式的 `max_copy_in_bytes` |
| `local_copy_in_total_bytes` | `1 GiB` | 本次调用复制进来的总量上限（保留模式只算增量部分），小于 `local_disk_limit_bytes`，给本次运行的产物留出空间 |

默认值是起点，不是实测值：`local_copy_in_*` 要能容下知识库图片（250 MiB）加上传文件加上一轮的中间产物。

这些字段不能被工具配置里的 JSON 覆盖。实现上不需要改 `factory.py`：隔离流程的所有参数都在执行时直接读 `settings.sandbox_conf`，`LocalExecutor` 构造时收到的 kwargs 不参与，工具配置里写了 `local_*` 也不起作用。`keep_run_dir`、`local_sync_path`、`workspace_prefix` 这类灵思按会话注入的键照常经构造函数传入。

## 代码改动

| 文件 | 改动 | 状态 |
|---|---|---|
| `local_isolation.py`（新） | 流程 1–9（临时模式）、预检（含能力检查）、环境白名单、受限读输出、磁盘监视；每次调用都确认 `local_run_root` 存在且为 root `0711`（改过路径后不必重启） | 已实现 |
| `local_uid_pool.py`（新） | uid 池、领 uid 时回收遗留运行目录；领 uid 与回收残留在标记目录的 `flock` 下进行 | 已实现 |
| `workspace_copy.py`（新） | 复制进来 / 收回来，含 `O_NOFOLLOW` 与对同一 fd 的 `fstat` 检查；保留模式的增量复制 `sync_in` | 已实现 |
| `local_executor.py` | `execute_code` 按 `local_isolation` 分流，`work_dir=None` 在隔离模式下拒绝；`off` 走原有 `_execute_code`，并保留原来的删字体缓存行为；隔离模式下不删；`run` 捕获 `LocalIsolationUnavailable`；`__init__` 读 `keep_run_dir` 并登记；`arun` 按"外层排队、内层互斥"执行，没有登记时直接转到同步 `run` | 已实现 |
| `base_executor.py` | `run_with_dir` 里的 `execute_code` 调用改经 `_execute_in_dir`，`LocalExecutor` 借它把 W 上的调用交给保留模式；快照差分、收割逻辑不动 | 已实现 |
| `container_executor.py` | `supports_retained_run = False`：它整体替换了 `execute_code`，不能被分到本机保留模式 | 已实现 |
| `settings.py` | `SandboxConf` 新字段 | 已实现 |
| `local_isolation.py` 的预检 | "权限收紧"：`chmod 0700 /app/bisheng`、`/app/data`（顶层目录、不递归、失败不中断），再以池里的 uid 实测启动检查表 | 已实现 |
| `local_isolation.py` 的 `run_retained`、`sweep_on_startup` | 保留模式的一次调用；进程启动清扫 | 已实现 |
| `local_run_registry.py`（新） | 保留模式的登记表（`realpath(W)` → uid、R、同步索引、外层 `asyncio.Lock`、内层 `threading.Lock`、`closing`）；`release_local_run(W)` | 已实现 |
| `code_interpreter/tool.py` | `CodeInterpreterTool` 新增 `_arun`，调 `executor.arun`；执行器没有 `arun`（E2B）时退回同步 `_run`；锁不放在工具对象上 | 已实现 |
| `task_exec.py` | `_cleanup_resources` 里，在自己的 `try` 中、排在第一位，按 `self.file_dir` 调用 `release_local_run(file_dir)`（`asyncio.shield` 加线程池），早于 `_stop_termination_monitor()` 和 `rmtree` | 已实现 |
| `worker.py` | `ScheduleCenterProcess.run` 进入主循环之前，每个进程跑一次启动清扫：按标记里 pid 加启动时间判断存活，清掉没有存活属主的 R 和标记 | 已实现 |
| `workbench_impl.py` | 构造代码解释器配置时，`config.local.keep_run_dir = True`（与 `local_sync_path` 同处） | 已实现 |
| `沙箱配置与使用说明.md` | 记录 `local_isolation` 的开启方式；部署部分写明宿主机 `config.yaml` 设 `0600`、属主 root，`data/bisheng` 目录会被改为 `0700`，依赖它的非 root 运维脚本要调整 | 已更新 |

`factory.py` 不改，原因见"配置字段"。

实现时在本文之外补了几处：

- **保留的 R 在每次调用前先复位**：R 在两次调用之间归该 uid，脚本可能改了它的权限，或把 `.tmp`、`.mpl` 换成指向别处的符号链接。root 往 R 里写任何东西之前，先把 R 设回 `0700`，删掉并重建 `.tmp`、`.mpl`，脚本文件也先删再写。
- **增量复制按 R 的实际状态判断**：除了"新增、W 变了、R 里没了"，R 里的副本被脚本改过、换成符号链接或硬链接时也重新复制；写入前先删掉原来的条目，不会顺着脚本放的链接写出去。W 里已删的文件在 R 里删除时，路径上任何一级不是真目录就跳过。
- **磁盘超限在保留模式下丢弃整个 R**：超限的内容留在 R 里会让之后每次调用都立刻超限，所以清场后释放 uid 和 R，下次调用重新全量复制。
- **释放能打断正在跑的子进程**：读输出的循环每 0.5 秒检查一次 `closing`，覆盖"检查 `closing` 之后、子进程启动之前"正好发生释放的窗口；释放在 30 秒内等不到内层锁时不强行回收，由那次调用结束时自己释放 uid 和 R。
- **领 uid 与清扫互斥**：4 个 worker 进程同时启动清扫时，一个进程判定为残留的 uid 可能刚被另一个进程重新领走、建好 R。领 uid（含回收残留）和清扫都在标记目录下的 `.lock` 上取 `flock`。

`ContainerExecutor` 继承 `LocalExecutor` 但整体覆盖了 `execute_code`，不受影响。`LocalExecutor.execute_code` 目前是类方法，`test_code_interpreter_timeout.py` 直接以类调用，所以保持类方法签名，配置在函数内部从 `settings.sandbox_conf` 取。

默认值是 `off`，现有的本机执行器测试不用加夹具。隔离相关的新测试单独放：`test/sandbox/test_local_isolation.py`、`test/sandbox/test_local_retained_run.py`（增量复制、登记与释放、串行、灵思接线）不需要 root；`test/sandbox/test_local_isolation_root.py` 只在 root 且 Linux 上跑，含保留模式的端到端用例。已在 107 的 backend 镜像里以 root 跑过这两份，并把 `test/linsight/test_code_interpreter_*.py` 里六组现有测试在 `BS_SANDBOX_CONF__LOCAL_ISOLATION=uid` 下重跑，全部通过。

## 与其他路径的关系

- **代码节点**：本分支的代码节点在 `type=local` 时走 `LocalExecutor.execute_code(work_dir=<临时目录>)`（`code_parse.py:260`），同样被这套隔离覆盖，用临时模式。代码节点的结果通道、结果上限和超时另见 [代码节点执行约定加固](./代码节点执行约定加固.md)：其结果上限按本文"输出读取"每个流保留的量取值。
- **知识库图片暂存**：暂存在 `run` 里、`run_with_dir` 之前写进 W，由复制进来带入 R。暂存代码不用改，父进程也不会再往用户可控的目录里写。
- **灵思**：W 就是 `local_sync_path`，用保留模式。任务结束时 `_cleanup_resources` 会 `rmtree(W)`，同一处先调用 `release_local_run(W)` 释放 R 和 uid。工具实例上的 `close()` 不负责释放。
- **`sync_to_workspace` / `sync_files_to_local`**：看到的是收回后的 W，行为不变。

## 测试

不依赖 root 的：

- 复制进来：跳过符号链接、超大文件、隐藏文件；超总量时有提示。
- 收回来：符号链接、FIFO、硬链接文件、超限文件不被收；`(size, mtime_ns)` 未变的文件不被收；路径穿越名被拒。
- 路径改写：W 字面量被换成 R，日志里 R 被换回 W；以 W 为前缀的更长路径不被误换。
- `work_dir=None` 在隔离模式下直接失败，不碰 `extensions/`。
- `off` 模式下仍会删除字体缓存，隔离模式下不删。
- `off` 模式下不产生 R、不占 uid、不写标记；`release_local_run(W)` 在 `off` 或没有登记时是空操作。
- 预检失败（缺能力、`prlimit` 缺失）时日志写明缺哪一项；预检用过的 uid 已还回池里。
- 保留模式的增量复制：第二次调用不重复复制没变的文件；W 里新增、改动的文件会被复制；R 里被删的文件会按 W 补回；W 里被删的文件在 R 里也被删；收回的文件下一次不会再被当成"W 里新变"重复复制。
- 保留模式的释放：`release_local_run(W)` 之后 R、标记、登记都没了，uid 回到池里；释放时有调用在跑，那次调用不做收回、返回"任务已结束"。
- 钩子的放置：`_stop_termination_monitor()` 抛异常时，`release_local_run` 仍然已经执行；`file_dir` 对应目录不存在时 R 仍被释放；`file_dir` 为 `None` 时钩子直接返回，不影响别的登记。
- 释放之后到达的调用：看到条目已关闭，直接返回"任务已结束"，不新建 R、不占 uid；同一个 W 的下一轮能建新句柄。
- 终止时线程仍在跑：取消 `agent_task` 之后进入清理，子进程被清场杀掉，R 被释放，不会留下持锁的线程。
- 启动清扫：标记对应的进程已不存在的 R 和标记被清掉；对应进程仍存活的（同一台机器上其他 worker 进程）不被清掉。
- 保留模式下同一个 W 的两次并发调用串行，且按发起顺序执行；等锁的时间不计入超时。
- 保留模式下，持锁的调用所在的 `await to_thread(...)` 被取消后，下一个排队的调用不会进入同一个 R，要等线程里的上一次退出。
- 释放时有调用在排队：排队的调用拿到锁后看到 `closing`，直接返回"任务已结束"，不执行脚本。
- `off`、容器模式下 `arun` 不加锁，行为与改动前一致。
- 环境白名单只含上表的变量。
- 受限读输出：超大输出只保留头尾；超硬上限被杀。
- uid 池：两个线程抢同一个 uid 只有一个成功；记录的进程已不在的标记被回收；还在的不被回收。
- `off` 模式与现有测试行为一致。

只在 `os.geteuid() == 0` 且 Linux 上跑的：

- 子进程 uid 在 30000–39999，附加组为空，环境只有白名单变量。
- 读 `/proc/1/environ`、`/root`、`/app/bisheng/config.yaml` 被拒；**宿主机上 `config.yaml` 是 `0644` 时也被拒**（靠 `/app/bisheng` 的 `0700`）。
- 列 `/app/bisheng`、`/app/data` 被拒；`/app/.venv/bin/python` 仍能启动并导入 numpy。
- 启动检查：人为把 `/app/bisheng` 改回 `0755` 后预检拒绝启用隔离，日志写明可读的路径；`/app/data` 改权限失败时只出 WARNING，隔离照常启用。
- `local_isolation=off` 时不改任何目录权限。
- 在 R 里建指向 `/etc/passwd` 的符号链接、硬链接、FIFO，收回后 W 里没有它们。
- 超时被杀，之后该 uid 在 `/proc` 里没有进程，标记已删除。
- 模拟 worker 被杀：遗留 R 和标记，下一个领到同一 uid 的调用开始前，R 已被清掉，读不到上一份内容。
- 模拟清场未确认：不收回任何文件，R 保留，这个 uid 不再被分配；保留模式下该 W 的登记作废，下次调用全量复制。
- 保留模式下，同一任务内第二次调用的子进程仍然是新进程，上一次留下的后台进程已被清掉。
- 同一个 W 并发发起两次调用，一次很长、一次很短：短的先返回，长的仍然正常完成，没有被短的清场误杀，结果完整。
- 两个不同的 W 并发，各自拿到不同的 uid；终止或清场其中一个，另一个不受影响。
- 预检：区间内存在不属于池标记的进程时，拒绝启用隔离并写明 uid。
- 画一张含中文的 matplotlib 图，不触发字体缓存重建。

## 剩余风险

这些在第一步之后仍然存在。chroot 监狱暂时不做，不作为下一步；本机模式就停在这里：

- **全局可读的文件仍然可读**：`/app/.venv`、`/app/bisheng_langchain` 等源码、`/etc`、`/usr`。`/app/bisheng`（含 `config.yaml`）和 `/app/data` 已由"权限收紧"关上；其中 `/app/data` 在存储不允许改权限时只打 WARNING，仍可能可读。`config.yaml` 另要求宿主机上设为 `0600`、属主 root。
- **全局可写目录**：`/tmp`、`/var/tmp`、`/dev/shm` 通常是 `1777`，子进程可以在里面落文件，也可以读别的运行留在那里的、权限为 `0644` 的文件。可选加固是启动时以 root 把这三处改成 `0755` 并清掉现有文件上的"其他用户可写"；这会改变容器里这些目录的行为，需要单独评估后再决定，不并进本方案。
- **`/proc/<pid>/cmdline` 等对所有人可读的进程信息**。现有进程的命令行不带密钥（见"权限收紧"），以后如果有人把密钥写进启动参数，就会泄露。
- **网络不隔离**：子进程仍能连容器网络内的 MySQL、Redis、MinIO、OpenFGA 等；环境变量里没有密钥，不等于连不上，也不等于这些服务没有默认凭据。
- **保留模式下同一任务的多次调用共享一个 R**：前一次调用写下的文件、符号链接，后一次调用的脚本都能看到（与容器 session 一致，同一任务、同一用户，不跨任务）。符号链接和硬链接依旧不会被收回 W。每次调用结束仍会清场，不会有进程跨调用留下来。
- 没有 cgroup：内存只靠 `RLIMIT_AS` 近似，磁盘靠监视线程，不是硬隔离。
- 内核漏洞、共享内核。

因此第一步之后，多租户且用户不可信的生产环境仍应使用 `type=container`。

## 不做

- 不改镜像，不引入 `chroot`。第二步（chroot 监狱）暂时不做。
- 不收紧语言，`sh` / `bash` 仍可运行。
- 不做网络隔离。
- 不在非 Linux、非 root 的机器上模拟这套隔离，那种环境用 `off`。
- 不同步删除。
- 代码节点（临时模式）不做增量复制：工作区小，每次全量复制。
- 不做空闲超时回收：保留模式的 R 随工作区删除而释放，崩溃的残留靠启动清扫。
- 不做跨进程共享 R：登记表只在进程内。

## 待确认

1. ~~`local_isolation` 默认值取 `uid` 还是 `off`~~ **已确认：取 `off`**，沿用现状，镜像和 compose 里显式设 `uid`。代价是自行部署、没设这个值的客户默认不隔离，首次执行时有一条 WARNING。
2. ~~基础镜像里是否有 `prlimit`~~ **已核实**：107 部署的后端和 worker 镜像里都有（util-linux 2.41，Debian 13）。仍保留预检：换了基础镜像、缺 `prlimit` 时直接失败并写明原因；备选是在 Dockerfile 里装 util-linux，或改用一小段引导脚本在子进程里 `setrlimit`（代价是 traceback 里多一层 `runpy` 栈帧）。
3. ~~灵思里是否会并行发起代码调用~~ **已核实：会**，见"同一个 W 的调用串行"。保留模式下同一个 W 的调用改为串行，会让同一条消息里的多个代码调用总耗时变成各次相加，这是用速度换正确性。仍需确认：线程池大小是否被调整过（本文按 Python 默认值 `min(32, CPU 核数 + 4)` 论证，没有查 `linsight_conf`）。
4. ~~释放钩子是否覆盖所有路径~~ **已核实**：新任务、续跑、继续对话三条路径都经 `_managed_execution` 或 `_managed_resume`，`finally` 里都调用 `_cleanup_resources`；停靠也走这条路径。详见"释放钩子的覆盖"。需要补进的四处（钩子独立于现有 `try`、终止时线程仍在跑、释放后到达的调用、每个进程的启动清扫）已写入设计。崩溃类场景钩子覆盖不到，靠启动清扫；清扫里仍要记日志，能看出有残留被清掉。
5. ~~`keep_run_dir` 是否能经 `factory.py` 传到 `LocalExecutor`~~ **已核实：能传到构造函数，但会在那里被丢掉**。
   - 现状的 `build_code_executor` 先把 `config[kind]` 合并进 `kwargs`；只有 `kind == "container"` 时才丢键，丢的是写死的 `_CONTAINER_POOL_KEYS`（`endpoints`、`token`、`max_copy_in_bytes` 等），并非 `SandboxConf` 的全部字段。`local` 分支直接 `LocalExecutor(**kwargs)`，不做任何过滤，所以 `config.local.keep_run_dir` 会作为关键字参数传进去。
   - 但 `BaseExecutor.__init__` 只从 `kwargs` 里取 `local_sync_path` 和 `workspace_prefix`，其余键读完即丢。实现时必须在 `LocalExecutor.__init__` 里显式接住：`self.keep_run_dir = bool(kwargs.get("keep_run_dir", False))`，否则标记到不了运行逻辑。
   - 本方案要给 `local` 加的过滤（丢掉 `local_*` 隔离字段、注入 `sandbox_conf`，见"配置字段"）只能针对 `SandboxConf` 里的隔离字段，`keep_run_dir` 不是 `SandboxConf` 字段，不能被列进去。需要一条测试：经 `build_code_executor("local", config={"local": {"keep_run_dir": True, "local_isolation": "off"}})` 构造后，`keep_run_dir` 为真，而 `local_isolation` 仍取自 `settings.sandbox_conf`。
6. ~~`local_rlimit_as_bytes` 默认 2 GiB 是否够灵思里处理大表格~~ **已确认：够**，默认保持 2 GiB，与容器模式一致。本机模式此前没有上限，超过 2 GiB 的单次运行会得到 `MemoryError`，这是预期行为。
7. ~~`/app/data` 收紧失败时只打 WARNING、不拒绝隔离，是否接受~~ **已确认：接受**。理由是内容为日志和历史、且部分存储（如开了 `root_squash` 的 NFS）改不了权限；代价是这类部署里子进程仍能读到它，WARNING 里写明这一点。
