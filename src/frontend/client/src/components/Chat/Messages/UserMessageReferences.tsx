import { Fragment } from "react";
import type { SentComposerReference } from "../Input/composerReferences";
import { InlineChatReference } from "../InlineChatReference";

interface UserMessageReferencesProps {
    text: string;
    references: SentComposerReference[];
}

export function UserMessageReferences({ text, references }: UserMessageReferencesProps) {
    const ordered = [...references].sort((first, second) => first.offset - second.offset);
    return <>
        {ordered.map(({ kind, label, offset, is_tag }, index) => (
            <Fragment key={index}>
                {text.slice(ordered[index - 1]?.offset ?? 0, offset)}
                <InlineChatReference kind={is_tag ? "tag" : kind} label={label} />
            </Fragment>
        ))}
        {text.slice(ordered[ordered.length - 1]?.offset ?? 0)}
    </>;
}
