# F086 部门投影运维

这是cofco-1111同版服务源码内的长期工具，不是旧F078临时替换包。不新增表/列/索引，不用替换pyproject，不读取旧v5计划作为执行授权。

测试交接见[QA-IMPACT.md](QA-IMPACT.md)，包含正常流程影响范围及24项重点回归；本地结果与待执行部署验收见[validation.md](validation.md)。

## 部署与自动恢复

API、Celery Worker、Beat及其他直接写部门/FGA的程序须同版。首次切换先排空并停止相关写入者，升级期间关闭department_projection_recovery.enabled，升级所有写入者后再启用并恢复写入；不要混跑不使用新部门租约的旧进程。仅关闭自动恢复不能回退新的同步执行器，也不能代替写入者排空。沿用正常版本升级步骤，不由脚本停止/启动服务。

```yaml
department_projection_recovery:
  enabled: true
  interval_seconds: 300
  batch_limit: 20
  page_size: 500
  max_scan_rows: 50000
  run_budget_seconds: 120
  max_fga_qps: 2
```

自动只恢复当前业务合法且原绑定/版本/模型未变、原目标仍可证明的操作。不查IAM，不决定组织树或生命周期。失败提示有界退避，周期按租户与部门游标兜底。实际task名为bisheng.worker.department.projection_recovery.recover_department_projections。自定义beat条目优先于interval配置；须确认Worker和Beat都在运行。

## 只读扫描

使用与同版API相同的配置、数据库、FGA和现有Python依赖。无需重做全库备份来扫描；默认不写SQL/FGA/Redis，不启动Catalog/model种子、迁移或其他存储。

```bash
cd src/backend
export PYTHONPATH=./
export config='<服务实际使用的配置文件>'
python -B scripts/reconcile_department_projections.py \
  --tenant-id 1 --environment-id production \
  --output-dir /evidence/f086/scan-001
```

需证明SQL无法核实的父级/路径或删除时加 `--iam-config /protected/iam.json`。仅查这些候选及必要直接父级；不查全IAM树。可以 `--department-id 19934 22203` 做定点扫描，工具仍自动纳入必要依赖。已确认相关写入者确实静默时，dry-run也可加 `--confirm-writers-idle`，避免仅因近期PROJECTING的时间阈值把停服候选标为处理中；不能用这个声明代替实际排空。FAILED门禁不会仅凭最近操作时间被当作仍在执行。

目录必须是新目录，文件权限0600/目录0700并受控持久化。

IAM配置示例，JSON中写环境变量名，不写密钥：

```json
{"base_url":"https://iam.example","bisheng_source":"wecom","app_id_env":"BS_DEPARTMENT_IAM_APP_ID","app_secret_env":"BS_DEPARTMENT_IAM_APP_SECRET","timeout_seconds":5,"max_qps":2,"max_requests":2000}
```

由受控凭据加载器设置这两个变量，不在命令行/日志回显。source应与实际Gateway支持的定点接口和本地source一致；当前实现匹配企微department/list协议，不按名称或external_id编码家族推断映射。

输出scan.jsonl、plan.jsonl、results.jsonl。检查complete、all_repairable、counts、execution_order、coverage、plan_checksum和环境。READY与AFTER_DEPENDENCIES是计划执行资格；RECOVER_ARCHIVE等是计划分类，数据库状态仍是原有CURRENT/PROJECTING/FAILED_CLOSED。

complete只表示当前扫描范围完整；正常CURRENT部门默认不做全FGA审计，ancestor_gate_only不是这些后代已逐条审计。BLOCKED需业务或环境纠正后重新预览。预算/差异/证据超限不能绕过；提高速率也不能代替实际SQL与FGA验证。dry-run明确write_path_unmeasured，不承诺apply十分钟完成。

## 执行与续跑

DBA已有覆盖业务库和FGA datastore的备份即可，用确认标志登记事实；可附真实backup-reference或已有backup-evidence，工具不验证备份可恢复，不要求再次备份或填写未做过的恢复演练。备份和整库恢复仍由DBA负责。

先确认扫描plan complete=true且all_repairable=true，相关组织/成员/祖先/挂载、模型发布、其他FGA写入者和自动Worker都已静默。普通模式也要求所选范围写入排空。保留原计划、确认值及窗口，不用旧包计划替代新格式。

```bash
python -B scripts/reconcile_department_projections.py \
  --tenant-id 1 --environment-id production --apply \
  --plan-file /evidence/f086/scan-001/plan.jsonl \
  --confirm-plan '<本次plan_checksum>' \
  --confirm-backups-completed --backup-reference '<实际备份引用，可省略此参数>' \
  --confirm-writers-idle --window-id maintenance-001 \
  --output-dir /evidence/f086/apply-001
```

普通FGA QPS默认2、最大5；确实整窗停服时可追加 `--offline-maintenance --max-fga-qps 20`，始终串行。该标志不会替你停止任何写入者。IAM仍独立限速，不能通过增加多进程突破。

T1封存当前计划并建立门禁/必要业务重挂或归档；T2真实核对FGA before/target、写最小差异、核验AFTER、严格清关联并同SQL收口。重挂和归档不是简单“覆盖OpenFGA”；归档不会删用户/迁人，独立资源Grant不改。

中断后先确认旧进程已退出；同plan、同window、相同IAM配置（若原扫描使用）及备份确认与静默条件，换新输出目录重跑同一apply命令。共享SQL审计用于识别完成项，不依赖旧本地results文件。已经完成项不重复写/增版本；FGA已目标但SQL未完成只补收口。停服模式略去完成项完整T1/T2和未完成T1的重复FGA读，仍保留未完成T2真实前后核查。

业务/模型/绑定/版本/窗口或FGA第三态改变时停止，不能改manifest、删门禁或改结果文件伪装继续；先保留证据再按当前事实重新预览。不要把before_saved或recovery_identity当SQL已提交。

结束须核对apply_summary complete=true、remaining_department_ids=[]及逐项结果，再做普通用户有权/无权访问验收后由运维开服。没有自动重启服务。

退出码：0=扫描完成且可修/执行完成；2=参数；3=业务阻塞/计划拒绝；4=运行失败；5=部分完成或末核验失败。complete/all_repairable不证明实际用户资源权限均已验收。

## 证据、清理与恢复

保留原计划、各轮results/before文件、window-id、实际备份引用及现有SQL prepared/finalized/superseded审计。外部证据含受控关联before，按生产数据管理；勿放公开目录。

本工具不修改/app文件或依赖，正常版本部署无需临时源码替换。只需清理获准删除的本次临时工作目录，保留审计与证据；清理文件不回滚业务数据。工具提供正向重入，**不提供在线inverse/一键还原**。整库恢复必须由DBA在相关写入者停下且两侧时间点一致的情况下协调业务库与FGA；开服后不能直接用旧全库备份覆盖新增数据。

告警规则与原因解释见[ALERTING.md](./ALERTING.md)。真实双库、FGA、Redis及生产时限验证情况见[validation.md](./validation.md)。
