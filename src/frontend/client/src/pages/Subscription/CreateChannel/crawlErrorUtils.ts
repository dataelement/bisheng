export function crawlErrorMessageKey(code: number | null | undefined): string {
    if (code === 19006) {
        return "api_errors.19006";
    }
    if (code === 19004 || code === 13004) {
        return "com_subscription.crawl_error_19004";
    }
    if (code === 19005 || code === 13005) {
        return "com_subscription.crawl_error_19005";
    }
    return "com_subscription.crawl_error_19003";
}
