const CRAWL_ERROR_KEYS: Record<number, string> = {
    19003: "crawl_error_19003",
    19004: "crawl_error_19004",
    19005: "crawl_error_19005",
    19006: "19006",
};

export function crawlErrorMessageKey(code: number | null | undefined): string {
    if (code == null) return CRAWL_ERROR_KEYS[19003];
    return CRAWL_ERROR_KEYS[code] ?? CRAWL_ERROR_KEYS[19003];
}
