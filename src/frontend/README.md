# 项目启动与部署指南

## 本地启动开发调试

### 环境准备

在开始之前，请确保你已经安装了以下工具：
- Node.js (建议使用 LTS 版本)
- npm 或 yarn 包管理工具

### 安装依赖

首先，克隆项目仓库并安装依赖：

```bash
git clone <your-repository-url>
cd <your-project-directory>
npm install
# 或者使用 yarn
# yarn install
```
### 代理配置

开发环境下，以下代理已配置：
- `target` 代理到 后端接口
- `/bisheng` 代理到 文件服务器地址
- `/custom_base/api` 开启子路由时需要配置此代理，并重写路径 `/custom_base/api` 为 `/api`

### 启动开发服务器

使用以下命令启动本地开发服务器：

```bash
npm run start
# 或者使用 yarn
# yarn start
```

开发服务器将会运行在 [http://localhost:3001](http://localhost:3001)。


## 正式环境部署

### 构建项目

在部署之前，需要先构建项目。使用以下命令进行构建：

```bash
npm run build
# 或者使用 yarn
# yarn build
```

构建后的文件将会输出到 `build` 目录。

### 部署静态文件

将 `build` 目录下的所有文件部署到你的静态文件服务器。

### 配置服务器代理

在生产环境中，你需要配置服务器代理，以便处理 API 请求和文件服务请求。以下是一个 Nginx 的示例配置：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    root /path/to/your/build;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass [backend url];
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /bisheng/ {
        proxy_pass [file server url];
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /custom_base/api/ {
        rewrite ^/custom_base/api/(.*)$ /api/$1 break;
        proxy_pass [backend url];
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 环境变量

在生产环境中，你可以通过设置环境变量 `VITE_PROXY_TARGET` 来配置 API 代理目标地址。

## 常见问题

### 如何修改代理目标地址？

可以通过修改 `.env` 文件中的 `VITE_PROXY_TARGET` 变量来更改代理目标地址：

```env
VITE_PROXY_TARGET=http://new-target-address:port
```

修改后，重新启动开发服务器或重新构建项目以应用新的代理目标地址。

### 如何添加新的代理路径？

可以在 `vite.config.js` 文件中的 `proxyTargets` 对象中添加新的代理路径：

```javascript
proxyTargets['/new-path'] = {
  target: "http://new-target-address:port",
  changeOrigin: true,
  withCredentials: true,
  secure: false
};
```

添加后会自动更新开发服务器以应用新的代理配置。

[\u4e00-\u9fa5]+


##### 开发模式下，无法访问到静态资源，注释掉以下代码
目录：node_modules/vite-plugin-html/dist/index.mjs

```javascript
// 150行的
server.middlewares.use(history...
```