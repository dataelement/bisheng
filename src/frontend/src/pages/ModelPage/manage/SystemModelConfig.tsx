import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import AssisModel from "./tabs/AssisModel";
import EvaluationModel from "./tabs/EvaluationModel";
import KnowledgeModle from "./tabs/KnowledgeModel";
import { useMemo } from "react";

export default function SystemModelConfig({ data, onBack }) {
    const { t } = useTranslation()
    const { llmOptions, embeddings } = useMemo(() => {
        let llmOptions = []
        let embeddings = []
        data.forEach(server => {
            const serverItem = { value: server.id, label: server.name, children: [] }
            serverItem.children = server.models.reduce((res, model) => model.model_type === 'embedding' ? [...res, {
                value: model.id,
                label: model.model_name
            }] : res, [])
            if (serverItem.children.length) embeddings.push(serverItem)
            llmOptions = [...llmOptions, ...server.models.filter(model => model.model_type === 'llm')];
        });

        return { llmOptions, embeddings }
    }, [data])

    return <div className="px-2 py-4 w-full relative">
        <div className="">
            <div className="flex ml-6 items-center gap-x-3">
                <ShadTooltip content={t('back')} side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => onBack()}>
                        <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                <span>系统模型设置</span>
            </div>
            <div className="px-4 h-full">
                <Tabs defaultValue="knowledge" className="h-full flex flex-col">
                    <TabsList className="w-[450px] m-auto">
                        <TabsTrigger value="knowledge" className="w-[150px]">知识库模型</TabsTrigger>
                        <TabsTrigger value="assis" className="w-[150px]">助手模型</TabsTrigger>
                        <TabsTrigger value="evaluation" className="w-[150px]">评测模型</TabsTrigger>
                    </TabsList>
                    <TabsContent value="knowledge">
                        <KnowledgeModle llmOptions={llmOptions} embeddings={embeddings} onBack={onBack}></KnowledgeModle>
                    </TabsContent>
                    <TabsContent value="assis">
                        <AssisModel llmOptions={llmOptions} onBack={onBack}></AssisModel>
                    </TabsContent>
                    <TabsContent value="evaluation">
                        <EvaluationModel llmOptions={llmOptions} onBack={onBack}></EvaluationModel>
                    </TabsContent>
                </Tabs>
            </div>
        </div>
    </div>
}