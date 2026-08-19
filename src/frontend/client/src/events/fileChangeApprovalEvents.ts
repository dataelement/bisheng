export const FILE_CHANGE_APPROVAL_REFRESH_EVENT = "knowledge-space-file-changes-refresh";

export function dispatchFileChangeApprovalRefresh(spaceId?: string | number): void {
    window.dispatchEvent(new CustomEvent(FILE_CHANGE_APPROVAL_REFRESH_EVENT, {
        detail: spaceId == null ? undefined : { spaceId },
    }));
}
