/**
 * Personal storage state, derived from the `knowledge_space_file` quota item.
 * `unknown` covers "not loaded yet / request failed" and never blocks a write.
 */
export type PersonalStorageStatus =
    | "unknown"
    | "unlimited"
    | "normal"
    | "warning"
    | "full"
    | "exceeded";

const WARNING_RATIO = 0.8;

/** Server quota values are GB; upload file sizes are bytes. */
const GB_BYTES = 1024 ** 3;

/**
 * One unit for both operands so the fraction stays readable, chosen from the
 * denominator (or, when unlimited, the numerator): MB under 1 GB, GB otherwise.
 * Trailing zeros read as false precision on a capacity readout ("1.50 GB").
 */
function formatSize(valueGb: number, unit: "MB" | "GB"): string {
    const value = unit === "MB" ? valueGb * 1024 : valueGb;
    return `${parseFloat(value.toFixed(2))} ${unit}`;
}

export interface PersonalStorage {
    status: PersonalStorageStatus;
    /** Blocks new `knowledge_space_file` usage; an unknown quota stays permissive. */
    exhausted: boolean;
    usedText: string;
    totalText: string;
    /** Bar is hidden when unlimited; clamped so an overage still reads as full. */
    percent: number;
    /**
     * Remaining capacity in bytes (effective - user_used). Null when the quota
     * is unknown or unlimited — those states never block on batch size.
     */
    remainingBytes: number | null;
}

/**
 * Server values are GB. Status comes from the raw numbers, never from the
 * rounded display strings, so a value just under the cap cannot round up into
 * the "full" state and wrongly block an upload.
 */
export function derivePersonalStorage(
    userUsed: number | undefined,
    effective: number | undefined,
): PersonalStorage {
    const status = deriveStatus(userUsed, effective);
    if (status === "unknown") {
        return { status, exhausted: false, usedText: "", totalText: "", percent: 0, remainingBytes: null };
    }
    const used = userUsed as number;
    const total = effective as number;
    const unit: "MB" | "GB" = (status === "unlimited" ? used : total) < 1 ? "MB" : "GB";
    const exhausted = status === "full" || status === "exceeded";

    return {
        status,
        exhausted,
        usedText: formatSize(used, unit),
        totalText: status === "unlimited" ? "" : formatSize(total, unit),
        percent: exhausted ? 100 : total > 0 ? Math.min(100, (used / total) * 100) : 0,
        remainingBytes: status === "unlimited" ? null : (total - used) * GB_BYTES,
    };
}

function deriveStatus(
    userUsed: number | undefined,
    effective: number | undefined,
): PersonalStorageStatus {
    if (userUsed == null || effective == null) return "unknown";
    if (effective === -1) return "unlimited";
    // Strictly greater, so a zero cap with nothing stored still reads as "full".
    if (userUsed > effective) return "exceeded";
    if (userUsed === effective) return "full";
    return userUsed / effective >= WARNING_RATIO ? "warning" : "normal";
}
