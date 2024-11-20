import react from "@vitejs/plugin-react-swc";
import path from "path";
import { defineConfig } from "vite";
import { createHtmlPlugin } from 'vite-plugin-html';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import svgr from "vite-plugin-svgr";
// import { visualizer } from 'rollup-plugin-visualizer';

// Use environment variable to determine the target.
const target = process.env.VITE_PROXY_TARGET || "http://192.168.106.120:3003";
// const target = process.env.VITE_PROXY_TARGET || "http://192.168.2.47:7860";
//  const target = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:7860";
const apiRoutes = ["^/api/", "/health"];

const proxyTargets = apiRoutes.reduce((proxyObj, route) => {
  proxyObj[route] = {
    target: target,
    changeOrigin: true,
    withCredentials: true,
    secure: false,
    ws: true
  };
  return proxyObj;
}, {});
// 文件服务地址
proxyTargets['/bisheng'] = {
  target: "http://192.168.106.116:9000",
  changeOrigin: true,
  withCredentials: true,
  secure: false
}
proxyTargets['/tmp-dir'] = proxyTargets['/bisheng']
proxyTargets['/custom_base/api'] = {
  target,
  changeOrigin: true,
  withCredentials: true,
  secure: false,
  rewrite: (path) => {
    return path.replace(/^\/custom_base\/api/, '/api');
  },
  configure: (proxy, options) => {
    proxy.on('proxyReq', (proxyReq, req, res) => {
      console.log('Proxying request to:', proxyReq.path);
    });
  }
}

/**
 * 开启子路由访问
 * 开启后一般外层网管匹配【custom】时直接透传转到内层网关
 * 内层网关访问 api或者前端静态资源需要去掉【custom】前缀
*/
// const app_env = { BASE_URL: '/custom_base' }
const app_env = { BASE_URL: '' }

export default defineConfig(() => {
  return {
    base: app_env.BASE_URL || '/',
    build: {
      // minify: 'esbuild', // 使用 esbuild 进行 Tree Shaking 和压缩
      outDir: "build",
      rollupOptions: {
        output: {
          manualChunks: {
            acebuilds: ['react-ace', 'ace-builds', 'react-syntax-highlighter', 'rehype-mathjax', 'react-markdown'],
            reactflow: ['@xyflow/react'],
            pdfjs: ['pdfjs-dist'],
            reactdrop: ['react-window', 'react-beautiful-dnd', 'react-dropzone']
          }
        }
      }
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      }
    },
    plugins: [
      react(),
      svgr(),
      createHtmlPlugin({
        minify: true,
        inject: {
          data: {
            // include: [/index\.html$/],
            aceScriptSrc: `<script src="${process.env.NODE_ENV === 'production' ? app_env.BASE_URL : ''}/node_modules/ace-builds/src-min-noconflict/ace.js" type="text/javascript"></script>`,
            baseUrl: app_env.BASE_URL
          }
        }
      }),
      viteStaticCopy({
        targets: [
          {
            src: [
              'node_modules/ace-builds/src-min-noconflict/ace.js',
              'node_modules/ace-builds/src-min-noconflict/mode-json.js',
              'node_modules/ace-builds/src-min-noconflict/worker-json.js',
              'node_modules/ace-builds/src-min-noconflict/mode-yaml.js',
              'node_modules/ace-builds/src-min-noconflict/worker-yaml.js'
            ],
            dest: 'node_modules/ace-builds/src-min-noconflict/'
          },
          {
            src: 'node_modules/pdfjs-dist/build/pdf.worker.min.js',
            dest: './'
          }
        ]
      }),
      // 打包物体积报告
      // visualizer({
      //   open: true,
      // })
    ],
    define: {
      __APP_ENV__: JSON.stringify(app_env)
    },
    server: {
      host: '0.0.0.0',
      port: 3001,
      proxy: {
        ...proxyTargets,
      },
    },
  };
});
