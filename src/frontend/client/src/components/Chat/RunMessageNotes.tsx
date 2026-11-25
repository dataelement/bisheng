/**
 * F004 — one-line status notes under a message of the unified agent runtime.
 * Both are neutral: neither is a failure.
 */
import { useLocalize } from "~/hooks";

/** Under a user message sent while a run was busy and not read by the agent yet (AC-13/AC-14). */
export function MessageQueuedNote() {
    const localize = useLocalize();
    return (
        <div role="status" data-testid="message-queued" className="mt-1 flex items-center gap-1.5 text-caption text-text-3">
            <span aria-hidden className="size-1.5 rounded-full bg-current opacity-60 animate-pulse" />
            {localize("dshChat.messageQueued")}
        </div>
    );
}

/** Under an answer whose run the user stopped: what was written so far stays above it. */
export function RunStoppedNote() {
    const localize = useLocalize();
    return (
        <div role="status" data-testid="message-stopped" className="mt-1 flex items-center gap-1.5 text-caption text-text-3">
            <span aria-hidden className="size-1.5 rounded-[1px] bg-current opacity-60" />
            {localize("runPlan.stopped")}
        </div>
    );
}
