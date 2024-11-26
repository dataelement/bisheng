import ResouceModal from "@/pages/ChatAppPage/components/ResouceModal";
import ThumbsMessage from "@/pages/ChatAppPage/components/ThumbsMessage";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
// import FileBs from "./FileBs";
// import MessageBs from "./MessageBs";
// import MessageSystem from "./MessageSystem";
// import MessageUser from "./MessageUser";
// import RunLog from "./RunLog";
// import Separator from "./Separator";
import { useMessageStore } from "./messageStore";
import MessageBs from "./MessageBs";
import MessageUser from "./MessageUser";
import Separator from "@/components/bs-comp/chatComponent/Separator";
import MessageBsChoose from "./MessageBsChoose";
import MessageNodeRun from "./MessageNodeRun";

export default function ChatMessages({ mark = false, logo, useName, guideWord, loadMore, onMarkClick }) {
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

    // const messagesList = [...hisMessages, ...messages]
    const messagesList = [...messages]
    console.log('ui message :>> ', messagesList);
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
        {
            messagesList.map((msg, index) => {
                switch (msg.category) {
                    case 'user':
                        return <MessageUser mark={mark} key={msg.message_id} useName={useName} data={msg} onMarkClick={() => onMarkClick('question', msg.id, findQa(messagesList, index))} />;
                    case 'guide_word':
                    case 'output_msg':
                        return <MessageBs
                            mark={mark}
                            logo={logo}
                            key={msg.message_id}
                            data={msg}
                            onUnlike={(chatId) => { thumbRef.current?.openModal(chatId) }}
                            onSource={(data) => { sourceRef.current?.openModal(data) }}
                            onMarkClick={() => onMarkClick('answer', msg.message_id, findQa(messagesList, index))}
                        />;
                    case 'separator':
                        return <Separator key={msg.message_id} text={msg.message || t('chat.roundOver')} />;
                    case 'output_choose_msg':
                        return <MessageBsChoose key={msg.message_id} data={msg} logo={logo} />;
                    case 'output_input_msg':
                        return <MessageBsChoose type='input' key={msg.message_id} data={msg} logo={logo} />;
                    case 'node_run':
                        return <MessageNodeRun key={msg.message_id} data={msg} />;
                    // case 'file':
                    //     return <FileBs key={msg.id} data={msg} />;
                    // case 'runLog':
                    //     return <RunLog key={msg.id} data={msg} />;
                    default:
                        return <div className="text-sm mt-2 border rounded-md p-2" key={msg.message_id}>Unknown message type</div>;
                }
            })
        }
        {/* <ThumbsMessage ref={thumbRef}></ThumbsMessage>
        <ResouceModal ref={sourceRef}></ResouceModal> */}
    </div>
};
