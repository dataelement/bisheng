import { usePersonalStorageQuota } from "~/hooks/usePersonalStorageQuota";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

/**
 * Personal storage capacity, summed across every knowledge space the user has
 * files in — it belongs to the user, not to the space they happen to be viewing,
 * which is why it lives in the profile menu rather than a space page.
 */
export function PersonalStorageCard({ className }: { className?: string }) {
    const localize = useLocalize();
    const { status, usedText, totalText, percent } = usePersonalStorageQuota();

    if (status === "unknown") {
        return null;
    }

    const unlimited = status === "unlimited";
    const alerting = status === "warning" || status === "full" || status === "exceeded";
    const hintKey =
        status === "full"
            ? "com_storage_quota.full_hint"
            : status === "exceeded"
                ? "com_storage_quota.exceeded_hint"
                : null;

    return (
        <div className={className}>
            <p className="text-[12px] leading-[18px] text-text-3">
                {localize("com_storage_quota.title")}
            </p>
            <p
                className={cn(
                    "mt-0.5 text-[12px] leading-[18px] tabular-nums",
                    alerting ? "text-warning" : "text-text-2",
                )}
            >
                {localize("com_storage_quota.usage", {
                    0: usedText,
                    1: unlimited ? localize("com_storage_quota.unlimited") : totalText,
                })}
            </p>
            {!unlimited && (
                <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-fill-2">
                    <div
                        className={cn("h-full rounded-full", alerting ? "bg-warning" : "bg-text-3")}
                        style={{ width: `${percent}%` }}
                    />
                </div>
            )}
            {hintKey && (
                <p className="mt-1 text-[12px] leading-[18px] text-warning">{localize(hintKey)}</p>
            )}
        </div>
    );
}
