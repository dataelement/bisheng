// @ts-strict-ignore
import { Button, Textarea, notification, toast } from '@bisheng/ui';
import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { Outlined } from "bisheng-icons";


import { DialogClose,DialogContent,DialogFooter } from "@/components/bs-ui/dialog";


import { getAssistantOptimizeTaskApi } from "@/controllers/API/assistant";
import { useAssistantStore } from "@/store/assistantStore";
import { AssistantTool } from "@/types/assistant";
import { FlowType } from "@/types/flow";
import { t } from "i18next";

import { useEffect,useRef,useState } from "react";
import { useParams } from "react-router-dom";
import { streamErrorMessage } from "./useInitialPromptStream";

const enum LoadType {
    Prompt = 5,
    GuideWord = 4,
    GuideQuestion = 3,
    Tool = 2,
    Flow = 1
}

export default function AutoPromptDialog({ onOpenChange }) {

    const { id } = useParams()
    const { assistantState, dispatchAssistant } = useAssistantStore()

    const eventSourceRef = useRef<EventSource | null>(null)
    const init = async () => {
        // A retry replaces the previous run instead of letting both stream into the dialog
        eventSourceRef.current?.close()
        const prompt = areaRef.current?.value || assistantState.prompt
        const res = await getAssistantOptimizeTaskApi(id, prompt)
        const apiUrl = `${__APP_ENV__.BASE_URL}/api/v1/assistant/auto?task_id=${res.task_id}`;
        const eventSource = new EventSource(apiUrl);
        eventSourceRef.current = eventSource
        setStoppedAt(0)
        if (areaRef.current) areaRef.current.value = ''
        let queue: number = LoadType.Prompt
        setLoading(queue)

        eventSource.onmessage = (event) => {
            // If the event is parseable, return
            if (!event.data) {
                return;
            }
            const parsedData = JSON.parse(event.data);
            // console.log('parsedData :>> ', parsedData);
            switch (parsedData.type) {
                case 'prompt':
                    areaRef.current.value += parsedData.message.replace('```markdown', ''); break
                case 'guide_word':
                    guideAreaRef.current.value += parsedData.message; break
                case 'guide_question':
                    setQuestion(parsedData.message); break
                case 'tool_list':
                    setTools(parsedData.message); break
                case 'flow_list':
                    setFlows(parsedData.message); break
                case 'end':
                    if (parsedData.message) {
                        // The server stops the whole run after an error: clear every pending step so retry works
                        eventSource.close()
                        setStoppedAt(queue)
                        queue = 0
                        setLoading(0)
                        notification.open({ type: 'error', title: String(t('tip') ?? ''), description: String(streamErrorMessage(parsedData) ?? '') });
                    } else {
                        setLoading(--queue)
                    }
                    break
            }
            // Auto scroll
            areaRef.current.scrollTop = areaRef.current.scrollHeight;
        };

        eventSource.onerror = (error: any) => {
            console.error("EventSource failed:", error);
            eventSource.close();
            // The stream is over either way (normal close after the last step, or a dropped connection)
            if (queue > 0) setStoppedAt(queue)
            queue = 0
            setLoading(0);
            if (error.data) {
                const parsedData = JSON.parse(error.data);
                notification.open({ type: 'error', title: String(parsedData.error ?? ''), description: String('') });
            }
        };
    }


    useEffect(() => {
        // api
        init()
        return () => eventSourceRef.current?.close()
    }, [])

    const [loading, setLoading] = useState(0)
    // Step the run stopped at after an error; it and the later steps have no result to use
    const [stoppedAt, setStoppedAt] = useState(0)
    const unfinished = (step: LoadType) => step <= loading || step <= stoppedAt
    const handleReload = () => {
        init()
    }

    /**
     * Use
     */

    // state
    const areaRef = useRef(null)
    const guideAreaRef = useRef(null)
    const [question, setQuestion] = useState<string[]>([])
    const [tools, setTools] = useState<AssistantTool[]>([])
    const [flows, setFlows] = useState<FlowType[]>([])
    // Update prompt
    const handleUsePropmt = () => {
        const value = areaRef.current.value
        dispatchAssistant('setPrompt', { prompt: value })
        toast.show({ type: 'success', message: [String(t('tip') ?? ''), String(t('build.promptReplaced') ?? '')].filter(Boolean).join('\n') })
    }

    const handleUserQuestion = () => {
        dispatchAssistant('setQuestion', { guide_question: [...question, ''] })
        toast.show({ type: 'success', message: [String(t('tip') ?? ''), String(t('build.guideReplaced') ?? '')].filter(Boolean).join('\n') })
    }

    const handleUseGuide = () => {
        const value = guideAreaRef.current.value
        dispatchAssistant('setGuideword', { guide_word: value })
        toast.show({ type: 'success', message: [String(t('tip') ?? ''), String(t('build.openingReplaced') ?? '')].filter(Boolean).join('\n') })
    }

    const handleUseTools = () => {
        dispatchAssistant('setTools', { tool_list: tools })
        toast.show({ type: 'success', message: [String(t('tip') ?? ''), String(t('build.toolsReplaced') ?? '')].filter(Boolean).join('\n') })
    }

    const handleUseFlows = () => {
        dispatchAssistant('setFlows', { flow_list: flows })
        toast.show({ type: 'success', message: [String(t('tip') ?? ''), String(t('build.skillsReplaced') ?? '')].filter(Boolean).join('\n') })
    }

    const handleUseAll = () => {
        dispatchAssistant('setPrompt', { prompt: areaRef.current.value })
        dispatchAssistant('setGuideword', { guide_word: guideAreaRef.current.value })
        dispatchAssistant('setTools', { tool_list: tools })
        dispatchAssistant('setFlows', { flow_list: flows })
        dispatchAssistant('setQuestion', { guide_question: [...question, ''] })
        // Collect results
        toast.show({ type: 'success', message: [String(t('tip') ?? ''), String(t('build.allReplaced') ?? '')].filter(Boolean).join('\n') })
        onOpenChange(false)
    }

    return <DialogContent className="sm:max-w-[925px] bg-background-login max-h-[90vh] overflow-hidden flex flex-col" close={false}>
        <div className="flex-1 overflow-y-auto">
            <div className="flex">
                {/* Prompt */}
                <div className="w-[50%] relative pr-6">
                    <div className="flex items-center justify-between">
                        <span className="text-lg font-semibold leading-none tracking-tight flex items-center">{t('build.portraitOptimization')}{LoadType.Prompt === loading && <Outlined.Loading size={16} className="shrink-0 animate-spin ml-2 text-gray-600" />}</span>
                        <Button variant="link" size="small" onClick={handleReload} disabled={!!loading}><Outlined.Refresh size={14} className="mr-2" />{t('build.retry')}</Button>
                    </div>
                    <div className="group flex justify-end mt-2 h-[600px] relative">
                        <Textarea ref={areaRef} placeholder={t('prompt')} textareaClassName={"h-full"}></Textarea>
                        <Button className="group-hover:flex hidden absolute bottom-4 right-4" disabled={unfinished(LoadType.Prompt)} size="small" onClick={handleUsePropmt}>{t('build.use')}</Button>
                    </div>
                </div>
                {/* Automatic configuration */}
                <div className="w-[50%] border-l pl-6">
                    <div>
                        <span className="text-lg font-semibold leading-none tracking-tight">{t('build.automaticallyConfigurations')}</span>
                    </div>
                    <div className="">
                        {/* Opening statement */}
                        <div className="group relative pb-12 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                            <div className="text-md mb-2 font-medium leading-none flex items-center">{t('build.openingRemarks')}{LoadType.GuideWord === loading && <Outlined.Loading size={16} className="shrink-0 animate-spin ml-2 text-gray-600" />}</div>
                            <Textarea ref={guideAreaRef} textareaClassName={"bg-transparent border-none bg-gray-50 dark:bg-[#171717]"} borderless></Textarea>
                            <Button className="group-hover:flex hidden absolute bottom-4 right-4" disabled={unfinished(LoadType.GuideWord)} size="small" onClick={handleUseGuide}>{t('build.use')}</Button>
                        </div>
                        {/* Guide questions */}
                        <div className="group relative pb-12 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                            <div className="text-md mb-2 font-medium leading-none flex items-center">{t('build.guidingQuestions')}{LoadType.GuideQuestion === loading && <Outlined.Loading size={16} className="shrink-0 animate-spin ml-2 text-gray-600" />}</div>
                            <div className="min-h-32">
                                {
                                    question.map(qs => (
                                        <p key={qs} className="text-sm text-muted-foreground bg-gray-50 dark:bg-[#171717] px-2 py-1 rounded-xl mb-2">{qs}</p>
                                    ))
                                }
                            </div>
                            <Button className="group-hover:flex hidden absolute bottom-4 right-4" disabled={unfinished(LoadType.GuideQuestion)} size="small" onClick={handleUserQuestion}>{t('build.use')}</Button>
                        </div>
                        {/* Tools */}
                        <div className="group relative pb-10 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                            <div className="text-md mb-2 font-medium leading-none flex items-center">{t('build.tools')}{LoadType.Tool === loading && <Outlined.Loading size={16} className="shrink-0 animate-spin ml-2 text-gray-600" />}</div>
                            <div className="pt-1 min-h-32">
                                {
                                    tools.map(tool => (
                                        <div key={tool.id} className="flex gap-2 items-center mt-2">
                                            <TitleIconBg id={tool.id} className=" w-7 h-7" />
                                            <p className="text-sm">{tool.name}</p>
                                        </div>
                                    ))
                                }
                            </div>
                            <Button className="group-hover:flex hidden absolute bottom-4 right-4" disabled={unfinished(LoadType.Tool) || !tools.length} size="small" onClick={handleUseTools}>{t('build.use')}</Button>
                        </div>
                        {/* Skills */}
                        {/* <div className="group relative pb-10 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none flex items-center">{t('build.skill')}{LoadType.Flow === loading && <Outlined.Loading size={16} className="shrink-0 animate-spin ml-2 text-gray-600" />}</div>
                        <div className="pt-1">
                            {
                                flows.map(flow => (
                                    <div key={flow.id} className="flex gap-2 items-center mt-2">
                                        <TitleIconBg id={flow.id} className=" w-7 h-7" />
                                        <p className="text-sm">{flow.name}</p>
                                    </div>
                                ))
                            }
                        </div>
                        <Button
                            className="group-hover:flex hidden absolute bottom-4 right-4"
                            disabled={unfinished(LoadType.Flow) || !flows.length}
                            size="sm"
                            onClick={handleUseFlows}
                        >{t('build.use')}</Button>
                    </div> */}
                    </div>
                </div>
            </div>
        </div>
        {/* Bottom button area - fixed at bottom */}
        <DialogFooter className="border-t pt-2">
            <DialogClose>
                <Button variant="outlined" type="button" color="default">{t('cancle')}</Button>
            </DialogClose>
            <Button type="submit" disabled={!!loading || stoppedAt > 0} onClick={handleUseAll}>{t('build.useAll')}</Button>
        </DialogFooter>
    </DialogContent>
};
