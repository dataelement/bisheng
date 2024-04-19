import SkillChatSheet from "@/components/bs-comp/sheets/SkillChatSheet";
import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { deleteChatApi, getChatsApi } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useDebounce } from "../../util/hook";
import { generateUUID } from "../../utils";
import ChatPanne from "./components/ChatPanne";
import { PlusBoxIcon } from "@/components/bs-icons/plusBox";
import { gradients } from "@/components/bs-comp/cardComponent";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

export default function SkillChatPage() {

    const { t } = useTranslation()
    const [selectChat, setSelelctChat] = useState<any>({
        id: '', chatId: '', type: ''
    })

    // 对话列表
    const { chatList, chatId, chatsRef, setChatId, addChat, deleteChat } = useChatList()

    // select flow(新建会话)
    const handlerSelectFlow = async (card) => {
        // 会话ID
        const _chatId = generateUUID(32)
        // add list
        addChat({
            "flow_name": card.name,
            "flow_description": card.desc,
            "flow_id": card.id,
            "chat_id": _chatId,
            "create_time": "-",
            "update_time": "-",
            "flow_type": card.flow_type
        })

        setSelelctChat({ id: card.id, chatId: _chatId, type: card.flow_type })
        setChatId(_chatId)
    }

    // select chat
    const handleSelectChat = useDebounce(async (chat) => {
        console.log('chat.id :>> ', chat);
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
            <div className="absolute flex top-0 w-full bg-[#fff] z-10 p-2">
                <SkillChatSheet onSelect={handlerSelectFlow}>
                    <div id="newchat" className="flex justify-around items-center w-[200px] h-[48px] rounded-lg px-10 py-2 mx-auto text-center text-sm cursor-pointer bg-[#fff] hover:bg-gray-100 dark:hover:bg-gray-800 relative z-10">
                        <PlusBoxIcon></PlusBoxIcon>
                        {t('chat.newChat')}
                    </div>
                </SkillChatSheet>
            </div>
            <div ref={chatsRef} className="scroll h-full overflow-y-scroll no-scrollbar p-2 pt-14">
                {
                    chatList.map((chat, i) => (
                        <div key={chat.chat_id}
                            className={` group item w-full rounded-lg mt-2 p-4 relative  hover:bg-[#EDEFF6] cursor-pointer dark:hover:bg-gray-800 ${chatId === chat.chat_id ? 'bg-[#EDEFF6] dark:bg-gray-800' : 'bg-[#f9f9fc]'}`}
                            onClick={() => handleSelectChat(chat)}>
                            <p className="break-words text-sm font-bold text-gray-950 leading-6">
                                <span className={`relative top-[-1px] inline-block w-2 h-2 mr-2 ${chat.flow_type === 'flow' ? 'bg-[#111]' : 'bg-primary'}`}></span>
                                {chat.flow_name}
                            </p>
                            <span className="block text-xs text-gray-600 mt-3 break-words truncate-multiline">{chat.flow_description}</span>
                            <Trash2 size={14} className="absolute bottom-2 right-2 text-gray-400 hidden group-hover:block" onClick={(e) => handleDeleteChat(e, chat.chat_id)}></Trash2>
                        </div>
                    ))
                }
            </div>
        </div>
        {/* chat */}
        <ChatPanne data={selectChat}></ChatPanne>
    </div>
};
/**
 * 本地对话列表
 */
const useChatList = () => {
    const [id, setId] = useState('')
    const [chatList, setChatList] = useState([])
    const chatsRef = useRef(null)

    useEffect(() => {
        getChatsApi().then(setChatList)
    }, [])

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
        }
    }
}

