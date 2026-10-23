import { Button, Textarea, Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useRef, useState, type ClipboardEventHandler, type CompositionEventHandler, type FormEventHandler, type ReactNode, type RefObject } from 'react';
export interface ConversationComposerProps {
  inputRef: RefObject<HTMLTextAreaElement>;
  canExecute: boolean;
  inputDisabled?: boolean;
  busy?: boolean;
  hasAttachments?: boolean;
  attachmentDisabled?: boolean;
  showStop?: boolean;
  stopDisabled?: boolean;
  showRestart?: boolean;
  restartDisabled?: boolean;
  labels: { send: string; stop: string; restart: string; attach?: string };
  placeholder?: string;
  hint?: string;
  attachments?: ReactNode;
  voice?: ReactNode;
  overlay?: ReactNode;
  leadingActions?: ReactNode;
  onSend: () => void | Promise<unknown>;
  onAttach?: () => void;
  onStop?: () => void | Promise<unknown>;
  onRestart?: () => void | Promise<unknown>;
  onInput?: FormEventHandler<HTMLTextAreaElement>;
  onPaste?: ClipboardEventHandler<HTMLTextAreaElement>;
  onCompositionStart?: CompositionEventHandler<HTMLTextAreaElement>;
  onCompositionEnd?: CompositionEventHandler<HTMLTextAreaElement>;
  onError?: (error: unknown) => void;
}
/** Client composer presentation; host owns drafts, uploads, voice and transport. */
export function ConversationComposer({ inputRef, canExecute, inputDisabled = false, busy = false, hasAttachments = false, attachmentDisabled = false,
  showStop, stopDisabled, showRestart, restartDisabled, labels, placeholder, hint, attachments, voice, overlay, leadingActions,
  onSend, onAttach, onStop, onRestart, onInput, onPaste, onCompositionStart, onCompositionEnd, onError }: ConversationComposerProps) {
  const inFlight = useRef(false);
  const [pending, setPending] = useState(false);
  const sendDisabled = !canExecute || inputDisabled || busy || pending;
  const handleSend = async () => {
    if (sendDisabled || inFlight.current || (!inputRef.current?.value.trim() && !hasAttachments)) return;
    inFlight.current = true; setPending(true);
    try { await onSend(); } catch (error) { onError?.(error); }
    finally { inFlight.current = false; setPending(false); }
  };
  return <div className="z-10 w-full shrink-0 bg-[#fff] dark:bg-[#1B1B1B]">
    <div className="mx-auto w-full max-w-[800px] px-4 pt-1">
      {overlay}
      <div className="relative px-4 rounded-3xl" style={{ backgroundColor: 'var(--surface-tertiary, rgb(var(--fill-2)))' }}>
        {attachments}
        {leadingActions}
        <div className="flex items-center gap-2 absolute right-3 bottom-3 z-10">
          {onAttach && labels.attach && <Tooltip content={labels.attach}><Button shape="circle" iconOnly color="default" variant="text" aria-label={labels.attach}
            disabled={!canExecute || inputDisabled || attachmentDisabled} onClick={() => { if (canExecute && !inputDisabled && !attachmentDisabled) onAttach(); }}><Outlined.Attachment size={18} /></Button></Tooltip>}
          {voice}
          {showStop ? <Tooltip content={labels.stop}><Button shape="circle" iconOnly aria-label={labels.stop}
            disabled={!canExecute || stopDisabled || !onStop} onClick={() => { if (canExecute && !stopDisabled) void onStop?.(); }}>
            <span className="size-3 bg-current rounded-[2px]" />
          </Button></Tooltip> : <Tooltip content={labels.send}><Button id="bs-send-btn" shape="circle" iconOnly aria-label={labels.send}
            disabled={sendDisabled} onClick={() => void handleSend()}><Outlined.Send size={18} /></Button></Tooltip>}
        </div>
        {showRestart && onRestart && <div className="absolute w-full flex justify-center left-0 -top-14">
          <Button variant="filled" disabled={!canExecute || restartDisabled} onClick={() => { if (canExecute && !restartDisabled) void onRestart(); }}>
            <Outlined.Refresh size={16} />{labels.restart}
          </Button>
        </div>}
        <Textarea id="bs-send-input" ref={inputRef} rows={2} style={{ height: 56 }} disabled={!canExecute || inputDisabled}
          placeholder={placeholder} borderless className="w-full" textareaClassName="resize-none p-4 pr-10 text-md min-h-24 max-h-80 scrollbar-hide"
          onInput={event => { event.currentTarget.style.height = 'auto'; event.currentTarget.style.height = `${event.currentTarget.scrollHeight}px`; onInput?.(event); }}
          onPaste={onPaste} onCompositionStart={onCompositionStart} onCompositionEnd={onCompositionEnd}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void handleSend(); }
          }} />
      </div>
      <p className="text-center text-sm pt-2 pb-4 text-gray-400">{hint}</p>
    </div>
  </div>;
}
