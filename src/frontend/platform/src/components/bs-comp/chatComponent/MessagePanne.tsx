// @ts-strict-ignore
import { PlatformConversationMessages } from '@/components/bs-comp/appChat/PlatformConversationMessages';
import { useEffect, useRef } from 'react';
import { SuggestedQuestions, useConversationScroll } from '@bisheng/chat';
import { messagesForPresentation } from '@bisheng/chat/core';
import { useMessageStore } from './messageStore';

export default function MessagePanne({ canExecute = false, mark = false, logo, useName, guideWord, questions = [], loadMore,chat, version,onMarkClick = undefined }) {
    const { chatId, messages, hisMessages, running, historyEnd, inputLocked, showGuideQuestion, setShowGuideQuestion, eventTarget } = useMessageStore()

    const questionKey = questions.join("\n");
    useEffect(() => { setShowGuideQuestion(!!questionKey); }, [chatId, questionKey, setShowGuideQuestion]);

    // 反馈
    // 溯源

    const messagesRef = useRef<HTMLDivElement>(null);
    useConversationScroll({ scrollRef: messagesRef, sessionKey: chatId,
        messages: messagesForPresentation(messages, { mode: 'assistant', sessionKey: chatId }),
        canLoadOlder: !running && !historyEnd, onLoadOlder: () => loadMore?.() });

    const messagesList = [...hisMessages, ...messages]
    return <div id="message-panne" ref={messagesRef} className="h-full overflow-y-auto scrollbar-hide pt-12 pb-60">
        <PlatformConversationMessages mode="assistant" sessionKey={chatId}
            messages={guideWord ? [{ category: 'guide_word', message: guideWord }, ...messagesList] : messagesList}
            canExecute={canExecute} canAnnotate={mark} logo={logo} title={chat?.name ?? ''} runCatalog={chat} userName={useName} version={version} onMarkClick={onMarkClick} />
        <SuggestedQuestions questions={questions} canExecute={canExecute && !inputLocked && showGuideQuestion}
            onSelect={word => { setShowGuideQuestion(false); eventTarget.dispatchEvent(new CustomEvent('userResendMsgEvent', { detail: { send: true, message: word } })); }} />
    </div>;
}
