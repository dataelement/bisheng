import { Outlined } from 'bisheng-icons';

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
        <div className="dsh-composer-references">
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
