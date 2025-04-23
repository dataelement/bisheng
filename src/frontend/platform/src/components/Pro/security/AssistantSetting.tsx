import { SettingIcon } from "@/components/bs-icons";
import { AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { getSensitiveApi, sensitiveSaveApi } from "@/controllers/API/pro";
import { CircleHelp } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { useTranslation } from "react-i18next";
import FormSet from "./FormSet";
import FormView from "./FormView";

interface AssistantSettingProps {
    id: string | number;
    type: string;
}

export interface AssistantSettingRef {
    create: (id: number) => Promise<boolean>;
}

const AssistantSetting = forwardRef<AssistantSettingRef, AssistantSettingProps>(({ id, type }, ref) => {
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
        if (id && id !== 3) {
            getSensitiveApi(id, type).then(res => {
                const { is_check, auto_reply, words, words_type } = res;
                setForm({
                    isCheck: !!is_check,
                    autoReply: auto_reply,
                    words,
                    wordsType: Array.isArray(words_type) ? words_type : [words_type],
                });
            });
        }
    }, [id, type]);

    // 验证表单
    const validateForm = (formData: typeof form) => {
        if (!formData.isCheck) return true
        const errors = [];
        if (formData.wordsType.length === 0) {
            errors.push(t('build.errors.selectAtLeastOneWordType'));
        }
        if (formData.autoReply === '') {
            errors.push(t('build.errors.autoReplyNotEmpty'));
        }
        if (errors.length) {
            toast({ title: t('prompt'), variant: 'error', description: errors.join(', ') });
            return false
        }
        return true
    };

    // 暴露 save 方法给 ref
    useImperativeHandle(ref, () => ({
        create: async (saveId?: number) => {
            if (!form.isCheck) return true
            if (!validateForm(form)) return false
            const res = await sensitiveSaveApi({ ...form, id: saveId, type });
            return true;
        }
    }));

    const handleFormChange = async (_form) => {
        if (!validateForm(_form)) return true

        setForm(_form);
        if (id) {
            await sensitiveSaveApi({ ..._form, id, type });
            message({ title: t('prompt'), variant: 'success', description: t('build.saveSuccess') });
            return false
        }
    };

    const onOff = (bln) => {
        setForm({ ...form, isCheck: bln });
        id && sensitiveSaveApi({ ...form, isCheck: bln, id, type });
        if (bln) setOpen(true);
    };

    return (
        <AccordionItem value="item-3">
            <AccordionTrigger>
                <div className="flex flex-1 items-center justify-between">
                    <div className="flex items-center space-x-2">
                        <span>{t('build.contentSecurityR')}</span>
                        <TooltipProvider delayDuration={0}>
                            <Tooltip>
                                <TooltipTrigger>
                                    <CircleHelp className="w-4 h-4" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="text-slate-50">{t('build.contentSecurityDesc')}</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <div className="h-[20px] flex items-center">
                        <Sheet open={open} onOpenChange={(bln) => setOpen(bln)}>
                            <SheetTrigger>
                                {/* @ts-ignore */}
                                {form.isCheck && <SettingIcon onClick={(e) => { e.stopPropagation(); setOpen(!open) }} className="w-[32px] h-[32px]" />}
                            </SheetTrigger>
                            <SheetContent className="w-[500px]" onClick={(e) => e.stopPropagation()}>
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
            </AccordionTrigger>
            <AccordionContent className="mb-[-16px]">
                {form.isCheck && <FormView data={form} />}
            </AccordionContent>
        </AccordionItem>
    );
})


AssistantSetting.displayName = "AssistantSetting";

export default AssistantSetting;