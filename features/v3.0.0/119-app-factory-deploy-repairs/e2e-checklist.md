# F119 E2E 验收

当前状态：本地合同与制品检查已执行；真实116发布E2E尚未执行。以下空框均不表示通过。K8s只做本地合同，不声明189上线。依据e2e-test技能，真实环境测试需要独立普通身份、允许/拒绝配对和完整响应断言。

## 前置与授权边界

- [ ] 核对本工作区提交/差异、backend/worker、manager/helper/assembler不可变镜像和116当前版本；本次代码必须先部署，不能用旧服务声称通过。
- [ ] 服务替换及真实发布须另获当前环境操作授权；此前只对116补齐Node镜像的授权不扩大为平台服务更新。
- [ ] 使用专用租户与 `e2e-f119-` 普通owner、publish-only、foreign以及approver；验证角色和动作，不使用super_admin作为权限通过证据。
- [ ] 运行前登记本套件已有残留ID并按精确前缀/归属清理，记录原业务容器、应用、profile/出网策略摘要；不删除其它任务或正式资源。

## CLI/业务真实旅程

| 完成 | 操作及必须断言 | AC |
| --- | --- | --- |
| [ ] | 在空venv安装平台实际下载的CLI post2，hash/版本与manifest一致，fresh login shell执行 `bisheng --version`，同步官方skills | AC-01, AC-27 |
| [ ] | 复制官方Python deploy-hosting示例，仅更改专用name/slug；CLI deploy→预检→真实审批→上线，保存deployment/version/operation关联，入口与 `/hits` 正常。没有版本字段的新输入按2/bundle，显式1保持旧方式 | AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-23, AC-27 |
| [ ] | 对此临时Python应用 `/hits` 写入计数；使用原应用动作停用再上线，计数继续增长。审批/管理预览写入不进入正式数据 | AC-06, AC-07, AC-38, AC-39 |
| [ ] | Node index.js或package.main最小项目，从平台下载材料准备→审批→上线；依赖精确版本和本地bin可用，没有npm隐式prestart/poststart | AC-12, AC-13, AC-14, AC-15, AC-16, AC-33, AC-35 |
| [ ] | static public/index.html现成包、根含源码index且build生成dist两种发布；分别验证入口内容正确。保留CLI默认打包排除规则，显式纳入产物 | AC-17, AC-18, AC-19, AC-20 |
| [ ] | 专用失败项目验证16227与16228分类、具体reason、CLI和管理页脱敏输出≤40行/16KiB；缺日志不宣称有日志，过期后不可读；publish-only只能看进度；跨租户拒绝 | AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27 |
| [ ] | 仅对本套件控制的缺镜像/坏入口资源验证准备前及维护前拒绝；旧正式路由/数据不变。不删除共用镜像制造故障 | AC-28, AC-29, AC-30, AC-31, AC-32, AC-37 |
| [ ] | offline缺精确版本材料拒绝；按原公共/私有材料导入补齐后重试；安装/编译仍禁网，运行出网不变 | AC-33, AC-34, AC-35, AC-36, AC-37 |
| [ ] | 检查代理5xx透传和原容量原因、清理本次精确ID资源、凭据和临时目录；与操作前正式资源摘要对比 | AC-40, AC-41, AC-42 |

## 只读真实API自动化

入口：`src/backend/test/e2e/test_e2e_f119_deploy_contract.py`。不创建/删除平台对象，故无删除cleanup；预先播种的专用资源由上方旅程统一清理。

运行前配置安全环境：`E2E_API_BASE`、`F119_E2E=1`、`F119_E2E_APP_ID/OPERATION_ID/TENANT_ID`、三组 `F119_E2E_{OWNER,PUBLISH_ONLY,FOREIGN}_{USERNAME,PASSWORD}`。仅访问已升级目标。测试包含普通edit允许、publish-only无日志和foreign精确16101拒绝。

`config=<local-config> PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest test/e2e/test_e2e_f119_deploy_contract.py -q -p no:cacheprovider`

未设置开关时的3个skip仅表示安全门工作，不计为真实E2E成功。CLI发布、人工审批、写库和停启保留由上方真实旅程留证，不降级为mock。

## 证据

记录执行时间、代码/服务镜像ID与digest、普通调用者角色、部署/版本/操作ID、响应与数据断言、清理结果。密钥、Cookie、下载票据、包源认证和原始私密日志不得写入报告。
