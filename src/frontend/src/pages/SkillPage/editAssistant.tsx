import { useAssistantStore } from "@/store/assistantStore";
import Header from "./components/editAssistant/Header";
import Prompt from "./components/editAssistant/Prompt";
import Setting from "./components/editAssistant/Setting";
import TestChat from "./components/editAssistant/TestChat";
import { useEffect } from "react";
import { useParams } from "react-router";

export default function editAssistant() {
    const { id: assisId } = useParams()
    // assistant data
    const loadData = useAssistantStore(state => state.loadAssistantState)
    useEffect(() => {
        loadData(assisId)
    }, [])

    return <div className="bg-[#F4F5F8]">
        <Header></Header>
        <div className="flex h-[calc(100vh-70px)]">
            <div className="w-[60%]">
                <div className="text-md font-medium leading-none p-4 shadow-sm">助手配置</div>
                <div className="flex h-[calc(100vh-120px)]">
                    <Prompt></Prompt>
                    <Setting></Setting>
                </div>
            </div>
            <div className="w-[40%] h-full bg-[#fff]">
                <TestChat assisId={assisId}></TestChat>
            </div>
        </div>
    </div>


};
