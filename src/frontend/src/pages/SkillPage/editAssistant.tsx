import { useAssistantStore } from "@/store/assistantStore";
import Header from "./components/editAssistant/Header";
import Prompt from "./components/editAssistant/Prompt";
import Setting from "./components/editAssistant/Setting";
import TestChat from "./components/editAssistant/TestChat";
import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { changeAssistantStatusApi, saveAssistanttApi } from "@/controllers/API/assistant";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";

export default function editAssistant() {
    const { id: assisId } = useParams()
    // assistant data
    const { assistantState, changed, loadAssistantState, saveAfter } = useAssistantStore()
    const { startNewRound, insetSystemMsg, setShowGuideQuestion } = useMessageStore()

    useEffect(() => {
        loadAssistantState(assisId).then((res) => {
            setShowGuideQuestion(true)
            setGuideQuestion(res.guide_question || [''])
        })
    }, [])

    // 引导词独立存储
    const [guideQuestion, setGuideQuestion] = useState([])
    const handleStartChat = async (params) => {
        await handleSave(true)
        saveAfter()
        startNewRound()
        setGuideQuestion(assistantState.guide_question)
        assistantState.guide_word && insetSystemMsg(assistantState.guide_word)
    }

    const { message, toast } = useToast()
    // 保存助手详细信息
    const handleSave = async (showMessage = false) => {
        await captureAndAlertRequestErrorHoc(saveAssistanttApi({
            ...assistantState,
            flow_list: assistantState.flow_list.map(item => item.id),
            tool_list: assistantState.tool_list.map(item => item.id)
        })).then(res => {
            if (!res) return
            showMessage && message({
                title: '提示',
                variant: 'success',
                description: '保存成功'
            })
        })
    }

    // 上线助手
    const handleOnline = async () => {
        await handleSave()
        await captureAndAlertRequestErrorHoc(changeAssistantStatusApi(assistantState.id, 1)).then(res => {
            if (!res) return
            message({
                title: '提示',
                variant: 'success',
                description: '上线成功'
            })
        })
    }

    return <div className="bg-[#F4F5F8]">
        <Header onSave={() => handleSave(true)} onLine={handleOnline}></Header>
        <div className="flex h-[calc(100vh-70px)]">
            <div className="w-[60%]">
                <div className="text-md font-medium leading-none p-4 shadow-sm">助手配置</div>
                <div className="flex h-[calc(100vh-120px)]">
                    <Prompt></Prompt>
                    <Setting></Setting>
                </div>
            </div>
            <div className="w-[40%] h-full bg-[#fff] relative">
                <TestChat guideQuestion={guideQuestion} assisId={assisId}></TestChat>
                {/* 变更触发保存的蒙版按钮 */}
                {changed && <div className="absolute w-full bottom-0 h-60" onClick={handleStartChat}></div>}
            </div>
        </div>
    </div>
};
