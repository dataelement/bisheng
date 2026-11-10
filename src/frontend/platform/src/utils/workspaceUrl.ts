/**
 * Cross-app links into the end-user client (`/workspace` base path).
 *
 * Production serves both apps from one origin, so the client path is relative.
 * Local dev runs the client on its own port (:4001), and a relative `/workspace`
 * would land on *this* app → router catch-all → `/404`. The dev origin is
 * therefore derived from the browser's own hostname (so localhost, 127.0.0.1
 * and LAN-IP access all work), unless `VITE_WORKSPACE_ORIGIN` pins one.
 */
const WORKSPACE_BASE_PATH = '/workspace';
/** Client dev server port (strictPort, see client/vite.config.ts). */
const DEV_WORKSPACE_PORT = '4001';

type WorkspaceEnvLike = {
    BASE_URL?: string;
    WORKSPACE_ORIGIN?: string;
};

type LocationLike = {
    protocol?: string;
    hostname?: string;
};

function joinUrlPath(base: string, path: string) {
    const normalizedBase = base.replace(/\/$/, '');
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${normalizedBase}${normalizedPath}`;
}

export function resolveWorkspaceOrigin(
    appEnv: WorkspaceEnvLike,
    loc?: LocationLike | null,
    isDev = false,
): string {
    const configured = String(appEnv.WORKSPACE_ORIGIN || '').trim().replace(/\/$/, '');
    if (configured) return configured;

    if (isDev && loc?.hostname) {
        return `${loc.protocol || 'http:'}//${loc.hostname}:${DEV_WORKSPACE_PORT}`;
    }

    return '';
}

export function getWorkspaceClientUrl(
    path = '/',
    // Test seam: callers never pass this; it defaults to the bundler's dev flag.
    isDev = Boolean(import.meta.env?.DEV),
) {
    const workspaceOrigin = resolveWorkspaceOrigin(
        __APP_ENV__,
        typeof location !== 'undefined' ? location : null,
        isDev,
    );
    const workspacePath = joinUrlPath(WORKSPACE_BASE_PATH, path);

    if (workspaceOrigin) {
        return `${workspaceOrigin}${workspacePath}`;
    }

    return joinUrlPath(__APP_ENV__.BASE_URL || '', workspacePath);
}
