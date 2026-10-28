/**
 * Object storage URLs belong to the origin-level bucket proxy. The Client's
 * BASE_URL identifies SPA routes; signed object paths retain their own root.
 * Accept legacy Client-prefixed bucket URLs and preserve signed query bytes.
 */
export function resolveKnowledgePreviewUrl(url: string): string {
    if (!url) return "";

    let path = url;
    const absolute = /^(?:https?:)?\/\//i.test(url);
    if (absolute) {
        try {
            const parsed = new URL(url, window.location.origin);
            path = `${parsed.pathname}${parsed.search}${parsed.hash}`;
        } catch {
            return url;
        }
    }

    // Remove legacy application prefixes only from known object-storage paths.
    const base = __APP_ENV__.BASE_URL.replace(/\/$/, "") || "/workspace";
    let objectPath = path.startsWith("/") ? path : `/${path}`;
    while (objectPath.startsWith(`${base}/`)) {
        objectPath = objectPath.slice(base.length);
    }

    if (/^\/(?:bisheng|tmp-dir)\//.test(objectPath)) {
        return objectPath;
    }

    if (absolute || /^(?:blob|data):/i.test(url)) {
        return url;
    }

    if (path.startsWith("/")) {
        return path;
    }

    return `${base}/${path}`;
}
