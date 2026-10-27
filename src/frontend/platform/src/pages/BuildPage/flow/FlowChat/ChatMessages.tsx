// @ts-strict-ignore
import { asRecord } from '@bisheng/chat/core';
import { PlatformConversationMessages } from '@/components/bs-comp/appChat/PlatformConversationMessages';
import { useRef } from 'react';
import { SuggestedQuestions, useConversationScroll } from '@bisheng/chat';
import { messagesForPresentation } from '@bisheng/chat/core';
import InputForm from './InputForm';
import { useMessageStore } from './messageStore';

export default function ChatMessages({
    canExecute = false,
    mark = false,
    logo,
    useName,
    title = '',
    guideWord,
    loadMore,
    onMarkClick = undefined,
    version,
}) {
    const { chatId, messages, inputForm, eventTarget, running, historyEnd, questions, inputLocked } = useMessageStore()

    const messagesRef = useRef<HTMLDivElement>(null);
    useConversationScroll({ scrollRef: messagesRef, sessionKey: chatId,
        messages: messagesForPresentation(messages, { mode: 'workflow', sessionKey: chatId }),
        canLoadOlder: typeof loadMore === 'function' && !running && !historyEnd, onLoadOlder: () => loadMore?.() });

    const messagesList = guideWord && !messages.some(message => message.category === 'guide_word') ? [{ category: 'guide_word', message: guideWord }, ...messages] : [...messages]
    return <div id="message-panne" ref={messagesRef} className="h-full overflow-y-auto scrollbar-hide pt-2 pb-44 px-4">
        <PlatformConversationMessages mode="workflow" sessionKey={chatId} messages={messagesList}
            canExecute={canExecute} canAnnotate={mark} title={title} logo={logo} userName={useName} version={version}
            onMarkClick={onMarkClick}
            onChoice={(message, value) => {
                const payload = asRecord(message.payload);
                eventTarget.dispatchEvent(new CustomEvent('outputMsgEvent', { detail: {
                    nodeId: payload.node_id, message: message.raw, data: { [String(payload.key)]: value }
                } }));
            }} />
        <SuggestedQuestions questions={questions} canExecute={canExecute && !inputLocked && !inputForm}
            onSelect={word => eventTarget.dispatchEvent(new CustomEvent('userResendMsgEvent', { detail: { send: true, message: word } }))} />
        {canExecute && inputForm && <InputForm data={inputForm} title={title} logo={logo} onSubmit={(data, msg) => eventTarget.dispatchEvent(new CustomEvent('inputFormEvent', { detail: { data, msg } }))} />}
    </div>;
}
