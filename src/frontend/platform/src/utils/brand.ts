type BrandAssetKey =
    | "favicon"
    | "loginHeroLight"
    | "loginHeroDark"
    | "headerLogoLight"
    | "headerLogoDark";

const ABSOLUTE_URL_PATTERN = /^(https?:|data:|blob:|\/\/)/i;

export function withBrandBaseUrl(url = "") {
    if (!url) return "";
    if (ABSOLUTE_URL_PATTERN.test(url)) return url;
    const baseUrl = (__APP_ENV__.BASE_URL || "").replace(/\/$/, "");
    if (baseUrl && (url === baseUrl || url.startsWith(`${baseUrl}/`))) return url;
    const normalizedUrl = url.startsWith("/") ? url : `/${url}`;
    return `${baseUrl}${normalizedUrl}`;
}

export function getBrandAssetUrl(key: BrandAssetKey, fallback: string) {
    const configuredUrl = window.BRAND_CONFIG?.assets?.[key]?.url || "";
    return withBrandBaseUrl(configuredUrl || fallback);
}

export function getBrandLoadingIconUrl() {
    return withBrandBaseUrl(
        window.BRAND_CONFIG?.URLLoadingIcon
        || window.BRAND_CONFIG?.loadingIcon
        || "",
    );
}
