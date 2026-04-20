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
  [key: string]: any;
};

declare const __VCONSOLE_ENABLED__: boolean;
