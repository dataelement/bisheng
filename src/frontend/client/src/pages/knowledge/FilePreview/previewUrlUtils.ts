/**
 * Rewrite backend/MinIO absolute URLs to same-origin paths under BASE_URL,
 * matching Platform RichPreviewFile and Client PreviewFile components.
 */
export function resolveKnowledgePreviewUrl(url: string): string {
    if (!url) return "";
    if (/^https?:\/\//.test(url)) {
        return url.replace(/https?:\/\/[^/]+/, __APP_ENV__.BASE_URL);
    }
    const normalizedPath = url.startsWith("/") ? url : `/${url}`;
    return `${window.location.origin}${__APP_ENV__.BASE_URL}${normalizedPath}`;
}
