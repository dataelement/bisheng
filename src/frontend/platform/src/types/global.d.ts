export { };

declare global {
    interface Window {
        SearchSkillsPage: any;
        errorAlerts: (errorList: string[]) => void
        _flow: any
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
