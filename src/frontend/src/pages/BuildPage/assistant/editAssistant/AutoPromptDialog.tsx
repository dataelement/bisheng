import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { LoadIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogFooter } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useAssistantStore } from "@/store/assistantStore";
import { AssistantTool } from "@/types/assistant";
import { FlowType } from "@/types/flow";
import { t } from "i18next";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

const enum LoadType {
    Prompt = 5,
    GuideWord = 4,
    GuideQuestion = 3,
    Tool = 2,
    Flow = 1
}

export default function AutoPromptDialog({ onOpenChange }) {
    const { toast } = useToast()
    const { id } = useParams()
    const { assistantState, dispatchAssistant } = useAssistantStore()

    const init = () => {
        const prompt = areaRef.current?.value || assistantState.prompt
        const apiUrl = `${__APP_ENV__.BASE_URL}/api/v1/assistant/auto?assistant_id=${id}&prompt=${encodeURIComponent(prompt)}`;
        const eventSource = new EventSource(apiUrl);
        if (areaRef.current) areaRef.current.value = ''
        let queue = LoadType.Prompt
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
                    setLoading(--queue)
                    if (parsedData.message) {
                        toast({
                            title: t('tip'),
                            variant: 'error',
                            description: parsedData.message
                        });
                    }
                    break
            }
            // 自动滚动
            areaRef.current.scrollTop = areaRef.current.scrollHeight;
        };

        eventSource.onerror = (error: any) => {
            console.error("EventSource failed:", error);
            eventSource.close();
            if (error.data) {
                const parsedData = JSON.parse(error.data);
                setLoading(0);
                toast({
                    title: parsedData.error,
                    variant: 'error',
                    description: ''
                });
            }
        };
    }


    useEffect(() => {
        // api
        init()
    }, [])

    const [loading, setLoading] = useState(0)
    const handleReload = () => {
        init()
    }

    /**
     * 使用
     */
    const { message } = useToast()
    // state
    const areaRef = useRef(null)
    const guideAreaRef = useRef(null)
    const [question, setQuestion] = useState<string[]>([])
    const [tools, setTools] = useState<AssistantTool[]>([])
    const [flows, setFlows] = useState<FlowType[]>([])
    // 更新提示词
    const handleUsePropmt = () => {
        const value = areaRef.current.value
        dispatchAssistant('setPrompt', { prompt: value })
        message({
            variant: 'success',
            title: t('tip'),
            description: t('build.promptReplaced')
        })
    }

    const handleUserQuestion = () => {
        dispatchAssistant('setQuestion', { guide_question: [...question, ''] })
        message({
            variant: 'success',
            title: t('tip'),
            description: t('build.guideReplaced')
        })
    }

    const handleUseGuide = () => {
        const value = guideAreaRef.current.value
        dispatchAssistant('setGuideword', { guide_word: value })
        message({
            variant: 'success',
            title: t('tip'),
            description: t('build.openingReplaced')
        })
    }

    const handleUseTools = () => {
        dispatchAssistant('setTools', { tool_list: tools })
        message({
            variant: 'success',
            title: t('tip'),
            description: t('build.toolsReplaced')
        })
    }

    const handleUseFlows = () => {
        dispatchAssistant('setFlows', { flow_list: flows })
        message({
            variant: 'success',
            title: t('tip'),
            description: t('build.skillsReplaced')
        })
    }

    const handleUseAll = () => {
        dispatchAssistant('setPrompt', { prompt: areaRef.current.value })
        dispatchAssistant('setGuideword', { guide_word: guideAreaRef.current.value })
        dispatchAssistant('setTools', { tool_list: tools })
        dispatchAssistant('setFlows', { flow_list: flows })
        dispatchAssistant('setQuestion', { guide_question: [...question, ''] })
        // 收集结果
        message({
            variant: 'success',
            title: t('tip'),
            description: t('build.allReplaced')
        })
        onOpenChange(false)
    }


    return <DialogContent className="sm:max-w-[925px] bg-background-login">
        <div className="flex">
            {/* 提示词 */}
            <div className="w-[50%] relative pr-6">
                <div className="flex items-center justify-between">
                    <span className="text-lg font-semibold leading-none tracking-tight flex">{t('build.portraitOptimization')}{LoadType.Prompt === loading && <LoadIcon className="ml-2 text-gray-600" />}</span>
                    <Button variant="link" size="sm" onClick={handleReload} disabled={!!loading} ><RefreshCw className="mr-2" />{t('build.retry')}</Button>
                </div>
                <div className="group flex justify-end mt-2 h-[600px] relative">
                    <Textarea ref={areaRef} className="h-full"
                        placeholder={t('prompt')}
                    ></Textarea>
                    <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={LoadType.Prompt <= loading} size="sm" onClick={handleUsePropmt}>{t('build.use')}</Button>
                </div>
            </div>
            {/* 自动配置 */}
            <div className="w-[50%] border-l pl-6">
                <div>
                    <span className="text-lg font-semibold leading-none tracking-tight">{t('build.automaticallyConfigurations')}</span>
                </div>
                <div className="max-h-[660px] overflow-y-auto">
                    {/* 开场白 */}
                    <div className="group relative pb-12 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none flex">{t('build.openingRemarks')}{LoadType.GuideWord === loading && <LoadIcon className="ml-2 text-gray-600" />}</div>
                        <Textarea ref={guideAreaRef} className="bg-transparent border-none bg-gray-50 dark:bg-[#171717]"></Textarea>
                        <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={LoadType.GuideWord <= loading} size="sm" onClick={handleUseGuide}>{t('build.use')}</Button>
                    </div>
                    {/* 引导词 */}
                    <div className="group relative pb-12 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none flex">{t('build.guidingQuestions')}{LoadType.GuideQuestion === loading && <LoadIcon className="ml-2 text-gray-600" />}</div>
                        {
                            question.map(qs => (
                                <p key={qs} className="text-sm text-muted-foreground bg-gray-50 dark:bg-[#171717] px-2 py-1 rounded-xl mb-2">{qs}</p>
                            ))
                        }
                        <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={LoadType.GuideQuestion <= loading} size="sm" onClick={handleUserQuestion}>{t('build.use')}</Button>
                    </div>
                    {/* 工具 */}
                    <div className="group relative pb-10 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none flex">{t('build.tools')}{LoadType.Tool === loading && <LoadIcon className="ml-2 text-gray-600" />}</div>
                        <div className="pt-1">
                            {
                                tools.map(tool => (
                                    <div key={tool.id} className="flex gap-2 items-center mt-2">
                                        <TitleIconBg id={tool.id} className=" w-7 h-7" />
                                        <p className="text-sm">{tool.name}</p>
                                    </div>
                                ))
                            }
                        </div>
                        <Button
                            className="group-hover:flex text-slate-50 hidden h-6 absolute bottom-4 right-4"
                            disabled={LoadType.Tool <= loading || !tools.length} size="sm"
                            onClick={handleUseTools}
                        >{t('build.use')}</Button>
                    </div>
                    {/* 技能 */}
                    <div className="group relative pb-10 bg-gray-100 dark:bg-[#2A2B2E] mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none flex">{t('build.skill')}{LoadType.Flow === loading && <LoadIcon className="ml-2 text-gray-600" />}</div>
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
                            className="group-hover:flex text-slate-50 hidden h-6 absolute bottom-4 right-4"
                            disabled={LoadType.Flow <= loading || !flows.length}
                            size="sm"
                            onClick={handleUseFlows}
                        >{t('build.use')}</Button>
                    </div>
                </div>
            </div>
        </div>
        <DialogFooter>
            <DialogClose>
                <Button variant="outline" className="px-11" type="button">{t('cancle')}</Button>
            </DialogClose>
            <Button type="submit" className="px-11" disabled={!!loading} onClick={handleUseAll}>{t('build.useAll')}</Button>
        </DialogFooter>
    </DialogContent>
};
