/**
 * Admin-preselected skills ("默认勾选" in 技能管理): skills flagged
 * default_checked are merged into the 'new' selection as soon as the 添加技能
 * entry is available, so the picker shows them checked in daily mode too, and
 * they become ordinary chips the user can remove once task mode is on. Daily
 * turns never send skills, so the daily-mode checkmark mounts nothing. Seeding
 * is frontend-only on purpose — the backend still mounts exactly the skills the
 * request names.
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { getSelectableSkills, type SelectableSkill } from '~/api/linsight';
import type { TaskModeSkill } from '~/store/linsight';

/** Append preselected skills not already in the selection; keeps the user's order. */
export function mergeDefaultCheckedSkills(
    selected: TaskModeSkill[],
    selectable: SelectableSkill[],
): TaskModeSkill[] {
    const have = new Set(selected.map((s) => s.name));
    const added = selectable
        .filter((s) => s.default_checked && !have.has(s.name))
        .map(({ name, display_name, description }) => ({ name, display_name, description }));
    return added.length ? [...selected, ...added] : selected;
}

// Whether the current selection was already seeded. Module scope (not a
// ref) because the input remounts when the welcome layout swaps to the
// conversation layout; a ref would re-add a chip the user just removed. Recoil
// is frozen for new atoms, and this flag needs no re-render anyway.
let seeded = false;

interface UseDefaultCheckedSkillsOptions {
    taskMode: boolean;
    /** The 添加技能 entry switch; when it is off, nothing is preselected either. */
    skillEntryEnabled: boolean;
    setSkills: (update: (prev: TaskModeSkill[]) => TaskModeSkill[]) => void;
}

export function useDefaultCheckedSkills({ taskMode, skillEntryEnabled, setSkills }: UseDefaultCheckedSkillsOptions) {
    const prevTaskModeRef = useRef(taskMode);
    const active = skillEntryEnabled;
    // Same query key as SkillSelector, so the picker and the seed share one cache.
    const { data, isFetching } = useQuery({
        queryKey: ['linsightSelectableSkills'],
        queryFn: getSelectableSkills,
        enabled: active,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });

    // Leaving task mode clears the selection (AiChatInput's effect, which runs
    // before this hook's), so put the admin defaults back right away.
    useEffect(() => {
        if (prevTaskModeRef.current && !taskMode) seeded = false;
        prevTaskModeRef.current = taskMode;
    }, [taskMode]);

    useEffect(() => {
        // Wait for the fetch to settle so a stale cache cannot seed outdated defaults.
        if (!active || seeded || !data || isFetching) return;
        seeded = true;
        setSkills((prev) => mergeDefaultCheckedSkills(prev, data));
        // taskMode re-runs this after the reset above; the flag is module state.
    }, [active, taskMode, data, isFetching, setSkills]);
}
