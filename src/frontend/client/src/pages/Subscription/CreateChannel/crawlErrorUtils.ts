import { extractApiStatusCode } from "../errorUtils";

export type CrawlErrorCode = number | "invalid_url" | "network" | "timeout";

/** Validate syntax before contacting the crawler; reachability is decided by the service. */
export function normalizeCrawlUrl(input: string): string | null {
    const value = input.trim();
    const candidate = /^([a-z0-9-]+\.)+[a-z]{2,}(?:[/?#]|$)/i.test(value)
        ? `https://${value}` : value;
    try {
        const url = new URL(candidate);
        if (["http:", "https:"].includes(url.protocol) && url.hostname &&
            /^[a-z0-9.:[\]-]+$/i.test(url.hostname) &&
            url.username === "" && url.password === "" && /^https?:\/\//i.test(candidate) &&
            /\s/.test(value) === false) return url.href;
    } catch {
        return null;
    }
    return null;
}

export function mapCrawlError(error: unknown): CrawlErrorCode {
    const code = extractApiStatusCode(error);
    if (code != null) {
        if (code >= 19001 && code <= 19008) return code;
        if (code >= 13003 && code <= 13005) return code + 6000;
    }
    const transportCode = (error as { code?: unknown } | null)?.code;
    if (transportCode === "ECONNABORTED" || transportCode === "ETIMEDOUT") return "timeout";
    if (transportCode === "ERR_NETWORK") return "network";
    return 19003;
}

export function crawlErrorMessageKey(code: CrawlErrorCode | null | undefined): string {
    if (typeof code === "string") return `com_subscription.crawl_error_${code}`;
    if (code === 19001 || code === 19002 || code === 19006 || code === 19007 || code === 19008) {
        return `api_errors.${code}`;
    }
    if (code === 19004 || code === 13004) {
        return "com_subscription.crawl_error_19004";
    }
    if (code === 19005 || code === 13005) {
        return "com_subscription.crawl_error_19005";
    }
    return "com_subscription.crawl_error_19003";
}
