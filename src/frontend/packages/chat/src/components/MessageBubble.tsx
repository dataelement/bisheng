import { Outlined } from 'bisheng-icons';
import { useState, type ReactNode, type Ref } from 'react';

export interface ReasoningDetailsProps {
  text: string;
  pending: boolean;
  labels: { thinking: string; completed: string };
}
/** Reasoning presentation extracted from the client answer message. */
export function ReasoningDetails({ text, pending, labels }: ReasoningDetailsProps) {
  const [open, setOpen] = useState(true);
  if (!text) return null;
  return <div className="py-1 mb-4">
    <div className="rounded-sm border">
      <div role="button" tabIndex={0} aria-expanded={open}
        className="flex justify-between items-center px-4 py-2 cursor-pointer"
        onClick={() => setOpen(value => !value)}
        onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setOpen(value => !value); } }}>
        <div className="flex items-center font-bold gap-2 text-sm">
          {pending ? <Outlined.Loading size={16} className="text-primary duration-300 animate-spin" />
            : <Outlined.CheckCircle size={16} className="text-success" />}
          <span>{pending ? labels.thinking : labels.completed}</span>
        </div>
        <Outlined.Down size={16} className={open ? 'rotate-180' : undefined} />
      </div>
      {open && <div className="bg-[#F5F6F8] dark:bg-[#313336] px-4 py-2 overflow-hidden text-sm">
        {text.split('\n').map((line, index) => <p className="text-md mb-1 text-muted-foreground" key={index}>{line}</p>)}
      </div>}
    </div>
  </div>;
}

export interface MessageBubbleProps {
  title?: string;
  logo?: ReactNode;
  sender?: string;
  selection?: ReactNode;
  reasoning?: ReactNode;
  children?: ReactNode;
  attachments?: ReactNode;
  footer?: ReactNode;
  pending?: boolean;
  contentRef?: Ref<HTMLDivElement>;
  hideBody?: boolean;
}
/** Host actions/resources are slots; one shared message layout owns both apps. */
export function MessageBubble({ title, logo, sender, selection, reasoning, children, attachments, footer, pending, contentRef, hideBody }: MessageBubbleProps) {
  return <div className="bisheng-message flex w-full py-2 items-start gap-2">
    {selection}
    <div className="w-fit group max-w-[90%]">
      {reasoning}
      {!hideBody && <>
        <div className="flex gap-2 items-center">{sender ? <p className="text-gray-600 text-xs mb-1 ml-2">{sender}</p> : <p />}</div>
        <div className="min-h-8 px-4 rounded-2xl">
          <div className="flex gap-3">
            {logo}
            <div className="min-w-0">
              {title && <p className="select-none font-semibold text-base mb-1">{title}</p>}
              <div ref={contentRef}>
                {children}
                {attachments}
                {pending && <Outlined.Loading size={24} className="animate-spin text-primary" />}
              </div>
            </div>
          </div>
        </div>
      </>}
      {footer && <div className="flex justify-between">{footer}</div>}
    </div>
  </div>;
}
