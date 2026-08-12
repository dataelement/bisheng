import { LoadIcon } from "@/components/bs-icons/loading";
import { ToastIcon } from "@/components/bs-icons/toast";
import { cname } from "@/components/bs-ui/utils";
import { useAssistantStore } from "@/store/assistantStore";
import { ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

// F041: every selected knowledge space is served by one backend tool named
// `knowledge_space_retriever`, so the run log carries this literal key instead of a knowledge id.
const SPACE_RETRIEVER_TOOL_KEY = 'space_retriever'
// KnowledgeTypeEnum.SPACE
const KNOWLEDGE_SPACE_TYPE = 3

export default function RunLog({ data }) {
    const [open, setOpen] = useState(false)
    const { t } = useTranslation()

    // Only used on the assistant debug page: match names against the assistant's own lists.
    const assistantState = useAssistantStore(state => state.assistantState)

    const [title, lost] = useMemo(() => {
        // Settled by the session closing rather than by its own end frame — say so
        // instead of showing a success tick the call never earned.
        if (data.interrupted) return [t('chat.runLog.interrupted'), true]
        let lost = false
        let title = ''
        const status = data.end ? t('chat.runLog.used') : t('chat.runLog.using')
        if (data.category === 'flow') {
            const flow = assistantState.flow_list?.find(flow => flow.id === data.message.tool_key)
            if (flow) {
                lost = flow.status === 1
                title = lost ? t('chat.runLog.flowOffline', { name: flow.name }) : `${status} ${flow.name}`
            } else {
                title = t('chat.runLog.flowDeleted')
            }
        } else if (data.category === 'tool') {
            const tool = assistantState.tool_list?.find(tool => tool.tool_key === data.message.tool_key)

            title = tool ? `${status} ${tool.name}` : t('chat.runLog.toolDeleted')
        } else if (data.category === 'knowledge') {
            const searchStatus = data.end ? t('chat.runLog.searched') : t('chat.runLog.searching')
            const toolKey = data.message.tool_key
            const knowledgeList = assistantState.knowledge_list || []
            const names = toolKey === SPACE_RETRIEVER_TOOL_KEY
                ? knowledgeList.filter(knowledge => knowledge.type === KNOWLEDGE_SPACE_TYPE).map(knowledge => knowledge.name)
                : knowledgeList.filter(knowledge => knowledge.id === parseInt(toolKey)).map(knowledge => knowledge.name)

            title = names.length ? `${searchStatus} ${names.join(', ')}` : t('chat.runLog.knowledgeDeleted')
        } else {
            title = data.end ? t('chat.runLog.done') : t('chat.runLog.thinking')
        }
        return [title, lost]
    }, [assistantState, data, t])

    // Nothing configured on the assistant — nothing to name, so hide the log.
    if ((assistantState.tool_list?.length ?? 0) + (assistantState.knowledge_list?.length ?? 0)
        + (assistantState.flow_list?.length ?? 0) === 0) return null

    if (data.type === 'end_cover') return null

    return <div className="py-1">
        <div className="rounded-sm border max-w-[90%]">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer" onClick={() => setOpen(!open)}>
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        data.end ? <ToastIcon type={lost ? 'error' : 'success'} /> :
                            <LoadIcon className="text-primary duration-300" />
                    }
                    <span>{title}</span>
                </div>
                <ChevronDown className={open ? 'rotate-180' : undefined} />
            </div>
            <div className={cname('bg-[#F5F6F8] dark:bg-[#313336] px-4 py-2 overflow-hidden text-sm ', open ? 'h-auto' : 'h-0 p-0')}>
                {data.thought.split('\n').map((line, index) => (
                    <p className="text-md mb-1 text-muted-foreground" key={index}>{line}</p>
                ))}
            </div>
        </div>
    </div>
};
