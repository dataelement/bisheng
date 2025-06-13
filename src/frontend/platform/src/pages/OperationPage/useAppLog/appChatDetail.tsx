import MessagePanne from "@/components/bs-comp/chatComponent/MessagePanne";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import ShadTooltip from "@/components/ShadTooltipComponent";
import ChatMessages from "@/pages/BuildPage/flow/FlowChat/ChatMessages";
import { useMessageStore as useFlowMessageStore } from "@/pages/BuildPage/flow/FlowChat/messageStore";
import { useAssistantStore } from "@/store/assistantStore";
import { AppNumType } from "@/types/app";
import { ArrowLeft } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import MsgVNodeCom from './MsgBox';

export default function AppChatDetail() {
    const { fid, cid, type: typeStr } = useParams()
    const type = Number(typeStr)
    // console.log('fid, cid :>> ', fid, cid);
    const { t } = useTranslation()

    const loading = false;
    const title = t('log.detailedSession');
    const { loadAssistantState, destroy } = useAssistantStore()
    const { loadHistoryMsg, loadMoreHistoryMsg, changeChatId, clearMsgs } = useMessageStore()
    const {
        loadHistoryMsg: loadFlowHistoryMsg,
        loadMoreHistoryMsg: loadMoreFlowHistoryMsg,
        changeChatId: changeFlowChatId,
        clearMsgs: clearFlowMsgs } = useFlowMessageStore()

    useEffect(() => {
        type === AppNumType.ASSISTANT && loadAssistantState(fid, 'v1')

        type === AppNumType.FLOW ? loadFlowHistoryMsg(fid, cid, {
            appendHistory: true,
            lastMsg: ""
        }) : loadHistoryMsg(fid, cid, {
            appendHistory: true,
            lastMsg: ''
        })
        changeChatId(cid)
        changeFlowChatId(cid)
        return () => {
            clearMsgs()
            clearFlowMsgs()
            type === AppNumType.ASSISTANT && destroy()
        }
    }, [])

    return <div>
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
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
                {type === AppNumType.FLOW
                    ? <ChatMessages
                        operation logo={''} useName={''} guideWord={''} loadMore={() => loadMoreFlowHistoryMsg
                        (fid, true)}  mark={false} onMarkClick={null}></ChatMessages>
                    : <MessagePanne
                        operation
                        logo=''
                        useName=''
                        guideWord=''
                        mark={false}
                        loadMore={() => loadMoreHistoryMsg(fid, true)}
                    ></MessagePanne>
                }
            </div>
        </div>
    </div >
};
