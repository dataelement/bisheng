# 自定义联网搜索部署与运维

## 界面配置

自定义搜索不要求新增环境变量。在工具设置中导入 OpenAPI、选择操作和搜索词参数、填写认证信息与结果映射，再测试、保存。无认证搜索无需填写供应商 API Key。公网 HTTPS 和受支持的企业私网出站仍按适配器策略校验。

## 加密方式

搜索 API Key 直接使用毕昇现有 `core.config.settings.encrypt_token / decrypt_token` 加密封装。密文仍包含用途、租户和分类绑定信息；凭据表只保存密文与固定 `platform` key ID，接口不返回明文。系统不生成、不保存、不读取独立的搜索 keyring，也不新增搜索密钥数据库配置项。

旧版本曾使用 `BISHENG_WEB_SEARCH_SECRET_KEYRING` 和 `BISHENG_WEB_SEARCH_SECRET_ACTIVE_KEY_ID`。升级时必须先用旧环境变量解密已有搜索凭据，再使用 `encrypt_token` 重加密并更新为 `platform` key ID，确认解密成功后才能移除旧变量并重建 API/worker。115 已完成此迁移；`config.web_search_keyring` 不存在，现有凭据已改用平台加密封装。

旧镜像仍依赖环境变量，不能先删变量再运行旧镜像。回滚旧镜像时必须恢复旧变量和旧格式密文；新镜像不读取旧 keyring。迁移脚本不得记录密钥、密文或明文。

## 可选网络限制

`BS_CUSTOM_SEARCH_ORIGINS`、`BS_CUSTOM_SCHEMA_ORIGINS`、`BS_CUSTOM_SEARCH_PORTS` 和 `BS_CUSTOM_SEARCH_PRIVATE_CIDRS` 仅用于额外收紧出站目标，不是界面配置前置条件。Compose 不新增这些变量。

## 验证范围

本地相关回归覆盖无两个旧密钥变量时的 Schema 导入、保存、测试和执行、租户/用途绑定及损坏密文拒绝。115 已验证无旧变量时 authless Schema 导入成功，现有凭据解密成功，已保存搜索仍可调用。

## beta2 操作证明移除（2026-11-24）

导入、测试、保存和工具初始化不再签发或校验 proof。已有配置和旧请求中的 proof 会被忽略，设置读接口不返回它，选中 custom 保存时清除，无需为旧 proof 重导入 Schema 或迁移数据库。API、前端和 Worker 应一并更新；旧前端仍强制要求 proof，与新导入响应不兼容。

API Key 仍按租户和工具类别单独加密保存，子租户未配置凭据时仍须填写获授权的 API Key。不能通过移除 proof 自动继承 Root 的密钥。完整 Schema 回显问题未在本次修改。
