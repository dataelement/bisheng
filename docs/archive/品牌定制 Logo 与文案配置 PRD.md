# 品牌定制 Logo 与文案配置 PRD

## 1. 背景

BiSheng 需要在管理后台提供可视化的品牌定制能力，让系统管理员在不重新打包前端代码的情况下，配置系统品牌名称、管理后台与登录页 Logo、浏览器标签图标以及 Loading 图标/动画。

同时，既有“系统品牌白标化定制手册”仍然保留：部署前仍可通过替换 `/assets/bisheng/` 下的默认素材和修改 `config.js` 完成基础白标化。本功能是在系统部署后提供可视化配置，不替代部署前静态替换方案。

## 2. 产品目标

1. 管理员可在系统配置中进入品牌定制页面，完成品牌名称和视觉素材配置。
2. 配置保存后，通过运行时脚本下发到管理后台和工作台，避免重新构建前端包。
3. Logo 素材支持默认素材和用户上传素材两类来源。
4. 上传素材按用途分类存储和选择，下拉选项展示图片预览与文件名。
5. 支持删除非默认上传素材；如果删除的是正在使用的素材，自动回退到对应默认素材。
6. 每个可配置项都提供独立预览按钮，预览区展示对应系统界面并高亮生效位置。
7. 保持工作台“构建 → 日常”已有图标配置逻辑不被品牌定制覆盖。

## 3. 非目标与边界

1. 不提供“品牌包”能力，不读取 `brand-default.json`。
2. 不在品牌定制页面配置 `linsightAgentName`。该字段仍按系统品牌白标化定制手册，通过 `config.js` 控制。
3. 不在品牌定制页面配置工作台左上角图标、欢迎页面图标、对话头像、欢迎语、输入框提示语等工作台日常配置；这些仍由“构建 → 日常”维护。
4. 不提供图片裁剪、压缩、在线设计、颜色提取等素材编辑能力。
5. 不支持按租户、部门、用户分别配置品牌；当前品牌定制为实例级配置。
6. 不替代主题配色能力；主题配色和品牌定制只是同属于“外观设置”下的两个子选项卡。

## 4. 入口与信息架构

入口：

`系统 → 外观设置 → 品牌定制`

外观设置下包含两个子选项卡：

| 子选项卡 | 说明 |
| --- | --- |
| 主题配色 | 原有颜色配置与组件预览能力 |
| 品牌定制 | 新增品牌文案、Logo、Loading 配置能力 |

品牌定制页面分为四个区域：

1. 文案配置
2. Logo 素材
3. Loading 配置
4. 预览

## 5. 角色与权限

| 角色 | 权限 |
| --- | --- |
| 管理员 | 可查看、上传、删除、保存、重置品牌配置 |
| 普通用户 | 不可进入品牌定制页面，但可看到已生效的品牌展示 |
| 未登录用户 | 可在登录页加载公开运行时品牌配置 |

后端配置接口需要管理员鉴权；运行时脚本 `/api/v1/brand/runtime.js` 为公开读取接口，用于页面初始化前加载品牌配置。

## 6. 功能说明

### 6.1 文案配置

当前品牌定制页面仅配置一个文案项：

| 配置项 | 字段 | 中文列 | 英文列 | 说明 |
| --- | --- | --- | --- | --- |
| 系统品牌名称 | `brandName` | 支持 | 支持 | 用于浏览器标题，以及系统中通过品牌名称变量展示的文案 |

规则：

1. 中文、英文分别存储。
2. 单字段最长 20 个字符。
3. 不允许输入 `<`、`>`，避免 HTML 注入。
4. 展示时根据当前语言取值：
   - 中文环境优先取 `zh`，为空时回退 `en`。
   - 非中文环境优先取 `en`，为空时回退 `zh`。
5. 品牌定制保存接口不接收、不保存、不下发 `linsightAgentName`。
6. `linsightAgentName` 继续通过部署目录的 `config.js` 配置，保证原系统品牌白标化定制手册方案不受影响。

### 6.2 Logo 素材配置

品牌定制负责以下 Logo/图片配置：

| 配置项 | 字段 | 默认素材 | 建议规格 | 生效位置 |
| --- | --- | --- | --- | --- |
| 浏览器标签图标 | `assets.favicon` | `/assets/bisheng/favicon.ico` | 32 x 32，建议 ico | 管理后台浏览器标签；工作台初始运行时也会加载，之后可能被“构建 → 日常”的对话头像配置覆盖 |
| 登录页左侧大图 | `assets.loginHeroLight` | `/assets/bisheng/login-logo-big.png` | 420 x 704 | 管理后台登录页浅色模式左侧大图 |
| 登录页左侧大图（暗黑） | `assets.loginHeroDark` | `/assets/bisheng/login-logo-dark.png` | 420 x 704 | 管理后台登录页暗黑模式左侧大图 |
| 表单与顶部 Logo | `assets.headerLogoLight` | `/assets/bisheng/login-logo-small.png` | 410 x 120 | 管理后台左上角 Logo、登录页顶部 Logo（浅色） |
| 表单与顶部 Logo（暗黑） | `assets.headerLogoDark` | `/assets/bisheng/logo-small-dark.png` | 410 x 120 | 管理后台左上角 Logo、登录页顶部 Logo（暗黑） |

不由品牌定制负责的工作台图标：

| 工作台图标 | 配置入口 |
| --- | --- |
| 工作台左上角图标 | 构建 → 日常 → 左侧边栏图标 |
| 欢迎页面图标与对话头像 | 构建 → 日常 → 欢迎页面图标 & 对话头像 |
| 工作台最终 favicon | 优先跟随“欢迎页面图标 & 对话头像” |

### 6.3 素材上传、选择与删除

上传规则：

1. 支持格式：`ico`、`png`、`jpg`、`jpeg`、`svg`、`gif`、`webp`。
2. 单文件不超过 5MB。
3. SVG 不允许包含 `<script>`、`javascript:`、事件处理器等风险内容。
4. 上传时按配置项分类存储到对象存储。
5. 存储对象名格式：`brand-assets/{category}/{uuid}_{原始文件名}`。
6. 页面展示文件名时隐藏对象存储路径，只展示用户上传时选择的原始文件名。

分类目录：

| 配置项 | category | 对象存储前缀 |
| --- | --- | --- |
| 浏览器标签图标 | `favicon` | `brand-assets/favicon/` |
| 登录页左侧大图 | `loginHeroLight` | `brand-assets/login-hero-light/` |
| 登录页左侧大图（暗黑） | `loginHeroDark` | `brand-assets/login-hero-dark/` |
| 表单与顶部 Logo | `headerLogoLight` | `brand-assets/header-logo-light/` |
| 表单与顶部 Logo（暗黑） | `headerLogoDark` | `brand-assets/header-logo-dark/` |
| Loading 图标 | `loadingIcon` | `brand-assets/loading-icon/` |

选择规则：

1. 每个配置项的下拉框固定包含一个默认素材选项。
2. 下拉选项展示图片预览、文件名、默认标识。
3. 非默认素材右侧展示删除按钮。
4. 默认素材不可删除。
5. 删除当前正在使用的素材后，该配置项自动切换为对应默认素材。

### 6.4 Loading 配置

| 配置项 | 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| Loading 图标 | `loading.icon` / `URLLoadingIcon` | 空，使用系统内置蓝色横线 Loading | 用于系统 Loading 组件 |
| Loading 动画 | `loading.animation` | 空 | 支持无动画、旋转、脉冲、弹跳 |

Loading 图标来源：

1. 内置默认 Loading：未配置图片时使用系统内置蓝色横线 Loading。
2. 上传素材：上传到 `brand-assets/loading-icon/` 后可在下拉框选择。
3. URL 素材：Loading 图标支持粘贴 URL；Logo 素材不支持 URL 输入。

URL 规则：

1. 不允许包含空格、`<`、`>`。
2. 仅支持以 `http://` 或 `https://` 开头的完整 URL，例如 `https://example.com/loading.svg`。
3. URL 可用性由用户自行保证，系统不校验远程文件长期有效性。

### 6.5 预览

预览区默认展示空白占位图。用户点击任一配置项右侧的“预览”按钮后，预览区展示对应系统界面，并用明显蓝色描边与外扩高亮标识该配置项影响的位置。

预览规则：

1. 系统品牌名称：展示登录页/浏览器框架预览，并高亮浏览器标题与页面品牌文案位置。
2. 浏览器标签图标：展示浏览器框架预览，并高亮标签图标。
3. 登录页左侧大图：展示登录页完整结构，并高亮左侧大图。
4. 表单与顶部 Logo：展示登录页或管理后台结构，并高亮 Logo。
5. Loading 图标/动画：展示加载场景，并高亮 Loading 图标。
6. 与当前配置项无关的内容可用色块或模糊骨架表示。
7. 预览使用当前表单值，无需保存即可预览。

### 6.6 保存

点击保存后：

1. 前端将品牌定制可编辑字段提交到后端。
2. 后端合并默认值并持久化到实例级配置项 `brand_config`。
3. 保存成功后，当前管理后台页面即时更新 `window.BRAND_CONFIG`、浏览器标题和 favicon。
4. 登录页、管理后台主框架 Logo、工作台启动配置在刷新或重新进入页面后读取最新运行时配置。
5. 保存成功展示成功提示；失败时按统一请求错误提示展示。

保存接口不保存 `linsightAgentName`，避免覆盖部署前 `config.js` 中的手册配置。

### 6.7 重置默认

点击“重置默认”后：

1. 页面表单恢复为系统默认品牌名称、默认 Logo、默认 Loading 配置。
2. 用户仍需点击保存才会写入后端。
3. 保存后默认素材路径保持为 `/assets/bisheng/...`，继续兼容部署前静态替换方案。

## 7. 生效机制

### 7.1 静态默认配置

管理后台和工作台入口 HTML 都会先加载静态配置：

`/assets/bisheng/config.js`

该文件用于部署前白标化，典型结构如下：

```javascript
window.BRAND_CONFIG = {
    brandName: {
        zh: "BISHENG",
        en: "BISHENG"
    },
    linsightAgentName: {
        zh: "灵思",
        en: "Linsight"
    },
    URLLoadingIcon: "",
    loadingIcon: "",
    loadingAnimation: ""
};
```

部署前白标化仍按原手册操作：

1. 替换部署目录 `/assets/bisheng/` 下的默认图片文件。
2. 修改 `config.js` 中的 `brandName`、`linsightAgentName`、`URLLoadingIcon` 等字段。
3. 保持默认文件名不变：
   - `favicon.ico`
   - `login-logo-big.png`
   - `login-logo-dark.png`
   - `login-logo-small.png`
   - `logo-small-dark.png`
   - 可选 `loading.svg`，并在 `config.js` 中配置 Loading 路径。

### 7.2 运行时配置

静态 `config.js` 加载后，页面继续加载：

`/api/v1/brand/runtime.js`

运行时脚本负责：

1. 读取后端持久化的品牌定制配置。
2. 与已有 `window.BRAND_CONFIG` 合并。
3. 更新 `brandName`、Logo assets、Loading 配置。
4. 不下发 `linsightAgentName`，避免覆盖 `config.js` 手册配置。
5. 设置 `document.title`。
6. 设置 favicon。
7. 对相对资源路径按当前应用 base path 归一化。
8. 响应头设置 `Cache-Control: no-store`，避免保存后刷新仍读旧配置。

加载顺序：

1. `config.js`
2. `runtime.js`
3. 前端应用初始化

### 7.3 本地与部署环境

正式部署中，管理后台和工作台可在同一个域名与端口下运行，例如：

`http://host:3002/sys`

`http://host:3002/workspace/c/new`

本地开发中，管理后台和工作台可能分别运行在不同端口，例如：

`http://127.0.0.1:3001/sys`

`http://127.0.0.1:4001/workspace/c/new`

要求：

1. 工作台应通过注入的后端/平台 base URL 加载 `config.js` 与 `runtime.js`。
2. 管理后台保存品牌配置后，工作台刷新或重新进入时应读取同一份后端品牌配置。
3. 同域部署和本地分端口部署都应正常工作。

## 8. 数据模型

### 8.1 后端持久化数据

后端配置项 key：

`brand_config`

持久化 JSON 示例：

```json
{
  "brandName": {
    "zh": "毕昇",
    "en": "BISHENG"
  },
  "assets": {
    "favicon": {
      "url": "/assets/bisheng/favicon.ico",
      "relative_path": "",
      "file_name": ""
    },
    "loginHeroLight": {
      "url": "/assets/bisheng/login-logo-big.png",
      "relative_path": "",
      "file_name": ""
    },
    "loginHeroDark": {
      "url": "/assets/bisheng/login-logo-dark.png",
      "relative_path": "",
      "file_name": ""
    },
    "headerLogoLight": {
      "url": "/assets/bisheng/login-logo-small.png",
      "relative_path": "",
      "file_name": ""
    },
    "headerLogoDark": {
      "url": "/assets/bisheng/logo-small-dark.png",
      "relative_path": "",
      "file_name": ""
    }
  },
  "loading": {
    "icon": null,
    "iconOptions": [],
    "animation": ""
  },
  "URLLoadingIcon": ""
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `brandName` | 品牌定制页面唯一可配置文案 |
| `assets.*.url` | 当前可访问 URL；默认素材为站内路径，上传素材保存运行时生成的访问 URL |
| `assets.*.relative_path` | 上传到对象存储后的对象路径；默认素材为空 |
| `assets.*.file_name` | 上传时的原始文件名，用于 UI 展示 |
| `loading.icon` | 当前选择的 Loading 图标 |
| `loading.iconOptions` | 用户粘贴 URL 后形成的可选项 |
| `loading.animation` | Loading 动画类名 |
| `URLLoadingIcon` | 兼容历史 Loading 字段 |

### 8.2 兼容字段

`BrandConfig` 模型仍保留 `linsightAgentName`，用于兼容已有前端 i18n 和静态 `config.js`。但品牌定制保存模型 `BrandConfigUpdate` 不包含该字段，runtime payload 也会移除该字段。

## 9. API 设计

### 9.1 获取品牌配置

`GET /api/v1/brand/config`

权限：管理员。

返回：合并默认值后的品牌配置。

### 9.2 保存品牌配置

`PUT /api/v1/brand/config`

权限：管理员。

请求体：`BrandConfigUpdate`，包含 `brandName`、`assets`、`loading`、`URLLoadingIcon`。

说明：请求体不包含 `linsightAgentName`。

返回：保存后的品牌配置。

### 9.3 获取素材选项

`GET /api/v1/brand/assets/options?category={category}`

权限：管理员。

支持 `category`：

1. `favicon`
2. `loginHeroLight`
3. `loginHeroDark`
4. `headerLogoLight`
5. `headerLogoDark`
6. `loadingIcon`

返回：默认素材 + 对应分类目录下已上传素材列表。

### 9.4 上传素材

`POST /api/v1/brand/assets`

权限：管理员。

请求：`multipart/form-data`

| 字段 | 说明 |
| --- | --- |
| `file` | 上传文件 |
| `category` | 素材分类 |

返回：素材 URL、对象存储路径、原始文件名。

### 9.5 删除素材

`DELETE /api/v1/brand/assets?category={category}&relative_path={relative_path}`

权限：管理员。

规则：

1. 只能删除对应分类目录下的上传素材。
2. 不允许删除默认素材。
3. 删除后如果该素材正在被配置使用，则后端配置自动回退到默认素材。

返回：该分类默认素材。

### 9.6 运行时脚本

`GET /api/v1/brand/runtime.js`

权限：公开。

返回：JavaScript 脚本。

作用：

1. 将品牌配置写入 `window.BRAND_CONFIG`。
2. 更新 `document.title`。
3. 更新 favicon。
4. 归一化相对资源路径。
5. 保留 `config.js` 中的 `linsightAgentName`。

## 10. 前端集成要求

### 10.1 管理后台

1. `index.html` 按顺序加载 `/assets/bisheng/config.js` 与 `/api/v1/brand/runtime.js`。
2. 登录页左侧大图使用 `loginHeroLight/loginHeroDark`。
3. 登录页顶部 Logo 使用 `headerLogoLight/headerLogoDark`。
4. 管理后台主框架左上角 Logo 使用 `headerLogoLight/headerLogoDark`。
5. 浏览器标题与 favicon 由运行时配置控制。
6. 保存成功后当前页面即时更新标题与 favicon；其他 Logo 位置刷新后生效。

### 10.2 工作台

1. `index.html` 按顺序加载 `config.js` 与 `runtime.js`。
2. 系统品牌名称可影响工作台初始化阶段的浏览器标题及 i18n 品牌变量。
3. runtime 会设置工作台初始 favicon。
4. 工作台加载“构建 → 日常”配置后，如果存在 `assistantIcon.image`，工作台 favicon 会被该配置覆盖。
5. 工作台左侧边栏图标、欢迎页面图标、对话头像继续由“构建 → 日常”配置，不由品牌定制接管。

## 11. 部署前白标化操作说明

适用于客户在系统部署前就希望默认展示客户品牌的场景。

操作步骤：

1. 在部署产物的 `/assets/bisheng/` 目录准备默认素材。
2. 使用客户素材替换以下文件，文件名保持不变：
   - `favicon.ico`
   - `login-logo-big.png`
   - `login-logo-dark.png`
   - `login-logo-small.png`
   - `logo-small-dark.png`
3. 如需默认 Loading 图标，放置 `loading.svg` 或其他图片，并在 `config.js` 中配置：
   - `URLLoadingIcon: "/assets/bisheng/loading.svg"`
   - `loadingIcon: "/assets/bisheng/loading.svg"`
   - `loadingAnimation` 按需配置。
4. 修改 `config.js`：
   - `brandName`：系统品牌名称。
   - `linsightAgentName`：智能体功能名。
5. 启动系统后，默认素材和默认文案即为客户品牌。
6. 系统部署后，管理员仍可在“系统 → 外观设置 → 品牌定制”中上传新素材或修改系统品牌名称。

注意：

1. 如果部署前只替换图片、不修改 `config.js`，文案仍使用默认文案。
2. 如果部署后在品牌定制中保存了配置，后端 `brand_config` 会覆盖同名 Logo 与 `brandName` 默认值。
3. `linsightAgentName` 不会被品牌定制覆盖，仍以 `config.js` 为准。

## 12. 验收标准

### 12.1 页面入口与布局

1. 系统配置中原“主题配色”入口调整为“外观设置”。
2. 外观设置下存在“主题配色”和“品牌定制”两个子选项卡。
3. 品牌定制页面展示文案配置、Logo 素材、Loading 配置、预览区。
4. 文案配置中仅展示“系统品牌名称”，不展示“智能体功能名”。

### 12.2 文案

1. 修改系统品牌名称中文/英文并保存后，浏览器标题按当前语言取对应字段。
2. 中文环境优先显示中文，英文或非中文环境优先显示英文。
3. 任一语言为空时，可回退到另一语言。
4. 输入 `<` 或 `>` 时后端拒绝保存。
5. 品牌定制保存后不影响 `config.js` 中的 `linsightAgentName`。

### 12.3 Logo 素材

1. 每个 Logo 配置项下拉框都展示默认素材。
2. 上传素材后，下拉框展示图片预览和原始文件名，不展示对象存储路径。
3. 选择上传素材并保存后，刷新对应页面可看到新素材。
4. 非默认上传素材可删除。
5. 删除正在使用的素材后，该配置项自动回退默认素材。
6. 默认素材不可删除。

### 12.4 Loading

1. 未配置 Loading 图标时，使用系统内置蓝色横线 Loading。
2. 上传 Loading 图标并保存后，系统 Loading 组件使用新图标。
3. 粘贴合法 URL 后，可选择该 URL 作为 Loading 图标。
4. 选择旋转、脉冲、弹跳动画后，预览区立即展示对应动画。
5. 保存后刷新页面，Loading 动画配置继续生效。

### 12.5 预览

1. 未点击预览按钮时，预览区展示空白占位图。
2. 点击配置项预览按钮后，预览区展示对应系统界面。
3. 预览区高亮框足够明显，不被文案遮挡。
4. 预览使用当前表单值，不要求先保存。
5. 与当前配置项无关的内容可使用骨架或色块表示。

### 12.6 运行时与兼容

1. `/api/v1/brand/runtime.js` 返回 JavaScript，且响应不缓存。
2. 管理后台和工作台均能加载 runtime。
3. 本地 3001 管理后台保存配置后，4001 工作台刷新可读取同一份配置。
4. 同域部署时，管理后台和工作台也能读取同一份配置。
5. runtime 不覆盖 `config.js` 中的 `linsightAgentName`。
6. 默认 `/assets/bisheng/...` 静态替换方案仍可用。

## 13. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 品牌定制与工作台日常配置边界混淆 | PRD 和 UI 文案明确：工作台侧栏图标、欢迎图标、对话头像归“构建 → 日常” |
| 删除素材导致页面裂图 | 删除当前使用素材时自动回退默认素材 |
| 对象存储 URL 临时签名过期 | 持久化 `relative_path`，读取配置和 runtime 时重新生成可访问 URL |
| 本地分端口导致工作台读不到配置 | 工作台通过注入 base URL 加载 `config.js` 和 `runtime.js` |
| runtime 覆盖部署前手册配置 | runtime 不下发 `linsightAgentName`，仅覆盖品牌定制负责的字段 |
| SVG 安全风险 | 上传时拒绝脚本、事件处理器和 `javascript:` 风险内容 |

## 14. 发布与回滚

发布要求：

1. 后端注册 `/api/v1/brand/*` 路由。
2. 管理后台和工作台入口 HTML 加载 `config.js` 与 `runtime.js`。
3. 管理后台和工作台都包含 `/assets/bisheng/` 默认静态素材。
4. MinIO/public bucket 与文件访问代理在本地和部署环境均可访问。

回滚策略：

1. 前端可回退到仅使用静态 `config.js` 与默认素材。
2. 后端保留已有 `brand_config`，不主动删除。
3. 如需清空运行时配置，可删除或重置 `brand_config`，系统回退到默认 `/assets/bisheng/...` 素材。

## 15. 待后续确认

1. 是否需要在品牌定制中增加“清空后端配置并完全回到部署前手册默认值”的操作。
2. 是否需要增加素材尺寸校验或上传后尺寸提示。
3. 是否需要记录品牌配置保存、上传、删除操作日志。
4. 是否需要未来按租户支持不同品牌配置。
