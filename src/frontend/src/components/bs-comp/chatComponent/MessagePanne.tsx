import ThumbsMessage from "@/pages/ChatAppPage/components/ThumbsMessage";
import FileBs from "./FileBs";
import MessageBs from "./MessageBs";
import MessageSystem from "./MessageSystem";
import MessageUser from "./MessageUser";
import RunLog from "./RunLog";
import Separator from "./Separator";
import { useMessageStore } from "./messageStore";
import { useRef } from "react";
import ResouceModal from "@/pages/ChatAppPage/components/ResouceModal";
import { useTranslation } from "react-i18next";

export default function MessagePanne({ useName, guideWord }) {
    const { t } = useTranslation()
    const { messages } = useMessageStore()

    // 反馈
    const thumbRef = useRef(null)
    // 溯源
    const sourceRef = useRef(null)

    return <div className="h-full overflow-y-auto scrollbar-hide pt-12 pb-52">
        {guideWord && <MessageSystem key={99999} data={{ category: '', thought: guideWord }} />}
        {
            messages.map(msg => {
                // 工厂
                let type = 'llm'
                if (msg.thought) {
                    type = 'system'
                } else if (msg.category === 'divider') {
                    type = 'separator'
                } else if (msg.isSend) {
                    type = 'user'
                } else if (msg.files?.length) {
                    type = 'file'
                } else if (msg.category === 'tool') {
                    type = 'runLog'
                }

                switch (type) {
                    case 'user':
                        return <MessageUser key={msg.id} useName={useName} data={msg} />;
                    case 'llm':
                        return <MessageBs
                            key={msg.id}
                            data={msg}
                            onUnlike={(chatId) => { thumbRef.current?.openModal(chatId) }}
                            onSource={(data) => { sourceRef.current?.openModal(data) }}
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
                        return <div className="text-sm mt-2 border rounded-md p-2" key={msg.id}>未知消息类型</div>;
                }
            })
        }
        {/* 踩 反馈 */}
        <ThumbsMessage ref={thumbRef}></ThumbsMessage>
        {/* 源文件类型 */}
        <ResouceModal ref={sourceRef}></ResouceModal>
    </div>
};
