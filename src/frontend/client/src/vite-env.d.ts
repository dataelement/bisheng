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

declare const __VCONSOLE_ENABLED__: boolean;

/** 首钢门户专属：ConfigMap 注入的"部署默认值"开关；首选 BiSheng 系统配置 YAML 的 shougang.portal_admin_url */
interface Window {
  __SHOUGANG_PORTAL_ADMIN_URL__?: string;
  /** Branding fields injected at runtime by public/assets/bisheng/config.js. */
  BRAND_CONFIG?: {
    brandName?: { zh?: string; en?: string };
    linsightAgentName?: { zh?: string; en?: string };
    linsightFullName?: { zh?: string; en?: string };
    dailyFullName?: { zh?: string; en?: string };
    loadingIcon?: string;
    loadingAnimation?: string;
  };
  /** Runtime app config injected by public/assets/bisheng/config.js. */
  APP_CONFIG?: {
    /** Hide Japanese from the language switcher and locale auto-detection. */
    disableJa?: boolean;
  };
}
