import { useMemo, useRef } from 'react';
import type { ComposerReference } from './ComposerEditor';

interface Skill { name: string; display_name?: string; }
interface Space { id: string | number; type?: string; name?: string; }
const skillKey = (item: Skill) => `skill:${item.name}`;
const spaceKey = (item: Space) => `space:${item.type}:${item.id}`;

/** Keep metadata available for native undo while selected IDs follow the document. */
export function useComposerReferences<S extends Skill, K extends Space>(
    skills: S[], spaces: K[], onSkillsChange: (items: S[]) => void, onSpacesChange?: (items: K[]) => void,
) {
    const catalog = useRef({ skills: new Map<string, S>(), spaces: new Map<string, K>() });
    skills.forEach((item) => catalog.current.skills.set(skillKey(item), item));
    spaces.forEach((item) => catalog.current.spaces.set(spaceKey(item), item));
    const references = useMemo<ComposerReference[]>(() => [
        ...skills.map((item) => ({ key: skillKey(item), label: `/${item.display_name || item.name}` })),
        ...spaces.map((item) => ({ key: spaceKey(item), label: `@${item.name || item.id}` })),
    ], [skills, spaces]);
    const onReferencesChange = (keys: string[]) => {
        const nextSkills = keys.flatMap((key) => {
            const item = catalog.current.skills.get(key);
            return item ? [item] : [];
        });
        const nextSpaces = keys.flatMap((key) => {
            const item = catalog.current.spaces.get(key);
            return item ? [item] : [];
        });
        if (nextSkills.map(skillKey).join('\0') !== skills.map(skillKey).join('\0')) onSkillsChange(nextSkills);
        if (nextSpaces.map(spaceKey).join('\0') !== spaces.map(spaceKey).join('\0')) onSpacesChange?.(nextSpaces);
    };
    return { references, onReferencesChange };
}
