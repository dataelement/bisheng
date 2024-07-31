import { TitleLogo } from "@/components/bs-comp/cardComponent";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import LoadMore from "@/components/bs-comp/loadMore";
import { AssistantIcon, SkillIcon } from "@/components/bs-icons";
import { PlusBoxIcon, PlusBoxIconDark } from "@/components/bs-icons/plusBox";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { message } from "@/components/bs-ui/toast/use-toast";
import { formatDate, formatStrTime } from "@/util/utils";
import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { deleteChatApi, getChatsApi } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useDebounce } from "../../util/hook";
import { generateUUID } from "../../utils";
import HomePage from "./components/ChatHome";
import ChatPanne from "./components/ChatPanne";

export default function SkillChatPage() {

    const { t } = useTranslation()
    const [selectChat, setSelelctChat] = useState<any>({
        id: '', chatId: '', type: ''
    })

    // 对话列表
    const { chatList, chatId, chatsRef, setChatId, addChat, deleteChat, onScrollLoad } = useChatList()

    const [location, setLocation] = useState(true)
    // select flow(新建会话)
    const handlerSelectFlow = async (card) => {
        console.log(card)
        if (!location) {
            setLocation(true)
            return
        }
        if (card) {
            // 会话ID
            const _chatId = generateUUID(32)
            // add list
            addChat({
                "logo": card.logo || '',
                "flow_name": card.name,
                "flow_description": card.desc,
                "flow_id": card.id,
                "chat_id": _chatId,
                "create_time": "-",
                "update_time": Date.now(),
                "flow_type": card.flow_type
            })
            setSelelctChat({ id: card.id, chatId: _chatId, type: card.flow_type })
            setChatId(_chatId)
            setLocation(false)
        } else {
            return message({ title: t('prompt'), variant: 'warning', description: t('chat.pleaseSelectAnApp') })
        }
    }

    // select chat
    const handleSelectChat = useDebounce(async (chat) => {
        setLocation(false)
        if (chat.chat_id === chatId) return
        setSelelctChat({ id: chat.flow_id, chatId: chat.chat_id, type: chat.flow_type })
        setChatId(chat.chat_id)
    }, 100, false)

    // del
    const handleDeleteChat = (e, id) => {
        e.stopPropagation();
        bsConfirm({
            desc: t('chat.confirmDeleteChat'),
            onOk(next) {
                deleteChat(id);
                setSelelctChat({ id: '', chatId: '', type: '' })
                next()
            }
        })
    }

    return <div className="flex h-full">
        <div className="h-full w-[220px] relative border-r">
            <div className="absolute flex top-0 w-full bs-chat-bg bg-background-main-content z-10 p-2">
                {/* <SkillChatSheet onSelect={handlerSelectFlow}>
                    <div id="newchat" className="flex justify-around items-center w-[200px] h-[48px] rounded-lg px-10 py-2 mx-auto text-center text-sm cursor-pointer bg-background-main-content hover:bg-gray-100 dark:hover:bg-gray-800 relative z-10">
                        <PlusBoxIcon className="dark:hidden"></PlusBoxIcon>
                        <PlusBoxIconDark className="hidden dark:block"></PlusBoxIconDark>
                        {t('chat.newChat')}
                    </div>
                </SkillChatSheet> */}
                <div onClick={() => handlerSelectFlow(null)} id="newchat" className="flex justify-around items-center w-[200px] h-[48px] rounded-lg px-10 py-2 mx-auto text-center text-sm cursor-pointer bg-background-main-content hover:bg-gray-100 dark:hover:bg-gray-800 relative z-10">
                    <PlusBoxIcon className="dark:hidden"></PlusBoxIcon>
                    <PlusBoxIconDark className="hidden dark:block"></PlusBoxIconDark>
                    {t('chat.newChat')}
                </div>
            </div>
            <div ref={chatsRef} className="scroll h-full overflow-y-scroll no-scrollbar p-2 pt-14">
                {
                    chatList.map((chat, i) => (
                        <div key={chat.chat_id}
                            className={`group item w-full rounded-lg mt-2 p-4 relative  hover:bg-[#EDEFF6] cursor-pointer dark:hover:bg-[#34353A] ${location
                                ? 'bg-[#f9f9fc] dark:bg-[#212122]'
                                : (chatId === chat.chat_id
                                    ? 'bg-[#EDEFF6] dark:bg-[#34353A]'
                                    : 'bg-[#f9f9fc] dark:bg-[#212122]')}`}
                            onClick={() => handleSelectChat(chat)}>
                            <div className="flex place-items-center space-x-3">
                                <div className=" inline-block bg-purple-500 rounded-md">
                                    <TitleLogo
                                        url={chat.logo}
                                        id={chat.flow_id}
                                    >
                                        {chat.flow_type === 'assistant' ? <AssistantIcon /> : <SkillIcon />}
                                    </TitleLogo>
                                </div>
                                <p className="truncate text-sm font-bold leading-6">{chat.flow_name}</p>
                            </div>
                            <span className="block text-xs text-gray-600 dark:text-[#8D8D8E] mt-3 break-words truncate">{chat.latest_message?.message || ''}</span>
                            <div className="mt-6">
                                <span className="text-gray-400 text-xs absolute bottom-2 left-4">{formatStrTime(chat.update_time, 'MM 月 dd 日')}</span>
                                <Trash2 size={14} className="absolute bottom-2 right-2 text-gray-400 hidden group-hover:block" onClick={(e) => handleDeleteChat(e, chat.chat_id)}></Trash2>
                            </div>
                        </div>
                    ))
                }
                <LoadMore onScrollLoad={onScrollLoad} />
            </div>
        </div>
        {/* chat */}
        {
            location
                ? <HomePage onSelect={handlerSelectFlow}></HomePage>
                : <ChatPanne appendHistory data={selectChat}></ChatPanne>
        }
    </div>
};
/**
 * 本地对话列表
 */
const useChatList = () => {
    const [id, setId] = useState('')
    const [chatList, setChatList] = useState([])
    const chatsRef = useRef(null)
    const { chatId, messages } = useMessageStore()

    useEffect(() => {
        if (messages.length > 0) {
            let latest: any = messages[messages.length - 1]
            // 有分割线取上一条
            if (latest.category === 'divider') latest = messages[messages.length - 2] || {}
            setChatList(chats => chats.map(chat => (chat.chat_id === chatId)
                ? {
                    ...chat,
                    update_time: latest.update_time || formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss'),
                    latest_message: {
                        ...chat.latest_message,
                        message: (latest.thought || latest.message[latest.chatKey] || latest.message).substring(0, 40)
                    }
                }
                : chat)
            )
        }
    }, [messages, chatId])

    const pageRef = useRef(0)
    const onScrollLoad = async () => {
        pageRef.current++
        const res = await getChatsApi(pageRef.current)
        setChatList((chats => [...chats, ...res]))
    }

    return {
        chatList,
        chatId: id,
        chatsRef,
        setChatId: setId,
        addChat: (chat) => {
            const newList = [chat, ...chatList]
            // localStorage.setItem(ITEM_KEY, JSON.stringify(newList))
            setChatList(newList)
            setId(chat.chat_id)
            setTimeout(() => {
                chatsRef.current.scrollTop = 1
            }, 0);
        },
        deleteChat: (id: string) => {
            // api
            captureAndAlertRequestErrorHoc(deleteChatApi(id).then(res => {
                setChatList(oldList => oldList.filter(item => item.chat_id !== id))
            }))
        },
        onScrollLoad
    }
}

