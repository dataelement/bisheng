import { useMemo, useRef } from 'react';
import type { ComposerReference } from './ComposerEditor';

interface Skill { name: string; display_name?: string; }
interface Space { id: string | number; type?: string; name?: string; }
interface Tool { id: string | number; name: string; }
const EMPTY_TOOLS: never[] = [];
const skillKey = (item: Skill) => `skill:${item.name}`;
const spaceKey = (item: Space) => `space:${item.type}:${item.id}`;
const toolKey = (item: Tool) => `tool:${item.id}`;

/** Keep metadata available for native undo while selected IDs follow the document. */
export function useComposerReferences<S extends Skill, K extends Space, T extends Tool = Tool>(
    skills: S[], spaces: K[], onSkillsChange: (items: S[]) => void, onSpacesChange?: (items: K[]) => void,
    tools: T[] = EMPTY_TOOLS, onToolsChange?: (items: T[]) => void,
) {
    const catalog = useRef({ skills: new Map<string, S>(), spaces: new Map<string, K>(), tools: new Map<string, T>() });
    skills.forEach((item) => catalog.current.skills.set(skillKey(item), item));
    spaces.forEach((item) => catalog.current.spaces.set(spaceKey(item), item));
    tools.forEach((item) => catalog.current.tools.set(toolKey(item), item));
    const references = useMemo<ComposerReference[]>(() => [
        ...skills.map((item) => ({ key: skillKey(item), kind: 'skill' as const, label: item.display_name || item.name })),
        ...spaces.map((item) => ({ key: spaceKey(item), kind: 'space' as const, label: String(item.name || item.id) })),
        ...tools.map((item) => ({ key: toolKey(item), kind: 'tool' as const, label: item.name })),
    ], [skills, spaces, tools]);
    const onReferencesChange = (keys: string[]) => {
        const nextSkills = keys.flatMap((key) => {
            const item = catalog.current.skills.get(key);
            return item ? [item] : [];
        });
        const nextSpaces = keys.flatMap((key) => {
            const item = catalog.current.spaces.get(key);
            return item ? [item] : [];
        });
        const nextTools = keys.flatMap((key) => {
            const item = catalog.current.tools.get(key);
            return item ? [item] : [];
        });
        if (nextTools.map(toolKey).join('\0') !== tools.map(toolKey).join('\0')) onToolsChange?.(nextTools);
        if (nextSkills.map(skillKey).join('\0') !== skills.map(skillKey).join('\0')) onSkillsChange(nextSkills);
        if (nextSpaces.map(spaceKey).join('\0') !== spaces.map(spaceKey).join('\0')) onSpacesChange?.(nextSpaces);
    };
    return { references, onReferencesChange };
}
