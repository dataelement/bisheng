import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { TabsContent } from "@/components/bs-ui/tabs";
import { Button } from "@/components/bs-ui/button";
import { useEffect, useRef, useState } from "react";


export default function SplitRules({
    strategies,
    setStrategies,
    handlePreview,
    onChange,
    t
}) {
    
const [dataArray, setDataArray] = useState([
    { id: 1, name: 'Excel文件1.xlsx' },
    { id: 2, name: '报表数据2.xlsx' },
    { id: 3, name: '财务记录3.xlsx' },
    { id: 4, name: '项目计划4.xlsx' }
  ]);
    const [checked, setChecked] = useState(false)
    // size
    const [size, setSize] = useState('15')
    // 符号
    const [overlap, setOverlap] = useState('1')
    useEffect(() => {
        onChange()
    }, [strategies, size, overlap])
    return (
        <TabsContent value="chunk">
            <div
                className="flex flex-col gap-4 max-w-[760px] mx-auto"
                style={{ gridTemplateColumns: '114px 1fr' }}
            >
                <div className="flex justify-end items-center gap-2">
                    <input
                        type="checkbox"
                        id="keepImages"
                        className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                        onChange={(e) => setChecked(e.target.checked)}
                    />
                    <Label htmlFor="keepImages" className="text-sm text-gray-700">
                        {t('keepImages')}
                    </Label>
                </div>




                {checked ? (<div>
                    <div className={`relative ${checked ? 'after:absolute after:inset-0 after:bg-gray-100/50 after:z-10 after:pointer-events-none' : ''}`}>
                    <div className="flex items-center justify-between p-4 border rounded-lg">
                        <h3 className={`text-lg font-bold shrink-0 ${checked ? 'text-gray-500' : 'text-gray-800'}`}>
                            {t('splitSettings')}
                        </h3>

                        <div className="flex items-center gap-1 mx-auto">
                            <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>每</span>
                            <div className="relative">
                                <Input
                                    id="splitLength"
                                    type="number"
                                    value={size}
                                    disabled={checked}
                                    className={`w-20 ${checked ? 'bg-gray-200' : ''}`}
                                />
                                <span className={`absolute right-2 top-1/2 -translate-y-1/2 ${checked ? 'text-gray-400' : 'text-gray-500'}`}>行</span>
                            </div>
                            <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>作为一个分段</span>
                        </div>

                        <div className="flex items-center gap-1 shrink-0">
                            <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>第</span>
                            <Input
                                type="number"
                                value={overlap}
                                disabled={checked}
                                className={`w-20 ${checked ? 'bg-gray-200' : ''}`}
                            />
                            <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>到</span>
                            <Input
                                type="number"
                                value={overlap}
                                disabled={checked}
                                className={`w-20 ${checked ? 'bg-gray-200' : ''}`}
                            />
                            <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>作为表头</span>
                        </div>
                    </div>
                </div>

<div className="space-y-4 mt-4 p-4 border rounded-lg bg-white shadow-sm">
  <h3 className="text-lg font-bold text-gray-800 text-left">
    {t('splitSettings')}
  </h3>
  
  <div className="relative mt-2">
    <select
      className="w-full p-2 pr-8 border border-gray-300 rounded-md shadow-sm
                focus:ring-blue-500 focus:border-blue-500
                hover:border-gray-400 transition-colors
                appearance-none bg-white bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiAjdjJ2NHY2IiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBvbHlsaW5lIHBvaW50cz0iNiA5IDEyIDE1IDE4IDkiPjwvcG9seWxpbmU+PC9zdmc+')]
                bg-no-repeat bg-[position:right_0.5rem_center] bg-[length:1.5em_1.5em]"
      size={Math.min(5, dataArray.length)}
      multiple
      onChange={(e) => console.log(Array.from(e.target.selectedOptions))}
    >
      {dataArray.map((item) => (
        <option 
          key={item.id}
          value={item.id}
          className="px-3 py-2 hover:bg-blue-50 focus:bg-white"
        >
          {item.name}
        </option>
      ))}
    </select>
  </div>
</div>
                </div>

            ) : (<div className="space-y-4 p-4 border rounded-lg">
                    <h3 className="text-lg font-bold text-gray-800 text-left">
                        {t('splitSettings')}
                    </h3>

                    <div className="flex flex-col gap-4">
                        {/* 第一行：第一个输入框独立显示 */}
                        <div className="flex items-center gap-3">
                            <Label htmlFor="splitLength" className="whitespace-nowrap text-sm min-w-[100px]">
                                {t('splitLength')}
                            </Label>
                            <div className="flex items-center gap-2 overflow-hidden">
                                <span className="shrink-0">每</span>
                                <div className="relative">
                                    <Input
                                        id="splitLength"
                                        type="number"
                                        value={size}
                                        onChange={(e) => setSize(Number(e.target.value))}
                                        placeholder={t('splitSizePlaceholder')}
                                        className="w-24 shrink-0"
                                    />
                                    <span className="absolute top-1/2 transform -translate-y-1/2 text-gray-500">
                                        行
                                    </span>
                                </div>
                                <span className="shrink-0">作为一个分段</span>
                            </div>
                        </div>

                        {/* 第二行：第二个输入框与勾选框组合 */}
                        <div className="flex items-center gap-4">
                            <div className="flex items-center gap-2">
                                <input
                                    type="checkbox"
                                    id="keepImages"
                                    className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                                />
                                <Label htmlFor="keepImages" className="text-sm text-gray-700">
                                    {t('keepImages')}
                                </Label>
                            </div>
                            <div className="flex items-center gap-3">
                                <span className="shrink-0">第</span>
                                <div className="relative">     <Input
                                    id="chunkOverlap"
                                    type="number"
                                    value={overlap}
                                    onChange={(e) => setOverlap(Number(e.target.value))}
                                    placeholder={t('chunkOverlapPlaceholder')}
                                    className="w-24 shrink-0"
                                />
                                    <span className="absolute top-1/2 transform -translate-y-1/2 text-gray-500">
                                        行
                                    </span>
                                </div>
                                <span className="shrink-0">到</span>
                                <Input
                                    id="chunkOverlap"
                                    type="number"
                                    value={overlap}
                                    onChange={(e) => setOverlap(Number(e.target.value))}
                                    placeholder={t('chunkOverlapPlaceholder')}
                                    className="w-24 shrink-0"
                                />
                                <span className="shrink-0">作为表头</span>
                            </div>
                        </div>
                    </div>
                </div>)}


                <div className="flex justify-between items-end ">
                    <Button className="h-8" id={'preview-btn'} onClick={handlePreview}>
                        {t('previewResults')}
                    </Button>
                </div>
            </div>

        </TabsContent>
    )
}
