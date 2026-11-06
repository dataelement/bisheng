# 任务模式评测执行器（harness）

这套脚本用 106 真实业务 query 评测任务模式。它通过 v2 开放 API 提交任务，取回结果后判分。

代码放在仓库 `tools/taskmode_eval/`。用例材料（输入文件、参考答案、知识空间文件、历史产出）是客户数据，**不进仓库**，只存放在三处：106 `/root/taskmode-eval/`、116 `/data/taskmode-eval/taskmode-eval-v1/`、114 `/opt/taskmode-eval/taskmode-eval-v1/`。

使用时先把本目录复制到材料包的 `harness/` 目录，再在部署了 BiSheng 的机器上运行。运行时生成的 `env.json` 含密钥，权限是 600，不要提交。

## 文件

| 文件 | 作用 |
|---|---|
| `selection.json` | 35 条正式用例：层级（core 31 条 / extended 4 条）、考察能力、入选理由；另列出 10 条落选候选及原因 |
| `REFERENCE_SCHEMA.md` | 参考答案 `cases/<id>/reference.json` 的格式与标注原则 |
| `setup_env.py` | 一次性准备环境：评测用户、服务账号密钥、客户技能、两个知识空间，写出 `env.json` |
| `run.py` | 批量执行器 |
| `grade.py` | 判分并生成报告 |
| `extract.py` | 把 docx / pptx / xlsx / html / md 产物抽成文本和格式摘要 |
| `baseline_run.py` | 把 106 的历史产出整理成一次 run（`runs/baseline-106`），作为 v0 基线 |
| `in-image.sh` | 在后端镜像的一次性容器里运行上面任一脚本，用于 docker compose 部署（宿主机 Python 缺依赖时） |

## 执行身份

脚本用服务账号 `taskmode-eval` 的密钥，代表普通用户 `taskmode_eval` 执行（请求头 `X-On-Behalf-Of`）。不用其它身份的原因如下：

- admin 不能作为委托对象，会返回 26007。
- 服务账号自身身份只能被授予应用、频道、助手、看板，拿不到技能和知识空间。

任务会出现在 `taskmode_eval` 的工作台里，排查时用这个账号登录，就能看执行过程。

## 步骤

### 源码部署（以 114 为例）

```bash
cd /opt/taskmode-eval/taskmode-eval-v1
PY=/opt/bisheng/src/backend/.venv/bin/python

# 1. 准备环境（只需一次；重复运行会复用已有资源，但会重新签发密钥）
$PY -I harness/setup_env.py --password '<admin 密码>' --model 9 --judge-model 16 [--vision-model <能读图的模型 id>]
#    --skip-spaces    暂不建知识空间
#    --replace-skills 用材料包里的技能版本覆盖环境里的同名技能

# 2. 执行
$PY -I harness/run.py --cases core --repeat 1 --concurrency 3
#    --cases 可写 core / extended / all / A01,B03 或混合，如 core,A11
#    中断后续跑：--run-id <原 run-id> --resume

# 3. 判分与报告
$PY -I harness/grade.py --run-id <run-id> [--compare baseline-106] [--no-judge]
#    报告：runs/<run-id>/report.md；逐条明细：runs/<run-id>/<case>/r<k>/grade.json
```

### docker compose 部署（以 test 环境 116 为例）

```bash
cd /data/taskmode-eval/taskmode-eval-v1
export DB_URL=$(docker exec bisheng-test-backend python -c \
  "from bisheng.common.services.config_service import settings; print(settings.database_url)" 2>/dev/null | tail -1)
bash harness/in-image.sh setup_env.py --base-url http://127.0.0.1:7861 --password '<admin 密码>' \
  --model 935 --judge-model 936 --platform-version "release@<镜像 digest>"
nohup bash harness/in-image.sh run.py --cases all --repeat 3 --concurrency 4 --run-id <run-id> > runs/<run-id>.log 2>&1 &
bash harness/in-image.sh grade.py --run-id <run-id> --compare baseline-106
```

被测模型必须先出现在「工作台模型」的对话模型列表里（任务模式和日常模式共用这张列表），否则 `run.py` 预检会报"模型不可用"。改完配置后，最多要等 100 秒缓存过期才生效。

## 判分规则

每条用例的判分分两部分：

- **确定性检查（checks）**：由脚本直接判定。终态 `c0` 固定是 critical。
- **评分要点（rubric）**：由评审模型逐条判通过或不通过，并给出原文证据。

得分是通过项的加权占比。一条用例要算通过，需要同时满足三点：所有 critical 项通过；得分达到 `pass_threshold`（默认 0.7）；没有未判的项。

评审模型用 `env.json` 的 `judge` 配置，接口为 OpenAI 兼容格式，温度为 0。评审模型最好和被测模型不是同一家族，减少自评偏差。

重复执行（`--repeat k`）时，报告给出每条用例的"通过次数/k"，用来区分稳定失败和偶发失败。

## 环境准备时踩过的坑

- 新建用户第一次登录后，才会生成 `user_tenant` 记录。在此之前它不能当委托对象，签发密钥会返回 26024。`setup_env.py` 已经自动先登录一次。
- super admin 做服务账号相关的写操作前，要先选定管理租户，否则返回 26073。`setup_env.py` 会调用 `management-scope`，并带上 `X-Management-Tenant` 请求头。
- 知识空间文件命中敏感词时，状态是 7（内容安全拦截）。在 test 环境上，研发管理空间的《JAVA 后端开发代码规范》因"去中央"被拦。正式用例没有用到这份文件。

## 已知限制

- 开放 API 执行期间不会向用户提问。所以信息不足类用例（F03、B05）测的是"按假设完成并写明假设"，不测追问能力。
- 评审模型只能看到抽取出来的文字和格式摘要（样式名、字体、版式名、页数），看不到渲染效果。B06 是否用了模板图片、公文的字体字号这类视觉要求，需要人工打开产物复核。
- 产物文本超过约 9 万字时会被截断后再交给评审模型。
