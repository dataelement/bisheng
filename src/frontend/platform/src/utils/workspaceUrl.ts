const WORKSPACE_BASE_PATH = '/workspace';

function joinUrlPath(base: string, path: string) {
    const normalizedBase = base.replace(/\/$/, '');
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${normalizedBase}${normalizedPath}`;
}

export function getWorkspaceClientUrl(path = '/') {
    const workspaceOrigin = String((__APP_ENV__ as { WORKSPACE_ORIGIN?: string }).WORKSPACE_ORIGIN || '').replace(/\/$/, '');
    const workspacePath = joinUrlPath(WORKSPACE_BASE_PATH, path);

    if (workspaceOrigin) {
        return `${workspaceOrigin}${workspacePath}`;
    }

    return joinUrlPath(__APP_ENV__.BASE_URL || '', workspacePath);
}
