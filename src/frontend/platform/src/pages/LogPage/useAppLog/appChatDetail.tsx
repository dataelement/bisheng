// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import AppAvator from "@/components/bs-comp/cardComponent/avatar";
import MessagePanne from "@/components/bs-comp/chatComponent/MessagePanne";
import { MessageStoreProvider as AssistantMessageStoreProvider, useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { LoadingIcon } from "@/components/bs-icons/loading";

import { Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { getAssistantDetailApi } from "@/controllers/API/assistant";
import { getDeleteFlowApi } from "@/controllers/API/flow";
import { showApiError } from "@/controllers/request";
import ChatMessages from "@/pages/BuildPage/flow/FlowChat/ChatMessages";
import { MessageStoreProvider as WorkflowMessageStoreProvider, useMessageStore as useFlowMessageStore } from "@/pages/BuildPage/flow/FlowChat/messageStore";
import { AppNumType } from "@/types/app";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

function AppChatDetailContent() {
    const { fid, cid, type: typeStr } = useParams()
    const type = Number(typeStr)
    // console.log('fid, cid :>> ', fid, cid);
    const { t } = useTranslation()

    const loading = false;
    const title = t('log.detailedSession');
    const [assistantState, setAssistantDetail] = useState({ name: '', logo: '' })
    const { loadHistoryMsg, loadMoreHistoryMsg, changeChatId, clearMsgs } = useMessageStore()
    const {
        loadHistoryMsg: loadFlowHistoryMsg,
        loadMoreHistoryMsg: loadMoreFlowHistoryMsg,
        changeChatId: changeFlowChatId,
        clearMsgs: clearFlowMsgs } = useFlowMessageStore()

    useEffect(() => {
        let active = true
        if (type === AppNumType.ASSISTANT) void getAssistantDetailApi(fid, 'v1').then(detail => { if (active) setAssistantDetail(detail) }).catch(showApiError)

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
            active = false
            clearMsgs()
            clearFlowMsgs()
        }
    }, [fid, cid, type])

    const logo = useAppAvatar(cid, type, assistantState)

    return <div>
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="bg-background-login px-4">
            <div className="flex justify-between items-center py-4">
                <div className="flex items-center">
                    <Tooltip content={t('back')} side="top">
                        <Button size="medium" aria-label={t('back')} variant="outlined" onClick={() => window.history.back()} color="default" iconOnly><Outlined.ArrowLeft size={16} /></Button>
                    </Tooltip>
                    <span className=" text-gray-700 text-sm font-black pl-4">{title}</span>
                </div>
            </div>
            <div className="h-[calc(100vh-132px-var(--license-banner-h,0px))]">
                {type === AppNumType.FLOW
                    ? <ChatMessages logo={logo} debug useName={''} guideWord={''} loadMore={() => loadMoreFlowHistoryMsg(fid, true)} onMarkClick={null}></ChatMessages>
                    : <MessagePanne chat={assistantState} logo={logo} debug useName='' guideWord=''
                        loadMore={() => loadMoreHistoryMsg(fid, true)}
                    ></MessagePanne>
                }
            </div>
        </div>
    </div >
};


const useAppAvatar = (cid, flowType, assistantState) => {
    const [logo, setLogo] = useState('')
    const [title, setTitle] = useState('')
    const loadAppDetail = async () => {
        const lostflow = await getDeleteFlowApi(cid)
        setLogo(lostflow.flow_logo)
        setTitle(lostflow.flow_name)
    }

    useEffect(() => {
        if (flowType !== AppNumType.ASSISTANT) {
            loadAppDetail()
        }
    }, [])

    return flowType === AppNumType.ASSISTANT ?
        <AppAvator id={assistantState.name} flowType={flowType} url={assistantState.logo} className="size-5 min-w-5"></AppAvator> :
        <AppAvator id={title} flowType={flowType} url={logo} className="size-5 min-w-5"></AppAvator>
}
export default function AppChatDetail() {
    const { fid, cid, type } = useParams();
    return <AssistantMessageStoreProvider key={`${fid}:${cid}:${type}`}><WorkflowMessageStoreProvider><AppChatDetailContent /></WorkflowMessageStoreProvider></AssistantMessageStoreProvider>;
}
