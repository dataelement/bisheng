# 安装并登录 bisheng 命令行（给 AI 助手看的执行指引）

你正在帮用户安装并登录**毕昇（BiSheng）平台的 `bisheng` 命令行**，好让用户之后把本地做的应用一键部署到平台。
请**按下面的步骤在用户机器上实际执行命令**，遇到报错就自行处置或降级到备选方案；全部完成后向用户简要汇报结果。
用户是非技术人员，请你把命令跑完，不要把这些步骤原样丢回给用户让他自己敲。

> **先判断操作系统，再选对应命令。** 下面每一步都分「Windows（PowerShell）」和「macOS / Linux（bash·zsh）」两套，
> **只执行与当前系统匹配的那套**。用错另一套的命令是这里最常见的失败源——Windows 上没有 `python3` / `~/.local/bin` /
> `ln` / `bash`，macOS/Linux 上没有 `py` / `where.exe`。

## 你需要的两样输入

1. **平台地址**：就用**你获取本指引所用的那个地址的主机部分**（协议 + 域名/IP + 端口），例如 `http://bisheng.example.com` 或 `http://192.168.1.10:7860`。用户的提示词里通常也带了同一个地址，两者应当一致。下文统一记作 `<平台地址>`。
2. **服务账号密钥**：形如 `bs-sak-…`，在用户的提示词里。下文记作 `<密钥>`。
   - **安全**：不要把 `<密钥>` 回显到聊天、写进任何文件、或留在会话记录里。

---

## 第 1 步：下载安装件（一个 Python wheel 文件，从平台下载，不依赖公网）

**Windows（PowerShell）** —— 注意必须用 `curl.exe`（PowerShell 里裸 `curl` 是 `Invoke-WebRequest` 的别名，行为不同）：
```powershell
curl.exe -OJ <平台地址>/api/v1/dev-toolkit/cli/download
```

**macOS / Linux**：
```bash
curl -OJ <平台地址>/api/v1/dev-toolkit/cli/download
```

- `-OJ` 很关键：让 curl 采用平台返回的正确文件名（`bisheng_cli-<版本>-py3-none-any.whl`）。**不要**用 `-o bisheng.whl` 这类自定义名——`pip` 只认那种五段式文件名，否则报 “Invalid wheel filename”。
- 若返回 404 或 JSON 报错：平台未发布安装件（未启用开放能力层，或版本过旧）。**停下来让用户联系平台管理员**，不要继续。

## 第 2 步：安装（关键：装到系统 PATH，新终端也能直接调用 `bisheng`）

**这一步最容易出隐蔽错误。** 用户装完后会**重启 AI 助手 / 新开一个终端**再来部署，那是一个不继承你当前会话临时环境的**全新 shell**。所以：

> ⚠️ **绝不要把命令行装进项目局部的虚拟环境**（你当前激活的 venv、项目里的 `.venv` / `venv`）。那样只有你这个会话能跑 `bisheng`，用户新开终端会 `bisheng: command not found` / “无法将 bisheng 识别为…名称”、报“没有配置 bisheng CLI”。**必须装到用户级 PATH 上。** 首选 `pipx`（专治这个）。

### Windows（PowerShell）

```powershell
# 1) 装 pipx（若已装可跳过）。Windows 用 py 启动器，不是 python3
py -m pip install --user pipx
# 2) 把 pipx 的可执行目录写进「用户 PATH」——这是新终端能找到 bisheng 的关键
py -m pipx ensurepath
# 3) 用 pipx 装命令行（.\ 指向第 1 步下载到当前目录的 wheel）
py -m pipx install .\bisheng_cli-*.whl --force
```
- 没有 `py` 就把上面的 `py` 换成 `python`。
- `--force` 保证同版本也覆盖重装（版本号可能不变但内容有修复）。
- `ensurepath` 改的是持久 PATH，**当前这个 PowerShell 不会立刻生效**，要**新开一个 PowerShell**才认——第 4 步就是去新终端验证。

### macOS / Linux

```bash
python3 -m pip install --user pipx  || python3 -m pip install --user --break-system-packages pipx
python3 -m pipx ensurepath
pipx install ./bisheng_cli-*.whl --force
```

## 第 3 步：登录（凭据存用户本机 `~/.bisheng/`，以后不用再输）

**Windows（PowerShell）**：
```powershell
bisheng login <平台地址> --api-key <密钥>
```

**macOS / Linux**（推荐 stdin，密钥不落 shell 历史）：
```bash
printf %s '<密钥>' | bisheng login <平台地址> --api-key-stdin
```

登录成功时，命令行会**自动把《部署纳管》技能同步到本机、并接入检测到的 AI 编程工具**（Claude Code / Codex）。留意输出最后几行会写明**接入了哪些工具**；若显示“未接入任何 AI 编程工具”，见文末排障。

## 第 4 步：核对——**必须在「全新终端」里验证**（这是判定成败的唯一标准）

用户是新开会话/终端来部署的，所以**不能**只在你当前会话里验证。开一个**全新 shell**再验：

**Windows（PowerShell）**：
```powershell
where.exe bisheng           # 能打印出一条 ...\bisheng.exe 路径，才说明进了 PATH
powershell -NoProfile -Command "bisheng --version"   # 在全新子 shell 里能打印版本号
```

**macOS / Linux**：
```bash
bash -lc 'bisheng --version'      # zsh：zsh -lic 'bisheng --version'
```

- 打印出版本号 = 真的装好。
- 若报“找不到 / command not found”，但你当前会话里 `bisheng` 能跑 —— 说明装到了只对当前会话有效的地方（项目 venv / 没进 PATH）。**回到第 2 步用 pipx 重装**；Windows 上确认跑过 `py -m pipx ensurepath` 后**新开一个 PowerShell** 再验（PATH 变更要新进程才生效）。验证通过前不要往下走。

然后向用户**简要汇报**：① 命令行已装好并登录到 `<平台地址>`；② 技能接入了哪些 AI 工具；③ **请用户重启一下当前 AI 助手**，让它读到刚接上的技能——之后新开会话用大白话描述想做的应用即可。

---

## 排障

- **`bisheng` 无法识别 / command not found（当初装的时候明明能跑）**：命令行没进用户 PATH（装进了项目 venv，或 PATH 没生效）。
  - **Windows**：`py -m pipx install .\bisheng_cli-*.whl --force` 重装 → `py -m pipx ensurepath` → **关掉再新开一个 PowerShell** → `where.exe bisheng` 应能打印路径。仍不行可临时用全路径调用：pipx 装的通常在 `"$env:USERPROFILE\.local\bin\bisheng.exe"`。
  - **macOS/Linux**：`pipx install ./bisheng_cli-*.whl --force` → `pipx ensurepath` → 新开终端 → `bash -lc 'bisheng --version'`。
- **PowerShell 里 `curl` 行为怪异 / 下载到的不是 wheel**：PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名。改用 `curl.exe -OJ …`。
- **`pip install` 报 “Invalid wheel filename (wrong number of parts)”**：第 1 步用了自定义文件名。删掉重下，务必 `-OJ` 保留五段式文件名。
- **`externally-managed-environment`（PEP 668，多见于 Linux）**：用 pipx；确要系统装再加 `--user` 或 `--break-system-packages`。
- **登录/部署报「平台不可达 / ConnectError」**：命令行装好了、是**网络层**连不上平台。① 确认这台机器能连到平台内网（必要时连 VPN）；② 若设了公司代理（`HTTP_PROXY`/`HTTPS_PROXY`），内网地址会被甩给代理连不上——加 `--no-proxy`（如 `bisheng deploy . --no-proxy`），或把平台 IP 加入 `NO_PROXY` 后重试；③ 可先用 `curl.exe -v <平台地址>/api/v1/dev-toolkit/versions` 直接测平台是否可达（能返回 200 就是通的）。
- **登录报 403 / `20001`**：多为该账号被停用、或密钥被平台侧撤销之类的**平台侧**问题——让用户联系管理员，不要反复重签密钥。
- **登录说“未接入任何 AI 编程工具”**：本机没检测到 `~/.claude`（Claude Code）或 `~/.codex`（Codex）。用这两个工具的，确认装过后重跑 `bisheng skills sync`；用 Cursor / Trae / 通义灵码等其它工具的，首次 `bisheng deploy` 会在项目里写 `AGENTS.md` 指明技能位置，AI 读它即可。
