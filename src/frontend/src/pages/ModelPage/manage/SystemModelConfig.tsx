import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import AssisModel from "./tabs/AssisModel";
import EvaluationModel from "./tabs/EvaluationModel";
import KnowledgeModle from "./tabs/KnowledgeModel";
import WorkflowModel from "./tabs/WorkflowModel";

export default function SystemModelConfig({ data, onBack }) {
    const { t } = useTranslation('model')
    const { llmOptions, embeddings } = useMemo(() => {
        let llmOptions = []
        let embeddings = []
        data.forEach(server => {
            const serverEmbItem = { value: server.id, label: server.name, children: [] }
            const serverLlmItem = { value: server.id, label: server.name, children: [] }
            server.models.forEach(model => {
                const item = {
                    value: model.id,
                    label: model.model_name
                }
                if (!model.online) return

                model.model_type === 'embedding' ?
                    serverEmbItem.children.push(item) : serverLlmItem.children.push(item)
            })

            if (serverLlmItem.children.length) llmOptions.push(serverLlmItem)
            if (serverEmbItem.children.length) embeddings.push(serverEmbItem)
        });

        return { llmOptions, embeddings }
    }, [data])

    return <div className="px-2 py-4 size-full pb-20 relative overflow-y-auto">
        <div className="">
            <div className="flex ml-6 items-center gap-x-3">
                <ShadTooltip content={t('back')} side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => onBack()}>
                        <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                <span>{t('model.systemModelSettings')}</span>
            </div>
            <div className="px-4">
                <Tabs defaultValue="knowledge" className="flex flex-col">
                    <TabsList className="w-[550px] m-auto">
                        <TabsTrigger value="knowledge" className="w-[150px]">{t('model.knowledgeBaseModel')}</TabsTrigger>
                        <TabsTrigger value="assis" className="w-[150px]">{t('model.assistantModel')}</TabsTrigger>
                        <TabsTrigger value="evaluation" className="w-[150px]">{t('model.evaluationModel')}</TabsTrigger>
                        <TabsTrigger value="workflow" className="w-[150px]">{t('model.workflowModel')}</TabsTrigger>
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
                    <TabsContent value="workflow">
                        <WorkflowModel llmOptions={llmOptions} onBack={onBack}></WorkflowModel>
                    </TabsContent>
                </Tabs>
            </div>
        </div>
    </div>
}