import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import request from "../src/controllers/request"
import { getAbnormalFilePreview } from "../src/controllers/API/abnormalUpload"
import { selectPreviewSource } from "../src/pages/LogPage/abnormalUpload/previewSource"

// Keep the real HTTP client, its auth headers and response interceptors. Only the transport is isolated.
vi.mock("@/components/bs-ui/toast/use-toast", () => ({ toast: vi.fn() }))
const previousAdapter = request.defaults.adapter
beforeEach(() => vi.stubGlobal("__APP_ENV__", { BASE_URL: "/platform" }))
afterEach(() => {
    request.defaults.adapter = previousAdapter
    vi.unstubAllGlobals()
    localStorage.clear()
})

describe("abnormal file preview", () => {
    it("requests the selected IDs, forwards cancellation, and unwraps only the authorized response", async () => {
        const { signal } = new AbortController()
        localStorage.setItem("ws_token", "test-session")
        const detail = { preview_url: "/bisheng/marker.pdf" }
        const adapter = vi.fn(async config => {
            expect(config).toMatchObject({ method: "get", url: "/api/v1/knowledge/space/12/files/31/preview", silent: true })
            expect(config.signal).toBe(signal)
            expect(config.timeout).toBeGreaterThan(0)
            expect(config.headers.Authorization).toBe("Bearer test-session")
            return { data: { status_code: 200, data: detail }, status: 200, statusText: "OK", headers: {}, config }
        })
        request.defaults.adapter = adapter
        await expect(getAbnormalFilePreview(12, 31, signal)).resolves.toEqual(detail)
        expect(adapter).toHaveBeenCalledTimes(1)
    })
    it("propagates business refusal without fallback or redirect", async () => {
        const before = window.location.href
        const adapter = vi.fn(async config => ({ data: { status_code: 403, data: { original_url: "/bisheng/denied.pdf" } }, status: 200, statusText: "OK", headers: {}, config }))
        request.defaults.adapter = adapter
        await expect(getAbnormalFilePreview(4, 2, new AbortController().signal)).rejects.toBeDefined()
        expect(adapter).toHaveBeenCalledTimes(1)
        expect(window.location.href).toBe(before)
    })
    it("does not start a cancelled read", async () => {
        const adapter = vi.fn()
        request.defaults.adapter = adapter
        await expect(getAbnormalFilePreview(1, 2, AbortSignal.abort())).rejects.toMatchObject({ code: "ERR_CANCELED" })
        expect(adapter).not.toHaveBeenCalled()
    })
    it("prioritizes the PDF rendition without needing a suffix; preserves signed query bytes", () => {
        const path = "/bisheng/42?sig=A%2Fb%2Bc&v=1"
        expect(selectPreviewSource({ pdf_preview_url: path, preview_url: "/tmp-dir/a.txt", original_url: "/bisheng/b.doc" }, "b.doc")).toEqual({ kind: "pdf", url: `/platform${path}` })
    })
    it("maps prefixed same-origin resources once and uses the representation type", () => {
        expect(selectPreviewSource({ preview_url: `${window.location.origin}/platform/tmp-dir/A.PDF?v=1` }, "a.ppt")).toEqual({ kind: "pdf", url: "/platform/tmp-dir/A.PDF?v=1" })
    })
    it("uses only stored HTML snapshots as plain text, not live web URLs", () => {
        const web = { source_url: "https://outside.example/page", html_preview_url: "/bisheng/snapshot" }
        expect(selectPreviewSource(web, "news")).toEqual({ kind: "text", url: "/platform/bisheng/snapshot" })
        expect(selectPreviewSource({ ...web, html_preview_url: "" }, "news")).toBeNull()
    })
    it.each([["txt", "text"], ["html", "text"], ["MD", "text"], ["xlsx", "sheet"], ["csv", "sheet"], ["docx", "docx"], ["pdf", "pdf"], ["png", "image"], ["mp3", "audio"], ["mp4", "video"]])("selects an authorized original .%s as %s", (ext, kind) => {
        expect(selectPreviewSource({ original_url: "/tmp-dir/420" }, `finance.${ext}`)).toEqual({ kind, url: "/platform/tmp-dir/420" })
    })
    it.each(["doc", "wps", "ppt", "pptx", "dps", "zip"])("does not guess a renderer for a .%s original", ext => {
        expect(selectPreviewSource({ preview_url: "/bisheng/opaque", original_url: "/bisheng/untyped" }, `report.${ext}`)).toBeNull()
    })
    it.each(["", "/api/private", "/bisheng-not-a-bucket/foo.pdf", "/platform/api/foo", "/bisheng/../api/private", "/bisheng/%2e%2e%2fapi/private", "javascript:alert(1)", "data:text/plain,hi", "//outside.test/bisheng/a", "https://outside.test/bisheng/a", "/\\outside.test/bisheng/file.pdf"])("refuses non-file-service resource %j", value => {
        expect(selectPreviewSource({ pdf_preview_url: value, original_url: value }, "a.pdf")).toBeNull()
    })
})
