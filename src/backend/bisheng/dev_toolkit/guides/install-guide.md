# 安装并登录 bisheng 命令行（给 AI 助手看的执行指引）

你正在帮用户安装并登录**毕昇（BiSheng）平台的 `bisheng` 命令行**，好让用户之后把本地做的应用一键部署到平台。
请**按下面的步骤在用户机器上实际执行命令**，遇到报错就自行处置或降级到备选方案；全部完成后向用户简要汇报结果。
用户是非技术人员，请你把命令跑完，不要把这些步骤原样丢回给用户让他自己敲。

## 你需要的两样输入

1. **平台地址**：就用**你获取本指引所用的那个地址的主机部分**（协议 + 域名/IP + 端口），例如 `http://bisheng.example.com` 或 `http://192.168.1.10:7860`。用户的提示词里通常也带了同一个地址，两者应当一致。下文统一记作 `<平台地址>`。
2. **服务账号密钥**：形如 `bs-sak-…`，在用户的提示词里。下文记作 `<密钥>`。
   - **安全**：不要把 `<密钥>` 回显到聊天、写进任何文件、或留在会话记录里；登录时尽量用标准输入传入（见第 3 步），避免它落进 shell 历史或进程列表。

## 第 1 步：下载安装件

命令行的安装件（一个 Python wheel 文件）从平台下载，**不依赖公网**。优先用 `curl`：

```bash
curl -OJ <平台地址>/api/v1/dev-toolkit/cli/download
```

- `-OJ` 很关键：让 `curl` 采用平台返回的正确文件名（`bisheng_cli-<版本>-py3-none-any.whl`）。**不要**用 `-o bisheng.whl` 这类自定义名——`pip` 只认前者那种五段式文件名，会以 “Invalid wheel filename” 报错。
- 没有 `curl` 时的备选：
  - `wget --content-disposition <平台地址>/api/v1/dev-toolkit/cli/download`
  - 或 `python3 -c "import urllib.request,re,cgi; r=urllib.request.urlopen('<平台地址>/api/v1/dev-toolkit/cli/download'); fn=cgi.parse_header(r.headers.get('Content-Disposition',''))[1].get('filename','bisheng_cli.whl'); open(fn,'wb').write(r.read()); print(fn)"`
- 若这一步返回 404 或 JSON 报错：说明平台未发布安装件（未启用开放能力层，或版本过旧）。**停下来告诉用户联系平台管理员**，不要继续。

## 第 2 步：安装（关键：让 `bisheng` 在“新会话”里也能调用）

**这一步最容易出隐蔽错误。** 用户装完后会**重启 AI 助手、开一个全新会话**再来部署；那是一个**全新的 shell**，不会继承你现在这个会话临时激活的环境。所以：

> ⚠️ **绝不要把命令行装进项目局部的虚拟环境**（如你当前 `source` 激活着的 venv、或项目里的 `./.venv`、`./venv`）。那样 `bisheng --version` 在你这个会话里能跑，但用户新开会话部署时会 `bisheng: command not found`、报“没有配置 bisheng CLI”。**必须装到系统 PATH 上，任何目录、任何新终端都能直接调用 `bisheng`。**

**首选 `pipx`**（装到 `~/.local/bin`，在 PATH 上且相互隔离，最稳）：

```bash
pipx install ./bisheng_cli-*.whl
```

**没有 `pipx`？先把它装上再用它**（哪条报 PEP 668 就给哪条加 `--break-system-packages`）：

```bash
python3 -m pip install --user pipx || python3 -m pip install --user --break-system-packages pipx
python3 -m pipx ensurepath        # 把 ~/.local/bin 写进 shell 配置，新会话即可直接调用
pipx install ./bisheng_cli-*.whl
```

**连 pipx 都装不上时，才退到 venv——但必须把入口软链到 PATH 上**（否则就是上面警告的坑）：

```bash
python3 -m venv ~/.bisheng-venv && ~/.bisheng-venv/bin/pip install ./bisheng_cli-*.whl
mkdir -p ~/.local/bin && ln -sf ~/.bisheng-venv/bin/bisheng ~/.local/bin/bisheng
```

若 `~/.local/bin` 不在 PATH 上：跑 `python3 -m pipx ensurepath`，或把 `export PATH="$HOME/.local/bin:$PATH"` 写进用户的 shell 配置（`~/.zshrc` / `~/.bashrc` / `~/.profile`）。

## 第 3 步：登录

用用户的密钥登录一次，凭据会存在用户本机（`~/.bisheng/`），以后不用再输：

```bash
# 推荐：密钥从标准输入传入，不落进 shell 历史 / 进程列表
printf %s '<密钥>' | bisheng login <平台地址> --api-key-stdin

# 或（等价，但密钥会出现在命令行参数里）
bisheng login <平台地址> --api-key <密钥>
```

登录成功时，命令行会**自动把《部署纳管》技能同步到本机、并接入检测到的 AI 编程工具**（Claude Code / Codex）。
留意登录输出的最后几行：它会写明**接入了哪些工具**。若显示“未接入任何 AI 编程工具”，见文末排障。

## 第 4 步：核对并汇报（务必在“全新 shell”里验证）

先确认子命令齐：`bisheng --help`（能看到 `login` / `deploy` / `skills`）。**但只在当前 shell 验证不够**——用户是新开会话部署的。用一个**全新登录 shell**再验一次，模拟新会话：

```bash
bash -lc 'bisheng --version'      # 或 zsh：zsh -lic 'bisheng --version'
```

- 这条**能打印版本号**才算真的装好。
- 若这条 `command not found`、但你当前会话里 `bisheng` 能跑——说明装到了只在当前会话有效的地方（项目 venv / 未进 PATH）。**回到第 2 步用 pipx 重装，或把入口软链进 `~/.local/bin` 并确保它在 PATH 上**，直到这条全新 shell 的验证通过，再往下。

然后向用户**简要汇报**：
① 命令行已装好并登录到 `<平台地址>`；② 《部署纳管》技能接入了哪些 AI 工具；③ **请用户重启一下当前的 AI 助手**，让它读到刚接上的技能——之后新开会话，用户用大白话描述想做的应用即可。

---

## 排障

- **`pip install` 报 “Invalid wheel filename (wrong number of parts)”**：第 1 步用了自定义文件名。删掉重下，务必用 `curl -OJ`（保留平台给的五段式文件名）。
- **下载得到的是名为 `download` 的文件**：同样是文件名问题（用了 `-O`/`-sO` 或 `pip install <url>`）。改用 `curl -OJ` 重下。
- **`externally-managed-environment`（PEP 668）**：优先改用 `pipx`；确要系统装，加 `--user` 或 `--break-system-packages`。
- **新会话里 `bisheng: command not found`（当初装的时候明明是好的）**：这是最常见的坑——命令行被装进了只在当初那个会话有效的环境（项目局部 venv，或没进 PATH）。用 `pipx install ./bisheng_cli-*.whl` 重装（装到 `~/.local/bin`，全局可用），或把已装好的入口软链进 PATH：`mkdir -p ~/.local/bin && ln -sf <venv>/bin/bisheng ~/.local/bin/bisheng` 后 `python3 -m pipx ensurepath`。判据：`bash -lc 'bisheng --version'` 在**全新 shell** 里能跑通。
- **登录报 403 / `20001`**：这多半不是密钥错，而是该账号所在租户被禁用之类的**平台侧**问题——让用户联系管理员，不要反复重签密钥。
- **登录说“未接入任何 AI 编程工具”**：本机没检测到 `~/.claude`（Claude Code）或 `~/.codex`（Codex）。用这两个工具的，确认装过后重跑 `bisheng skills sync`；用 Cursor / Trae / 通义灵码等其它工具的，首次 `bisheng deploy` 会在项目里写一个 `AGENTS.md` 指明技能位置，AI 读它即可。
- **代理环境**：内网地址走了公司代理会连不上平台，可对该地址设置 `NO_PROXY` 后重试。
