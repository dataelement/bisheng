import { CopyMessageAction } from '@bisheng/chat';
import { useLocalize } from '~/hooks';
import { splitMessageContent, type ChatMessage } from '@bisheng/chat/core';
import type { RefObject } from 'react';
import { useParams } from 'react-router-dom';
import type { ChatMessageType } from '~/@types/chat';
import CitationReferencesDrawer, { type CitationReferencesDesktopPayload } from '~/components/Chat/Messages/Content/CitationReferencesDrawer';
import { ExportSelectionButton } from '~/components/Chat/MessageSelection';
import { TextToSpeechButton } from '~/components/Voice/TextToSpeechButton';
import { copyText, formatStrTime } from '~/utils';
import { parseAgentNotices } from '../agentNotices';
import MessageButtons from './MessageButtons';

interface ClientMessageFooterProps {
    message: ChatMessage;
    contentRef: RefObject<HTMLDivElement>;
    readOnly: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
}
/** Resource and business operations remain in the client boundary. */
export function ClientMessageFooter({ message, contentRef, readOnly, onOpenCitationPanel, activeCitationMessageId }: ClientMessageFooterProps) {
    const localize = useLocalize();
    const raw = message.raw as unknown as ChatMessageType;
    const { conversationId = '' } = useParams();
    const id = message.sourceMessageId;
    const { referenceText, webContent } = splitMessageContent(message.text);
    if (message.kind === 'user' || message.kind === 'run') return null;
    if (message.kind === 'form' || message.kind === 'choice') return readOnly ? null : <TextToSpeechButton messageId={id ?? message.key} text={message.text} />;
    if (message.category === 'guide_word') return readOnly ? null : <TextToSpeechButton messageId={message.key} text={message.text} />;
    return <>
        {message.final && parseAgentNotices(message.raw.extra).map(code => <p key={code} className="text-xs text-amber-600 dark:text-amber-400">{localize(`com_agent_runtime.notice.${code}`)}</p>)}
        <CitationReferencesDrawer content={referenceText} webContent={webContent} citations={raw.citations} messageId={id}
            desktopMode={onOpenCitationPanel ? 'inline-panel' : 'overlay'}
            open={onOpenCitationPanel ? activeCitationMessageId === id : undefined}
            onDesktopOpen={onOpenCitationPanel} buttonClassName="ml-4" />
        {(readOnly || message.kind !== 'answer' || !id) && <div className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity"><CopyMessageAction label={localize('com_ui_copy')} copiedLabel={localize('com_ui_copied')} onCopy={() => copyText(contentRef.current ?? message.text)} /></div>}
        {!readOnly && id && message.kind === 'answer' && <MessageButtons id={raw.id ?? id} data={raw.liked} text={message.text} onCopy={() => copyText(contentRef.current ?? message.text)}>
            {raw.create_time && <span className="text-slate-400 text-sm pt-0.5">{formatStrTime(raw.create_time, localize('shared:app_chat.timestamp_format'))}</span>}
            {conversationId && <ExportSelectionButton chatId={conversationId} messageId={id} />}
        </MessageButtons>}
    </>;
}
