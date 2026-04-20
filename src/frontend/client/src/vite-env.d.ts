/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_LOGGER: string;
  readonly VITE_LOGGER_FILTER: string;
  // Add other env variables here
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __APP_ENV__: {
  BASE_URL: string;
  BISHENG_HOST?: string;
  /** 开发时管理端 origin，与 BASE_URL 不同端口时用于拼管理后台链接 */
  PLATFORM_ORIGIN?: string;
  [key: string]: any;
};
