import { useRef } from "react";
import { useRecoilValue } from "recoil";
import GuideWord from "./components/GuideWord";
import InputForm from "./components/InputForm";
import MessageBs from "./components/MessageBs";
import MessageBsChoose from "./components/MessageBsChoose";
import MessageFeedbackForm from "./components/MessageFeedbackForm";
import MessageFile from "./components/MessageFile";
import MessageNodeRun from "./components/MessageNodeRun";
import MessageSystem from "./components/MessageSystem";
import MessageUser from "./components/MessageUser";
import ResouceModal from "./components/ResouceModal";
import { currentChatState, currentRunningState } from "./store/atoms";
import { useMessage } from "./useMessages";

export default function ChatMessages({ useName, logo }) {
    const { messageScrollRef, chatId, messages } = useMessage()
    const { inputForm, guideWord } = useRecoilValue(currentRunningState)
    const chatState = useRecoilValue(currentChatState)

    console.log('messages :>> ', chatState, messages);
    // 反馈
    const thumbRef = useRef(null)
    // 溯源
    const sourceRef = useRef(null)


    return <div ref={messageScrollRef} className="h-full overflow-y-auto scrollbar-hide pt-12 pb-60 px-4">
        {
            messages.map((msg, index) => {
                // 技能特殊消息
                if (msg.files?.length) {
                    return <MessageFile key={msg.id} data={msg} logo={logo} />
                } else if (['tool', 'flow', 'knowledge'].includes(msg.category)) {
                    return <div>123xxxxxx</div>
                } else if (msg.thought) {
                    return <MessageSystem key={msg.id} data={msg} />;
                }

                // output节点特殊msg
                switch (msg.category) {
                    case 'input':
                        return null
                    case 'question':
                        return <MessageUser
                            key={msg.id}
                            useName={useName}
                            data={msg}
                        />;
                    case 'guide_word':
                    case 'output_msg':
                    case 'stream_msg':
                    case "answer":
                        return <MessageBs
                            key={msg.id}
                            data={msg}
                            logo={logo}
                            onUnlike={(messageId) => { thumbRef.current?.openModal(messageId) }}
                            onSource={(data) => { sourceRef.current?.openModal({ ...data, chatId }) }}
                        />;
                    case 'divider':
                        return <div key={msg.id} className={'flex items-center justify-center py-4 text-gray-400 text-sm'}>
                            ----------- {msg.message} -----------
                        </div>
                    case 'output_with_choose_msg':
                        return <MessageBsChoose key={msg.id} data={msg} logo={logo} />;
                    case 'output_with_input_msg':
                        return <MessageBsChoose type='input' key={msg.id} data={msg} logo={logo} />;
                    case 'node_run':
                        return <MessageNodeRun key={msg.id} data={msg} />;
                    case 'system':
                        return <MessageSystem key={msg.id} data={msg} />;
                    default:
                        return <div className="text-sm mt-2 border rounded-md p-2" key={msg.id}>Unknown message type</div>;
                }
            })
        }
        {/* 引导词 */}
        {guideWord && <GuideWord data={guideWord} />}
        {/* 表单 */}
        {inputForm && <InputForm data={inputForm} flow={chatState.flow} />}
        <MessageFeedbackForm ref={thumbRef}></MessageFeedbackForm>
        <ResouceModal ref={sourceRef}></ResouceModal>
    </div>
};
