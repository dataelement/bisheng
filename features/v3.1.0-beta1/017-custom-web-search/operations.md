# 自定义联网搜索部署与运维

## 界面配置

自定义搜索不要求新增环境变量。在工具设置中导入 OpenAPI、选择操作和搜索词参数、填写认证信息与结果映射，再测试、保存。无认证搜索无需填写供应商 API Key。公网 HTTPS 和受支持的企业私网出站默认按适配器策略校验，环回、链路本地、云元数据、重定向和环境代理仍禁止。

## 系统密钥

首次导入、保存或初始化自定义搜索时，后端自动生成随机 Fernet key，使用平台既有的配置加密封装持久化到共享数据库 `config` 表的 `web_search_keyring` 行。API、Celery 和 Linsight 从同一行读取；数据库唯一键处理多实例首次创建竞争，不依赖本地文件或进程环境。

此系统密钥用于加密搜索 API Key 和签发接口定义 proof，不是供应商 API Key，接口不会返回它。凭据和 proof 继续绑定 tenant/category 及不同用途的域标签。已有数据损坏、未知 key ID 或认证失败会明确失败，不自动换钥、清空凭据或降级成无认证。

## 旧环境升级

先在受控运维会话中读取旧 `BISHENG_WEB_SEARCH_SECRET_KEYRING` 和 `BISHENG_WEB_SEARCH_SECRET_ACTIVE_KEY_ID`，验证全部 key 和当前 ID；将 `{"keys": <旧 keyring>, "active": <旧 active ID>}` 使用 `core.config.settings.encrypt_token` 加密后写入 `config.web_search_keyring`，保留旧 ID 与 key，校验所有已存凭据可解密。已有该行时只允许验证一致，不覆盖未知数据。

然后部署新代码、从实际 Compose env_file 或其他配置源移除这两个变量并重建 API/worker。旧镜像仍依赖环境变量，不能先删变量再使用旧镜像运行。保留受限权限的旧配置备份及旧镜像，回滚时同时恢复旧变量；不把密钥写入日志、命令参数或仓库。未配置过旧密钥的新安装无需执行迁移。

备份与恢复应包含 config 表及搜索密文表；只迁移搜索密文而不迁移系统 keyring 无法解密。轮换需保留旧 key 和 ID，并以受控运维事务更新 keyring 与逐条重加密；本次不新增轮换 UI。

## 可选网络限制

`BS_CUSTOM_SEARCH_ORIGINS`、`BS_CUSTOM_SCHEMA_ORIGINS` 和 `BS_CUSTOM_SEARCH_PORTS` 仅用于额外收紧出站目标，不是使用界面配置的前置条件。设置后仍按精确 origin/端口校验。`BS_CUSTOM_SEARCH_PRIVATE_CIDRS` 可收紧允许的企业私网范围；始终禁止的地址类型不会因此放开。私有 CA 可通过 `BS_CUSTOM_SEARCH_CA_FILE` 配置并挂载到所有执行实例。Compose 不新增这些变量。

## 验证范围

本地回归覆盖无上述密钥变量时的 Schema 导入、保存、测试和执行，以及多实例密钥初始化、跨租户/跨用途拒绝、损坏数据拒绝与旧 key ID 迁移。实际环境需另外核对运行容器变量、旧凭据解密及真实搜索结果；健康检查通过不能代替搜索验收。
