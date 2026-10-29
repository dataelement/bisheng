// @ts-strict-ignore
import { toast } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import { Button } from "@bisheng/ui"
import { locationContext } from "@/contexts/locationContext"
import { userContext } from "@/contexts/userContext"
import { useContext, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
// import { transformModule, transformEvent, transformObjectType } from "../LogPage/utils"


import { changeLLmServerStatus, getAssistantModelList, getModelListApi, verifyLLmModelStatus } from "@/controllers/API/finetune"
import { useQuery } from "@tanstack/react-query"
import { useNavigate, useSearchParams } from "react-router-dom"
import ModelConfig from "./ModelConfig"
import { canManageModelSettings } from "./permissions"
import { isSpeechModelType } from "./speechConfig"
import { ScopeBar } from "./ScopeBar"
import { ModelProviderRow } from "./ModelProviderRow"
import SystemModelConfig from "./SystemModelConfig"

// Saving a provider returns before its model probes finish: they run in the
// background, each bounded by the backend's 30s probe timeout. The list polls
// for a bounded window so the rows that the save reset to unknown pick up the
// verdict without a manual refresh.
const PROBE_POLL_MS = 3000
const PROBE_WINDOW_MS = 45000
const STATUS_UNKNOWN = 2

export default function Management() {
    const { t, i18n } = useTranslation();
    useEffect(() => {
        i18n.loadNamespaces('model');
    }, [i18n]);

    const [data, setData] = useState([])
    const { user } = useContext(userContext)
    const { appConfig } = useContext(locationContext)
    const [modelId, setModelId] = useState(null)
    const [systemModel, setSystemModel] = useState(false)
    const [systemModelTab, setSystemModelTab] = useState<string | undefined>(undefined)
    const [loading, setLoading] = useState(false)
    const { refetch } = useModel()
    const canManage = canManageModelSettings(user, appConfig.multiTenantEnabled)
    const [searchParams, setSearchParams] = useSearchParams()
    const navigate = useNavigate()
    useEffect(() => {
        const tab = searchParams.get('systemModel')
        if (tab === 'dsh') {
            navigate('/dsh', { replace: true })
            return
        }
        // Wait for model list to load before opening SystemModelConfig — otherwise
        // AssisModel's ModelSelect sees empty options and nulls out existing model_ids.
        if (tab && data.length > 0) {
            setSystemModelTab(tab)
            setSystemModel(true)
            const next = new URLSearchParams(searchParams)
            next.delete('systemModel')
            setSearchParams(next, { replace: true })
        }
    }, [searchParams, setSearchParams, data, navigate])

    const reload = async () => {
        setLoading(true)
        setData(await getModelListApi())
        setLoading(false)
        refetch()
    }
    useEffect(() => { reload() }, [])

    // 0 = not polling; otherwise the time after which polling gives up.
    const [probeUntil, setProbeUntil] = useState(0)
    useEffect(() => {
        if (!probeUntil) return
        const timer = setInterval(async () => {
            const list = await getModelListApi()
            setData(list)
            const pending = list.some(server => server.models.some(m => m.status === STATUS_UNKNOWN))
            if (!pending || Date.now() > probeUntil) setProbeUntil(0)
        }, PROBE_POLL_MS)
        return () => clearInterval(timer)
    }, [probeUntil])

    const handleGetRepeatName = (name) => {
        let index = 0
        let nameIndex = ''
        data.forEach(el => {
            if (el.name.indexOf(name) === 0) {
                const match = el.name.match(/\d+$/)
                const num = match ? match[0] : 0
                index = Math.max(index, Number(num))
                nameIndex = ` ${index + 1}`
            }
        })
        return `${name}${nameIndex}`
    }


    // off & online
    const handleCheck = async (serverId: number, modelId: number, online: boolean) => {
        await changeLLmServerStatus(String(modelId), Number(online));
        setData(prev => prev.map(server => server.id === serverId
            ? { ...server, models: server.models.map(model => model.id === modelId ? { ...model, online } : model) }
            : server));
        void refetch();
        return true;
    }

    const handleVerify = async (serverId: number, modelId: number) => {
        const result = await verifyLLmModelStatus(modelId);
        if (result?.id) {
            handleVerified(serverId, result);
            toast.show({ type: 'success', message: String(t('model.statusUpdated') ?? '') });
        }
    }

    // Patch the verified row from the response rather than refetching the whole
    // list — a refetch would collapse nothing but does throw away the expanded
    // state's scroll position for a single-row change.
    const handleVerified = (serverId, model) => {
        setData(prev => prev.map(server => server.id === serverId
            ? {
                ...server,
                models: server.models.map(el => el.id === model.id
                    ? { ...el, status: model.status, remark: model.remark, status_update_time: model.status_update_time }
                    : el)
            }
            : server))
    }

    if (modelId) return <ModelConfig
        id={modelId}
        onGetName={handleGetRepeatName}
        onBack={() => setModelId(null)}
        onReload={reload}
        onBerforSave={(id, name) => data.some(el => el.name === name && el.id !== id)}
        onAfterSave={(msg) => {
            toast.show({ type: 'success', message: String(msg ?? '') })
            reload()
            setProbeUntil(Date.now() + PROBE_WINDOW_MS)
        }}
    />

    if (systemModel) return <SystemModelConfig
        data={data}
        defaultTab={systemModelTab}
        onTabChange={setSystemModelTab}
        onBack={() => { setSystemModel(false); setSystemModelTab(undefined); }}
    />

    return <div className="relative bg-background-login h-full px-2 py-4">
        {loading && (
            <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <Outlined.Loading  className="size-4 animate-spin"/>
            </div>
        )}
        <div className="h-full overflow-y-auto">
            {/* v2.5.1 F019: scope switcher lives here (LLM is the only page
                whose data actually changes with scope). System-level config
                stays super-admin only regardless of active scope. */}
            <div className="ml-4 mr-2 flex items-center justify-between gap-4">
                <div>
                    {appConfig.multiTenantEnabled && <ScopeBar user={user} onScopeChange={reload} />}
                </div>
                <div className="flex gap-4">
                    {canManage && <Button onClick={() => setSystemModel(true)} variant="filled"
                        className="gap-1 text-danger hover:text-danger" color="default">
                        <Outlined.Setting className="text-danger" />
                        {t('model.systemModelSettings')}
                    </Button>}
                    {canManage && <Button onClick={() => setModelId(-1)}>{t('model.addModel')}</Button>}
                    <Button variant="solid" color="default" onClick={reload}>{t('model.refresh')}</Button>
                </div>
            </div>
            <div className="h-[85%]">
                <div className="flex h-10 justify-between items-center font-medium text-muted-foreground text-sm">
                    <span className="ml-4">{t('model.serviceProvider')}</span>
                    <span className="mr-5">{t('model.actions')}</span>
                </div>
                <div className="pb-20">
                    {
                        data.map(d => <ModelProviderRow
                            key={d.id}
                            canManage={canManage}
                            data={d}
                            probing={probeUntil > 0}
                            onToggle={(modelId, online) => handleCheck(d.id, modelId, online)}
                            onVerify={modelId => handleVerify(d.id, modelId)}
                            onModel={setModelId}
                        />)
                    }
                </div>
            </div>
        </div>
    </div>

}

// model list（embeddings llm）
export function useModel(type = 'llm') {
    const { data, isLoading, refetch } = useQuery({
        queryKey: [type === 'llm' ? "QueryModelsKey" : "QueryAssistantModelsKey"],
        queryFn: () => type === 'llm' ? getModelListApi() : getAssistantModelList(),
        select: (data) => {
            const llmOptions = []
            const embeddings = []
            const asrModel = []
            const ttsModel = []
            const rerank = []
            data.forEach(server => {
                const serverEmbItem = { value: server.id, label: server.name, children: [] }
                const serverLlmItem = { value: server.id, label: server.name, children: [] }
                const serverAsrItem = { value: server.id, label: server.name, children: [] }
                const serverTtsItem = { value: server.id, label: server.name, children: [] }
                const rerankItem = { value: server.id, label: server.name, children: [] }
                server.models.forEach(model => {
                    const item = {
                        value: String(model.id),
                        label: model.model_name
                    }
                    if (!model.online) return
                    if (isSpeechModelType(model.model_type)) {
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

            return { llmOptions, embeddings, asrModel, ttsModel, rerank }
        }
    });

    const {
        llmOptions = [],
        embeddings = [],
        asrModel = [],
        ttsModel = [],
        rerank = []
    } = data ?? {};
    return {
        llmOptions,
        embeddings,
        asrModel,
        ttsModel,
        isLoading,
        rerank,
        refetch
    }
}
