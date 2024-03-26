import { SkillIcon } from "@/components/bs-icons/skill";
import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogFooter } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { ReloadIcon } from "@radix-ui/react-icons";
import { useRef, useState } from "react";

export default function AutoPromptDialog({ onOpenChange }) {

    const [loading, setLoading] = useState(false)
    const handleReload = () => {
        setLoading(true)
        const timer = setInterval(() => {
            areaRef.current.value += '打字'
            guideAreaRef.current.value += '开场白'
        }, 120)
        setTimeout(() => {
            clearInterval(timer)
            setLoading(false)
        }, 2000);
    }

    const { message } = useToast()
    const areaRef = useRef(null)
    const guideAreaRef = useRef(null)
    const handleUsePropmt = () => {
        const value = areaRef.current.value
        message({
            variant: 'success',
            title: '提示',
            description: '提示词已替换'
        })
    }

    const handleUseGuide = (params) => {
        const value = guideAreaRef.current.value
        message({
            variant: 'success',
            title: '提示',
            description: '开场白已替换'
        })
    }

    const handleUseTools = (type) => {
        message({
            variant: 'success',
            title: '提示',
            description: type + '已替换'
        })
    }

    const handleUseAll = () => {
        // 收集结果
        // zuland
    }


    return <DialogContent className="sm:max-w-[925px]">
        <div className="flex">
            {/* 提示词 */}
            <div className="w-[50%] relative pr-6">
                <div className="flex items-center justify-between">
                    <span className="text-lg font-semibold leading-none tracking-tight">助手画像优化</span>
                    <Button variant="link" size="sm" onClick={handleReload} disabled={loading} ><ReloadIcon className="mr-2" />重试</Button>
                </div>
                <div className="group flex justify-end mt-2 h-[600px] relative">
                    <Textarea ref={areaRef} className="h-full"
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
                    <div className="group relative pb-12 bg-gray-100 mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none">开场白</div>
                        <Textarea ref={guideAreaRef} className="bg-transparent border-none"></Textarea>
                        {/* <p className="text-sm text-muted-foreground">开场白开场白开场白开场白开场白开场白开场白开场白开场白开场白开场白</p> */}
                        <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={loading} size="sm" onClick={handleUseGuide}>使用</Button>
                    </div>
                    <div className="group relative pb-10 bg-gray-100 mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none">工具</div>
                        <div className="pt-1">
                            <div className="flex gap-2 items-center mt-2">
                                <div className="flex items-center justify-center w-7 h-7 bg-blue-500"><SkillIcon></SkillIcon></div>
                                <p className="text-sm">文档 OCR 识别</p>
                            </div>
                            <div className="flex gap-2 items-center mt-2">
                                <div className="flex items-center justify-center w-7 h-7 bg-blue-500"><SkillIcon></SkillIcon></div>
                                <p className="text-sm">文档 OCR 识别</p>
                            </div>
                        </div>
                        <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={loading} size="sm" onClick={() => handleUseTools('tools')}>使用</Button>
                    </div>
                    <div className="group relative pb-10 bg-gray-100 mt-4 px-4 py-2 rounded-md">
                        <div className="text-md mb-2 font-medium leading-none">技能</div>
                        <div className="pt-1">
                            <div className="flex gap-2 items-center mt-2">
                                <div className="flex items-center justify-center w-7 h-7 bg-green-700"><SkillIcon></SkillIcon></div>
                                <p className="text-sm">尽调报告生成</p>
                            </div>
                        </div>
                        <Button className="group-hover:flex hidden h-6 absolute bottom-4 right-4" disabled={loading} size="sm" onClick={() => handleUseTools('skill')}>使用</Button>
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
