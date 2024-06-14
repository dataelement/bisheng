
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { uploadFile } from "@/controllers/API";
import { UploadIcon } from "@radix-ui/react-icons";
import { t } from "i18next";
import { useEffect, useState } from "react";

export default function FormSet({ data, onChange, onSave, onCancel }) {

    const [form, setForm] = useState<any>({})
    useEffect(() => {
        setForm(data)
    }, [data])

    const handleCheckboxChange = (val, name) => {
        let temp = form.wordsType
        val ? setForm({
            ...form, wordsType: [...temp, name]
        }) : setForm({
            ...form, wordsType: temp.filter(v => v !== name)
        })
    }

    const handleUploadFile = (e) => {
        const file = e.target.files[0]
        if (file) {
            const reader = new FileReader()
            reader.onload = (evt) => {
                const text = evt.target.result
                //@ts-ignore
                const formatContent = text.replace(/[\s,，\r\n]+/g, '\n') // 将所有符号替换成换行符
                setForm({ ...form, words: formatContent })
            }
            reader.readAsText(file)
        }
    }
    const handleSave = () => {
        onSave()
        onChange(form)
    }
    return <>
        <div className="px-4 mt-6">
            <span className="bisheng-label">审查类型</span>
            <RadioGroup value="1"
                className="flex space-x-2 h-[20px] mt-4 mb-6">
                <div>
                    <Label className="flex justify-center">
                        <RadioGroupItem className="mr-2" value="1" />敏感词表匹配
                    </Label>
                </div>
                <div>
                    <Label className="flex justify-center">
                        <RadioGroupItem disabled className="mr-2" value="模型审查" />模型审查
                    </Label>
                </div>
            </RadioGroup>
            <div className="mb-6"> {/* 后期更新 */}
                <span className="bisheng-label">词表类型</span>
                <div className="mt-4 mb-6 space-y-3">
                    <div className="space-x-2 flex items-center">
                        <Checkbox
                            id="c1"
                            value="1"
                            checked={form.wordsType?.includes('1')}
                            onCheckedChange={(val) => handleCheckboxChange(val, '1')}
                        />
                        <Label htmlFor="c1" className="cursor-pointer">内置词表</Label>
                    </div>
                    <div className="space-x-2 flex items-center">
                        <Checkbox
                            id="c2"
                            value="2"
                            checked={form.wordsType?.includes('2')}
                            onCheckedChange={(val) => handleCheckboxChange(val, '2')}
                        />
                        <Label htmlFor="c2" className="cursor-pointer">自定义词表</Label>
                    </div>
                </div>
                <div className="flex justify-center relative">
                    <Textarea className="h-[100px]" value={form.words}
                        onChange={(e) => setForm({ ...form, words: e.target.value })}
                        placeholder="使用换行符进行分隔，每行一个"></Textarea>
                    <input type="file" accept=".txt" id="fileUpload" className="hidden" onChange={handleUploadFile} />
                    <div className="flex items-center absolute right-1 top-1 cursor-pointer" onClick={() => document.querySelector('#fileUpload').click()}>
                        <UploadIcon id="ul" color="blue" className="w-3 h-3" />
                        <Label htmlFor="ul"><span className="text-xs text-primary cursor-pointer">txt文件</span></Label>
                    </div>
                </div>
            </div>
            <span className="bisheng-label">自动回复内容</span>
            <div className="flex justify-center mt-4">
                <Textarea className="h-[100px]" value={form.autoReply}
                    onChange={(e) => setForm({ ...form, autoReply: e.target.value })}
                    maxLength={500}
                    placeholder="填写命中安全审查时的自动回复内容，例如“当前对话内容违反相关规范，请修改后重新输入"></Textarea>
            </div>
        </div>
        <div className="absolute bottom-10 right-4 sapce-x-10 flex space-x-8">
            <Button onClick={onCancel} variant="outline">{t('cancel')}</Button>
            <Button onClick={handleSave}>{t('save')}</Button>
        </div>
    </>
};
