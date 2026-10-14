# 客户端第三方安装开关接入说明

> 对应 BiSheng 分支 `feat/bisheng-work-103`。服务端接口和管理页面已实现；桌面客户端读取与拦截尚待接入、联调。本说明是当前分支的接口契约，不代表已部署到客户环境。

## 1. 功能边界

管理员在 BiSheng「客户端 → 企业插件 → 安装设置」分别控制：

| 字段 | 管理页文案 | `false` 时客户端行为 |
| --- | --- | --- |
| `allow_third_party_plugins` | 允许安装第三方插件 | 拒绝从企业插件市场以外的来源新增安装第三方插件 |
| `allow_third_party_workbenches` | 允许安装第三方工作台 | 拒绝新增安装第三方工作台 |

两个字段独立、按登录租户保存；未配置时均为 `true`，保持升级前的安装行为。`false` 只约束**新增安装**，不要求卸载、停用或删除已安装内容，也不禁止卸载。企业插件市场中的管理员导入、员工安装走现有市场发布与签名校验流程，不属于这里的“第三方插件”开关。

该策略由桌面客户端执行。BiSheng 服务器无法代替客户端拦截本地文件、URL 或其他本地安装入口；客户端需在所有新增安装入口统一检查，不能只隐藏按钮。

## 2. 客户端读取接口

```http
GET {BiSheng公开地址}/api/v1/dsh/market/capabilities
Authorization: Bearer <DSH access token>
```

- 使用现有登录流程取得的 **DSH access token**，不是 refresh token、浏览器 Cookie、管理员凭证或个人访问令牌。沿用 [DSH 客户端接口契约](../../v3.0.0-beta2/062-dsh-desktop-model-access/client-api.md)中的同一个 BiSheng 公开地址；客户端不直连 Gateway 或数据库。
- 不传 `tenant_id`、`user_id` 或 `X-DSH-Market-Tenant` 来选择策略。服务端从已验证的 DSH 身份确定租户，并按当前会话、席位状态验证凭证。
- 响应头 `Cache-Control: no-store`。这个接口返回 **BiSheng 统一响应信封**，与 DSH 模型接口的裸 JSON 不同；成功时检查 `status_code === 200`，再读取 `data`。

成功示例（其余市场能力字段仍按原接口使用）：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "enabled": false,
    "public_key": null,
    "contract_version": 1,
    "tenant_id": "2",
    "max_upload_bytes": 536870912,
    "lease_seconds": 3600,
    "sync_seconds": 60,
    "allow_third_party_plugins": false,
    "allow_third_party_workbenches": true
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data.allow_third_party_plugins` | boolean | 是否允许新增安装第三方插件 |
| `data.allow_third_party_workbenches` | boolean | 是否允许新增安装第三方工作台 |
| `data.tenant_id` | string | 已认证的登录租户；用于检查客户端当前会话是否一致，不可作为请求参数回传来选择租户 |

`enabled` 只表示**企业插件市场签名能力**是否可用，与上述两个安装开关彼此独立。即使 `enabled=false`，仍须读取和执行两个布尔字段。`contract_version` 仍为 `1`；新增字段不改变 `/sync` 的签名 payload，也不会出现在 `/api/v1/dsh/config` 中。

## 3. 客户端执行时机与异常

1. 登录或切换 BiSheng 地址、账号、租户后，重新获取能力；旧账号与旧租户的策略不得复用。
2. 每次从本地文件、外部 URL 或其他第三方来源发起**新增安装**前，在线重新请求 `/capabilities`，按安装类型检查对应字段。管理员保存后，下一次安装检查即可看到新值；没有服务端推送事件。
3. 字段为 `false` 时停止进入安装流程，提示“管理员已关闭第三方插件安装”或“管理员已关闭第三方工作台安装”。不得通过换一个安装入口绕过。
4. 请求失败、凭证无效、业务码非 `200`、字段类型不是 boolean 或租户不匹配时，暂停本次新增安装，提示用户重试或重新登录。不要将失败当作允许安装；已安装内容的正常使用不因此受影响。
5. 兼容尚未部署此扩展的旧 BiSheng：若成功响应的 `data` **同时缺少**这两个字段，按升级前行为视为均允许；若只缺一个字段，视为异常并暂停安装。

第三方插件与第三方工作台的分类由客户端已有安装来源和类型决定。切换其中一个开关，不改变另一个类型的安装许可。

## 4. 管理端接口（供联调）

桌面客户端**只读** `/capabilities`，不得调用以下管理接口。BiSheng 管理页面使用普通 Web 登录身份，且需当前租户管理员权限：

| 方法和路径 | 用途 |
| --- | --- |
| `GET /api/v1/dsh/market/admin/install-policy` | 读取当前登录租户的两个开关；返回 `data: {tenant_id: number, allow_third_party_plugins: boolean, allow_third_party_workbenches: boolean}` |
| `PATCH /api/v1/dsh/market/admin/install-policy` | 立即保存一个开关；请求体见下例，响应返回保存后的完整策略 |

```json
{"field":"allow_third_party_plugins","allowed":false}
```

`field` 只能是表中的两个字段之一，`allowed` 必须是布尔值。管理接口的 `X-DSH-Market-Tenant` 仅用于校验与登录租户一致，不能借此修改其他租户。桌面 DSH 凭证调用管理接口会被拒绝。

## 5. 联调清单

- 同一租户分别关闭两个开关，客户端新增安装各自被拦截；重新开启后可安装。
- 只关闭其中一个开关，另一类安装仍可进行；企业插件市场中的已发布插件安装不受这两个开关影响。
- 切换租户或账号后重新读取策略；不同租户的设置互不串用。
- 管理员改动后，客户端下一次安装前读取到新值；响应虽为 HTTP 200，仍检查 `status_code` 和字段类型。
- 断网、过期或撤销凭证、策略读取失败时阻止新的第三方安装并允许重试；已安装内容仍可正常使用。

服务端已有市场模块测试覆盖默认值、独立更新、租户隔离及 `/capabilities` 返回字段。客户端安装入口与真实企业网关联调尚未完成。
