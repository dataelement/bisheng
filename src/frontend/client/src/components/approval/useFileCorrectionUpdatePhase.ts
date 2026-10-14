import { useEffect, useState } from "react";
import {
    getFileCorrection,
    type FileCorrectionUpdatePhase,
} from "~/api/fileCorrection";

const POLL_MS = 2000;

/**
 * 读取纠错单的采纳并更新阶段, 解析中时轮询直到结束或失败.
 */
export function useFileCorrectionUpdatePhase(
    correctionId: number,
    enabled: boolean,
): { phase: FileCorrectionUpdatePhase; status: string; reload: () => void } {
    const [phase, setPhase] = useState<FileCorrectionUpdatePhase>("idle");
    const [status, setStatus] = useState("pending");
    const [tick, setTick] = useState(0);

    useEffect(() => {
        if (!enabled || !correctionId) {
            setPhase("idle");
            return;
        }
        let cancelled = false;
        let timer: number | undefined;
        const load = async () => {
            try {
                const record = await getFileCorrection(correctionId);
                if (cancelled) return;
                const nextPhase = record.update_phase || "idle";
                setPhase(nextPhase);
                setStatus(record.status);
                if (record.status === "pending" && nextPhase === "updating") {
                    timer = window.setTimeout(() => setTick((value) => value + 1), POLL_MS);
                }
            } catch {
                if (!cancelled) setPhase("idle");
            }
        };
        void load();
        return () => {
            cancelled = true;
            if (timer) window.clearTimeout(timer);
        };
    }, [correctionId, enabled, tick]);

    return {
        phase,
        status,
        reload: () => setTick((value) => value + 1),
    };
}
