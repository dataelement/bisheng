import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { TextareaAutosize } from "~/components/ui";
import AiModelSelect from "~/components/Chat/AiModelSelect";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { SendIcon } from "~/components/svg";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import type { BsConfig } from "~/types/chat";
import { cn } from "~/utils";

export interface ModelSelectProps {
    options?: BsConfig["models"];
    value: number;
    onChange: (val: string) => void;
    /** Value repair by AiModelSelect — applied but never remembered. */
    onAutoChange?: (val: string) => void;
    disabled?: boolean;
}

/**
 * The dock input: model select · auto-grow textarea (≤180px) · mic · send.
 * `variant` controls both the frame and the layout:
 *   - 'box'  collapsed: a white rounded bordered box. Single row while the text
 *            fits one line; restacks (textarea on top, model + send below) on wrap.
 *   - 'line' expanded: no box; sits inside the chat card on a white fill with a top
 *            divider. Always two rows — full-width textarea over a model + send row.
 */
export function DockInput({
    value,
    onChange,
    onSend,
    model,
    disabled,
    isStreaming,
    placeholder,
    variant,
    fixedHeight,
    onFocusChange,
}: {
    value: string;
    onChange: (v: string) => void;
    onSend: (text: string) => void;
    model: ModelSelectProps;
    disabled: boolean;
    isStreaming: boolean;
    placeholder: string;
    variant: "box" | "line";
    /** When set, force the input container to this px height (e.g. mobile-expanded = 120). */
    fixedHeight?: number;
    /** Forward textarea focus/blur so the panel can dim the page while typing. */
    onFocusChange?: (focused: boolean) => void;
}) {
    const [multiline, setMultiline] = useState(false);
    const taRef = useRef<HTMLTextAreaElement>(null);
    const { data: modelData } = useGetWorkbenchModelsQuery();
    const showVoice = !!modelData?.asr_model?.id;

    // Expanded ('line') is always two rows; collapsed ('box') restacks only on wrap.
    const stacked = variant === "line" || multiline;

    // Reset to single row when the text is cleared (incl. parent-driven clears on send).
    useEffect(() => {
        if (!value) setMultiline(false);
    }, [value]);

    const submit = () => {
        const trimmed = value.trim();
        if (!trimmed || disabled || isStreaming) return;
        onSend(trimmed);
        if (taRef.current) taRef.current.style.height = "auto";
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!isStreaming) submit();
        }
    };

    const modelSelect = model.options ? (
        <AiModelSelect
            disabled={!!disabled}
            value={model.value}
            options={model.options}
            onChange={model.onChange}
            onAutoChange={model.onAutoChange}
        />
    ) : null;

    const sendControls = (
        <div className="flex shrink-0 items-center gap-1.5">
            {showVoice && (
                <SpeechToTextComponent
                    disabled={disabled}
                    onChange={(e) => onChange(value + e)}
                />
            )}
            <button
                type="button"
                onClick={submit}
                disabled={!value.trim() || disabled || isStreaming}
                className="btn-brand-primary flex h-8 w-8 items-center justify-center rounded-full bg-primary transition-all duration-200 disabled:cursor-not-allowed disabled:bg-fill-3 [&>svg]:text-white disabled:[&>svg]:text-text-2"
                aria-label="Send message"
            >
                <SendIcon size={18} />
            </button>
        </div>
    );

    return (
        <div
            className={cn(
                "flex bg-white",
                variant === "box"
                    ? "rounded-[20px] border border-border-base p-3 shadow-[0_2px_12px_rgba(0,0,0,0.06)]"
                    : "border-t border-[#EBEBEB] p-3",
                stacked ? "flex-col gap-2" : "items-center gap-2",
            )}
            style={fixedHeight ? { height: `${fixedHeight}px` } : undefined}
        >
            {/* Single-row only: model select sits to the left of the textarea. */}
            {!stacked && modelSelect && (
                <div key="model-inline" className="shrink-0">{modelSelect}</div>
            )}

            {/* Textarea — keyed so it stays mounted across the layout switch. */}
            <div key="textarea" className={cn(stacked ? "w-full" : "min-w-0 flex-1", fixedHeight && "min-h-0 flex-1")}>
                <TextareaAutosize
                    ref={taRef}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onHeightChange={(h: number, meta?: { rowHeight?: number }) => {
                        // Only escalate to multi-row; collapsing back on height would
                        // oscillate (wider row re-fits to one line → infinite loop).
                        if (h > (meta?.rowHeight ?? 24) * 1.4) setMultiline(true);
                    }}
                    onFocus={() => onFocusChange?.(true)}
                    onBlur={() => onFocusChange?.(false)}
                    disabled={disabled}
                    placeholder={placeholder}
                    rows={1}
                    className={cn(
                        "m-0 block w-full resize-none bg-transparent py-1 text-sm leading-6 outline-none placeholder-text-3",
                        fixedHeight ? "h-full max-h-full overflow-y-auto" : "max-h-[180px]",
                    )}
                />
            </div>

            {/* Controls. Single-row: mic + send on the right. Two-row: model left, mic + send right. */}
            <div
                key="controls"
                className={cn("flex items-center", stacked ? "w-full justify-between" : "shrink-0")}
            >
                {stacked && modelSelect && <div className="shrink-0">{modelSelect}</div>}
                {sendControls}
            </div>
        </div>
    );
}
