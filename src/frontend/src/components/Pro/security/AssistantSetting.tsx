import { SettingIcon } from "@/components/bs-icons";
import { AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { Switch } from "@/components/bs-ui/switch";
import { useEffect, useState } from "react";
import FormSet from "./FormSet";
import FormView from "./FormView";
import { getSensitiveApi, sensitiveSaveApi } from "@/controllers/API/pro";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useTranslation } from "react-i18next";

export default function AssistantSetting({ id, type }) {

    const { t } = useTranslation()

    const [open, setOpen] = useState(false);
    const { toast, message } = useToast()
    const [form, setForm] = useState({
        isCheck: false,
        autoReply: "您的输入带有敏感词汇，我拒绝回答",
        words: "",
        wordsType: [],
    })

    // load
    useEffect(() => {
        id !== 3 && getSensitiveApi(id, type).then(res => {
            console.log(res, 'xxx');

        })
    }, [id])

    const handleFormChange = async (_form) => {
        const errors = []
        if (_form.wordsType.length === 0) errors.push('词表至少需要选择一个')
        if (_form.autoReply === '') errors.push('自动回复内容不可为空')
        if (errors.length) {
            return toast({ title: t('prompt'), variant: 'error', description: errors })
        }

        setForm(_form)
        await sensitiveSaveApi({ ..._form, id, type })
        message({ title: t('prompt'), variant: 'success', description: '保存成功' })
    }

    const onOff = (bln) => {
        setForm({ ...form, isCheck: bln })
        sensitiveSaveApi({ ...form, isCheck: bln, id, type })
        if (bln) setOpen(true)
    }

    return <AccordionItem value="item-3">
        <AccordionTrigger>
            <div className="flex flex-1 items-center justify-between">
                <span>内容安全审查</span>
                <div className="h-[20px] flex items-center">
                    <Sheet open={open} onOpenChange={(bln) => setOpen(bln)}>
                        <SheetTrigger>
                            <SettingIcon onClick={(e) => { e.stopPropagation(); setOpen(!open) }} className="w-[32px] h-[32px]" />
                        </SheetTrigger>
                        <SheetContent className="w-[500px]" onClick={(e) => e.stopPropagation()}>
                            <SheetTitle className="font-[500] pl-3 pt-2">内容安全审查设置</SheetTitle>
                            <FormSet data={form} onChange={handleFormChange} onCancel={() => setOpen(false)} />
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
            <FormView data={form} />
            <div className="text-center text-xs text-muted-foreground mb-2">通过敏感词表或 API 对会话内容进行安全审查</div>
        </AccordionContent>
    </AccordionItem>
};