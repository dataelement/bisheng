import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { UploadIcon } from "@radix-ui/react-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export default function ContentSecuritySheet({isOpen, data, onCloseSheet, onSave, children}) {
    const { t } = useTranslation()
    const { toast, message } = useToast()

    const [content, setContent] = useState({
        reviewType: '',
        vocabularyType: [],
        vocabularyInput: '',
        automaticReply: ''
    })
    useEffect(() => { data && setContent(data) },[data])

    const handleCheckboxChange = (val, name) => {
        let temp = content.vocabularyType
        val ? setContent({
            ...content, vocabularyType:[...temp, name]
        }) : setContent({
            ...content, vocabularyType:temp.filter(v => v !== name)
        })
    }
    const uploadFile = (e) => {
        const file = e.target.files[0]
        if(file) {
            const reader = new FileReader()
            reader.onload = (evt) => {
                const text = evt.target.result
                //@ts-ignore
                const formatContent = text.replace(/[\s,，\r\n]+/g, '\n') // 将所有符号替换成换行符
                const temp = content.vocabularyInput
                setContent({...content, vocabularyInput:temp + formatContent})
            }
            reader.readAsText(file)
        }
    }
    const confirmSave = () => {
        if(content.reviewType === '') {
            toast({title:t('prompt'), variant:'error',description:'审查类型至少选择一个'})
            return
        }
        if(content.reviewType === '敏感词表匹配') {
            if(content.vocabularyType.length === 0) {
                toast({title: t('prompt'), variant: 'error', description: '词表至少需要选择一个'})
                return
            }
            if(content.automaticReply === '') {
                toast({title: t('prompt'), variant: 'error', description: '自动回复内容不可为空'})
                return 
            }
        }
        onSave(content)
        message({title: t('prompt'), variant: 'success', description: '保存成功'})
        onCloseSheet()
    }
    
    return <>
    <Sheet open={isOpen} onOpenChange={() => onCloseSheet(false)}>
        <SheetTrigger>
            {children}
        </SheetTrigger>
        <SheetContent className="w-[500px]" onClick={(e) => e.stopPropagation()}>
            <SheetTitle className="font-[500] pl-3 pt-2">内容安全审查设置</SheetTitle>
            <div className="pl-3 mt-6">
                <span>审查类型</span>
                <RadioGroup value={content.reviewType} onValueChange={(v) => setContent({...content,reviewType:v})}
                className="flex space-x-2 h-[20px] mt-4 mb-6">
                    <div>
                        <Label className="flex justify-center">
                            <RadioGroupItem className="mr-2" value="敏感词表匹配"/>敏感词表匹配
                        </Label>
                    </div>
                    <div>
                        <Label className="flex justify-center">
                            <RadioGroupItem disabled className="mr-2" value="模型审查"/>模型审查
                        </Label>
                    </div>
                </RadioGroup>
                <div className="mb-6"> {/* 后期更新 */}
                    <span>词表类型</span>
                    <div className="mt-4 mb-6 space-y-3">
                        <div className="space-x-2 flex items-center">
                            <Checkbox id="c1" value="内置词表" checked={content.vocabularyType?.includes('内置词表')}
                            onCheckedChange={(val) => handleCheckboxChange(val,'内置词表')}/><Label htmlFor="c1">内置词表</Label>
                        </div>
                        <div className="space-x-2 flex items-center">
                            <Checkbox id="c2" value="自定义词表" checked={content.vocabularyType?.includes('自定义词表')}
                            onCheckedChange={(val) => handleCheckboxChange(val,'自定义词表')}/><Label htmlFor="c2">自定义词表</Label>
                        </div>
                    </div>
                    <div className="flex justify-center">
                        <Textarea className="w-[90%] h-[100px] bg-[whitesmoke]" value={content.vocabularyInput} 
                        onChange={(e) => setContent({ ...content, vocabularyInput:e.target.value })}
                        placeholder="使用换行符进行分隔，每行一个"></Textarea>
                        <input type="file" accept=".txt" id="fileUpload" className="hidden" onChange={uploadFile}/>
                        <div className="flex items-center absolute right-6" onClick={() => document.querySelector('#fileUpload').click()}>
                            <UploadIcon id="ul" className="text-blue-600"/>
                            <Label htmlFor="ul"><span className="text-xs text-blue-600">txt文件</span></Label>
                        </div>
                    </div>
                </div>
                <span className="mb-4">自动回复内容</span>
                <div className="flex justify-center mt-4">
                    <Textarea className="w-[90%] h-[100px] bg-[whitesmoke]" value={content.automaticReply}
                    onChange={(e) => setContent({ ...content, automaticReply:e.target.value })}
                    maxLength={500}
                    placeholder="填写命中安全审查时的自动回复内容，例如“当前对话内容违反相关规范，请修改后重新输入"></Textarea>
                </div>
            </div>
            <div className="absolute bottom-10 right-4 sapce-x-10 flex space-x-8">
                <Button onClick={onCloseSheet} variant="outline">{t('cancel')}</Button>
                <Button onClick={confirmSave}>{t('save')}</Button>
            </div>
        </SheetContent>
    </Sheet>
    </>
}