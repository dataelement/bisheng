import type { AbnormalFilePreviewDetail } from "@/controllers/API/abnormalUpload"

declare const __APP_ENV__: { BASE_URL: string }

export type PreviewSource = { kind: "pdf" | "text" | "image" | "sheet" | "docx" | "audio" | "video"; url: string }

function fileProxyUrl(value: unknown): string | null {
    if (typeof value !== "string" || !value || value.startsWith("//") || /[\\\s\x00-\x1f]/.test(value)) return null
    try {
        const url = new URL(value, window.location.origin)
        if (url.origin !== window.location.origin || url.username || url.password || !/^https?:$/.test(url.protocol)) return null
        const base = __APP_ENV__.BASE_URL.replace(/\/$/, "")
        const path = base && url.pathname.startsWith(`${base}/`) ? url.pathname.slice(base.length) : url.pathname
        // Only object paths routed to MinIO by both Vite and nginx are loadable.
        if (!/^\/(bisheng|tmp-dir)\/.+/.test(path) || /%(?:2f|5c|00)/i.test(path)) return null
        return `${base}${path}${url.search}`
    } catch {
        return null
    }
}

function kindForName(name: string): PreviewSource["kind"] | null {
    const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1].toLowerCase()
    if (ext === "pdf" || ext === "docx") return ext
    if (/^(txt|md|html?)$/.test(ext || "")) return "text"
    if (/^(png|jpe?g|gif|webp|bmp)$/.test(ext || "")) return "image"
    if (/^(xlsx?|et|csv)$/.test(ext || "")) return "sheet"
    if (/^(mp3|wav|ogg|m4a|aac|flac)$/.test(ext || "")) return "audio"
    if (/^(mp4|webm|mov|m4v|ogv)$/.test(ext || "")) return "video"
    return null
}

export function selectPreviewSource(detail: AbnormalFilePreviewDetail | null | undefined, name: string): PreviewSource | null {
    if (!detail) return null
    const pdf = fileProxyUrl(detail.pdf_preview_url)
    if (pdf) return { kind: "pdf", url: pdf }
    const preview = fileProxyUrl(detail.preview_url)
    const previewKind = preview && kindForName(preview.split("?")[0])
    if (preview && previewKind) return { kind: previewKind, url: preview }
    const snapshot = fileProxyUrl(detail.html_preview_url)
    if (snapshot) return { kind: "text", url: snapshot }
    const original = fileProxyUrl(detail.original_url)
    const originalKind = kindForName(name)
    return original && originalKind ? { kind: originalKind, url: original } : null
}
