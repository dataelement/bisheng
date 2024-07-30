import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import AssisModel from "./tabs/AssisModel";
import EvaluationModel from "./tabs/EvaluationModel";
import KnowledgeModle from "./tabs/KnowledgeModel";

export default function SystemModelConfig({ onBack }) {
    const { t } = useTranslation()

    return <div className="w-full relative">
        <div className="">
            <div className="flex ml-6 items-center gap-x-3">
                <ShadTooltip content={t('back')} side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => onBack()}>
                        <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                <span>系统模型设置</span>
            </div>
            <div className=" absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 h-full">
                <Tabs defaultValue="knowledge" className="h-full flex flex-col">
                    <TabsList className="w-[450px] m-auto">
                        <TabsTrigger value="knowledge" className="w-[150px]">知识库模型</TabsTrigger>
                        <TabsTrigger value="assis" className="w-[150px]">助手模型</TabsTrigger>
                        <TabsTrigger value="evaluation" className="w-[150px]">评测模型</TabsTrigger>
                    </TabsList>
                    <TabsContent value="knowledge">
                        <KnowledgeModle onBack={() => onBack()}></KnowledgeModle>
                    </TabsContent>
                    <TabsContent value="assis">
                        <AssisModel onBack={() => onBack()}></AssisModel>
                    </TabsContent>
                    <TabsContent value="evaluation">
                        <EvaluationModel onBack={() => onBack()}></EvaluationModel>
                    </TabsContent>
                </Tabs>
            </div>
        </div>
    </div>
}