# LocalExecutor 安全优化方案 · 第二步：chroot 监狱

状态：暂时不做。文档保留，不排期、不实现。本机模式停在 [第一步：普通 uid + 私有运行目录](./LocalExecutor安全优化方案-第一步-uid隔离.md)；需要更强隔离时用 `type=container`。下文是搁置前的设计，重开时再按当时的第一步实现核对。本文只写相对第一步的增量，复制进来 / 收回来、uid 池、环境白名单、资源上限、输出读取、磁盘监视都沿用第一步，不再重复。

## 目标

第一步之后，子进程仍然看得到整个容器文件系统里所有"全局可读"的文件，也有完整的 shell 和外部程序。第二步把它关进一棵只读的 `chroot` 树里：

- 看不到 `/app` 下的后端源码和 `config.yaml`，看不到 `/proc`、`/etc` 里的宿主内容。
- 没有 shell，没有 LibreOffice、pandoc 等外部程序，只剩 Python 和白名单里的库。
- 只执行 Python。

第一步剩余风险与第二步的对应关系：

| 第一步剩余风险 | 第二步 |
|---|---|
| 全局可读文件（源码、`config.yaml`、`/app/data`） | 解决：监狱里没有这些路径，不再依赖宿主文件权限 |
| `/proc/<pid>/cmdline` 等进程信息 | 解决：监狱里没有 `/proc` |
| 子进程可以起 shell、调外部程序 | 解决：监狱里没有 |
| 网络不隔离 | 不解决 |
| 内核漏洞、共享内核 | 不解决 |

## 相对第一步改什么

| | 第一步 | 第二步 |
|---|---|---|
| `local_isolation` | `uid` | `jail` |
| 运行目录 R | `local_run_root/<随机>` | `/opt/local-root/work/<随机>`（子进程看到 `/work/<随机>`） |
| 启动方式 | `Popen(user=…)` 直接 exec 解释器 | root 父进程 `prlimit … chroot --userspec … --skip-chdir` |
| 可执行内容 | `sh` / `bash` / Python | 只有 Python |
| 镜像 | 不改 | 构建 `/opt/local-root` |
| 外部程序 | PATH 里的都能用 | 都不能用 |

## 监狱里有什么

根目录固定 `/opt/local-root`，所有调用进入同一棵树，属主 root，目录 `555`、文件 `444` / `555`，没有 `setuid` / `setgid` 文件（构建时检查，发现即失败）。

放进去的（按原绝对路径）：

- 解释器、标准库、`libpython`、动态链接器，以及对整棵站点包里所有 `.so` 做 `ldd` 得到的全部共享库。**不能只扫标准库**，numpy、pandas、PyMuPDF、Pillow 的扩展模块各自依赖系统库。
- `/app/.venv`：只放"允许列表"里的包及其依赖闭包（见下）。路径与宿主相同，`sys.executable` 在监狱内外都是 `/app/.venv/bin/python`。
- 构建时预编译好的 `__pycache__`。
- `/etc/ld.so.cache`（`ldconfig -r` 生成，不设 `LD_LIBRARY_PATH`）、`/etc/passwd` 和 `/etc/group`（只有 root 和 nobody）、`/etc/localtime`、`/usr/share/zoneinfo`。
- `/usr/share/fonts`、`/usr/local/share/fonts`、`/etc/fonts`。`insert_set_font_code` 会设置 `WenQuanYi Zen Hei`，没有字体中文图表会变方块。
- 预生成的 matplotlib 字体缓存：`/usr/share/bisheng/mplcache/`。
- `/dev/null`、`/dev/zero`、`/dev/urandom`（`mknod`，`0666`）。
- `/work`：属主 root，`0711`，运行时在里面建 R，不打进镜像。

明确不放的：

| 不放 | 后果 |
|---|---|
| `/proc`、`/sys` | `os.listdir('/proc')` 失败；`psutil` 一类依赖它的库不可用 |
| `/bin/sh` 和任何 shell | `subprocess(shell=True)`、`os.system` 失败 |
| LibreOffice、pandoc、`pdftoppm` | 调它们的脚本失败，见"兼容性影响" |
| `/tmp` | `tempfile` 用 `TMPDIR`（指向 `R/.tmp`）；硬编码 `/tmp` 的库会失败 |
| `/dev/shm` | `multiprocessing` 的信号量、`ProcessPoolExecutor` 不可用 |
| `/etc/resolv.conf`、`/etc/hosts`、`nsswitch.conf` | 主机名解析失败。这只是副作用，不是网络隔离，直接连 IP 照样通 |

## 镜像构建

### 放在哪一步

在 `src/backend/Dockerfile` 里，放在最后一次 `uv sync` 和 `dmssl` 整理之后：

```text
RUN uv sync --frozen --no-dev …
RUN python -c "import nltk; …"
COPY ./ ./
RUN … dmssl …
RUN sh build-local-root.sh          # 新增
```

脚本模仿 `docs/workflow/build-code-root.sh`（Python heredoc），放在 `src/backend/build-local-root.sh`。

### 为什么复制，不用硬链接

原始设想用硬链接让镜像"只存一份"。对当前 Dockerfile 不成立：`FROM dataelement/bisheng-backend:base.v10`，venv 的大头在 base 镜像的层里，这个 Dockerfile 里的 `uv sync` 只补差异。在后面的 `RUN` 里对 base 层文件做硬链接，overlayfs 会先 copy-up，等于还是多存一份，而且还留下两个隐患：

- 之后任何一次 `uv sync` 替换了某个包，监狱里的硬链接指向旧 inode，监狱和 `/app/.venv` 静默地版本不一致。
- 硬链接共享 inode，对监狱文件做 `chmod` / `chown` 会同时改动真实 venv。

所以直接复制。因为它和 `/app/.venv` 在同一个 Dockerfile 构建里、从同一份最终状态生成，构建当下不会不一致；运行期再加一道校验（见"启动预检"）。

### 站点包用允许列表，不整棵复制

整棵 `/app/.venv` 很大（本机开发环境约 1.5 GiB，镜像内以实际为准），而且里面有 `pymysql`、`redis`、`minio`、`sqlalchemy`、各家 LLM SDK 这类子进程完全不需要、却能直接用来连内网服务的库。构建脚本只复制允许列表及其依赖闭包（用 `importlib.metadata` 的 `Requires-Dist` 递归求闭包，按每个分发包的 `RECORD` 取文件）：

- 默认列表：`pandas`、`numpy`、`matplotlib`、`openpyxl`、`xlsxwriter`、`python-docx`、`python-pptx`、`pillow`、`reportlab`、`pymupdf`，再加 `pyproject.toml` 里已有、数据处理常用的 `scipy`、`sympy`、`xlrd`、`jieba`、`bs4`。
- 列表写在脚本顶部的一个常量里。**这份列表就是对模型的承诺**，要和代码执行器的 `LOCAL_DESCRIPTION` 里的"AVAILABLE LIBRARIES"保持一致；在监狱模式下没复制进去的库会 `ImportError`。
- 列表里任何一个包在镜像里找不到，构建失败。

### 其他构建步骤

1. 复制前先对 `/app/.venv` 跑 `python -m compileall -q`，让监狱带着 `.pyc`。监狱只读且运行时用 `-B`，没有它每次调用都会重新编译 pandas、matplotlib 这类大库。
2. 用 `MPLCONFIGDIR=/opt/local-root/usr/share/bisheng/mplcache` 导入一次 `matplotlib.font_manager`，生成字体缓存，并检查其中含 `WenQuanYi Zen Hei`。
3. 建 `/dev` 节点、`/work`，规范权限，检查没有 `setuid` / `setgid` 文件。
4. 把 `sha256(uv.lock)` 写进 `/opt/local-root/.lock-hash`。
5. 构建期自检，用 uid 65534、与运行时相同的 `chroot` 参数：
   - 导入允许列表里的每个模块；
   - 在一个临时目录里各生成一份 xlsx、docx、pptx、pdf 和一张含中文的 PNG；
   - `/`、`/app/.venv`、解释器目录都不可写；
   - `/proc`、`/bin/sh`、`/etc/shadow`、`/app/bisheng` 都不存在；
   - `os.listdir('/')` 恰好等于预期集合；
   - 从 cwd 出发 `os.listdir('..')` 仍在监狱内（防 `--skip-chdir` 误用）；
   - `getpass.getuser()` 在设置 `USER` 时可用。

   自检失败则镜像构建失败。构建日志打印 `du -sh /opt/local-root`，镜像体积增量以此为准。

### 体积

监狱是"精简站点包 + 系统库"的副本，比整棵 venv 小得多，但仍是额外的一份。具体数字我没有测，**以第一次构建的 `du` 输出为准**。若以后要彻底只存一份，需要改 base 镜像，让 venv 直接建在监狱里，`/app/.venv` 在外面做符号链接。那要动 base 镜像的构建流程，不在本方案内。

## 运行流程的差异

沿用第一步的 1–9 步，只改以下几处：

**运行目录**：R 建在 `/opt/local-root/work/<随机>`，`chown` 给 uid，`0700`。`/work` 本身 `0711`，当前 uid 能穿过它，列不出别人的目录，也打不开别人的 R。

**启动**：父进程仍是 root，不用 `Popen(user=…)`，而是用 `chroot` 命令完成"切根、降权、exec"。线程化 worker 里不能 `os.fork()` 之后继续跑 Python，也不能在 `preexec_fn` 里调 `os.chroot`。

```python
subprocess.Popen(
    ["prlimit", "--as=…", "--cpu=…", "--nproc=…", "--fsize=…", "--nofile=…", "--core=0", "--",
     "chroot", f"--userspec={uid}:{uid}", f"--groups={uid}", "--skip-chdir",
     "/opt/local-root", "/app/.venv/bin/python", "-s", "-B", "-X", "utf8", script_name],
    cwd=f"/opt/local-root/work/{rid}", env=env,
    stdin=subprocess.DEVNULL, stdout=PIPE, stderr=PIPE,
    start_new_session=True, close_fds=True,
)
```

- `prlimit` 在 `chroot` 之前由 root 执行：rlimit 随进程保留，换 uid 之后 `RLIMIT_NPROC` 按新 uid 计数。root 不受 `NPROC` 限制，所以不会打断 worker。
- `--groups=<uid>` 必须显式给出，数字 uid 不在 `/etc/passwd` 里时，不同 coreutils 版本对附加组的处理不一样，不能依赖默认行为。
- `chroot(8)` 默认会把 cwd 改成 `/`。要让脚本在 `/work/<随机>` 里运行，就把父进程的 `cwd` 设成这个目录在监狱内的路径，再加 `--skip-chdir`，此时 cwd 在新根之内。**不能**在 cwd 位于监狱之外时用 `--skip-chdir`：cwd 在新根之外，普通用户沿 `..` 就能走出去。构建自检里的 `listdir('..')` 就是防这个。
- 解释器写绝对路径。`chroot` 之后按子进程环境里的 `PATH` 找命令，而容器 `PATH` 以 `/app/.venv/bin` 开头。
- 清场仍是以该 uid 在监狱外起 `kill(-1)` 的小进程（第一步），不需要进监狱。

**环境变量**：在第一步的白名单上改 `PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin`（监狱里只有这些），其余不变。`HOME` 为 `/work/<随机>`，`TMPDIR` 为 `/work/<随机>/.tmp`，`MPLCONFIGDIR` 为 `/work/<随机>/.mpl`，其中预填充的是监狱里预生成的缓存，不再用 root 自己的缓存目录。

**路径改写**：代码里的 W 字面量改写为 `/work/<随机>`；日志里 `/work/<随机>` 和 `/opt/local-root/work/<随机>` 都替换回 W。

**复制进来 / 收回来**：逻辑不变，只是目标目录换成 `/opt/local-root/work/<随机>`。

## 只执行 Python

在 `lang` 层统一拒绝，不靠"输入以什么开头"：

- `LocalExecutor.run` 里 `infer_lang` 之后，监狱模式下 `lang` 不是 `python*` 一律不执行，返回 `{"exitcode": 1, "log": <说明>, "file_list": []}`。
- `infer_lang` 对以 `pip` / `python ` 开头的输入返回 `sh`，对围栏里写 ` ```bash` 的会走 `_cmd`。这些都落在上面的拒绝里，说明文案是："本机代码执行环境只运行 Python 脚本，不支持 shell 命令和 pip；直接写 Python 脚本本身。"
- 工具描述 `LocalExecutor.description` 在监狱模式下追加一句："没有 shell，也没有 LibreOffice、pandoc 等外部程序；`subprocess` 调用它们会失败。"（`linsight/AGENTS.md` 要求描述必须写明环境提供什么，提示词和工具要同步。）

`infer_lang` 对语法错误返回 `unknown` 并抛 `NotImplementedError` 的旧问题不在本方案内，不动。

## 兼容性影响

必须在发布说明里写明：

| 影响 | 谁会碰到 |
|---|---|
| 内置 skills 的 `bisheng-xlsx/scripts/recalc_check.py`、`bisheng-pptx/scripts/render_deck.py`、`bisheng-docx/scripts/render_docx.py` 依赖 `soffice`（它们用 `shutil.which` 找，找不到会自己报错） | 灵思选了 `type=local` 并用这几个 skill 的用户 |
| `sh` / `bash` / `pip` 不再可用 | 依赖它们的模型输出 |
| 允许列表之外的库不可导入 | 以前碰巧能用的库 |
| `multiprocessing`、`ProcessPoolExecutor`、硬编码 `/tmp` 的库 | 少数脚本 |
| 部署必须是 root + 默认能力集 | 见"部署要求" |

对需要 LibreOffice 的 skills，两条路：让 `type=local` 的灵思在这几个 skill 上给出明确提示并引导改用 `type=container`；或者把 LibreOffice 放进监狱。后者会让监狱增加几百 MB 并扩大攻击面，不建议。

## 开关与失败策略

`local_isolation` 增加取值 `jail`，同一个版本里把默认值从 `uid` 改为 `jail`。没带监狱的镜像（旧镜像、开发镜像）需要显式设为 `uid`。

以下情况在 `jail` 模式下直接失败，不退回 `uid`，更不退回旧的同用户执行：

- 父进程不是 root，或不是 Linux
- `/opt/local-root` 不存在，或其中没有 `/app/.venv/bin/python`
- 系统没有 `chroot` 或 `prlimit` 命令，或 `chroot` 不支持 `--skip-chdir`
- `/opt/local-root/.lock-hash` 与 `/app/uv.lock` 的哈希不一致（有人在派生镜像里又跑了 `uv sync`，监狱已过期）
- 预检失败

预检沿用第一步的做法，改为在监狱里跑：uid 非 0、`/proc` 不存在、`/app/bisheng` 不存在、能导入允许列表里的模块、能在 R 里写文件。失败抛 `LocalIsolationUnavailable`，处理方式同第一步。

## 部署要求

- 后端、各 Celery worker、灵思 worker 的容器以 root 运行（现在的镜像没有 `USER`）。
- 保留 Docker 默认能力集里的 `CAP_SYS_CHROOT`、`CAP_SETUID`、`CAP_SETGID`；不要 `cap_drop: ALL`，不要 `runAsNonRoot`。不需要 `CAP_SYS_ADMIN`。
- 根文件系统不能是只读的：`/opt/local-root/work` 和 `/var/run/bisheng-local-uids` 要可写（只读根的部署用 `emptyDir` 挂这两处）。
- seccomp 保持默认即可。现有 `docker/docker-compose.yml` 的后端用 `seccomp:unconfined`，也能工作。
- 这些要求写进 `沙箱配置与使用说明.md`。

## 代码改动

| 文件 | 改动 |
|---|---|
| `src/backend/build-local-root.sh`（新） | 构建监狱：允许列表、`ldd` 闭包、预编译、字体缓存、`/dev`、权限、哈希、自检 |
| `src/backend/Dockerfile` | 最后加一行 `RUN sh build-local-root.sh` |
| `local_isolation.py` | 增加 `jail` 分支：R 的位置、`chroot` 启动参数、监狱专用环境、预检、哈希校验 |
| `local_executor.py` | 监狱模式下拒绝非 Python；描述追加一句；预生成字体缓存的来源换成监狱里的 |
| `settings.py` | `local_isolation` 加 `jail` 取值，默认改为 `jail`；新增 `local_jail_root`（默认 `/opt/local-root`） |
| `沙箱配置与使用说明.md`、`src/backend/AGENTS.md` | 部署要求、发布说明、开发机和 CI 设成 `off` |

## 测试

构建期自检见上。运行期，在 root、Linux 且存在 `/opt/local-root` 时才跑：

- 一次成功执行：生成 xlsx、docx、pptx、pdf、含中文的 PNG，都能收回 W，字体缓存没有被重建。
- 在脚本里读 `/app/bisheng/config.yaml`、`/proc/self/environ`、`/etc/shadow`：都是 `FileNotFoundError`，不是 `PermissionError`。
- `os.listdir('/')` 只有监狱里的内容；`os.listdir('/work')` 被拒；打不开别的 R。
- `subprocess.run(['soffice'])`、`os.system('ls')` 失败；`import pymysql`、`import redis` 报 `ImportError`。
- 提交 ` ```bash` 和以 `pip install` 开头的输入，得到"只运行 Python"的说明，没有进程被启动。
- 子进程 uid 在 30000–39999，附加组只有 `<uid>`，环境只有白名单变量。
- 在 R 里建符号链接、硬链接、FIFO，收回后 W 里没有。
- 超时之后按 uid 清场，`/proc` 里无残留，标记已删除。
- 哈希不一致、监狱缺失、非 root 时都失败，且没有任何子进程被启动。

不依赖 root 的：启动参数拼装（`--groups`、`--skip-chdir`、`prlimit` 的位置）、`lang` 层拒绝、路径改写，用假的 `Popen` 断言。

## 剩余风险

- **网络仍不隔离**：`chroot` 管不到套接字。子进程仍可能直连容器网络里的 MySQL、Redis、MinIO、OpenFGA 和内网地址。允许列表里没有这些库的客户端，只是提高了门槛，用标准库 `socket` 照样能连。要堵住需要独立的网络命名空间或按 uid 的防火墙，超出本方案。
- `chroot` 不是对抗 root 的边界。它的前提是子进程是普通 uid 且没有 `CAP_SYS_CHROOT`，所以监狱里不能出现任何 `setuid` 文件，构建期已检查。
- 共享内核：内核漏洞可以绕过一切。
- 没有 cgroup，内存靠 `RLIMIT_AS`，磁盘靠监视线程。
- 同一宿主机上多个容器共用 uid 区间，`NPROC` 按 uid 在内核里合计。
- 因此多租户、用户不可信的生产环境，主选仍是 `type=container`；`type=local` + 监狱是"没有容器沙箱时的下限"。

## 不做

- 不给每个 uid 复制一棵 `chroot`。
- 不把 LibreOffice、pandoc 放进监狱。
- 不做网络隔离。
- 不在非 Linux、非 root 的机器上模拟监狱，那种环境用 `off`。
- 不动 `type=container` 的 sandbox 镜像，也不动 `/opt/code-root`（2.6 热补丁线上的代码节点方案）。
- 不修 `infer_lang` 对语法错误返回 `unknown` 的旧问题。

## 待确认

1. 允许列表的内容。它决定模型在监狱里能 `import` 什么，也决定镜像体积。默认列表是否要加或减。
2. 依赖 `soffice` 的三个 skill，在 `type=local` 下是给提示并引导用 container，还是接受不可用。
3. 默认值从 `uid` 切到 `jail` 是否和监狱镜像同一个版本发布；使用旧镜像、自建镜像的客户升级时要显式设 `uid`，需要提前通知。
4. 是否保留 `off`。保留的话 macOS 开发机和 CI 可以继续用 local；不保留则这些环境只能用 container。
