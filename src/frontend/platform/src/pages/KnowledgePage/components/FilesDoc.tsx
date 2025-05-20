import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { TabsContent } from "@/components/bs-ui/tabs";
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";



export default function FilesDoc({
    strategies,
    setStrategies,
    handlePreview,
    settings,
    onSettingChange,
    t
}) {
    return (
        <TabsContent value="smart">
            <div
                className="flex flex-col gap-4 mt-8 max-w-[760px] mx-auto"
                style={{ gridTemplateColumns: '114px 1fr' }}
            >
                <div className="space-y-4 p-4 border rounded-lg">
                    {/* 顶部标题 - 作为整个容器的标题 */}
                    <h3 className="text-lg font-bold text-gray-800 text-left ">
                        {t('splitSettings')}
                    </h3>

                    {/* 输入框组 - 水平排列 */}
                    <div className="flex gap-4">
                        {/* 第一个输入项 */}
                        <div className="w-1/2 flex items-center gap-3">
                            <Label htmlFor="splitLength" className="whitespace-nowrap text-sm min-w-[100px]">
                                {t('splitLength')}
                            </Label>
                            <Input
                                id="splitLength"
                                type="number"
                                value={settings.size}
                                onChange={(e) => onSettingChange('size', e.target.value)}
                                placeholder={t('splitSizePlaceholder')}
                                className="flex-1 min-w-[150px]"
                            />
                        </div>

                        {/* 第二个输入项 */}
                        <div className="w-1/2 flex items-center gap-3">
                            <Label htmlFor="chunkOverlap" className="whitespace-nowrap text-sm min-w-[100px]">
                                {t('chunkOverlap')}
                            </Label>
                            <Input
                                id="chunkOverlap"
                                type="number"
                                value={settings.overlap}
                                onChange={(e) => onSettingChange('overlap', e.target.value)}
                                placeholder={t('chunkOverlapPlaceholder')}
                                className="flex-1 min-w-[150px]"
                            />
                        </div>
                    </div>
                    {/* 新增的勾选框字段 - 左下方 */}
                    <div className="flex items-center gap-2 pt-2">
                        <Checkbox
                            id="retain"
                            checked={settings.retain}
                            onCheckedChange={(checked) => onSettingChange('retain', checked)}
                            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        <Label htmlFor="keepImages" className="text-sm text-gray-700">
                            {t('keepImages')} {/* 请确保你的翻译函数中有这个键 */}
                        </Label>
                    </div>

                </div>
                <div className=" p-4 border rounded-lg">
                    <Label htmlFor="splitMethod" className="flex justify-start text-lg text-left font-bold text-gray-800 text-left">
                        {t('splitMethod')}
                        {/* <QuestionTooltip content={t('splitMethodHint')} /> */}
                    </Label>
                    <FileUploadSplitStrategy data={strategies} onChange={setStrategies} />
                </div>
                <div className="space-y-4 p-4 border rounded-lg">
                    {/* 顶部标题 - 作为整个容器的标题 */}
                    <h3 className="text-lg font-bold text-gray-800 text-left ">
                        {t('pdfAnalysis')}
                    </h3>
                    {/* 新增的勾选框字段 - 左下方 */}
                    <div className="flex items-center gap-2 pt-2">
                        <Checkbox
                            id="forocr"
                            checked={settings.forocr}
                            onCheckedChange={(checked) => onSettingChange('forocr', checked)}
                            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        <Label htmlFor="ocrForce" className="text-sm text-gray-700">
                            {t('ocrForce')}
                        </Label>
                        <Checkbox
                            id="formula"
                            checked={settings.formula}
                            onCheckedChange={(checked) => onSettingChange('formula', checked)}
                            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        <Label htmlFor="enableRec" className="text-sm text-gray-700">
                            {t('enableRec')}
                        </Label>
                        <Checkbox
                            id="filhf"
                            checked={settings.filhf}
                            onCheckedChange={(checked) => onSettingChange('filhf', checked)}
                            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        <Label htmlFor="hfFilter" className="text-sm text-gray-700">
                            {t('hfFilter')}
                        </Label>
                    </div>

                </div>
                <div className="flex justify-between items-end ">
                    <Button className="h-8" id={'preview-btn'} onClick={handlePreview}>
                        {t('previewResults')}
                    </Button>
                </div>
            </div>

        </TabsContent>
    )
}
