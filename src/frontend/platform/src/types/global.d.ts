export { };

declare global {
    interface Window {
        SearchSkillsPage: any;
        errorAlerts: (errorList: string[]) => void
        _flow: any
        /** Branding fields injected at runtime by brand-runtime.js (from /api/v1/brand/runtime-config, cached in localStorage). */
        BRAND_CONFIG?: {
            brandName?: { zh?: string; en?: string };
            linsightAgentName?: { zh?: string; en?: string };
            loadingIcon?: string;
            URLLoadingIcon?: string;
            loadingAnimation?: string;
            /** Admin-set workbench accent theme preset (drives the end-user app). */
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

    const __VCONSOLE_ENABLED__: boolean;

    /** Build-time app config, injected by vite `define` (see vite.config.mts). */
    const __APP_ENV__: {
        /** Sub-path the app is served under (e.g. `/custom`); empty for root. */
        BASE_URL: string;
        /** Origin of the end-user client app; empty when it shares ours. */
        WORKSPACE_ORIGIN: string;
        /** Origin the OnlyOffice Document Server can reach us at; empty in production. */
        OFFICE_PUBLIC_ORIGIN: string;
    };
}

declare module "*.png" {
    const content: any;
    export default content;
}


declare module "*.svg" {
    const content: any;
    export default content;
}
