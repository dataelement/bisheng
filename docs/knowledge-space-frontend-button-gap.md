# 知识空间前端按钮缺口整理

## 1. 目的

本文档用于整理知识空间模块中：

- 文档已声明或后端已支持
- 但前端页面尚未提供按钮/菜单入口

的功能缺口，供前端开发直接落地。

本次结论基于三类信息对比：

- 产品/技术文档：`docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
- 后端接口与服务：`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`、`src/backend/bisheng/permission/api/endpoints/resource_permission.py`
- 前端页面与组件：`src/frontend/client/src/pages/knowledge/**`

## 2. 本次排查范围

仅覆盖知识空间前端主流程：

- 侧边栏
- 空间详情页
- 文件/文件夹卡片与表格
- 知识广场
- 空间预览抽屉
- 文件预览页

不覆盖：

- 非知识空间模块的复用能力
- 纯后端权限模型设计本身
- 文案缺失、样式问题、交互细节优化

## 3. 当前前端已存在的按钮入口

以下能力前端已经有明确按钮或菜单入口，不属于“缺按钮”：

### 3.1 侧边栏

- 创建知识空间  
  位置：`src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx`
- 去知识广场  
  位置：`src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx`
- 空间设置  
  位置：`src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`
- 成员管理  
  位置：`src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`
- 置顶 / 取消置顶  
  位置：`src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`
- 删除空间 / 退出空间  
  位置：`src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`

### 3.2 空间详情页

- AI 助手
- 分享
- 批量下载
- 批量加标签
- 批量重试
- 批量删除
- 新建文件夹
- 上传文件

位置：`src/frontend/client/src/pages/knowledge/SpaceDetail/KnowledgeSpaceHeader.tsx`

### 3.3 文件/文件夹

- 下载
- 编辑标签
- 重命名
- 删除
- 重试

位置：

- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileCard.tsx`
- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`

### 3.4 文件预览页

- 下载
- AI 助手

位置：`src/frontend/client/src/pages/knowledge/FilePreview/FilePreviewPage.tsx`

## 4. 确认缺失的按钮

以下为本次确认的“前端缺按钮/缺入口”的功能。

### 4.1 空间权限管理按钮

#### 结论

缺。

#### 文档依据

知识空间 `owner` / `can_manage` 均应具备“管理空间权限”能力。

来源：

- `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` 第 249 行
- `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` 第 256 行

#### 后端依据

后端已有通用资源权限接口，且资源类型支持 `knowledge_space`：

- `POST /api/v1/permissions/resources/{resource_type}/{resource_id}/authorize`
- `GET /api/v1/permissions/resources/{resource_type}/{resource_id}/permissions`

来源：

- `src/backend/bisheng/permission/api/endpoints/resource_permission.py`
- `src/backend/bisheng/permission/domain/schemas/permission_schema.py`

#### 当前前端现状

知识空间当前只有：

- 空间设置
- 成员管理
- 置顶
- 删除 / 退出

没有“权限管理”入口。

涉及文件：

- `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`
- `src/frontend/client/src/pages/knowledge/CreateKnowledgeSpaceDrawer.tsx`
- `src/frontend/client/src/pages/knowledge/SpaceDetail/KnowledgeSpaceHeader.tsx`

#### 建议落点

优先级最高，建议二选一或同时支持：

- 侧边栏空间项菜单新增 `权限管理`
- 空间设置抽屉内新增 `权限管理` 入口

### 4.2 文件夹权限管理按钮

#### 结论

缺。

#### 文档依据

文档明确要求知识空间支持“管理文件夹及文件级权限”。

来源：

- `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` 第 249 行
- `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` 第 256 行
- `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` 第 963 行

#### 后端依据

后端权限资源类型支持 `folder`，可直接走通用权限接口。

来源：

- `src/backend/bisheng/permission/domain/schemas/permission_schema.py`

#### 当前前端现状

文件夹当前菜单只有：

- 下载
- 重命名
- 删除
- 重试

没有“权限管理”入口。

涉及文件：

- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileCard.tsx`
- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`

#### 建议落点

在文件夹卡片/表格的更多菜单中新增：

- `权限管理`

### 4.3 文件权限管理按钮

#### 结论

缺。

#### 文档依据

同样属于“管理文件夹及文件级权限”范围。

来源：

- `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` 第 249 行
- `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` 第 256 行

#### 后端依据

后端权限资源类型支持 `knowledge_file`，可直接走通用权限接口。

来源：

- `src/backend/bisheng/permission/domain/schemas/permission_schema.py`

#### 当前前端现状

文件菜单当前只有：

- 下载
- 编辑标签
- 重命名
- 删除
- 重试

没有“权限管理”入口。

涉及文件：

- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileCard.tsx`
- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`

#### 建议落点

在文件卡片/表格的更多菜单中新增：

- `权限管理`

### 4.4 删除空间标签 / 标签池管理按钮

#### 结论

缺。

#### 后端依据

后端已支持删除空间标签：

- `DELETE /api/v1/knowledge/space/{space_id}/tag`

服务层已有：

- `delete_space_tag`

来源：

- `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`
- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`

#### 当前前端现状

标签弹窗仅支持：

- 拉取空间标签
- 新建标签
- 给单文件覆盖标签
- 给多文件批量加标签

前端没有：

- 删除已有空间标签按钮
- 独立的空间标签管理入口

涉及文件：

- `src/frontend/client/src/pages/knowledge/SpaceDetail/EditTagsModal.tsx`
- `src/frontend/client/src/api/knowledge.ts`

#### 建议落点

建议两种实现方式选其一：

- 在 `EditTagsModal` 的“已有标签”区域给每个标签增加删除操作
- 在空间设置中增加“标签管理”子面板

### 4.5 知识广场 / 空间预览里的撤回申请或取消加入按钮

#### 结论

缺。

#### 后端依据

前端已接入退出空间接口：

- `unsubscribeSpaceApi`

侧边栏已加入空间也能正常退出。

来源：

- `src/frontend/client/src/api/knowledge.ts`
- `src/frontend/client/src/pages/knowledge/hooks/useSpaceActions.ts`

#### 当前前端现状

在以下两个入口中：

- 知识广场卡片
- 空间预览抽屉

状态为：

- `joined`
- `pending`
- `rejected`

时按钮都直接禁用，无法继续操作。

涉及文件：

- `src/frontend/client/src/pages/knowledge/KnowledgeSquareCard.tsx`
- `src/frontend/client/src/pages/knowledge/KnowledgeSpacePreviewDrawer.tsx`

#### 建议落点

建议补充以下按钮逻辑：

- `joined` -> `退出空间`
- `pending` -> `撤回申请`
- `rejected` -> `重新申请`

备注：

`重新申请` 当前前端已有后端能力基础，因为 `subscribe_space` 对 `REJECTED` 状态会重新走申请逻辑；真正缺的是按钮入口。

### 4.6 高级重试 / 重新解析按钮

#### 结论

缺，但优先级低于前几项。

#### 后端依据

除当前前端已接的 `batch-retry` 外，后端还支持：

- `POST /api/v1/knowledge/space/{space_id}/files/retry`

接口注释说明为“带新的切分规则重试”。

来源：

- `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`

#### 当前前端现状

当前前端“重试”统一走：

- 单个重试 -> `batchRetryApi`
- 批量重试 -> `batchRetryApi`

涉及文件：

- `src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx`

因此当前只有普通重试，没有：

- 高级重试
- 重新解析参数设置
- 重试时修改切分规则

#### 建议落点

可后置为增强项，在失败文件菜单中增加：

- `重新解析`
- `高级重试`

## 5. 不应误判为缺按钮的能力

以下能力虽然容易被提及，但本次不归类为“缺按钮”：

### 5.1 单文件 AI 问答

文件预览页已经支持单文件聊天能力，不属于缺按钮：

- `FilePreviewPage` 已通过 `fileChat` 将 `spaceId + fileId` 传入 AI 面板
- `useFileChat` 已接入单文件聊天 SSE、历史记录、清空历史

涉及文件：

- `src/frontend/client/src/pages/knowledge/FilePreview/FilePreviewPage.tsx`
- `src/frontend/client/src/hooks/useFileChat.ts`

### 5.2 退出空间

侧边栏“已加入空间”已有退出入口，不属于完全缺失，只是广场和预览抽屉未提供同类入口。

## 6. 建议开发优先级

### P0

- 空间权限管理按钮
- 文件夹权限管理按钮
- 文件权限管理按钮

### P1

- 删除空间标签 / 标签池管理
- 广场 / 预览里的撤回申请、取消加入

### P2

- 高级重试 / 重新解析

## 7. 推荐前端落点图

### 7.1 侧边栏空间菜单

文件：`src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`

建议新增：

- `权限管理`

### 7.2 空间设置抽屉

文件：`src/frontend/client/src/pages/knowledge/CreateKnowledgeSpaceDrawer.tsx`

建议新增：

- `标签管理`
- `权限管理`

### 7.3 文件/文件夹更多菜单

文件：

- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileCard.tsx`
- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`

建议新增：

- 文件夹：`权限管理`
- 文件：`权限管理`
- 文件：`高级重试`（可后置）

### 7.4 知识广场和空间预览

文件：

- `src/frontend/client/src/pages/knowledge/KnowledgeSquareCard.tsx`
- `src/frontend/client/src/pages/knowledge/KnowledgeSpacePreviewDrawer.tsx`

建议新增：

- `退出空间`
- `撤回申请`
- `重新申请`

## 8. 最终结论

如果只做一轮最小可用补齐，建议先补四个按钮入口：

1. 空间权限管理
2. 文件夹权限管理
3. 文件权限管理
4. 标签删除 / 标签管理

这四项最符合当前文档与后端能力，也最容易在现有页面结构上直接落地。
