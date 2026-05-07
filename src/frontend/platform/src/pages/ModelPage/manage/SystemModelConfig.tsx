import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { userContext } from "@/contexts/userContext";
import { getTenantsApi } from "@/controllers/API/tenant";
import { useAdminScope } from "@/hooks/useAdminScope";
import { Tenant } from "@/types/api/tenant";
import { ArrowLeft } from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { isGlobalSuperUser } from "./permissions";
import { ScopeBanner } from "./SystemConfigBanners";
import AssisModel from "./tabs/AssisModel";
import EvaluationModel from "./tabs/EvaluationModel";
import KnowledgeModle from "./tabs/KnowledgeModel";
import WorkflowModel from "./tabs/WorkflowModel";
import WorkbenchModel from "./tabs/WorkbenchModel";

const ROOT_TENANT_ID = 1;

export default function SystemModelConfig({ data, defaultTab, onBack }: { data: any; defaultTab?: string; onBack: () => void }) {
    const { t } = useTranslation('model')
    const { user } = useContext(userContext) as any
    // useAdminScope's GET /admin/tenant-scope returns HTTP 403 + 19701 for
    // non-super callers (INV-T14). Only enable the fetch for the global
    // super admin; Child Admins keep the empty default scope, which the
    // ScopeBanner / childTenant memo below handle correctly.
    const { scope } = useAdminScope({ enabled: isGlobalSuperUser(user) })
    const [tenants, setTenants] = useState<Tenant[]>([])

    // Refetch tenants once on mount; ScopeBar already does the same fetch
    // independently — caching across components would require a shared
    // react-query key, an OK trade-off for this dialog's small footprint.
    useEffect(() => {
        let cancelled = false
        getTenantsApi({ page: 1, page_size: 100, status: 'active' })
            .then((res) => {
                if (!cancelled) setTenants(res?.data || [])
            })
            .catch(() => {
                if (!cancelled) setTenants([])
            })
        return () => { cancelled = true }
    }, [])

    const rootTenant = useMemo(
        () => tenants.find((row) => row.id === ROOT_TENANT_ID) || null,
        [tenants],
    )
    const childTenant = useMemo(() => {
        if (scope.scope_tenant_id === null || scope.scope_tenant_id === ROOT_TENANT_ID) return null
        return tenants.find((row) => row.id === scope.scope_tenant_id) || null
    }, [scope.scope_tenant_id, tenants])

    const isGlobalSuper = isGlobalSuperUser(user)

    const { llmOptions, embeddings, asrModel, ttsModel} = useMemo(() => {
        let llmOptions = []
        let embeddings = []
        let asrModel = []
        let ttsModel = []
        const rerank = []
        data.forEach(server => {
            const serverEmbItem = { value: server.id, label: server.name, children: [] }
            const serverLlmItem = { value: server.id, label: server.name, children: [] }
            const serverAsrItem = { value: server.id, label: server.name, children: [] }
            const serverTtsItem = { value: server.id, label: server.name, children: [] }
            const rerankItem = { value: server.id, label: server.name, children: [] }

            server.models.forEach(model => {
                const item = {
                    value: model.id,
                    label: model.model_name
                }
                if (!model.online) return
                if (model.model_type === 'asr') {
                    serverAsrItem.children.push(item)
                } else if (model.model_type === 'tts') {
                    serverTtsItem.children.push(item)
                } else if (model.model_type === 'embedding') {
                    serverEmbItem.children.push(item)
                } else if (model.model_type === 'llm') {
                    serverLlmItem.children.push(item)
                } else {
                    rerankItem.children.push(item)
                }
            })

            if (serverLlmItem.children.length) llmOptions.push(serverLlmItem)
            if (serverEmbItem.children.length) embeddings.push(serverEmbItem)
            if (serverAsrItem.children.length) asrModel.push(serverAsrItem)
            if (serverTtsItem.children.length) ttsModel.push(serverTtsItem)
            if (rerankItem.children.length) rerank.push(rerankItem)
        });

        return { llmOptions, embeddings, asrModel, ttsModel,rerank}
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
                <ScopeBanner
                    isGlobalSuper={isGlobalSuper}
                    scopeTenantId={scope.scope_tenant_id ?? null}
                    rootTenant={rootTenant}
                    childTenant={childTenant}
                />
                <Tabs defaultValue={defaultTab || "workbench"} className="flex flex-col">
                    <TabsList className="w-[550px] m-auto">
                        <TabsTrigger value="workbench" className="w-[150px]">{t('model.workModel')}</TabsTrigger>
                        <TabsTrigger value="knowledge" className="w-[150px]">{t('model.knowledgeBaseModel')}</TabsTrigger>
                        <TabsTrigger value="assis" className="w-[150px]">{t('model.assistantModel')}</TabsTrigger>
                        <TabsTrigger value="evaluation" className="w-[150px]">{t('model.evaluationModel')}</TabsTrigger>
                        <TabsTrigger value="workflow" className="w-[150px]">{t('model.workflowModel')}</TabsTrigger>
                    </TabsList>
                     <TabsContent value="workbench">
                        <WorkbenchModel llmOptions={llmOptions} embeddings={embeddings} asrModel={asrModel} ttsModel={ttsModel} onBack={onBack}></WorkbenchModel>
                    </TabsContent>
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
