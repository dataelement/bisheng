# 会话标题同步实施与验收

日期：2026-10-20。范围：规格0.24 AC-T01至AC-T09、设计0.14 §4.7，另移除“查看本用户会话”“查看父会话”。仅本轮结果，不沿用历史E2E结论。

## 自动验证

| 项目 | 当前结果 | 边界 |
|---|---|---|
| 后端`pytest test/dsh -k model_audit -q` | 201通过、3跳过 | 包含新增15项标题HTTP/SQL测试；独立SQLite及合成身份/模型，不等于109真实鉴权 |
| Platform审计相关10个测试文件 | 77通过 | 标题纯文本、编号回退、导航删除、查询及原文按需读取 |
| 前端根目录`pnpm typecheck` | Platform/Client/file-viewers通过 | 无新增依赖或UI组件 |
| 改动文件ESLint、后端Ruff | 通过 | 全仓既有lint债务未宣称通过 |
| Desktop `npm test -- --reporter=dot` | 224文件通过、1文件跳过；1914通过、2跳过 | 包含插件JS、service/broker生命周期；不等于实际Electron UI |
| Desktop `npm run build`、`npm run typecheck` | 通过 | 构建包含主进程与preload，插件行为另由运行测试覆盖 |
| Alembic head | 唯一`f062_dsh_audit_tree` | 新完整标题表经模型发现建表，不改既有审计大表、无历史数据迁移 |

## 代码及任务自审

依照task-review及code-review检查边界、认证/租户、并发、泄露、测试、风格、设计同步：未发现剩余high/medium。模式先有界读取，再锁租户模式行；绑定已有本人请求；新标题表按事件序号比较；保存确认在事务提交后。读侧一次批量主键IN，不对大表GROUP/LIKE，不重建树。标题或SQL错误不进入模型调用链。

修正的候选设计偏差：Gateway通用转发已覆盖新路径，两个旧模型过滤规则均不匹配，不需要新增DshRoutes分类；服务端暂不可用复用标准26128/HTTP500，客户端按5xx重试。标题元数据可能敏感，已按D-10允许METADATA；不开新的正文采集或密钥依赖。移除无其他调用方的父导航组件及其测试，保留来源文本；旧服务端父查询API保留兼容既有客户端。

任务检查：表及租户注册、输入/仓储/Service/Endpoint、可选能力、批量查询、Desktop插件/契约/主进程、Platform展示/删除入口均已完成；双端提交、CI、109部署和实际客户端操作仍需分别留证。

## 发布与实际客户端验收

- [x] 双端审计分支提交推送并核对远端SHA。
- [x] Drone核对本次BiSheng提交，后端/前端镜像构建发布成功。
- [x] 109:13001替换对应tag镜像，保留回滚镜像，核对健康、新表及唯一迁移头。
- [x] 实际客户端使用企业模型创建隔离测试会话，标题已落SQL，改名后的最新标题在审计节点显示。
- [x] 最后一次请求完成后仅改名，不再调用模型；管理刷新见新标题、原编号及请求数不变。
- [x] 普通及真实子Agent请求的两个导航按钮均不存在，来源标签/父子展开/请求详情/原文读取仍正常。

### 精确交付证据

- BiSheng功能提交：`a3a9216c1ff6a1025e395222a90998cc7c056b3c`；Desktop：`73961535622bee347ab4044f2e9ec14d255fbc17`。均推送至各自`feat/3.0.0-dsh-audit`并用ls-remote核对。
- [Drone #5434](http://110.16.193.170:50059/dataelement/bisheng/5434)对应上述BiSheng提交，状态success；后端、前端和sandbox构建步骤均success，用时4分38秒。
- 109项目`dsh-bisheng`仅更新backend/backend_worker/frontend，API healthy、Worker inspect ping返回pong、前端nginx -t通过；公开13001的config含标题能力，未带DSH凭据的标题请求按标准返回401。
- 后端与Worker镜像ID：`sha256:dfda7555b2913752d5e3be0e5500a47c483c5c4454baf1b4f359f9e395ad4fb7`，仓库digest：`sha256:a7d0890666f295de94dd02f5546460b9d0389842e4a51900da30ed83d7167601`。
- 前端镜像ID：`sha256:56abf40393a2e3d1eb951187ef1e7ccd6ae18dd3b8c92a4281cdc468484fcf63`，仓库digest：`sha256:137903d5259834a2f4a8da9efc883690bcd1fb69f04f98e08af08e9b2c6ec6f9`。tag均为`feat_3.0.0-dsh-audit`。
- 两个镜像仓库均保存`audit-rollback-20261020-a3a9216c1-before`。未修改Gateway、Nginx挂载配置、密钥、数据卷或历史审计。标题新表已自动创建，utf8mb4；数据库迁移头仍唯一`f062_dsh_audit_tree`，租户1模式保持CONTENT。

### 原生客户端操作与回读

使用本机bisheng-work实际开发客户端，正常恢复已有dshadmin企业连接；在新会话发送仅要求回复“验收通过”、禁止工具/文件读取的隔离消息。客户端成功回复，服务端标题记录为客户端接受的`审计标题联调 e2e-audit-title-20261`，事件序号14。

随后仅通过原生会话菜单改名为`e2e-audit-title-20261020-改名验证`。服务端同一条标题事实更新为事件序号19；对应审计请求仍只有1条，SUCCEEDED/COMPLETED/SETTLED/COMPLETE、统一NORMAL。会话编号始终为`session-9b1eede8-c565-40cd-9e74-24236653c995`，请求编号`4d75d1ef-6bee-42ff-97fc-daa0916a17f3`。本次无新增标题生成模型调用、无模型重放。

109实际管理页刷新后显示`dshadmin · e2e-audit-title-20261020-改名验证`；请求详情仍有原编号，显式查看原文可解密并渲染独立回复“验收通过”。普通会话来源标签保留；另只读展开已有父/子会话元数据，确认子Agent来源标签可见、“查看本用户会话”“查看父会话”按钮数均为0，没有读取其他历史原文。新会话首次显示曾等待目录快照收敛，Worker正常prepare/READY后出现；未手工改写投影或历史数据。

原生自动化初始出现截图/输入状态不同步，仅为本次开发实例加`--disable-gpu --force-renderer-accessibility`重启后恢复，未修改源码或持久启动配置。把本机会话令牌转到Chrome的备选操作被安全策略拒绝，未执行或重试；最终发送与改名均在原生客户端完成，Chrome只访问109正常登录的管理页。未保存或发布任何凭据/令牌。

尚未验收：DM8真库、Windows实际运行、跨设备复用会话ID、高并发容量和长会话耗时。不将SQLite/编译结果冒充双库或全平台运行。109不回填旧标题、不改写历史审计状态、不修改其他用户会话。
