/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_LOGGER: string;
  readonly VITE_LOGGER_FILTER: string;
  // Add other env variables here
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** Build-time app config, injected by vite `define` (see vite.config.ts `app_env`). */
declare const __APP_ENV__: {
  /** Sub-path this app is served under. */
  BASE_URL: string;
  /** Sub-path of the admin/platform app, for cross-app links. */
  BISHENG_HOST: string;
};

declare const __VCONSOLE_ENABLED__: boolean;

interface Window {
  /** Branding fields injected at runtime by brand-runtime.js (from /api/v1/brand/runtime-config, cached in localStorage). */
  BRAND_CONFIG?: {
    brandName?: { zh?: string; en?: string };
    linsightAgentName?: { zh?: string; en?: string };
    loadingIcon?: string;
    URLLoadingIcon?: string;
    loadingAnimation?: string;
    /** Admin-set workbench accent theme preset; applied by brand-runtime.js. */
    workbenchTheme?: "blue" | "green";
    loading?: {
      icon?: { url?: string; relative_path?: string; file_name?: string } | null;
      iconOptions?: Array<{ url?: string; relative_path?: string; file_name?: string }>;
      animation?: string;
    };
    assets?: {
      favicon?: { url?: string };
      loginHeroLight?: { url?: string };
      loginHeroDark?: { url?: string };
      headerLogoLight?: { url?: string };
      headerLogoDark?: { url?: string };
    };
  };
  __BRAND_CONFIG_READY__?: Promise<any>;
  /** Runtime app config injected by public/assets/bisheng/config.js. */
  APP_CONFIG?: {
    /** Hide Japanese from the language switcher and locale auto-detection. */
    disableJa?: boolean;
  };
}
