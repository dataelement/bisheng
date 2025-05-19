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
import Separator from "@/components/bs-comp/chatComponent/Separator";
import InputForm from "./InputForm";
import MessageBs from "./MessageBs";
import MessageBsChoose from "./MessageBsChoose";
import MessageNodeRun from "./MessageNodeRun";
import { useMessageStore } from "./messageStore";
import MessageUser from "./MessageUser";

export default function ChatMessages({
    debug,
    mark = false,
    logo,
    useName,
    guideWord,
    loadMore,
    onMarkClick = undefined
}) {
    const { t } = useTranslation()
    const { chatId, messages, inputForm } = useMessageStore()

    // 反馈
    const thumbRef = useRef(null)
    // 溯
    const sourceRef = useRef(null
    )
    // 自动滚动
    const messagesRef = useRef(null)
    const scrollLockRef = useRef(false)
    useEffect(() => {
        scrollLockRef.current = false
        queryLockRef.current = false
    }, [chatId])
    const lastScrollTimeRef = useRef(0); // 记录上次执行的时间戳
    useEffect(() => {
        if (scrollLockRef.current) return;

        const now = Date.now();
        const throttleTime = 1200; // 1秒

        // 如果距离上次执行的时间小于 throttleTime，则直接返回
        if (now - lastScrollTimeRef.current < throttleTime) {
            return;
        }

        // 执行滚动操作
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;

        // 更新上次执行的时间戳
        lastScrollTimeRef.current = now;
    }, [messages]);

    // 消息滚动加载
    const queryLockRef = useRef(false)
    useEffect(() => {
        function handleScroll() {
            if (queryLockRef.current) return
            const { scrollTop, clientHeight, scrollHeight } = messagesRef.current
            // 距离底部 600px内，开启自动滚动
            scrollLockRef.current = (scrollHeight - scrollTop - clientHeight) > 400

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
        if (['stream_msg', 'answer', 'output_msg'].includes(item.category)) {
            const a = item.message.msg || item.message
            let q = ''
            while (index > -1) {
                const qItem = msgs[--index]
                if (['question', 'input'].includes(qItem?.category)) {
                    q = qItem.message[qItem.chatKey] || qItem.message
                    break
                }
            }
            return { q, a }
        } else if (['question', 'input'].includes(item?.category)) {
            const q = item.message[item.chatKey] || item.message
            let a = ''
            while (msgs[++index]) {
                const aItem = msgs[index]
                if (['stream_msg', 'answer', 'output_msg'].includes(aItem.category)) {
                    a = aItem.message.msg || aItem.message
                    break
                }
            }
            return { q, a }
        }
    }

    return <div id="message-panne" ref={messagesRef} className="h-full overflow-y-auto scrollbar-hide pt-12 pb-60 px-4">
        {
            messagesList.map((msg, index) => {
                // output节点特殊msg
                switch (msg.category) {
                    case 'input':
                        return null
                    case 'question':
                        return <MessageUser
                            mark={mark}
                            key={msg.message_id}
                            useName={useName}
                            data={msg}
                            onMarkClick={() => { onMarkClick?.('question', msg.id, findQa(messagesList, index)) }}
                        />;
                    case 'guide_word':
                    case 'output_msg':
                    case 'stream_msg':
                    case "answer":
                        return <MessageBs
                            debug={debug}
                            mark={mark}
                            logo={logo}
                            key={msg.message_id}
                            data={msg}
                            onUnlike={(chatId) => { thumbRef.current?.openModal(chatId) }}
                            onSource={(data) => { sourceRef.current?.openModal(data) }}
                            onMarkClick={() => onMarkClick?.('answer', msg.message_id, findQa(messagesList, index))}
                        />;
                    case 'separator':
                        return <Separator key={msg.message_id} text={msg.message || t('chat.roundOver')} />;
                    case 'output_with_choose_msg':
                        return <MessageBsChoose key={msg.message_id} data={msg} logo={logo} />;
                    case 'output_with_input_msg':
                        return <MessageBsChoose type='input' key={msg.message_id} data={msg} logo={logo} />;
                    case 'node_run':
                        return <MessageNodeRun key={msg.message_id} data={msg} />;
                    default:
                        return <div className="text-sm mt-2 border rounded-md p-2" key={msg.message_id}>Unknown message type</div>;
                }
            })
        }
        {inputForm && <InputForm data={inputForm} />}
        <ThumbsMessage ref={thumbRef}></ThumbsMessage>
        <ResouceModal ref={sourceRef}></ResouceModal>
    </div>
};
