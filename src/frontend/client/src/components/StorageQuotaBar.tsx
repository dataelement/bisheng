import { useMemo } from "react";
import { Progress } from "~/components/ui/Progress";
import { useEffectiveQuota } from "~/hooks/useEffectiveQuota";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

/** Bar turns orange at 80% of the cap and red once the cap is reached. */
const WARN_PCT = 80;

// Trim a GB value for display: 2 decimals, then drop trailing zeros
// (0.09 → "0.09", 82.4 → "82.4", 100 → "100", 2.5 → "2.5").
function trimGb(gb: number): string {
    if (!Number.isFinite(gb)) return "0";
    return gb.toFixed(2).replace(/\.?0+$/, "");
}

interface StorageQuotaBarProps {
    className?: string;
}

/**
 * Knowledge-space file-upload quota meter (已使用 X GB / 上限 Y GB), rendered
 * inside the user account popup so users can see their storage budget before
 * they hit the upload cap instead of only learning about it via an error toast.
 *
 * Data comes from /api/v1/quota/effective via useEffectiveQuota — for
 * `knowledge_space_file` both `user_used` and `effective` are already in GB, and
 * `effective === -1` means unlimited (no progress bar shown).
 */
export function StorageQuotaBar({ className }: StorageQuotaBarProps) {
    const localize = useLocalize();
    const { quotas, loading } = useEffectiveQuota();
    const item = quotas["knowledge_space_file"];

    const used = Number(item?.user_used) || 0;
    const total = Number(item?.effective);
    const unlimited = total === -1;

    const percent = useMemo(() => {
        if (unlimited) return 0;
        if (total > 0) return Math.min(100, Math.max(0, (used / total) * 100));
        // total === 0 = prohibited: full bar once anything is used.
        return used > 0 ? 100 : 0;
    }, [used, total, unlimited]);

    // Don't flash an empty bar before the first fetch resolves.
    if (loading || !item) return null;

    // Static class strings (not interpolated) so Tailwind's JIT keeps them.
    // `[&>div]` targets the Radix Progress indicator, overriding its bg-primary.
    const indicatorClass =
        percent >= 100
            ? "[&>div]:bg-[#f53f3f]"
            : percent >= WARN_PCT
              ? "[&>div]:bg-[#ff7d00]"
              : "[&>div]:bg-blue-500";

    const usedText = trimGb(used);
    const label = unlimited
        ? localize("com_knowledge.storage_quota_unlimited", { used: usedText })
        : localize("com_knowledge.storage_quota_used", { used: usedText, total: trimGb(total) });

    return (
        <div className={cn("px-3 py-2", className)}>
            <div className="mb-1.5 text-[12px] text-[#86909c]">
                {localize("com_knowledge.storage_quota_title")}
            </div>
            {!unlimited && (
                <Progress value={percent} className={cn("h-1.5 bg-[#f2f3f5]", indicatorClass)} />
            )}
            <div className={cn("text-[12px] text-[#4e5969]", !unlimited && "mt-1.5")}>{label}</div>
        </div>
    );
}
