// @ts-strict-ignore
import { LoadIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/bs-ui/input";
import { useAssistantStore } from "@/store/assistantStore";
import { Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import AutoPromptDialog from "./AutoPromptDialog";
import { assistantRoleExample } from "./roleExample";
import { useInitialPromptStream } from "./useInitialPromptStream";

export default function Prompt({ canEdit = false }) {

    const { t } = useTranslation()

    const [open, setOpen] = useState(false);

    const { assistantState, dispatchAssistant } = useAssistantStore()

    // A new assistant gets its optimized prompt streamed straight into this panel
    const [isNew] = useState(() => Boolean(window.assistantCreate))
    useEffect(() => {
        delete window.assistantCreate
    }, [])
    const { streaming, promptStreaming } = useInitialPromptStream(isNew && canEdit)

    return <div className="w-[50%] h-full bg-background-login shadow-sm p-4 overflow-y-auto scrollbar-hide">
        <div className="flex-between-center">
            <div className="flex items-center min-w-0">
                <span className="text-sm font-medium leading-none shrink-0">{t('build.assistantPortrait')}</span>
                {/* The panel is read-only while generating; a thinking model may stay silent for a minute */}
                {promptStreaming && <>
                    <LoadIcon className="ml-2 shrink-0 text-gray-600" />
                    <span className="ml-1 truncate text-xs text-muted-foreground">{t('build.portraitGenerating')}</span>
                </>}
            </div>
            <Dialog open={open && canEdit} onOpenChange={(next) => canEdit && setOpen(next)}>
                <DialogTrigger asChild>
                    <Button variant="link" className="p-0" disabled={!canEdit || streaming}><Settings2 className="mr-1 h-4 w-4" />{t('build.automaticOptimization')}</Button>
                </DialogTrigger>
                {open && <AutoPromptDialog onOpenChange={setOpen}></AutoPromptDialog>}
            </Dialog>
        </div>
        <Textarea
            boxClassName='h-[90%]'
            className="h-full border-none bg-transparent scrollbar-hide focus-visible:ring-0 resize-none text-sm text-muted-foreground"
            value={assistantState.prompt}
            placeholder={assistantRoleExample()}
            disabled={!canEdit || promptStreaming}
            onInput={(e => dispatchAssistant('setPrompt', { prompt: e.target.value }))}
        ></Textarea>
    </div>
};
