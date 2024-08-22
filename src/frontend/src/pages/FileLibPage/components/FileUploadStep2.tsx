import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { t } from "i18next";
import { useRef, useState } from "react";

export default function FileUploadStep2(params) {
    // size
    const [size, setSize] = useState('1000')
    // 符号
    const [symbol, setSymbol] = useState('\\n\\n')
    const chunkType = useRef('smart')
    const [overlap, setOverlap] = useState('100')

    return <div className="flex flex-col">
        <div className="flex items-center gap-2 my-6 px-12">
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
                <div className="grid items-center gap-4 mt-8 max-w-[760px] mx-auto" style={{ gridTemplateColumns: '114px 1fr' }}>
                    <Label htmlFor="name" className="text-right flex items-center justify-end">切分方式 <QuestionTooltip content={'xx'} /></Label>
                    <Input id="name" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder={t('code.delimiterPlaceholder')} />
                    <Label htmlFor="name" className="text-right">{t('code.splitLength')}</Label>
                    <Input id="name" value={size} onChange={(e) => setSize(e.target.value)} placeholder={t('code.splitSizePlaceholder')} />
                    <Label htmlFor="name" className="text-right">{t('code.chunkOverlap')}</Label>
                    <Input id="name" value={overlap} onChange={(e) => setOverlap(e.target.value)} placeholder={t('code.chunkOverlap')} />
                </div>
            </TabsContent>
        </Tabs>
    </div>
};
