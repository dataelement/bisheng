import { FileStatus } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";

import { dispatchFileChangeApprovalRefresh } from "./fileMutationUtils";
import { partitionUploadMutationResults } from "./fileUploadUtils";

export const REGISTERED_PROCESSING_STATUSES = new Set<FileStatus>([
    FileStatus.UPLOADING,
    FileStatus.WAITING,
    FileStatus.PROCESSING,
    FileStatus.REBUILDING,
]);

type Localize = (key: string, options?: Record<string, unknown>) => string;
type ShowToast = (toast: { message: string; severity: NotificationSeverity }) => void;

export function handleUploadMutationFeedback(
    spaceId: string,
    results: ReturnType<typeof partitionUploadMutationResults>,
    localize: Localize,
    showToast: ShowToast,
): void {
    if (results.pending.length > 0) dispatchFileChangeApprovalRefresh(spaceId);
    results.invalid.forEach((item) => {
        showToast({
            message: item.errorMessage
                ? localize("com_knowledge.file_upload_failed_with_reason", { 0: item.inputId, 1: item.errorMessage })
                : localize("com_knowledge.file_upload_failed", { 0: item.inputId }),
            severity: NotificationSeverity.ERROR,
        });
    });
}
