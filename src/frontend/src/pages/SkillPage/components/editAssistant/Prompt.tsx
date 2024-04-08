import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { MixerHorizontalIcon } from "@radix-ui/react-icons";
import AutoPromptDialog from "./AutoPromptDialog";
import { useEffect, useState } from "react";
import { useAssistantStore } from "@/store/assistantStore";
import { Textarea } from "@/components/bs-ui/input";

export default function Prompt() {

    const [open, setOpen] = useState(false);

    const { assistantState, dispatchAssistant } = useAssistantStore()

    useEffect(() => {
        // 新建助手自动开启优化
        if (window.assistantCreate && assistantState.prompt) {
            setOpen(true)
            delete window.assistantCreate
        }
    }, [assistantState.prompt])

    return <div className="w-[50%] h-full bg-[#fff] shadow-sm p-4 overflow-y-auto scrollbar-hide">
        <div className="flex-between-center">
            <span className="text-sm font-medium leading-none">助手画像</span>
            <Dialog open={open} onOpenChange={setOpen}>
                <DialogTrigger asChild>
                    <Button variant="link" className="p-0"><MixerHorizontalIcon className="mr-1" />自动优化</Button>
                </DialogTrigger>
                {open && <AutoPromptDialog onOpenChange={setOpen}></AutoPromptDialog>}
            </Dialog>
        </div>
        <div className="h-[90%]">
            <Textarea
                className="border-none bg-transparent scrollbar-hide h-full focus-visible:ring-0 resize-none text-sm text-muted-foreground"
                value={assistantState.prompt}
                placeholder="详细、具体地描述助手与用户的交互方式，例如助手的身份、完成任务的具体方法和步骤、回答问题时的语气以及应该注意什么问题等"
                onInput={(e => dispatchAssistant('setPrompt', { prompt: e.target.value }))}
            ></Textarea>
        </div>
    </div>
};
