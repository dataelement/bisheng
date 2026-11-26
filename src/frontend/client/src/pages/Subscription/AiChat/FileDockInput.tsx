interface FileDockInputProps {
  value: string;
  onChange: (v: string) => void;
  onSend: (text: string) => void;
  model: ModelSelectProps;
  disabled: boolean;
  isStreaming: boolean;
  placeholder: string;
  variant: "box" | "line";
  fixedHeight?: number;
  onFocusChange?: (focused: boolean) => void;
}
import { useSendInputMethod } from "~/hooks/useSendInputMethod";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { TextareaAutosize } from "~/components/ui";
import AiModelSelect from "~/components/Chat/AiModelSelect";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { SendIcon } from "~/components/svg";
import { usePrefersMobileLayout } from "~/hooks";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import { cn } from "~/utils";
import type { ModelSelectProps } from "./ArticleDockInput";
export function FileDockInput({
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
}: FileDockInputProps) {
  const [multiline, setMultiline] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const { onSendPointerDown, consumeTouchSend } = useSendInputMethod();
  const { data: modelData } = useGetWorkbenchModelsQuery();
  const showVoice = !!modelData?.asr_model?.id;
  const isH5 = usePrefersMobileLayout();

  // Mobile is always two-row (textarea on top, model + send below) — matches the file-list input.
  const stacked = variant === "line" || multiline || isH5;

  useEffect(() => {
    if (!value) setMultiline(false);
  }, [value]);

  const submit = (touchSend = false) => {
    const trimmed = value.trim();
    if (!trimmed || disabled || isStreaming) return;
    onSend(trimmed);
    if (taRef.current) taRef.current.style.height = "auto";
    // A touch send dismisses the keyboard; mouse and keyboard sends keep focus.
    // The grey overlay (driven by focus → keyboardVisible) clears instead of lingering.
    if (touchSend) taRef.current?.blur();
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
        onPointerDown={onSendPointerDown}
        onClick={(event) => submit(consumeTouchSend(event))}
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
      {!stacked && modelSelect && (
        <div key="model-inline" className="shrink-0">
          {modelSelect}
        </div>
      )}

      <div
        key="textarea"
        className={cn(
          stacked ? "w-full" : "min-w-0 flex-1",
          fixedHeight && "min-h-0 flex-1",
        )}
      >
        <TextareaAutosize
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onHeightChange={(h: number, meta?: { rowHeight?: number }) => {
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

      <div
        key="controls"
        className={cn(
          "flex items-center",
          stacked ? "w-full justify-between" : "shrink-0",
        )}
      >
        {stacked && modelSelect && (
          <div className="shrink-0">{modelSelect}</div>
        )}
        {sendControls}
      </div>
    </div>
  );
}
