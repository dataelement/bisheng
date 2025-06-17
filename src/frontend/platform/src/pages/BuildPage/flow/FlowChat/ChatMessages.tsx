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
import InputForm from "./InputForm";
import MessageBsChoose from "./MessageBsChoose";
import MessageNodeRun from "./MessageNodeRun";
import { useMessageStore } from "./messageStore";
import MessageUser from "./MessageUser";

export default function ChatMessages({
    debug,
    operation = false,
    audit = false,
    mark = false,
    logo,
    useName,
    disableBtn = false,
    guideWord,
    loadMore,
    onMarkClick = undefined,
    msgVNode,
    flow
}) {
    const { t } = useTranslation()
    const { chatId, messages, historyEnd, hisMessages, inputForm } = useMessageStore()

    const [isViolation, setIsViolation] = useState(false);
    const [keyword, setKeyword] = useState('');

    // 用于目标消息定位
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

    useEffect(() => {
        // 只有审计和运营页面存在滚动过去的逻辑
        if (!audit && !operation) return;
        // 当前是否存在违规
        const reviewStatus = localStorage.getItem('reviewStatus');
        setIsViolation(reviewStatus === '3');
        // 当前是否存在搜索关键词带入
        let keyword = '';
        if (audit) {
            keyword = localStorage.getItem('auditKeyword');
        }
        if (operation) {
            keyword = localStorage.getItem('operationKeyword');
        }
        setKeyword(keyword);
    })

    
    useEffect(() => {
        // 页面校验： 只有审计和运营页面存在滚动过去的逻辑
        if (!audit && !operation) return;
        // 逻辑校验： 只有第一次进入 同时消息列表有数据 才进行滚动
        if (!isFirstLoad && !messages.length) return;
        
        if (keyword) {
            const lastMsg = findKeywordMsg();
            if (lastMsg) {
                scrollToMessage(lastMsg);
                setIsFirstLoad(false);
            } else {
                // 没加载完则进行加载
                !historyEnd && loadMore();
            }
            return;
        }
        // 只有审核页面进行违规消息滚动
        if (isViolation && audit) {
            const lastViolation = findLastViolation();
            if (lastViolation) {
                scrollToMessage(lastViolation);
                setIsFirstLoad(false);
            } else {
                // 没加载完则进行加载
                !historyEnd && loadMore();
            }
            return;
        }
    }, [messages, isViolation, keyword, isFirstLoad])

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
    
    /**
     * 滚动到指定消息
     * @param {Message} message
     */
    const scrollToMessage = useCallback((message) => {
        console.log('目标滚动的msg', message);
        if (!message) return;
        
        const element = document.getElementById(`msg-${message.id}`);
        if (!element) return;
        
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
        const violationMessages = messagesList.filter(item => item.review_reason);
        return violationMessages.pop();
    }, [chatId, messages]);

    const findKeywordMsg = useCallback(() => {
        const lastHasKeywordMsg = messagesList.findLast(item =>
            item.message?.msg?.includes?.(keyword) || 
            item.message?.includes?.(keyword)
        );
        return lastHasKeywordMsg;
    }, [keyword, messages])

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
    }, [messagesRef.current, messages, chatId, isFirstLoad]);

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
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item">
                            <MessageUser
                                operation={operation}
                                audit={audit}
                                mark={mark}
                                key={msg.message_id}
                                useName={useName}
                                data={msg}
                                onMarkClick={() => { onMarkClick?.('question', msg.id, findQa(messagesList, index)) }}
                            />
                        </div>;
                    case 'guide_word':
                    case 'output_msg':
                    case 'stream_msg':
                    case "answer":
                        return <div
                        id={`msg-${msg.id}`}
                        key={msg.id}
                        className="message-item">
                            <MessageBs
                                debug={debug}
                                flow={flow}
                                operation={operation}
                                audit={audit}
                                mark={mark}
                                logo={logo}
                                disableBtn={disableBtn}
                                key={msg.message_id}
                                data={msg}
                                msgVNode={msgVNode}
                                onUnlike={(chatId) => { thumbRef.current?.openModal(chatId) }}
                                onSource={(data) => { sourceRef.current?.openModal(data) }}
                                onMarkClick={() => onMarkClick?.('answer', msg.message_id, findQa(messagesList, index))}
                            />
                        </div>;
                    case 'separator':
                        return <div
                        id={`msg-${msg.id}`}
                        key={msg.id}
                        className="message-item">
                            <Separator
                                key={msg.message_id}
                                text={msg.message || t('chat.roundOver')}
                            />
                        </div>;
                    case 'output_with_choose_msg':
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item">
                                <MessageBsChoose
                                    key={msg.message_id}
                                    data={msg}
                                    logo={logo}
                                    flow={flow}
                                />
                            </div>;
                    case 'output_with_input_msg':
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item">
                                <MessageBsChoose
                                type='input'
                                key={msg.message_id}
                                data={msg}
                                logo={logo}
                                flow={flow}
                                />
                            </div>;
                    case 'node_run':
                        return <div
                            id={`msg-${msg.id}`}
                            key={msg.id}
                            className="message-item">
                                <MessageNodeRun
                                    key={msg.message_id}
                                    data={msg}
                                    flow={flow}
                                />
                            </div>;
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
