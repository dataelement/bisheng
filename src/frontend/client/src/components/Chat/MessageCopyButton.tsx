import { DshMessageActionIcon } from "./DshMessageActionIcon";
import { useCallback, useState } from "react";
import { stripCitationHandles } from "~/components/Chat/Messages/Content/citationUtils";
import { useLocalize } from "~/hooks";
import { copyText } from "~/utils";

interface CopyButtonProps {
    text: string;
    /** F075: also drop unresolved [Sn] citation handles (daily chat answers).
        copyText always strips the private-use citation markers. */
    stripHandles?: boolean;
}

/** Copy button with a short "copied" state, used under chat messages. */
export function CopyButton({ text, stripHandles = false }: CopyButtonProps) {
    const localize = useLocalize();
    const [copied, setCopied] = useState(false);
    const handleCopy = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        copyText(stripHandles ? stripCitationHandles(text) : text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    }, [text, stripHandles]);

    return (
        <button
            type="button"
            onClick={handleCopy}
            className="dsh-message-action"
            title={localize('com_ui_copy')}
            aria-label={localize('com_ui_copy')}
        >
            <DshMessageActionIcon kind={copied ? "check" : "copy"} />
        </button>
    );
}
