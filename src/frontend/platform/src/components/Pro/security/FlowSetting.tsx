import { SettingIcon } from "@/components/bs-icons";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { getSensitiveApi, sensitiveSaveApi } from "@/controllers/API/pro";
import { CircleHelp } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import FormSet from "./FormSet";
import FormView from "./FormView";

export default function FlowSetting({ id, type, isOnline, onSubTask }) {
    const { t } = useTranslation();

    const [open, setOpen] = useState(false);
    const { toast, message } = useToast();
    const [form, setForm] = useState({
        isCheck: false,
        autoReply: "",
        words: "",
        wordsType: [],
    });

    // load
    useEffect(() => {
        id !== 3 && getSensitiveApi(id, type).then(res => {
            const { is_check, auto_reply, words, words_type } = res
            setForm({
                isCheck: !!is_check,
                autoReply: auto_reply,
                words,
                wordsType: Array.isArray(words_type) ? words_type : [words_type],
            })
        })
    }, [id])

    const handleFormChange = async (_form) => {
        const errors = [];
        if (_form.wordsType.length === 0) errors.push(t('build.errors.selectAtLeastOneWordType'));
        if (_form.autoReply === '') errors.push(t('build.errors.autoReplyNotEmpty'));
        if (errors.length) {
            return toast({ title: t('prompt'), variant: 'error', description: errors.join(', ') });
        }

        setForm(_form);
        if (isOnline) return; // 在线状态不允许修改
        const callBack = async (id) => {
            await sensitiveSaveApi({ ..._form, id, type });
            message({ title: t('prompt'), variant: 'success', description: t('build.saveSuccess') });
        }
        id ? callBack(id) : onSubTask?.(callBack);
    };

    const onOff = (bln) => {
        setForm({ ...form, isCheck: bln });
        if (bln) setOpen(true);
        if (isOnline) return; // 在线状态不允许修改
        const callBack = async (id) => {
            sensitiveSaveApi({ ...form, isCheck: bln, id, type });
        }
        id ? callBack(id) : onSubTask?.(callBack);
    };

    return (
        <div>
            <div className="mt-6 flex items-center h-[30px] mb-4 px-6">
                {/* <span className="text-sm font-medium leading-none">开启内容安全审查</span> */}
                <div className="flex items-center space-x-2">
                    <span>{t('build.enableContentSecurityReview')}</span>
                    <TooltipProvider delayDuration={0}>
                        <Tooltip>
                            <TooltipTrigger>
                                <CircleHelp className="w-4 h-4" />
                            </TooltipTrigger>
                            <TooltipContent>
                                <p className="text-[white]">{t('build.contentSecurityDesc')}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
                <div className="flex items-center ml-6">
                    <Sheet open={open} onOpenChange={(bln) => setOpen(bln)}>
                        <SheetTrigger>
                            {form.isCheck && <SettingIcon onClick={(e) => { e.stopPropagation(); setOpen(!open) }} className="w-[32px] h-[32px]" />}
                        </SheetTrigger>
                        <SheetContent className="w-[500px] bg-background-login" onClick={(e) => e.stopPropagation()}>
                            <SheetTitle className="font-[500] pl-3 pt-2">{t('build.contentSecuritySettings')}</SheetTitle>
                            <FormSet data={form} onChange={handleFormChange} onSave={() => setOpen(false)} onCancel={() => setOpen(false)} />
                        </SheetContent>
                    </Sheet>
                    <Switch
                        className="mx-4"
                        onClick={(e) => e.stopPropagation()}
                        checked={form.isCheck}
                        onCheckedChange={onOff}
                    />
                </div>
            </div>
            <div className="text-sm">
                {form.isCheck && <FormView data={form} />}
            </div>
        </div>
    );
}
