// @ts-strict-ignore
import { captureQaOperation, isCurrentQaOperation, type QaOperation } from '@bisheng/chat/core';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import type { AnnotationFormHandle } from './annotationTypes';
import { Button } from '@bisheng/ui';
import MessagePanne from "@/components/bs-comp/chatComponent/MessagePanne";
import { MessageStoreProvider as AssistantMessageStoreProvider, useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";

import { RadioGroup, Radio, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { getMarkPermissionApi, getMarkStatusApi, getNextMarkChatApi, updateMarkStatusApi } from "@/controllers/API/log";
import { MessageStoreProvider as WorkflowMessageStoreProvider, useMessageStore as useFlowMessageStore } from "@/pages/BuildPage/flow/FlowChat/messageStore";
import { AppNumType } from "@/types/app";
import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import ChatMessages from "../BuildPage/flow/FlowChat/ChatMessages";
import AddSimilarQuestions from "./AddSimilarQuestions";
import SaveQaLibForm from "./SaveQaLibForm";

const PageChange = () => {
    const { id, cid } = useParams()
    const [hasPrev, setHasPrev] = useState(false)
    const [hasNext, setHasNext] = useState(false)
    const prevInfoRef = useRef<any>(null)
    const nextInfoRef = useRef<any>(null)
    const { t } = useTranslation()
    useEffect(() => {
        getNextMarkChatApi({ action: 'prev', chat_id: cid, task_id: id }).then(res => {
            setHasPrev(!!res)
            prevInfoRef.current = res
        })
        getNextMarkChatApi({ action: 'next', chat_id: cid, task_id: id }).then(res => {
            setHasNext(!!res)
            nextInfoRef.current = res
        })
    }, [cid])

    const navigate = useNavigate()
    const jumpToNext = (way: number) => {
        const info = way === -1 ? prevInfoRef.current : nextInfoRef.current
        const { flow_id, chat_id, flow_type } = info
        navigate(`/label/chat/${id}/${flow_id}/${chat_id}/${flow_type}`)
    }

    return <div className="flex gap-2">
        <Button variant="outlined" disabled={!hasPrev} className="border-primary text-primary text-xs h-8" onClick={() => jumpToNext(-1)} color="default">{t('label.previousChat')}</Button>
        <Button variant="outlined" disabled={!hasNext} className="border-primary text-primary text-xs h-8" onClick={() => jumpToNext(1)} color="default">{t('label.nextChat')}</Button>
    </div>
}

// 标注状态
const enum LabelStatus {
    Unlabeled = '1',
    Labeled = '2',
    Unnecessary = '3'
}

function TaskAppChatsContent() {
    const { id, fid, cid, type: typeStr } = useParams()
    const type = Number(typeStr)
    // console.log('fid, cid :>> ', fid, cid);
    const { t } = useTranslation()
    const navigator = useNavigate()

    const mark = useAuth()

    const [status, setStatus] = React.useState(LabelStatus.Unlabeled)
    const [isSelf, setIsSelf] = useState(false)
    const loading = false;
    const { loadHistoryMsg, loadMoreHistoryMsg, changeChatId, clearMsgs } = useMessageStore()
    const { loadHistoryMsg: loadFlowHistoryMsg,
        loadMoreHistoryMsg: loadMoreFlowHistoryMsg,
        changeChatId: changeFlowChatId,
        clearMsgs: clearFlowMsgs
    } = useFlowMessageStore()
    const qaFormRef = useRef<AnnotationFormHandle>(null)
    const similarFormRef = useRef<AnnotationFormHandle>(null)
    const sessionRef = useRef({ taskId: id, conversationId: cid, generation: 0 })
    if (sessionRef.current.taskId !== id || sessionRef.current.conversationId !== cid) {
        sessionRef.current = { taskId: id, conversationId: cid, generation: sessionRef.current.generation + 1 }
    }
    const actionSequence = useRef(0)
    const pendingMarks = useRef(new Map<string, { operation: Readonly<QaOperation>; unlabeled: boolean }>())
    useEffect(() => {
        const session = sessionRef.current
        qaFormRef.current?.close()
        similarFormRef.current?.close()
        // type === 'assistant' && loadAssistantState(fid, 'v1') 禁用助手详情,涉及权限403问题
        type === AppNumType.FLOW ? loadFlowHistoryMsg(fid, cid, {
            appendHistory: true,
            lastMsg: ""
        }) : loadHistoryMsg(fid, cid, {
            appendHistory: true,
            lastMsg: ''
        })
        changeChatId(cid)
        changeFlowChatId(cid)

        // get status
        getMarkStatusApi({ task_id: Number(id), chat_id: cid }).then((res: any) => {
            if (sessionRef.current !== session) return
            setStatus(String(res.status || 1))
            setIsSelf(res.is_self === undefined ? true : res.is_self)
        })

        return () => {
            sessionRef.current = { ...sessionRef.current, generation: sessionRef.current.generation + 1 }
            clearMsgs()
            clearFlowMsgs()
        }
    }, [cid])

    const handleMarkClick = (kind: 'question' | 'answer', msgId: string, qa) => {
        if (!mark || !msgId || !id || !cid) return
        const operation = captureQaOperation({ taskId: id, conversationId: cid,
            sourceMessageId: String(msgId), actionId: `${++actionSequence.current}`,
            sessionGeneration: sessionRef.current.generation })
        pendingMarks.current.set(operation.actionId, { operation, unlabeled: status === LabelStatus.Unlabeled })
        if (kind === 'question') similarFormRef.current?.open(msgId, qa, operation)
        else qaFormRef.current?.open(msgId, qa, operation)
    }

    const isCurrentSession = (operation: Readonly<QaOperation>) => isCurrentQaOperation(operation, {
        ...operation, taskId: sessionRef.current.taskId ?? '', conversationId: sessionRef.current.conversationId ?? '',
        sessionGeneration: sessionRef.current.generation
    })
    const handleMarkAfter = async (operation?: Readonly<QaOperation>) => {
        if (!operation) return
        const pending = pendingMarks.current.get(operation.actionId)
        if (!pending || !isCurrentQaOperation(operation, pending.operation)) return
        pendingMarks.current.delete(operation.actionId)
        if (!pending.unlabeled) return
        await updateMarkStatusApi({ session_id: operation.conversationId,
            task_id: Number(operation.taskId), status: Number(LabelStatus.Labeled) })
        if (isCurrentSession(operation)) setStatus(LabelStatus.Labeled)
    }
    const changeMarkStatus = (nextStatus: LabelStatus) => {
        const session = sessionRef.current
        void captureAndAlertRequestErrorHoc(updateMarkStatusApi({ session_id: cid, task_id: Number(id), status: Number(nextStatus) })
            .then(() => { if (sessionRef.current === session) setStatus(nextStatus) }))
    }

    return <div className="flex h-full min-h-0 flex-col">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="bg-background-login px-4 flex min-h-0 flex-1 flex-col">
            <div className="flex shrink-0 flex-wrap gap-3 justify-between items-center py-4">
                <div className="flex items-center">
                    <Tooltip content={t('back')} side="top">
                        <Button size="medium" aria-label={t('back')} variant="outlined" onClick={() => navigator('/label/' + id)} color="default" iconOnly><Outlined.ArrowLeft size={16} /></Button>
                    </Tooltip>
                    <span className=" text-gray-700 text-sm font-black pl-4">{t('label.returnToList')}</span>
                </div>
                <RadioGroup value={status}
                    onValueChange={(value: LabelStatus) => changeMarkStatus(value)} disabled={!isSelf && status !== LabelStatus.Unlabeled}>
                    <Radio disabled={!mark} value={LabelStatus.Unlabeled}>{t('label.unlabeled')}</Radio>
                    <Radio disabled={!mark} value={LabelStatus.Labeled}>{t('label.labeled')}</Radio>
                    <Radio disabled={!mark} value={LabelStatus.Unnecessary}>{t('label.unnecessary')}</Radio>
                </RadioGroup>
                <PageChange />
            </div>
            <div className="min-h-0 flex-1">
                {type === AppNumType.FLOW
                    ? <ChatMessages mark={mark} logo='' useName='' guideWord='' loadMore={() => loadMoreFlowHistoryMsg(fid, true)} onMarkClick={handleMarkClick}></ChatMessages>
                    : <MessagePanne mark={mark} logo='' useName='' guideWord=''
                        loadMore={() => loadMoreHistoryMsg(fid, true)}
                        onMarkClick={handleMarkClick}
                    ></MessagePanne>
                }
            </div>
        </div>
        {/* 问题 */}
        <SaveQaLibForm ref={qaFormRef} onMarked={handleMarkAfter} />
        {/* 答案 */}
        <AddSimilarQuestions ref={similarFormRef} onMarked={handleMarkAfter} />
    </div>
};

// 权限
const useAuth = () => {
    const [mark, setMark] = useState(false);
    useEffect(() => {
        getMarkPermissionApi().then(setMark)
    }, [])

    return mark
}

export default function TaskAppChats() {
    const { id, cid } = useParams();
    return <AssistantMessageStoreProvider key={`${id}:${cid}`}><WorkflowMessageStoreProvider><TaskAppChatsContent /></WorkflowMessageStoreProvider></AssistantMessageStoreProvider>;
}
