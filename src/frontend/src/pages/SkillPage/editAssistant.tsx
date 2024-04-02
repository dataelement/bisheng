import { useAssistantStore } from "@/store/assistantStore";
import Header from "./components/editAssistant/Header";
import Prompt from "./components/editAssistant/Prompt";
import Setting from "./components/editAssistant/Setting";
import TestChat from "./components/editAssistant/TestChat";
import { useEffect } from "react";
import { useParams } from "react-router";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { saveAssistanttApi } from "@/controllers/API/assistant";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";

export default function editAssistant() {
    const { id: assisId } = useParams()
    // assistant data
    const { assistantState, changed, loadAssistantState, saveAfter } = useAssistantStore()
    const { insetSeparator } = useMessageStore()

    useEffect(() => {
        loadAssistantState(assisId)
    }, [])

    const handleStartChat = async (params) => {
        await handleSave({})
        saveAfter()
        insetSeparator('配置已更新')
    }

    const { message, toast } = useToast()
    // 保存助手详细信息
    const handleSave = async (params) => {
        await captureAndAlertRequestErrorHoc(saveAssistanttApi({
            ...assistantState,
            ...params,
            flow_list: assistantState.flow_list.map(item => item.id),
            tool_list: assistantState.tool_list.map(item => item.id)
        })).then(res => {
            if (!res) return
            message({
                title: '提示',
                variant: 'success',
                description: params.status ? '上线成功' : '保存成功'
            })
        })
    }

    return <div className="bg-[#F4F5F8]">
        <Header onSave={handleSave}></Header>
        <div className="flex h-[calc(100vh-70px)]">
            <div className="w-[60%]">
                <div className="text-md font-medium leading-none p-4 shadow-sm">助手配置</div>
                <div className="flex h-[calc(100vh-120px)]">
                    <Prompt></Prompt>
                    <Setting></Setting>
                </div>
            </div>
            <div className="w-[40%] h-full bg-[#fff] relative">
                <TestChat assisId={assisId}></TestChat>
                {changed && <div className="absolute w-full bottom-0 h-60" onClick={handleStartChat}></div>}
            </div>
        </div>
    </div>


};
