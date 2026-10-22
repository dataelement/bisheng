import { ConversationMessages, ConversationAttachments, CopyMessageAction } from '@bisheng/chat';
import { asRecord, parsePayload, describeRun, createRunLabels, displayText, messagesForPresentation, selectQaPair, splitMessageContent, type ChatMessage, type ChatMode } from '@bisheng/chat/core';
import { useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@bisheng/ui';
import { FlagIcon } from '@/components/bs-icons';
import { copyText } from '@/utils';
import { PlatformChatMarkdown } from './PlatformChatMarkdown';
import { checkSassUrl } from '@/components/bs-comp/FileView';
import { downloadFile } from '@/util/utils';
import { PlatformVoiceAction } from './PlatformVoiceAction';
import CitationReferencesDrawer from '../chatComponent/CitationReferencesDrawer';
import { normalizeCitationItems } from '../chatComponent/citationUtils';
import SourceEntry from '../chatComponent/SourceEntry';
import ResouceModal from '@/pages/ChatAppPage/components/ResouceModal';

interface PlatformConversationMessagesProps {
    mode: ChatMode;
    sessionKey: string;
    messages: readonly unknown[];
    canExecute: boolean;
    canAnnotate: boolean;
    logo?: ReactNode;
    title?: string;
    runCatalog?: unknown;
    userName?: string;
    version?: string;
    onMarkClick?: (kind: 'question' | 'answer', sourceMessageId: string, qa: { q: string; a: string }) => void;
    onChoice?: (message: ChatMessage, value: string) => void | Promise<void>;
}
/** Authenticated host operations surround the same client-based message renderer. */
export function PlatformConversationMessages({ mode, sessionKey, messages: rows, canExecute, canAnnotate, logo, title = '', runCatalog, userName = '', version, onMarkClick, onChoice }: PlatformConversationMessagesProps) {
    const { t } = useTranslation(['bs', 'shared']);
    const messages = messagesForPresentation(rows, { mode, sessionKey });
    const sourceRef = useRef<{ openModal: (value: { chatId: string; messageId?: string; message: string }) => void }>(null);
    const handleMark = (message: ChatMessage) => {
        if (!canAnnotate || !message.sourceMessageId) return;
        const pair = selectQaPair(messages, message.key);
        if (pair) onMarkClick?.(message.kind === 'user' ? 'question' : 'answer', message.sourceMessageId, { q: pair.question, a: pair.answer });
    };
    return <>
        <ConversationMessages messages={messages} canExecute={canExecute} onChoice={onChoice}
            labels={{ confirm: t('chat.confirm'), confirmed: t('chat.confirmed'), thinking: t('flow:thinking'), completed: t('flow:thoughtCompleted') }}
            slots={{
                runPresentation: message => describeRun(message, runCatalog, createRunLabels(key => String(t(key)))),
                title: message => message.kind === 'user' ? displayText(message.raw.user_name) || userName : title,
                avatar: message => message.kind === 'user' ? <img className="w-6 h-6 min-w-6" src={__APP_ENV__.BASE_URL + '/assets/user.png'} alt="" /> : logo,
                content: (text, message) => {
                    if (['divider', 'separator'].includes(message.category)) return text || t('chat.roundOver');
                    const { referenceText, webContent } = splitMessageContent(text);
                    return <PlatformChatMarkdown content={referenceText} citations={normalizeCitationItems(message.raw)?.map(detail => ({ ...detail, type: detail.type ?? '' }))} webContent={webContent} />;
                },
                attachments: message => <ConversationAttachments files={message.files} services={{ resolveUrl: checkSassUrl,
                    onDownload: file => downloadFile(checkSassUrl(file.url), file.name),
                    labels: { download: t('shared:app_chat.attachment_download'), unavailable: t('shared:app_chat.attachment_unavailable'), close: t('shared:app_chat.close'), preview: t('shared:app_chat.image_preview') },
                }} />,
                footer: (message, contentRef) => {
                    const id = message.sourceMessageId;
                    if (message.category === 'guide_word') return canExecute ? <PlatformVoiceAction id={id ?? message.key} text={message.text} /> : null;
                    if (message.kind === 'form' || message.kind === 'choice') return <PlatformVoiceAction id={id ?? message.key} text={message.text} />;
                    if (message.kind === 'user') return canAnnotate && id ? <><span /><div className="mt-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity"><Button size="small" variant="solid" color="primary" onClick={() => handleMark(message)}><FlagIcon className="size-3.5" />{t('addSimilarQuestion')}</Button></div></> : null;
                    const { referenceText, webContent } = splitMessageContent(message.text);
                    return <>
                        <div>
                            <CitationReferencesDrawer content={referenceText} webContent={webContent} citations={normalizeCitationItems(message.raw)} allowRemoteCitationResolve />
                            <SourceEntry extra={asRecord(parsePayload(message.raw.extra))} end={message.final} source={message.raw.source} onSource={() => sourceRef.current?.openModal({ chatId: sessionKey, messageId: id, message: referenceText })} />
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                            {mode === 'assistant' && version !== 'v2' && <PlatformVoiceAction id={id ?? message.key} text={referenceText} />}
                            <CopyMessageAction label={t('shared:app_chat.copy')} copiedLabel={t('shared:app_chat.copied')} onCopy={() => copyText(contentRef.current ?? referenceText)} />
                            {canAnnotate && id && message.kind === 'answer' && message.text.trim() && <Button size="small" variant="solid" color="primary" onClick={() => handleMark(message)}><FlagIcon className="size-3.5" />{t('addQa')}</Button>}
                        </div>
                    </>;
                },
            }} />
        <ResouceModal ref={sourceRef} />
    </>;
}
