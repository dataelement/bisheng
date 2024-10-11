import MessagePanne from "@/components/bs-comp/chatComponent/MessagePanne";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { Button } from "@/components/bs-ui/button";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft } from "lucide-react";
import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import AddSimilarQuestions from "./AddSimilarQuestions";
import SaveQaLibForm from "./SaveQaLibForm";
import { useTranslation } from "react-i18next";
import { useAssistantStore } from "@/store/assistantStore";

export default function AppChatDetail() {
    const { fid, cid, type } = useParams()
    // console.log('fid, cid :>> ', fid, cid);
    const { t } = useTranslation()

    const loading = false;
    const title = t('log.detailedSession');
    const { loadAssistantState, destroy } = useAssistantStore()
    const { loadHistoryMsg, loadMoreHistoryMsg, changeChatId, clearMsgs } = useMessageStore()
    const qaFormRef = useRef(null)
    const similarFormRef = useRef(null)
    useEffect(() => {
        type === 'assistant' && loadAssistantState(fid, 'v1')
        loadHistoryMsg(fid, cid, {
            appendHistory: true,
            lastMsg: ''
        })
        changeChatId(cid)
        return () => {
            clearMsgs()
            type === 'assistant' && destroy()
        }
    }, [])

    const handleMarkClick = (type: 'question' | 'answer', msgId: string, qa) => {
        if (type === 'question') {
            similarFormRef.current.open(msgId, qa)
        } else if (type === 'answer') {
            qaFormRef.current.open(msgId, qa)
        }
    }

    return <div>
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="bg-background-login px-4">
            <div className="flex justify-between items-center py-4">
                <div className="flex items-center">
                    <ShadTooltip content="back" side="top">
                        <Button
                            className="w-[36px] px-2 rounded-full"
                            variant="outline"
                            onClick={() => window.history.back()}
                        ><ArrowLeft className="side-bar-button-size" /></Button>
                    </ShadTooltip>
                    <span className=" text-gray-700 text-sm font-black pl-4">{title}</span>
                </div>
            </div>
            <div className="h-[calc(100vh-132px)]">
                <MessagePanne mark logo='' useName='' guideWord=''
                    loadMore={() => loadMoreHistoryMsg(fid, true)}
                    onMarkClick={handleMarkClick}
                ></MessagePanne>
            </div>
        </div>
        {/* 问题 */}
        <SaveQaLibForm ref={qaFormRef} />
        {/* 答案 */}
        <AddSimilarQuestions ref={similarFormRef} />
    </div>
};
