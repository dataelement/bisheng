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

    // Deliberately not prefixed with the admin app's BASE_URL: the client app is
    // served at /workspace from the root, outside the admin prefix. Prefixing it
    // would produce /platform/workspace/... and 404.
    return workspacePath;
}
