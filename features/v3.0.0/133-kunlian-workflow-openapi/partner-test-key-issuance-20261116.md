# 对方测试Key签发记录（不含秘密）

用户明确选择：当前全部已接入昆联租户、全部Workflow能力、永久。2026-11-16在104部署环境签发。

- Key ID：1；遮罩：bs-kl-********an1E。
- 接入方：kunlian-partner-test-20261116；可信连接：kunlian-workflow-test。
- 范围：签发时10个enabled/materialized外部租户（映射本地租户2～11），不是所有未来租户；新增不自动加入。
- 能力：read/write/publish/invoke/grant；expires_at=null，不设到期。
- 签发前User Owner实时复核本地管理员user_id1为当前全局超管，在平台tenant1记录持久审计意图，签发后审计完成。未修改业务用户/成员/授权。
- 明文只存受限独立交付文件，公开API文档、仓库和本记录不包含；本地凭据文件权限600并加入.git/info/exclude防误提交。对方联调结束应通知平台撤销Key1。
- 原签发脚本结束时出现aiomysql loop-closed析构警告；签发响应和持久记录已成功，未因warning重复签发。

## 只读探测

通过gateway:8080与正式Key：中数SSO只读测试、中数SSO编辑测试列表HTTP200/业务200，data为嵌套cursor对象，当前item_count0。仅证明Key/账号准入及空列表，不证明有工作流运行/编辑/授权权限。

tong.leisheng存在精确重名记录，HTTP403/19322；不为测试擅自改名或合并用户。

有效Key缺user_account实际HTTP401/26001，属于v2解析失败旧凭据回退的已知行为；混旧Query和重复账号实际HTTP422/19320。未做写链路测试。

## 风险与后续

永久全能力Key是高信任代用户凭据，可代表获准租户的有效用户及租户管理员，禁止代表全局超管。环境HTTP无TLS，只能在受控网络联调，正式接入应改HTTPS。不得将其交给浏览器前端或公开粘贴。需要缩范围、轮换或撤销时使用平台超管控制面，不操作数据库明文Key。
