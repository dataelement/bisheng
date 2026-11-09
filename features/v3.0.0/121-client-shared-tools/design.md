# 实现说明

## 范围与决策

Small feature：前端增加既有功能的入口，不改变 API、持久化形态或执行链路。沿用当前客户端配置所属分支 `v3.0.0-fix-dsh`，本次不提交、不合并，保留工作区其他改动。

- `SharedToolSettings` 位于 `WorkbenchModel` 的“其他模型配置”末尾。
- 使用通用“搜索工具”“绘图工具”标签；复用 `WebSearchForm`、`Dalle3ToolForm`，避免字段与校验分叉。更换绘图实现时替换此绑定，不将 Dalle3 写入入口文案。
- 通过子工具稳定标识 `web_search` / `dalle_image_generator` 查找工具分类，不依赖分类的中文显示名。标识改变时需重新评估绑定。
- 每次打开请求既有 `getToolsApi('default', { action: 'visible' })`，以分类 ID 调用 `updateToolApi`；直接写平台配置，不写模型配置副本。不跨入口缓存配置，以免打开后显示过期值。
- 配置单独保存并明确提示共用影响范围。保存期间通过 ref 锁与禁用 fieldset 阻止重复提交及关闭，失败保留表单。
- 仅 `is_global_super` 显示入口并允许触发请求，后端既有 `update_tool_config` 的超管检查保留。架构约束引用 `docs/constitution.md`。

## 数据流与边界

打开入口 → GET `/api/v1/tool?is_preset=1&action=visible` → 精确匹配唯一分类 → 校验并解析 extra → 已有工具表单 → POST `/api/v1/tool/config`（tool_id、extra）→ 成功后关闭。

密钥掩码沿用工具列表响应和 `JsonFieldMasker.update_json_with_masked`，不增加密钥打印。移除 Dalle3 表单既有密钥调试日志，使用 `lint:prune` 自动删除对应 no-console 豁免。

缺失、重复、无效 JSON 均报错；JSON 解析错误转换成通用本地化提示，避免错误消息回显配置内容。

## 已知限制与验收

- 两个入口沿用原有工具配置的最后一次保存生效规则，不新增乐观锁。
- 复用表单存在原有 DialogClose 嵌套 button 的 React 警告；本次自动化交互可正常完成，未改动共享表单结构。
- 本机未运行前后端服务，未执行真实登录及持久化联动验证。见 `e2e-checklist.md`。

## 修订记录

2026-11-09：根据用户确认的“修改后平台也生效”，采用现有平台工具配置的双入口方案。
