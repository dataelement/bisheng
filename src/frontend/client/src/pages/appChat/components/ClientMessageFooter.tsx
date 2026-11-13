import { CopyMessageAction } from '@bisheng/chat';
import { useQuery } from '@tanstack/react-query';
import { useLocalize } from '~/hooks';
import { splitMessageContent, type ChatMessage } from '@bisheng/chat/core';
import type { RefObject } from 'react';
import { useParams } from 'react-router-dom';
import type { ChatMessageType } from '~/@types/chat';
import { getMemoryFlagsApi, type MemoryFlags } from '~/api/memory';
import { MemoryNotice } from '~/components/Chat/MemoryNotice';
import CitationReferencesDrawer, { type CitationReferencesDesktopPayload } from '~/components/Chat/Messages/Content/CitationReferencesDrawer';
import { ExportSelectionButton } from '~/components/Chat/MessageSelection';
import { TextToSpeechButton } from '~/components/Voice/TextToSpeechButton';
import { copyText, formatStrTime } from '~/utils';
import MessageButtons from './MessageButtons';

interface ClientMessageFooterProps {
    message: ChatMessage;
    contentRef: RefObject<HTMLDivElement>;
    readOnly: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
    /** F132: memory notice + attribution — signed-in assistant chats only (never workflow). */
    memoryEnabled?: boolean;
}

/** Live flags ride on the answer row; after a reload they come from the chat's flags. */
function AppMemoryNotice({ chatId, messageId, live }: { chatId: string; messageId?: string; live?: MemoryFlags }) {
    const { data: history } = useQuery({
        queryKey: ['memory', 'flags', chatId],
        queryFn: () => getMemoryFlagsApi(chatId),
        enabled: !!chatId && !live,
        staleTime: 60_000,
    });
    const flags = live ?? (messageId ? history?.[messageId] : undefined);
    return <MemoryNotice flags={flags} messageId={messageId} />;
}

/** Resource and business operations remain in the client boundary. */
export function ClientMessageFooter({ message, contentRef, readOnly, onOpenCitationPanel, activeCitationMessageId, memoryEnabled = false }: ClientMessageFooterProps) {
    const localize = useLocalize();
    const raw = message.raw as unknown as ChatMessageType;
    const { conversationId = '' } = useParams();
    const id = message.sourceMessageId;
    const { referenceText, webContent } = splitMessageContent(message.text);
    if (message.kind === 'user' || message.kind === 'run') return null;
    if (message.kind === 'form' || message.kind === 'choice') return readOnly ? null : <TextToSpeechButton messageId={id ?? message.key} text={message.text} />;
    if (message.category === 'guide_word') return readOnly ? null : <TextToSpeechButton messageId={message.key} text={message.text} />;
    const actions = <>
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
    if (!memoryEnabled || readOnly || message.kind !== 'answer') return actions;
    const live = (raw as unknown as { memory?: MemoryFlags }).memory;
    return <div className="flex w-full flex-col">
        <div className="flex justify-between">{actions}</div>
        <AppMemoryNotice chatId={conversationId} messageId={id} live={live} />
    </div>;
}
