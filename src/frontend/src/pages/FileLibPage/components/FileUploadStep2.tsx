import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { t } from "i18next";
import { useEffect, useRef, useState } from "react";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useNavigate } from "react-router-dom";

const initialStrategies = [
    { id: '2', regex: '\\n\\n', position: 'before' },
    { id: '6', regex: '\\.', position: 'after' }
];

export default function FileUploadStep2({ onPrev, onPreview, onChange }) {
    const chunkType = useRef('smart')
    // 切分
    const [strategies, setStrategies] = useState(initialStrategies);
    // size
    const [size, setSize] = useState('1000')
    // 符号
    const [overlap, setOverlap] = useState('100')
    useEffect(() => {
        onChange()
    }, [strategies, size, overlap])

    const { message } = useToast()
    const navaigate = useNavigate()
    const handleSubmit = () => {
        console.log('data :>> ', strategies, size, overlap);
        message({ variant: 'success', description: '添加成功' })
        navaigate(-1)
    }

    return <div className="flex flex-col">
        <div className="flex items-center gap-2 my-6 px-12 text-sm font-bold max-w-96">
            <span>①上传文件</span>
            <div className="h-[1px] flex-grow bg-gray-300"></div>
            <span className="text-primary">②文档处理策略</span>
        </div>
        <Tabs defaultValue="smart" className="w-full mt-4 text-center" onValueChange={(val) => chunkType.current = val}>
            <TabsList className="a mx-auto">
                <TabsTrigger value="smart" className="roundedrounded-xl">默认策略</TabsTrigger>
                <TabsTrigger value="chunk">自定义策略</TabsTrigger>
            </TabsList>
            <TabsContent value="smart">
            </TabsContent>
            <TabsContent value="chunk">
                <div className="grid items-start gap-4 mt-8 max-w-[760px] mx-auto" style={{ gridTemplateColumns: '114px 1fr' }}>
                    <Label htmlFor="name" className="mt-2.5 flex justify-end text-left">切分方式 <QuestionTooltip content={'可选择筛选项中的切分规则，或通过正则表达式自定义切分规则，例如在"第.{1,3}条" 前进行切分时，会在“第1条”、“第ab条”“第三条”等文本之前进行切分'} /></Label>
                    <FileUploadSplitStrategy data={strategies} onChange={setStrategies} />
                    <Label htmlFor="name" className="mt-2.5 text-right">{t('code.splitLength')}</Label>
                    <Input id="name" value={size} onChange={(e) => setSize(e.target.value)} placeholder={t('code.splitSizePlaceholder')} />
                    <Label htmlFor="name" className="mt-2.5 text-right">{t('code.chunkOverlap')}</Label>
                    <Input id="name" value={overlap} onChange={(e) => setOverlap(e.target.value)} placeholder={t('code.chunkOverlap')} />
                </div>
            </TabsContent>
        </Tabs>
        <div className="flex justify-end mt-8 gap-4">
            <Button className="h-8" variant="outline" onClick={onPrev}>上一步</Button>
            <Button className="h-8" onClick={handleSubmit}>提交</Button>
            <Button className="h-8" onClick={() => onPreview()}>预览分段结果</Button>
        </div>
    </div>
};
