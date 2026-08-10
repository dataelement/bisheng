import { useLocation } from "react-router-dom"

/**
 * Standalone pages are mounted under `/standalone/*` and render without the
 * platform shell (no sidebar, no header), so they can be embedded into other
 * systems via iframe. They require a logged-in session but are intentionally
 * not filtered by `web_menu` permissions — the embedding host owns access
 * control, the backend still enforces per-API authorization.
 */
export const STANDALONE_PREFIX = "/standalone"

/** True when `pathname` (basename already stripped by react-router) is standalone. */
export function isStandalonePath(pathname: string): boolean {
    return pathname === STANDALONE_PREFIX || pathname.startsWith(`${STANDALONE_PREFIX}/`)
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
