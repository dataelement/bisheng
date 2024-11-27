import MessagePanne from "@/components/bs-comp/chatComponent/MessagePanne";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { useAssistantStore } from "@/store/assistantStore";
import { ArrowLeft } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import AddSimilarQuestions from "../LogPage/useAppLog/AddSimilarQuestions";
import SaveQaLibForm from "../LogPage/useAppLog/SaveQaLibForm";
import { getMarkPermissionApi, getMarkStatusApi, getNextMarkChatApi, updateMarkStatusApi } from "@/controllers/API/log";

const PageChange = () => {
    const { id, cid } = useParams()
    const [hasPrev, setHasPrev] = useState(false)
    const [hasNext, setHasNext] = useState(false)
    const prevInfoRef = useRef<any>(null)
    const nextInfoRef = useRef<any>(null)
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
        <Button
            variant="outline"
            disabled={!hasPrev}
            className="border-primary text-primary text-xs h-8"
            onClick={() => jumpToNext(-1)}
        >上一条会话</Button>
        <Button
            variant="outline"
            disabled={!hasNext}
            className="border-primary text-primary text-xs h-8"
            onClick={() => jumpToNext(1)}
        >下一条会话</Button>
    </div>
}

// 标注状态
const enum LabelStatus {
    Unlabeled = '1',
    Labeled = '2',
    Unnecessary = '3'
}

export default function index() {
    const { id, fid, cid, type } = useParams()
    // console.log('fid, cid :>> ', fid, cid);
    const { t } = useTranslation()
    const navigator = useNavigate()

    const mark = useAuth()

    const [status, setStatus] = React.useState(LabelStatus.Unlabeled)
    const [isSelf, setIsSelf] = useState(false)
    const loading = false;
    const { loadAssistantState, destroy } = useAssistantStore()
    const { loadHistoryMsg, loadMoreHistoryMsg, changeChatId, clearMsgs } = useMessageStore()
    const qaFormRef = useRef(null)
    const similarFormRef = useRef(null)
    useEffect(() => {
        // type === 'assistant' && loadAssistantState(fid, 'v1') 禁用助手详情,涉及权限403问题
        loadHistoryMsg(fid, cid, {
            appendHistory: true,
            lastMsg: ''
        })
        changeChatId(cid)

        // get status
        getMarkStatusApi({ task_id: Number(id), chat_id: cid }).then((res: any) => {
            setStatus(String(res.status || 1))
            setIsSelf(res.is_self === undefined ? true : res.is_self)
        })

        return () => {
            clearMsgs()
            type === 'assistant' && destroy()
        }
    }, [cid])

    const handleMarkClick = (type: 'question' | 'answer', msgId: string, qa) => {
        if (type === 'question') {
            similarFormRef.current.open(msgId, qa)
        } else if (type === 'answer') {
            qaFormRef.current.open(msgId, qa)
        }
    }

    // 完成标注
    const handleMarkAfter = () => {
        if (status === LabelStatus.Unlabeled) {
            changeMarkStatus(LabelStatus.Labeled)
        }
    }
    const changeMarkStatus = (status: LabelStatus) => {
        updateMarkStatusApi({ session_id: cid, task_id: Number(id), status: Number(status) })
        setStatus(status)
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
                            onClick={() => navigator('/label/' + id)}
                        ><ArrowLeft className="side-bar-button-size" /></Button>
                    </ShadTooltip>
                    <span className=" text-gray-700 text-sm font-black pl-4">返回列表</span>
                </div>
                <RadioGroup className="flex space-x-2 h-[20px] items-center" value={status}
                    onValueChange={(value: LabelStatus) => changeMarkStatus(value)} disabled={!isSelf && status !== LabelStatus.Unlabeled}>
                    <Label className="flex justify-center">
                        <RadioGroupItem className="mr-2" disabled={!mark} value={LabelStatus.Unlabeled} />未标注
                    </Label>
                    <Label className="flex justify-center">
                        <RadioGroupItem className="mr-2" disabled={!mark} value={LabelStatus.Labeled} />已标注
                    </Label>
                    <Label className="flex justify-center">
                        <RadioGroupItem className="mr-2" disabled={!mark} value={LabelStatus.Unnecessary} />无需标注
                    </Label>
                </RadioGroup>
                <PageChange />
            </div>
            <div className="h-[calc(100vh-132px)]">
                <MessagePanne mark={mark} logo='' useName='' guideWord=''
                    loadMore={() => loadMoreHistoryMsg(fid, true)}
                    onMarkClick={handleMarkClick}
                ></MessagePanne>
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
