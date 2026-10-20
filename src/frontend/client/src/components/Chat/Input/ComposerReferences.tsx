import { Outlined } from 'bisheng-icons';
import { useLayoutEffect, useRef } from 'react';

interface SkillReference {
    name: string;
    display_name?: string;
}

interface SpaceReference {
    id: string | number;
    type?: string;
    name?: string;
}

interface ComposerReferencesProps {
    skills: SkillReference[];
    spaces: SpaceReference[];
    disabled?: boolean;
    onRemoveSkill: (skill: SkillReference) => void;
    onRemoveSpace: (space: SpaceReference) => void;
    onFocusInput: () => void;
}

/** References use the native Work text treatment; attachment cards live above them. */
export function ComposerReferences({
    skills, spaces, disabled, onRemoveSkill, onRemoveSpace, onFocusInput,
}: ComposerReferencesProps) {
    const railRef = useRef<HTMLDivElement>(null);
    // Reserve the actual inline footprint in the existing textarea. This keeps
    // native IME, paste, undo and selection behavior while references own IDs.
    useLayoutEffect(() => {
        const rail = railRef.current;
        const writing = rail?.parentElement;
        if (!rail || !writing) return;
        const measure = () => {
            const last = rail.lastElementChild;
            if (!last) return;
            const bounds = rail.getBoundingClientRect();
            const end = last.getBoundingClientRect();
            const indent = end.right - bounds.left + 8;
            const nextLine = bounds.width - indent < 64;
            writing.style.setProperty('--dsh-reference-indent', `${nextLine ? 0 : indent}px`);
            writing.style.setProperty('--dsh-reference-top', `${end.top - bounds.top + (nextLine ? 24 : 0)}px`);
        };
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(rail);
        return () => {
            observer.disconnect();
            writing.style.removeProperty('--dsh-reference-indent');
            writing.style.removeProperty('--dsh-reference-top');
        };
    }, [skills, spaces]);
    const references = [
        ...skills.map((skill) => ({
            key: `skill:${skill.name}`,
            label: `/${skill.display_name || skill.name}`,
            remove: () => onRemoveSkill(skill),
        })),
        ...spaces.map((space) => ({
            key: `space:${space.type}:${space.id}`,
            label: `@${space.name || space.id}`,
            remove: () => onRemoveSpace(space),
        })),
    ];
    return (
        <div className="dsh-composer-references" ref={railRef}>
            {references.map(({ key, label, remove }) => (
                <span className="dsh-composer-reference" key={key}>
                    <button type="button" className="dsh-reference-label" title={label}
                        disabled={disabled} onClick={onFocusInput}
                        onKeyDown={(event) => {
                            if (event.key === 'Backspace' || event.key === 'Delete') {
                                event.preventDefault();
                                remove();
                                onFocusInput();
                            }
                        }}>{label}</button>
                    <button type="button" className="dsh-reference-remove" aria-label={`Remove ${label}`}
                        disabled={disabled} onClick={() => { remove(); onFocusInput(); }}>
                        <Outlined.Close size={12} />
                    </button>
                </span>
            ))}
        </div>
    );
}
