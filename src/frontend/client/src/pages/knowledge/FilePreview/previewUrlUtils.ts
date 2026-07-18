/**
 * Normalize MinIO share URLs for Client fetch/media under `/workspace`.
 * nginx only proxies `^/(workspace/bisheng|bisheng|tmp-dir)/` — paths like
 * `/workspace/workspace/bisheng/...` fall through to SPA index.html.
 */
export function resolveKnowledgePreviewUrl(url: string): string {
    if (!url) return "";

    let path = url;
    if (/^https?:\/\//.test(url)) {
        try {
            const parsed = new URL(url);
            path = `${parsed.pathname}${parsed.search}${parsed.hash}`;
        } catch {
            path = url.replace(/^https?:\/\/[^/]+/, "");
        }
    }

    // Collapse accidental duplicate workspace prefixes from repeated normalization.
    const base = __APP_ENV__.BASE_URL.replace(/\/$/, "") || "/workspace";
    while (path.startsWith(`${base}${base}/`) || path.startsWith(`${base}${base}`)) {
        path = path.slice(base.length);
    }

    if (path.startsWith(`${base}/bisheng/`) || path.startsWith(`${base}/tmp-dir/`)) {
        return path;
    }

    if (path.startsWith("/bisheng/") || path.startsWith("/tmp-dir/")) {
        return `${base}${path}`;
    }

    if (path.startsWith(base)) {
        return path;
    }

    return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}
