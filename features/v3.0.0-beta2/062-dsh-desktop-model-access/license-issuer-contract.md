# F062 DSH License 发行契约 v1

T002 的服务端/发行工具共同输入；客户端契约仍为 0.1.0。厂商私钥不交付客户，不复用旧 License 解密密钥。当前仅提供测试向量，真实发行样本、目标旧 Gateway 二进制及旧 RSA 分段兼容仍是发布门禁。

## 外层与签名

沿用既有 License 配置项与 RSA 密文封装，在解密后的原 JSON 对象中仅追加 `dsh_entitlement` 字符串；不更改原 `version/expireDay` 或其他字段。签名扩展采用 JWS Compact Serialization，严格三段无填充 base64url。签名覆盖收到的 header.payload 原始 ASCII 字节，验证时不重新序列化。

v1 固定 RS256（RSA PKCS#1 v1.5 + SHA-256），新厂商 RSA 签名密钥至少 2048 位；这里只规定新签名密钥，不改变旧加密算法。格式依据 [RFC 7515 §5.2](https://www.rfc-editor.org/rfc/rfc7515.html#section-5.2) 与算法依据 [RFC 7518 §3.3](https://www.rfc-editor.org/rfc/rfc7518.html#section-3.3)。

Protected header 只允许 `alg=RS256`、`typ=bisheng-dsh-license+jwt`、非空 `kid`。拒绝 none/HS256、未知参数/crit、jku/x5u/jwk、重复 JSON key、非法 UTF-8、非对象和非有限数值。kid 只匹配运维预配厂商公钥集合，不网络发现；测试 fixture 的公钥绝不自动载入运行时信任配置。

## 签名载荷

| 字段 | 必填约束 |
|---|---|
| schema_version | JSON integer，严格等于 1，boolean 不视作 integer |
| iss / aud | 精确为 `bisheng-license-issuer` / `bisheng-gateway:dsh`；aud 必须是字符串 |
| jti | 1～128字符，发行方唯一 License ID；不是累计额度的分片 |
| installation_id | 1～64字符，与服务端受管实例标识精确一致 |
| iat / nbf / exp | 非负整数 Unix UTC 秒，≤2^53−1；iat≤nbf<exp；不接受浮点或字符串，不给 exp 额外宽限 |
| legacy_binding | 原解密 JSON 除 dsh_entitlement 以外的**全部字段**对象，包含原值；不是只绑定 trial/pro 标签 |
| capabilities | 仅包含 dsh 对象；其字段固定为 enabled:boolean、seat_limit:integer，0≤seat_limit≤2^31−1，boolean 不是整数 |

v1 拒绝未知载荷/能力字段，未来 schema 明确升级；该规则仅作用于 DSH 扩展，不收紧没有扩展的旧 License 解析。服务端严格验证 schema、签名、绑定与实例，再判断 `nbf≤now<exp`；有效签名但 exp 已到期报告 license_expired；未生效、未知格式、关闭能力及其他无效情况报告 license_invalid。enabled=true 且 seat_limit=0 表示有效但没有可分配容量，不表示无限额。

`legacy_binding` 与外层去掉扩展后进行类型敏感的结构化比较：对象键顺序无意义，数组次序与字符串原值必须一致，null 与字段缺失不同，布尔与数值不同。为两种语言一致，签名扩展中的数字及被绑定原对象数字只接受安全整数，禁止重复 key/浮点；无扩展旧 License 不受此新增限制。不要将外层 version 改成新类型，当前旧程序非 trial 分支仍可能被视为 pro。

## 大小、加密分段及换版

扩展 Compact JWS 的 UTF-8 编码≤32768字节；新增扩展后的解密 JSON≤65536字节。先检查限额再解析 DSH；超限只让 DSH 无效，不使原可解析商业授权连带过期。旧外层解密失败仍保持原整站降级逻辑。

发行工具必须保留目标旧 Gateway 所用外层 RSA padding、密钥和分块约定。**不能根据新签名 RSA 位数推导旧密文分段长度**；目标发行工具/旧 artifact 样本确认前禁止发布含扩展的新密文。测试向量提供解密后的外层 JSON 和新签名，用于跨语言验签，不声称已经证明旧 RSA 外层兼容。

公钥按 kid 配置轮换，可重叠保留旧公钥直到其 License 结束或明确撤销；仅更新信任集合不得覆盖现用有效授权。License 换版遵循 Design 全副本暂停 DSH→等待事务→安装同版本/摘要→核对→恢复；保留原密文以便关闭 DSH 后回退。旧商业 trial 到期与有效 DSH 签名独立判定；不能延期原 SSO。

## 测试向量与发行门禁

[license-entitlement-v1.json](./contracts/license-entitlement-v1.json) 使用一次性随机测试密钥生成签名，仅保留公钥，私钥未写入文件。用固定 now 验证有效 pro、旧 trial 已过期但 DSH 有效、DSH 过期/未生效、错误实例/schema/audience/kid、非法容量、外层替换及篡改签名。向量中的测试身份/实例不能用于客户授权。

真实厂商样本、目标旧 artifact 摘要、旧/new程序读取结果、近上限密文分段及受控回退结果须写入后续 license-compatibility-report.md；缺失时兼容门禁保持未验证，不以本测试公钥替代生产信任根。
