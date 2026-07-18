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
}

declare module "*.png" {
    const content: any;
    export default content;
}


declare module "*.svg" {
    const content: any;
    export default content;
}
