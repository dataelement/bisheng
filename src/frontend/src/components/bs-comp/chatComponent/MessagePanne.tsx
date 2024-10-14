import ResouceModal from "@/pages/ChatAppPage/components/ResouceModal";
import ThumbsMessage from "@/pages/ChatAppPage/components/ThumbsMessage";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import FileBs from "./FileBs";
import MessageBs from "./MessageBs";
import MessageSystem from "./MessageSystem";
import MessageUser from "./MessageUser";
import RunLog from "./RunLog";
import Separator from "./Separator";
import { useMessageStore } from "./messageStore";

export default function MessagePanne({ mark = false, logo, useName, guideWord, loadMore, onMarkClick = (...a: any) => {} }) {
    const { t } = useTranslation()
    const { chatId, messages, hisMessages } = useMessageStore()

    // 反馈
    const thumbRef = useRef(null)
    // 溯源
    const sourceRef = useRef(null)

    // 自动滚动
    const messagesRef = useRef(null)
    const scrollLockRef = useRef(false)
    useEffect(() => {
        scrollLockRef.current = false
        queryLockRef.current = false
    }, [chatId])
    useEffect(() => {
        if (scrollLockRef.current) return
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }, [messages])

    // 消息滚动加载
    const queryLockRef = useRef(false)
    useEffect(() => {
        function handleScroll() {
            if (queryLockRef.current) return
            const { scrollTop, clientHeight, scrollHeight } = messagesRef.current
            // 距离底部 600px内，开启自动滚动
            scrollLockRef.current = (scrollHeight - scrollTop - clientHeight) > 600

            if (messagesRef.current.scrollTop <= 90) {
                console.log('请求 :>> ', 1);
                queryLockRef.current = true
                loadMore()
                // TODO 翻页定位
                // 临时处理防抖
                setTimeout(() => {
                    queryLockRef.current = false
                }, 1000);
            }
        }

        messagesRef.current?.addEventListener('scroll', handleScroll);
        return () => messagesRef.current?.removeEventListener('scroll', handleScroll)
    }, [messagesRef.current, messages, chatId]);

    const messagesList = [...hisMessages, ...messages]
    // 成对的qa msg
    const findQa = (msgs, index) => {
        const item = msgs[index]
        if (item.category === 'answer') {
            const a = item.message[item.chatKey] || item.message
            let q = ''
            while (index > -1) {
                const qItem = msgs[--index]
                if (qItem.category === 'question') {
                    q = qItem.message[qItem.chatKey] || qItem.message
                    break
                }
            }
            return { q, a }
        } else if (item.category === 'question') {
            const q = item.message[item.chatKey] || item.message
            let a = ''
            while (msgs[++index]) {
                const aItem = msgs[index]
                if (aItem.category === 'answer') {
                    a = aItem.message[aItem.chatKey] || aItem.message
                    break
                }
            }
            return { q, a }
        }
    }

    return <div id="message-panne" ref={messagesRef} className="h-full overflow-y-auto scrollbar-hide pt-12 pb-60">
        {guideWord && <MessageBs
            key={9999}
            data={{ message: guideWord, isSend: false, chatKey: '', end: true, user_name: '' }} />}
        {
            messagesList.map((msg, index) => {
                // 工厂
                let type = 'llm'
                if (msg.isSend) {
                    type = 'user'
                } else if (msg.category === 'divider') {
                    type = 'separator'
                } else if (msg.files?.length) {
                    type = 'file'
                } else if (['tool', 'flow', 'knowledge'].includes(msg.category)
                    // || (msg.category === 'processing' && msg.thought.indexOf(`status_code`) === -1)
                ) { // 项目演示？
                    type = 'runLog'
                } else if (msg.thought) {
                    type = 'system'
                }

                switch (type) {
                    case 'user':
                        return <MessageUser mark={mark} key={msg.id} useName={useName} data={msg} onMarkClick={() => onMarkClick('question', msg.id, findQa(messagesList, index))} />;
                    case 'llm':
                        return <MessageBs
                            mark={mark}
                            logo={logo}
                            key={msg.id}
                            data={msg}
                            onUnlike={(chatId) => { thumbRef.current?.openModal(chatId) }}
                            onSource={(data) => { sourceRef.current?.openModal(data) }}
                            onMarkClick={() => onMarkClick('answer', msg.id, findQa(messagesList, index))}
                        />;
                    case 'system':
                        return <MessageSystem key={msg.id} data={msg} />;
                    case 'separator':
                        return <Separator key={msg.id} text={msg.message || t('chat.roundOver')} />;
                    case 'file':
                        return <FileBs key={msg.id} data={msg} />;
                    case 'runLog':
                        return <RunLog key={msg.id} data={msg} />;
                    default:
                        return <div className="text-sm mt-2 border rounded-md p-2" key={msg.id}>Unknown message type</div>;
                }
            })
        }
        {/* 踩 反馈 */}
        <ThumbsMessage ref={thumbRef}></ThumbsMessage>
        {/* 源文件类型 */}
        <ResouceModal ref={sourceRef}></ResouceModal>
    </div>
};
