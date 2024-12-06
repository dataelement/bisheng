import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/bs-ui/input";
import { useAssistantStore } from "@/store/assistantStore";
import { Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import AutoPromptDialog from "./AutoPromptDialog";

export default function Prompt() {

    const { t } = useTranslation()

    const [open, setOpen] = useState(false);

    const { assistantState, dispatchAssistant } = useAssistantStore()

    useEffect(() => {
        // 新建助手自动开启优化
        if (window.assistantCreate && assistantState.prompt) {
            setOpen(true)
            delete window.assistantCreate
        }
    }, [assistantState.prompt])

    return <div className="w-[50%] h-full bg-background-login shadow-sm p-4 overflow-y-auto scrollbar-hide">
        <div className="flex-between-center">
            <span className="text-sm font-medium leading-none">{t('build.assistantPortrait')}</span>
            <Dialog open={open} onOpenChange={setOpen}>
                <DialogTrigger asChild>
                    <Button variant="link" className="p-0"><Settings2 className="mr-1 h-4 w-4" />{t('build.automaticOptimization')}</Button>
                </DialogTrigger>
                {open && <AutoPromptDialog onOpenChange={setOpen}></AutoPromptDialog>}
            </Dialog>
        </div>
        <Textarea
            boxClassName='h-[90%]'
            className="h-full border-none bg-transparent scrollbar-hide focus-visible:ring-0 resize-none text-sm text-muted-foreground"
            value={assistantState.prompt}
            placeholder={t('prompt')}
            onInput={(e => dispatchAssistant('setPrompt', { prompt: e.target.value }))}
        ></Textarea>
    </div>
};
