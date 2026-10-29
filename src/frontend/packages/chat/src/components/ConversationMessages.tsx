import { useRef, type ReactNode, type RefObject } from 'react';
import { Outlined } from 'bisheng-icons';
import { asRecord, displayText, sourceId } from '../core/normalizeHistory';
import { splitMessageContent } from '../core/messageContent';
import type { RunPresentation } from '../core/describeRun';
import type { ChatMessage } from '../core/types';
import { ChoiceMessage } from './ChoiceMessage';
import { MessageBubble, ReasoningDetails } from './MessageBubble';
import { MessageFrame } from './MessageFrame';
import { GreetingMessage } from './GreetingMessage';

export interface ConversationLabels {
  confirm: string;
  confirmed: string;
  thinking: string;
  completed: string;
}
export interface ConversationMessageSlots {
  content: (text: string, message: ChatMessage) => ReactNode;
  avatar?: (message: ChatMessage) => ReactNode;
  title?: (message: ChatMessage) => string;
  attachments?: (message: ChatMessage) => ReactNode;
  selection?: (message: ChatMessage) => ReactNode;
  footer?: (message: ChatMessage, contentRef: RefObject<HTMLDivElement>) => ReactNode;
  runPresentation?: (message: ChatMessage) => RunPresentation;
}
export interface ConversationMessagesProps {
  messages: readonly ChatMessage[];
  canExecute: boolean;
  labels: ConversationLabels;
  slots: ConversationMessageSlots;
  onChoice?: (message: ChatMessage, value: string) => void | Promise<void>;
  onError?: (error: unknown) => void;
}
interface ConversationRowProps extends Omit<ConversationMessagesProps, 'messages'> { message: ChatMessage }
function ConversationRow({ message, canExecute, labels, slots, onChoice, onError }: ConversationRowProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const payload = asRecord(message.payload);
  const { text, reasoning } = splitMessageContent(message.text);
  const title = slots.title?.(message) ?? '';
  const logo = slots.avatar?.(message);
  if (message.kind === 'hidden') return null;
  if (['divider', 'separator'].includes(message.category)) {
    return <div className="flex items-center justify-center py-4 text-gray-400 text-sm">{slots.content(text, message)}</div>;
  }
  if (message.category === 'guide_word') return <GreetingMessage title={title} logo={logo} footer={slots.footer?.(message, contentRef)}>
    <div ref={contentRef}>{slots.content(text, message)}</div>{slots.attachments?.(message)}
  </GreetingMessage>;
  if (message.kind === 'reasoning') return <><ReasoningDetails text={text || message.reasoning} pending={!message.final} labels={labels} />{slots.attachments?.(message)}</>;
  if (message.kind === 'form' || message.kind === 'choice') {
    const options = Array.isArray(payload.options) ? payload.options.flatMap(item => {
      const option = asRecord(item); const id = sourceId(option.id);
      return id === undefined ? [] : [{ id, label: displayText(option.label) }];
    }) : [];
    return <MessageFrame title={title} logo={logo}><div className="group text-base text-[#0D1638] dark:text-[#CFD5E8]">
      <div ref={contentRef}>{slots.content(displayText(payload.msg), message)}</div>
      {slots.attachments?.(message)}
      <ChoiceMessage kind={message.kind === 'form' ? 'input' : 'choice'} canExecute={canExecute && !!onChoice}
        labels={labels} initialValue={displayText(payload.input_msg)} selectedValue={sourceId(payload.hisValue)} options={options}
        selectedIcon={<span className="size-5 bg-primary rounded-md p-1"><Outlined.Check size={14} className="text-white" /></span>}
        onSubmit={value => onChoice?.(message, value)} onError={onError} />
      <div className="flex justify-end py-2 opacity-0 group-hover:opacity-100 transition-opacity">{slots.footer?.(message, contentRef)}</div>
    </div></MessageFrame>;
  }
  if (message.kind === 'run') {
    const run = slots.runPresentation?.(message);
    if (message.category === 'node_run') return <div className="py-1 px-4 flex items-center font-bold gap-2 text-sm">
      {!message.final && <Outlined.Loading size={16} className="animate-spin text-primary" />}
      <span>{displayText(payload.name)}</span>
    </div>;
    return <div><details className="py-1 rounded-sm border max-w-[90%]">
      <summary className="flex items-center gap-2 px-4 py-2 cursor-pointer text-sm font-bold">
        {!message.final ? <Outlined.Loading size={16} className="animate-spin text-primary" />
          : (message.raw.interrupted || run?.unavailable) ? <Outlined.CloseCircle size={16} className="text-danger" /> : <Outlined.CheckCircle size={16} className="text-success" />}
        {run?.title || displayText(payload.name) || (message.final ? labels.completed : labels.thinking)}
      </summary>
      <div className="bg-[#F5F6F8] dark:bg-[#313336] px-4 py-2 whitespace-pre-wrap text-sm">{displayText(message.raw.thought ?? message.raw.intermediate_steps ?? message.payload)}</div>
    </details>{slots.attachments?.(message)}</div>;
  }
  const reasoningText = message.reasoning || reasoning;
  return <MessageBubble title={title} logo={logo} sender={displayText(message.raw.sender)} contentRef={contentRef}
    selection={slots.selection?.(message)}
    reasoning={<ReasoningDetails text={reasoningText} pending={!message.final} labels={labels} />}
    hideBody={!!reasoningText && !text && !message.files.length}
    pending={message.kind !== 'user' && !message.final && !text && !message.files.length}
    attachments={slots.attachments?.(message)}
    footer={message.final ? slots.footer?.(message, contentRef) : undefined}>
    {message.kind === 'user' ? <div className="text-[#0D1638] dark:text-[#CFD5E8] text-base break-all whitespace-break-spaces">{text}</div>
      : text && <div className="bs-mkdown text-base break-words [word-break:break-all]">{slots.content(text, message)}</div>}
    {!!message.raw.receiver && <p className="text-blue-500 text-sm">@ {displayText(asRecord(message.raw.receiver).user_name)}</p>}
  </MessageBubble>;
}
/** Both hosts bind services/actions around this single category dispatcher. */
export function ConversationMessages({ messages, ...props }: ConversationMessagesProps) {
  return <>{messages.map(message => <ConversationRow key={message.key} message={message} {...props} />)}</>;
}
