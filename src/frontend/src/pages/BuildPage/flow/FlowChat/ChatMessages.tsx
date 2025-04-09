import ResouceModal from "@/pages/ChatAppPage/components/ResouceModal";
import ThumbsMessage from "@/pages/ChatAppPage/components/ThumbsMessage";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
// import FileBs from "./FileBs";
// import MessageBs from "./MessageBs";
// import MessageSystem from "./MessageSystem";
// import MessageUser from "./MessageUser";
// import RunLog from "./RunLog";
// import Separator from "./Separator";
import Separator from "@/components/bs-comp/chatComponent/Separator";
import MessageBs from "./MessageBs";
import MessageBsChoose from "./MessageBsChoose";
import MessageNodeRun from "./MessageNodeRun";
import { useMessageStore } from "./messageStore";
import MessageUser from "./MessageUser";
import MsgVNodeCom from "@/pages/OperationPage/useAppLog/MsgBox";

export default function ChatMessages({ audit = false, mark = false, logo, useName, disableBtn = false, guideWord, loadMore, onMarkClick, msgVNode, flow }) {
    const { t } = useTranslation()
    const { chatId, messages, hisMessages } = useMessageStore()

    // 新增状态记录是否需要特殊滚动
    const [shouldScrollToTarget, setShouldScrollToTarget] = useState({
    search: false,
    violation: false
    });
    // 用于目标消息定位
    const targetMessageRef = useRef(null);
    const scrollTimeoutRef = useRef(null);
    // 仅第一次加载进行滚动
    const [isFirstLoad, setIsFirstLoad] = useState(true);


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
    }, [messages])
    
    /**
     * 滚动到指定消息
     * @param {Message} message
     */
    const scrollToMessage = useCallback((message) => {
        if (!message) return;
        
        const element = document.getElementById(`msg-${message.id}`);
        if (!element) return;
        
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        element.classList.add('highlight-message');
        
        if (scrollTimeoutRef.current) {
          clearTimeout(scrollTimeoutRef.current);
        }
        
        scrollTimeoutRef.current = setTimeout(() => {
        element.classList.remove('highlight-message');
        }, 2000);
    }, []);
        
    /**
     * 查找最后违规的消息id
     * @returns {Message|null}
     */
    const findLastViolation = useCallback(() => {
        const viollationMessages = messagesList.filter(item => item.review_reason);
        return viollationMessages.pop();
    }, [chatId, messages]);

    // 消息滚动加载
    const queryLockRef = useRef(false)
    useEffect(() => {
        function handleScroll() {
            if (queryLockRef.current) return
            const lastViolation = findLastViolation();
           // if (isFirstLoad && audit && lastViolation) {
            //     console.log('滚动', isFirstLoad);
            //     // 这里写违规消息和历史记录搜索的滚动逻辑
            //     scrollToMessage(lastViolation);
            //     setIsFirstLoad(false);
            //     return;
           // }

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
    }, [messagesRef.current, messages, chatId, isFirstLoad]);

    // const messagesList = [...hisMessages, ...messages]
    const messagesList = [...messages]
    console.log('ui message :>> ', messagesList);
    // 成对的qa msg
    const findQa = (msgs, index) => {
        const item = msgs[index]
        if (['stream_msg', 'answer'].includes(item.category)) {
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
                if (['stream_msg', 'answer'].includes(aItem.category)) {
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
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item">
                            <MessageUser audit={audit} mark={mark} key={msg.message_id} useName={useName} data={msg} onMarkClick={() => { onMarkClick('question', msg.id, findQa(messagesList, index)) }} />
                        </div>;
                    case 'guide_word':
                    case 'output_msg':
                    case 'stream_msg':
                        return <div
                        id={`msg-${msg.id}`}
                        key={msg.id}
                        className="message-item"><MessageBs
                            audit={audit}
                            mark={mark}
                            logo={logo}
                            disableBtn={disableBtn}
                            key={msg.message_id}
                            data={msg}
                            msgVNode={msgVNode}
                            onUnlike={(chatId) => { thumbRef.current?.openModal(chatId) }}
                            onSource={(data) => { sourceRef.current?.openModal(data) }}
                            onMarkClick={() => onMarkClick('answer', msg.message_id, findQa(messagesList, index))}
                        /></div>;
                    case 'separator':
                        return <div
                        id={`msg-${msg.id}`}
                        key={msg.id}
                        className="message-item"><Separator key={msg.message_id} text={msg.message || t('chat.roundOver')} /></div>;
                    case 'output_choose_msg':
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item"><MessageBsChoose key={msg.message_id} data={msg} logo={logo} flow={flow} /></div>;
                    case 'output_input_msg':
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item"><MessageBsChoose type='input' key={msg.message_id} data={msg} logo={logo} flow={flow} /></div>;
                    case 'node_run':
                        // TODO
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item"><MessageNodeRun key={msg.message_id} data={msg} flow={flow} /></div>;
                    default:
                        return <div className="text-sm mt-2 border rounded-md p-2" key={msg.message_id}>Unknown message type</div>;
                }
            })
        }
        <ThumbsMessage ref={thumbRef}></ThumbsMessage>
        <ResouceModal ref={sourceRef}></ResouceModal>
    </div>
};
