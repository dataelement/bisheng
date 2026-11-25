import { Outlined } from "bisheng-icons";
import "./inline-chat-reference.css";

const referenceIcons = {
    skill: Outlined.Skill,
    tool: Outlined.Hammer,
    space: Outlined.Book,
    tag: null,
};

interface InlineChatReferenceProps {
    kind: keyof typeof referenceIcons;
    label: string;
}

export function InlineChatReference({ kind, label }: InlineChatReferenceProps) {
    const Icon = referenceIcons[kind];
    return (
        <span className="dsh-inline-reference" data-reference-kind={kind} title={label}>
            {Icon && <Icon size={14} aria-hidden="true" focusable="false" />}
            <span className="dsh-inline-reference-label">{label}</span>
        </span>
    );
}
