# 工场镜像同名重复发布变更核对

日期：2026-11-23。基线：`origin/feat/3.1.0-beta1`的`95e5b6445c3a3848b895a416bcd3ffbebcbf15a4`。用户明确要求移除同名镜像覆盖限制；属于已有发行流程的定向修正，不新增业务API或部署动作。

## 结果与边界

- `build_runtime_images.sh`与`sync_runtime_images_cr.sh`移除检查远端标签是否已存在的拒绝分支，不再读取`RUNTIME_REPLACE_RELEASE`。
- `runtime-images.yml`移除`github.event.forced`到覆盖参数的映射；tag push、手动构建和重试使用相同发布规则，允许覆盖同一release/架构标签。
- 前后端`ci.yml`原本直接`buildx build --push`及同步CR，无同名标签拒绝检查，本轮不改写它们。
- 保留原生架构/Engine、干净源码及revision、全部隔离冒烟后推送、CR精确Image ID同步和错误传播。双架构/双仓库成功才生成目录，正式服务标签仍按`release.yml`推广。
- 重发后的镜像使用本次digest区分；不修改已有profile不可变修订、已冻结应用镜像或运行版本。
- 同release工作流串行配置保留。发布仍逐镜像推送，注册表不是跨镜像/跨仓库原子事务；失败须按真实任务状态和digest处理，不能把部分推送记为整套发布成功。

## 验证

两个同名发布行为用例在旧脚本分别因Docker Hub、CR同名镜像拒绝而失败。修改后执行：

```bash
# src/runtime-manager；使用仓库现有Python3.11虚拟环境
python -m pytest tests/test_image_release.py tests/test_cr_image_sync.py -q
```

两个模块共51项：默认沙箱49项通过、2项因本机HTTP端口监听被禁止而失败；仅对这两项允许loopback监听后补跑，2项通过。未修改断言或SQLite业务以绕过环境限制。覆盖同名发布、全部冒烟先于首次推送、冒烟失败零推送、CR复用已验证ID、鉴权/推送失败不签发成功清单、源码/架构和目录完整性。

`bash -n`两个脚本、工作流YAML解析/目录依赖/同release串行、两个Python文件Ruff check/format、架构守卫及`git diff --check`通过。本地使用Docker替身，不访问或推送真实注册表，不宣称真实Linux双架构构建、CR同步或正式Release已完成。

## 七维增量审查

| 维度 | 结论 | 依据 |
| --- | --- | --- |
| 边界条件 | PASS | release格式、目标架构、显式publish和原始库存字段校验保留；已存在标签从拒绝转为正常推送 |
| 权限与认证 | PASS | 只移除用户指定的重复发布策略；原登录、凭据、发布账号权限和推送错误处理不变 |
| 并发安全 | PASS | 同release串行锁不变；不声称跨仓库原子发布 |
| 信息泄漏 | PASS | 无凭据、现场配置、业务数据或新日志载荷 |
| 测试覆盖 | PASS | 两处旧逻辑红测成立；51项验证覆盖新行为及原失败边界 |
| 代码风格 | PASS | 删除死参数/分支，Shell/YAML/Python与架构检查通过 |
| 文档同步 | PASS | OPERATIONS、F009当前设计/修订和任务记录同步；固定digest与profile修订规则保持 |

总体：**PASS（本轮增量）**。旧Actions运行不会自动采用新脚本，需更新tag到本次修复提交再触发；新构建是否完成须另核对GitHub Actions与注册表，不以源码通过代替。
