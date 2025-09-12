/**
 * 接收ws event 滚动
 */
import { useEffect, useRef } from "react";
import { useParams } from "react-router";
import { useRecoilState, useRecoilValue } from "recoil";
import { getChatHistoryApi } from "~/api/apps";
import { useAutoScroll } from "~/hooks/useAutoScroll";
import { chatIdState, chatsState, currentChatState } from "./store/atoms";

export const useMessage = () => {
    const { conversationId } = useParams();
    const chatState = useRecoilValue(currentChatState)
    const [chatId] = useRecoilState(chatIdState)

    const { flow, messages } = chatState || { flow: null, messages: [] }

    const messageScrollRef = useRef<HTMLDivElement>(null)
    // 自动滚动
    useAutoScroll(messageScrollRef, messages)
    useLoadMessage(chatId, chatState, messageScrollRef)


    return {
        chatId: conversationId,
        messages,
        messageScrollRef
    }
}


const useLoadMessage = (chatId: string, chatState: any, messageScrollRef: React.RefObject<HTMLDivElement>) => {
    const [chats, setChats] = useRecoilState(chatsState)
    const { flow, messages, running, historyEnd } = chatState || {}

    // 滚动到底部
    useEffect(() => {
        if (chatId && messageScrollRef.current) {
            requestAnimationFrame(() => {
                if (messageScrollRef.current) {
                    messageScrollRef.current.scrollTop = messageScrollRef.current.scrollHeight
                }
            })
        }
    }, [chatId])

    const loadMore = async (chatId: string) => {
        // 运行中or没有更多 || 最后一条消息id不存在，忽略
        if (running || historyEnd || !messages?.[0]?.id || !flow) return
        const messageId = messages[0].id
        // u-开头的消息表示新建会话，新建会话无需加载历史消息
        if (typeof messageId === 'string' && messageId.startsWith('u-')) return

        const msgs = await getChatHistoryApi(flow.id, chatId, flow.flow_type, messages[0].id || 0)
        setChats((prev) => {
            const chatData = prev[chatId]
            const param = msgs.length ?
                { ...chatData, messages: [...msgs.reverse(), ...chatData!.messages] }
                : { ...chatData, historyEnd: true }

            return {
                ...prev,
                [chatId]: param
            }
        })
    }

    // 滚动加载
    const queryLockRef = useRef(false)
    useEffect(() => {
        function handleScroll() {
            const scrollElement = messageScrollRef.current
            if (queryLockRef.current) return
            if (!scrollElement) return
            const { scrollTop } = scrollElement

            if (scrollTop <= 90) {
                console.log('请求 :>> ', 1);
                queryLockRef.current = true
                loadMore(chatId)
                // 临时处理防抖
                setTimeout(() => {
                    queryLockRef.current = false
                }, 1000);
            }
        }

        messageScrollRef.current?.addEventListener('scroll', handleScroll);
        return () => messageScrollRef.current?.removeEventListener('scroll', handleScroll)
    }, [messageScrollRef.current, chatState, chatId]);
}