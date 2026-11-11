export const WORKFLOW_MANAGEMENT_PATH = '/build/workflows';
export const WORKFLOW_MANAGEMENT_SCOPE = 'workflow_management';
const WORKFLOW_MANAGEMENT_SOURCE = 'workflow-management';

export function isWorkflowManagementPath(pathname: string): boolean {
    return pathname === WORKFLOW_MANAGEMENT_PATH || pathname.startsWith(`${WORKFLOW_MANAGEMENT_PATH}/`);
}

export function claimWorkflowManagementSsoAttempt(): boolean {
    const state = window.history.state;
    if (state?.workflowManagementSsoAttempted) return false;
    window.history.replaceState({ ...state, workflowManagementSsoAttempted: true }, '');
    return true;
}

export function workflowManagementEditorPath(id: string): string {
    return `/flow/${encodeURIComponent(id)}?from=${WORKFLOW_MANAGEMENT_SOURCE}`;
}

export function workflowManagementReturnTarget(search: string): string | undefined {
    return new URLSearchParams(search).get('from') === WORKFLOW_MANAGEMENT_SOURCE
        ? WORKFLOW_MANAGEMENT_PATH
        : undefined;
}
