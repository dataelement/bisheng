import { Trash2 } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsconfirm } from "../../alerts/confirm";
import { TabsContext } from "../../contexts/tabsContext";
import { deleteChatApi, getChatsApi, getFlowFromDatabase, readOnlineFlows } from "../../controllers/API";
import { FlowType } from "../../types/flow";
import { generateUUID } from "../../utils";
import SkillTemps from "../SkillPage/components/SkillTemps";
import ChatPanne from "./components/ChatPanne";

export default function SkillChatPage() {
    const [open, setOpen] = useState(false)
    const [face, setFace] = useState(true);

    const { t } = useTranslation()

    const { flows } = useContext(TabsContext);
    const [flow, setFlow] = useState<FlowType>(null)
    const [onlineFlows, setOnlineFlows] = useState([])
    useEffect(() => {
        readOnlineFlows().then(res => setOnlineFlows(res))
    }, [])
    // 对话列表
    const { chatList, chatId, chatsRef, setChatId, addChat, deleteChat } = useChatList()
    const chatIdRef = useRef('')

    // select flow
    const handlerSelectFlow = async (node: FlowType) => {
        setFlow(null)
        // 会话ID
        chatIdRef.current = generateUUID(32)
        setOpen(false)
        // add list
        addChat({
            "flow_name": node.name,
            "flow_description": node.description,
            "flow_id": node.id,
            "chat_id": chatIdRef.current,
            "create_time": "-",
            "update_time": "-"
        })

        // 预留 websoket 重连时间
        setTimeout(() => {
            setFlow(node)
            setChatId(chatIdRef.current)
            setFace(false)
        }, 200);
    }

    // select chat
    const handleSelectChat = async (chat) => {
        if (chat.chat_id === chatId) return
        setFlow(null)

        chatIdRef.current = chat.chat_id
        let flow = flows.find(flow => flow.id === chat.flow_id) || await getFlowFromDatabase(chat.flow_id)

        // if (!flow) {
        //     setInputState({ lock: true, errorCode: '1004' })
        //     clearHistory()
        //     return setFace(false)
        // }

        // 预留 websoket 重连时间
        flow && setTimeout(() => {
            setFlow(flow)
            setChatId(chat.chat_id)
            setFace(false)
        }, 200);
    }


    // del
    const handleDeleteChat = (e, id) => {
        e.stopPropagation();
        bsconfirm({
            desc: t('chat.confirmDeleteChat'),
            onOk(next) {
                deleteChat(id);
                setFace(true)
                next()
            }
        })
    }


    return <div className="flex">
        <div className="h-screen w-[200px] relative border-r">
            <div className="absolute flex pt-2 ml-[20px] bg-[#fff] dark:bg-gray-950">
                <div className="border rounded-lg px-4 py-2 text-center text-sm cursor-pointer w-[160px] bg-gray-50 hover:bg-gray-100 dark:hover:bg-gray-800 relative z-10" onClick={() => setOpen(true)}>{t('chat.newChat')}</div>
            </div>
            <div ref={chatsRef} className="scroll p-4 h-full overflow-y-scroll no-scrollbar pt-12">
                {
                    chatList.map((chat, i) => (
                        <div key={chat.chat_id}
                            className={` group item rounded-xl mt-2 p-2 relative hover:bg-gray-100 cursor-pointer  dark:hover:bg-gray-800  ${chatId === chat.chat_id && 'bg-gray-100 dark:bg-gray-800'}`}
                            onClick={() => handleSelectChat(chat)}>
                            <p className="break-words text-sm font-bold text-gray-600">{chat.flow_name}</p>
                            <span className="text-xs text-gray-500">{chat.flow_description}</span>
                            <Trash2 size={14} className="absolute bottom-2 right-2 text-gray-400 hidden group-hover:block" onClick={(e) => handleDeleteChat(e, chat.chat_id)}></Trash2>
                        </div>
                    ))
                }
            </div>
        </div>
        {/* chat */}
        {face
            ? <div className="flex-1 chat-box h-screen overflow-hidden relative">
                <p className="text-center mt-[100px] text-sm text-gray-600">{t('chat.selectChat')}</p>
            </div>
            : <div className="flex-1 chat-box h-screen relative">
                {flow && <ChatPanne chatId={chatId} flow={flow} onReload={handlerSelectFlow} />}
            </div>}
        {/* 选择对话技能 */}
        <SkillTemps
            flows={onlineFlows}
            title={t('chat.skillTempsTitle')}
            desc={t('chat.skillTempsDesc')}
            open={open} setOpen={setOpen}
            onSelect={(e) => handlerSelectFlow(e)}></SkillTemps>
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
            deleteChatApi(id)
            setChatList(oldList => oldList.filter(item => item.chat_id !== id))
        }
    }
}