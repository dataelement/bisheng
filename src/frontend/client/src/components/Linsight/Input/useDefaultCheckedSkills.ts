/**
 * Admin-preselected skills ("默认勾选" in 技能管理): each time the user enters
 * task mode, skills flagged default_checked are merged into the selection as
 * ordinary chips the user can remove. Seeding is frontend-only on purpose — the
 * backend still mounts exactly the skills the request names.
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

// Whether the current task-mode entry was already seeded. Module scope (not a
// ref) because the input remounts when the welcome layout swaps to the
// conversation layout; a ref would re-add a chip the user just removed. Recoil
// is frozen for new atoms, and this flag needs no re-render anyway.
let seededForEntry = false;

interface UseDefaultCheckedSkillsOptions {
    taskMode: boolean;
    /** The 添加技能 entry switch; when it is off, nothing is preselected either. */
    skillEntryEnabled: boolean;
    setSkills: (update: (prev: TaskModeSkill[]) => TaskModeSkill[]) => void;
}

export function useDefaultCheckedSkills({ taskMode, skillEntryEnabled, setSkills }: UseDefaultCheckedSkillsOptions) {
    const prevTaskModeRef = useRef(taskMode);
    const active = taskMode && skillEntryEnabled;
    // Same query key as SkillSelector, so the picker and the seed share one cache.
    const { data, isFetching } = useQuery({
        queryKey: ['linsightSelectableSkills'],
        queryFn: getSelectableSkills,
        enabled: active,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });

    // Leaving task mode clears the selection (AiChatInput), so the next entry
    // starts over from the admin defaults.
    useEffect(() => {
        if (prevTaskModeRef.current && !taskMode) seededForEntry = false;
        prevTaskModeRef.current = taskMode;
    }, [taskMode]);

    useEffect(() => {
        // Wait for the fetch to settle so a stale cache cannot seed outdated defaults.
        if (!active || seededForEntry || !data || isFetching) return;
        seededForEntry = true;
        setSkills((prev) => mergeDefaultCheckedSkills(prev, data));
    }, [active, data, isFetching, setSkills]);
}
