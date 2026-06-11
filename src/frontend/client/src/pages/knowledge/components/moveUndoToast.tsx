/**
 * TEMPORARY standalone "move succeeded — undo" toast (F034).
 *
 * The shared `useToastContext` toast has no action slot, and the move-undo flow
 * needs an inline 「撤回」 button. Rather than extend the global toast now, this
 * is a self-contained imperative singleton rendered into its own portal. It is
 * intentionally isolated so it can be swapped out when the toast UI is unified.
 *
 * Usage: showMoveUndoToast({ message, actionLabel, onAction }).
 */
import { Check } from "lucide-react";
import { createRoot, type Root } from "react-dom/client";

interface ShowMoveUndoToastArgs {
    message: string;
    actionLabel: string;
    onAction: () => void;
    /** Auto-dismiss delay in ms. */
    duration?: number;
}

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let timer: number | null = null;

function teardown() {
    if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
    }
    // Defer unmount so we never unmount the toast's own root from inside its
    // click handler (React warns on synchronous unmount during render).
    const r = root;
    const h = host;
    root = null;
    host = null;
    if (r) window.setTimeout(() => r.unmount(), 0);
    if (h) window.setTimeout(() => h.remove(), 0);
}

function MoveUndoToastView({
    message,
    actionLabel,
    onAction,
}: {
    message: string;
    actionLabel: string;
    onAction: () => void;
}) {
    return (
        <div className="pointer-events-none fixed left-1/2 top-6 z-[9999] -translate-x-1/2">
            <div className="pointer-events-auto flex items-center gap-3 rounded-full bg-white px-4 py-2.5 shadow-[0_4px_16px_rgba(0,0,0,0.12)]">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-[#00B42A]">
                    <Check className="size-3 text-white" strokeWidth={3} />
                </span>
                <span className="whitespace-nowrap text-sm text-[#1d2129]">{message}</span>
                <button
                    type="button"
                    onClick={onAction}
                    className="shrink-0 text-sm text-[#86909c] transition-colors hover:text-[#165dff]"
                >
                    {actionLabel}
                </button>
            </div>
        </div>
    );
}

export function showMoveUndoToast({ message, actionLabel, onAction, duration = 5000 }: ShowMoveUndoToastArgs) {
    teardown();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    root.render(
        <MoveUndoToastView
            message={message}
            actionLabel={actionLabel}
            onAction={() => {
                onAction();
                teardown();
            }}
        />,
    );
    timer = window.setTimeout(teardown, duration);
}
