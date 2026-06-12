import type { BrandAssetOption, BrandConfig } from "@/controllers/API";

export const BRAND_ASSET_ACCEPT = ".ico,.png,.jpg,.jpeg,.svg,.gif,.webp";

export type BrandAssetKey = keyof BrandConfig["assets"];
export type BrandTextKey = "brandName";
export type BrandPreviewTarget = BrandTextKey | BrandAssetKey | "loadingIcon" | "loadingAnimation";

export const DEFAULT_BRAND_CONFIG: BrandConfig = {
    brandName: { zh: "BISHENG", en: "BISHENG" },
    linsightAgentName: { zh: "灵思", en: "Linsight" },
    assets: {
        favicon: {
            url: "/assets/bisheng/favicon.ico",
            relative_path: "",
            file_name: "",
        },
        loginHeroLight: {
            url: "/assets/bisheng/login-logo-big.png",
            relative_path: "",
            file_name: "",
        },
        loginHeroDark: {
            url: "/assets/bisheng/login-logo-dark.png",
            relative_path: "",
            file_name: "",
        },
        headerLogoLight: {
            url: "/assets/bisheng/login-logo-small.png",
            relative_path: "",
            file_name: "",
        },
        headerLogoDark: {
            url: "/assets/bisheng/logo-small-dark.png",
            relative_path: "",
            file_name: "",
        },
    },
    loading: {
        icon: {
            url: "/assets/bisheng/loading.svg",
            relative_path: "",
            file_name: "loading.svg",
        },
        iconOptions: [],
        animation: "",
    },
    URLLoadingIcon: "/assets/bisheng/loading.svg",
};

export const cloneBrandConfig = (config: BrandConfig): BrandConfig => (
    JSON.parse(JSON.stringify(config))
);

export const buildDefaultAssetOptions = (): Record<BrandAssetKey, BrandAssetOption[]> => (
    Object.entries(DEFAULT_BRAND_CONFIG.assets).reduce((result, [key, asset]) => ({
        ...result,
        [key]: [{
            ...asset,
            file_name: asset.url.split("/").pop() || asset.url,
            is_default: true,
        }],
    }), {} as Record<BrandAssetKey, BrandAssetOption[]>)
);
