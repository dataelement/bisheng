/** Seed admin defaults once for the shared Chat skill selection, across execution modes. */
import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
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
    /** The 添加技能 entry switch; when it is off, nothing is preselected either. */
    skillEntryEnabled: boolean;
    setSkills: (update: (prev: TaskModeSkill[]) => TaskModeSkill[]) => void;
}

export function useDefaultCheckedSkills({ skillEntryEnabled, setSkills }: UseDefaultCheckedSkillsOptions) {
    const active = skillEntryEnabled;
    // Same query key as SkillSelector, so the picker and the seed share one cache.
    const { data, isFetching } = useQuery({
        queryKey: ['linsightSelectableSkills'],
        queryFn: getSelectableSkills,
        enabled: active,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });

    useEffect(() => {
        // Wait for the fetch to settle so a stale cache cannot seed outdated defaults.
        if (!active || seeded || !data || isFetching) return;
        seeded = true;
        setSkills((prev) => mergeDefaultCheckedSkills(prev, data));
    }, [active, data, isFetching, setSkills]);
}
