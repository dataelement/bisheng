/** F004 — progress of a run's plan (AC-08). Pure; re-exported by `runStore`. */
import type { RunPlanItem } from './runStore';

export interface PlanProgress {
    done: number;
    total: number;
}

const EMPTY_PROGRESS: PlanProgress = Object.freeze({ done: 0, total: 0 }) as PlanProgress;
// Small identity cache so a selector returns the same object while the plan
// array is unchanged (each `plan` event replaces the array).
const PROGRESS_CACHE_SIZE = 16;
const progressCache: Array<{ items: RunPlanItem[]; progress: PlanProgress }> = [];

/** Completed rows / rows (AC-08). Cancelled rows count in neither number. */
export function planProgressOf(items: RunPlanItem[] | null | undefined): PlanProgress {
    if (!items || items.length === 0) return EMPTY_PROGRESS;
    const cached = progressCache.find((entry) => entry.items === items);
    if (cached) return cached.progress;
    const live = items.filter((i) => i.status !== 'cancelled');
    const progress = { done: live.filter((i) => i.status === 'completed').length, total: live.length };
    progressCache.push({ items, progress });
    if (progressCache.length > PROGRESS_CACHE_SIZE) progressCache.shift();
    return progress;
}
