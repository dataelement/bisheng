import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { LoadIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogFooter } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useAssistantStore } from "@/store/assistantStore";
import { AssistantTool } from "@/types/assistant";
import { FlowType } from "@/types/flow";
import { ReloadIcon } from "@radix-ui/react-icons";
import { useEffect, useRef, useState } from "react";

export default function AutoPromptDialog({ onOpenChange }) {

    const { assistantState, dispatchAssistant } = useAssistantStore()

    const init = () => {
        // sse
        createSSE()
        // made tools
        createTools()
    }

    // 流式读取引导词及开场白
    const createSSE = () => {
        const { prompt } = assistantState
        // sse api
        const timer = setInterval(() => {
            areaRef.current.value += '打字'
            guideAreaRef.current.value += '开场白'
        }, 120)
        setTimeout(() => {
            clearInterval(timer)
            setLoading(false)
        }, 2000);
    }

    // 获取可用工具和技能
    const createTools = () => {
        const { prompt } = assistantState
        // api
        setTools([{ id: 1, name: '文档 OCR 识别' }, { id: 2, name: 'RPA扫描' },])
        setFlows([])
    }

    useEffect(() => {
        // api
        init()
    }, [])

    const [loading, setLoading] = useState(true)
    const handleReload = () => {
        setLoading(true)
        init()
    }

    const { message } = useToast()
    // state
    const areaRef = useRef(null)
    const guideAreaRef = useRef(null)
    const [tools, setTools] = useState<AssistantTool[]>([])
    const [flows, setFlows] = useState<FlowType[]>([])
    // 更新提示词
    const handleUsePropmt = () => {
        const value = areaRef.current.value
        dispatchAssistant('setPrompt', { prompt: value })
        message({
            variant: 'success',
            title: '提示',
            description: '提示词已替换'
        })
    }

    const handleUseGuide = (params) => {
        const value = guideAreaRef.current.value
        dispatchAssistant('setGuideword', { guide_word: value })
        message({
            variant: 'success',
            title: '提示',
            description: '开场白已替换'
        })
    }

    const handleUseTools = () => {
        dispatchAssistant('setTools', { tool_list: tools })
        message({
            variant: 'success',
            title: '提示',
            description: '工具已替换'
        })
    }

    const handleUseFlows = () => {
        dispatchAssistant('setFlows', { flow_list: flows })
        message({
            variant: 'success',
            title: '提示',
            description: '技能已替换'
        })
    }

    const handleUseAll = () => {
        dispatchAssistant('setPrompt', { prompt: areaRef.current.value })
        dispatchAssistant('setGuideword', { guide_word: guideAreaRef.current.value })
        dispatchAssistant('setTools', { tool_list: tools })
        dispatchAssistant('setFlows', { flow_list: flows })
        // 收集结果
        message({
            variant: 'success',
            title: '提示',
            description: '已全部替换'
        })
        onOpenChange(false)
    }


    return <DialogContent className="sm:max-w-[925px]">
        <div className="flex">
            {/* 提示词 */}
            <div className="w-[50%] relative pr-6">
                <div className="flex items-center justify-between">
                    <span className="text-lg font-semibold leading-none tracking-tight flex">助手画像优化{loading && <LoadIcon className="ml-2 text-gray-600" />}</span>
                    <Button variant="link" size="sm" onClick={handleReload} disabled={loading} ><ReloadIcon className="mr-2" />重试</Button>
                </div>
                <div className="group flex justify-end mt-2 h-[600px] relative">
                    <Textarea ref={areaRef} className="h-full" defaultValue={assistantState.prompt}
                        placeholder="详细、具体地描述助手与用户的交互方式，例如助手的身份、完成任务的具体方法和步骤、回答问题时的语气以及应该注意什么问题等"
                    ></Textarea>
                    <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={loading} size="sm" onClick={handleUsePropmt}>使用</Button>
                </div>
            </div>
            {/* 自动配置 */}
            <div className="w-[50%] border-l pl-6">
                <div>
                    <span className="text-lg font-semibold leading-none tracking-tight">自动为您选择相关配置</span>
                </div>
                <div className="max-h-[660px] overflow-y-auto">
                    {/* 开场白 */}
                    <div className="group relative pb-12 bg-gray-100 mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none">开场白</div>
                        <Textarea ref={guideAreaRef} className="bg-transparent border-none"></Textarea>
                        {/* <p className="text-sm text-muted-foreground">开场白开场白开场白开场白开场白开场白开场白开场白开场白开场白开场白</p> */}
                        <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={loading} size="sm" onClick={handleUseGuide}>使用</Button>
                    </div>
                    {/* 工具 */}
                    <div className="group relative pb-10 bg-gray-100 mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none">工具</div>
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
                            className="group-hover:flex hidden h-6 absolute bottom-4 right-4"
                            disabled={loading || !tools.length} size="sm"
                            onClick={handleUseTools}
                        >使用</Button>
                    </div>
                    {/* 技能 */}
                    <div className="group relative pb-10 bg-gray-100 mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none">技能</div>
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
                            className="group-hover:flex hidden h-6 absolute bottom-4 right-4"
                            disabled={loading || !flows.length}
                            size="sm"
                            onClick={handleUseFlows}
                        >使用</Button>
                    </div>
                </div>
            </div>
        </div>
        <DialogFooter>
            <DialogClose>
                <Button variant="outline" className="px-10" type="button">取消</Button>
            </DialogClose>
            <Button type="submit" className="px-10" disabled={loading} onClick={handleUseAll}>全部使用</Button>
        </DialogFooter>
    </DialogContent>
};
