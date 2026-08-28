import { useLocation } from "react-router-dom"

/**
 * Standalone pages are mounted under `/standalone/*` and render without the
 * platform shell (no sidebar, no header), so they can be embedded into other
 * systems via iframe. They require a logged-in session but are intentionally
 * not filtered by `web_menu` permissions — the embedding host owns access
 * control, the backend still enforces per-API authorization.
 */
export const STANDALONE_PREFIX = "/standalone"

/** 运营岗 iframe 允许的 standalone 前缀; 不含 approval/sys/log. */
const PLATFORM_OPERATOR_STANDALONE_PREFIXES = [
    "/standalone/dashboard",
    "/standalone/knowledge-tag-library",
    "/standalone/content-security",
] as const

export type NoAdminConsoleAction = "allow-standalone" | "standalone-403" | "kick"

/** True when `pathname` (basename already stripped by react-router) is standalone. */
export function isStandalonePath(pathname: string): boolean {
    return pathname === STANDALONE_PREFIX || pathname.startsWith(`${STANDALONE_PREFIX}/`)
}

/**
 * 去掉 basename 与尾斜杠, 得到与 react-router 一致的 pathname.
 */
export function normalizePlatformPathname(pathname: string, baseUrl = ""): string {
    const raw = (pathname || "/").split("?")[0]
    const base = (baseUrl || "").replace(/\/+$/, "")
    let path = raw.startsWith("/") ? raw : `/${raw}`
    if (base && (path === base || path.startsWith(`${base}/`))) {
        path = path.slice(base.length) || "/"
    }
    if (!path.startsWith("/")) {
        path = `/${path}`
    }
    if (path.length > 1 && path.endsWith("/")) {
        path = path.slice(0, -1)
    }
    return path
}

/**
 * 是否运营岗可留在当前 standalone 页 (门户 iframe 三条).
 * 精确前缀匹配, 允许 /standalone/dashboard/:id; 不含 approval/sys/log 与有壳 /dashboard.
 */
export function isPlatformOperatorStandalonePath(pathname: string, baseUrl = ""): boolean {
    const path = normalizePlatformPathname(pathname, baseUrl)
    return PLATFORM_OPERATOR_STANDALONE_PREFIXES.some(
        (prefix) => path === prefix || path.startsWith(`${prefix}/`),
    )
}

/**
 * 无管理端 WEB_MENU 时对当前 URL 的处置: 白名单留下, 其它 standalone 进 403, 有壳管理页踢走.
 */
export function resolveNoAdminConsoleAction(pathname: string, baseUrl = ""): NoAdminConsoleAction {
    const path = normalizePlatformPathname(pathname, baseUrl)
    if (isPlatformOperatorStandalonePath(path)) {
        return "allow-standalone"
    }
    if (isStandalonePath(path)) {
        return "standalone-403"
    }
    return "kick"
}

/**
 * Path prefix to prepend when navigating between pages, so a page opened in
 * standalone mode keeps its shell-less chrome instead of jumping back into
 * the platform layout. Returns `""` inside the normal platform shell.
 */
export function useStandalonePrefix(): string {
    const { pathname } = useLocation()
    return isStandalonePath(pathname) ? STANDALONE_PREFIX : ""
}
