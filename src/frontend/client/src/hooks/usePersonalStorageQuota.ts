import { useCallback, useMemo } from "react";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import { derivePersonalStorage } from "~/utils/personalStorage";
import useLocalize from "./useLocalize";
import { useEffectiveQuota, useRefreshEffectiveQuota } from "./useEffectiveQuota";

/**
 * Personal storage capacity across every knowledge space, for the profile menu
 * card and the upload guards.
 */
export function usePersonalStorageQuota() {
    const { quotas, loading } = useEffectiveQuota();
    const refresh = useRefreshEffectiveQuota();
    const item = quotas["knowledge_space_file"];

    return useMemo(
        () => ({
            ...derivePersonalStorage(item?.user_used, item?.effective),
            loading,
            refresh,
        }),
        [item, loading, refresh],
    );
}

/**
 * Guard for actions that would add `knowledge_space_file` usage (upload, folder
 * upload, drag-drop, web import, duplicate overwrite). Returns true when the
 * action must not proceed, having already told the user why. Pass the batch's
 * total size in bytes to also reject uploads that would not fit into the
 * remaining capacity (acknowledge-only dialog); unknown / unlimited quotas and
 * a zero-arg call only check the exhausted state. This is upfront feedback
 * only — the server rejection remains the authoritative check.
 */
export function useStorageQuotaGuard() {
    const { exhausted, status, remainingBytes } = usePersonalStorageQuota();
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const localize = useLocalize();

    return useCallback(
        (uploadBytes?: number) => {
            if (exhausted) {
                showToast({
                    message: localize(
                        status === "exceeded"
                            ? "com_storage_quota.exceeded_hint"
                            : "com_storage_quota.full_hint",
                    ),
                    severity: NotificationSeverity.WARNING,
                });
                return true;
            }
            if (uploadBytes != null && remainingBytes != null && uploadBytes > remainingBytes) {
                void confirm({
                    title: localize("com_storage_quota.title"),
                    description: localize("com_storage_quota.insufficient_hint"),
                    hideCancel: true,
                });
                return true;
            }
            return false;
        },
        [exhausted, status, remainingBytes, showToast, confirm, localize],
    );
}
