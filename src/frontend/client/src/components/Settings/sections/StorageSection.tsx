import { useEffect, type ReactNode } from "react";
import { useLocalize } from "~/hooks";
import { usePersonalStorageQuota } from "~/hooks/usePersonalStorageQuota";
import type { PersonalStorage } from "~/utils/personalStorage";
import { cn } from "~/utils";

/**
 * One quota readout: `title` and the usage text share a row (title left,
 * usage right), the full-width progress bar sits below, hint last.
 */
function StorageQuotaDisplay({ data, title }: { data: PersonalStorage; title: ReactNode }) {
    const localize = useLocalize();
    const { status, usedText, totalText, percent } = data;

    const unlimited = status === "unlimited";
    // Bar color per state: normal = green, warning = orange, full/exceeded = red.
    const barColor =
        status === "warning"
            ? "bg-warning"
            : status === "full" || status === "exceeded"
                ? "bg-danger"
                : "bg-success";
    const hintKey =
        status === "full"
            ? "com_storage_quota.full_hint"
            : status === "exceeded"
                ? "com_storage_quota.exceeded_hint"
                : null;

    return (
        <div>
            <div className="flex items-center justify-between gap-4">
                {title}
                <p className="text-right text-[14px] leading-6 tabular-nums text-[#86909c]">
                    {status === "unknown"
                        ? "—"
                        : localize("com_storage_quota.usage", {
                            0: usedText,
                            1: unlimited ? localize("com_storage_quota.unlimited") : totalText,
                        })}
                </p>
            </div>
            {status !== "unknown" && !unlimited && (
                <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-fill-2">
                    <div
                        className={cn("h-full rounded-full", barColor)}
                        style={{ width: `${percent}%` }}
                    />
                </div>
            )}
            {hintKey && (
                <p className="mt-2 text-[12px] leading-[18px] text-[#86909c]">
                    {localize(hintKey)}
                </p>
            )}
        </div>
    );
}

/**
 * Personal storage capacity, summed across every knowledge space the user has
 * files in — it belongs to the user, not to the space they happen to be
 * viewing, which is why it lives in personal settings rather than a space page.
 */
export function StorageSection() {
    const localize = useLocalize();
    const quota = usePersonalStorageQuota();

    // The quota can change from any knowledge-space upload/delete; refetch on entry.
    const { refresh } = quota;
    useEffect(() => {
        void refresh();
    }, [refresh]);

    return (
        <StorageQuotaDisplay
            title={
                <span className="text-[14px] text-[#1d2129]">
                    {localize("com_storage_quota.title")}
                </span>
            }
            data={quota}
        />
    );
}
