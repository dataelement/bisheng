import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { TabsContent } from "@/components/bs-ui/tabs";
import { Button } from "@/components/bs-ui/button";
import { useEffect, useRef, useState } from "react";
import { Checkbox } from "@/components/bs-ui/checkBox";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/bs-ui/accordion";



export default function TabularDoc({
  handlePreview,
  settings,
  onSettingChange,
  dataArray,
  fileConfigs,
  setFileConfigs,
  updateConfig,
  t
}) {


  const [checked, setChecked] = useState(false)
  const [selectedDropdown, setSelectedDropdown] = useState(0)
  return (
    <TabsContent value="chunk">
      <div
        className="flex flex-col gap-4"
        style={{ gridTemplateColumns: '114px 1fr' }}
      >
        <div className="flex justify-end items-center gap-2">
          <Checkbox
            id="setSeparately"
            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            onCheckedChange={setChecked}
          />
          <Label htmlFor="setSeparately" className="text-sm text-gray-700">
            {t('setSeparately')}
          </Label>
        </div>




        {checked ? (
          <div>
            <div className={`relative ${checked ? 'after:absolute after:inset-0 after:bg-gray-100/50 after:z-10 after:pointer-events-none' : ''}`}>
              <div className="flex items-center justify-between p-4 border rounded-lg">
                <h3 className={`text-lg font-bold shrink-0 ${checked ? 'text-gray-500' : 'text-gray-800'}`}>
                  {t('splitSettings')}
                </h3>

                <div className="flex items-center gap-1 mx-auto">
                  <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>{t('every')}</span>
                  <div className="relative">
                    <Input
                      id="split"
                      type="number"
                      value={settings.burst}
                      disabled={checked}
                      className={`w-20 ${checked ? 'bg-gray-200' : ''}`}
                    />
                    <span className={`absolute right-2  top-1/2 -translate-y-1/2 ${checked ? 'text-gray-400' : 'text-gray-500'}`}>{t('row')}</span>
                  </div>
                  <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>{t('segemnt')}</span>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>{t('bonly')}</span>
                  <Input
                    type="number"
                    value={settings.gauge}
                    disabled={checked}
                    className={`w-20 ${checked ? 'bg-gray-200' : ''}`}
                  />
                  <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>{t('arrive')}</span>
                  <Input
                    type="number"
                    value={settings.rowend}
                    disabled={checked}
                    className={`w-20 ${checked ? 'bg-gray-200' : ''}`}
                  />
                  <span className={`whitespace-nowrap ${checked ? 'text-gray-500' : ''}`}>{t('gauge')}</span>
                </div>
              </div>
            </div>

            <div className="space-y-4 mt-4 p-4 border rounded-lg bg-white shadow-sm">
              <h3 className="text-lg font-bold text-gray-800 text-left">
                {t('splitMethod')}
              </h3>

              <div className="relative mt-2">
                {dataArray.map((item) => (
                  <Accordion
                    key={item.idi}
                    type="single"
                    collapsible
                    className="w-full mb-4"
                    value={selectedDropdown === item.idi ? item.idi : undefined}
                    onValueChange={(value) => setSelectedDropdown(value === item.idi ? item.idi : null)}
                  >
                    <AccordionItem value={item.idi}>
                      {/* 下拉触发按钮 */}
                      <AccordionTrigger className="w-full mt-2 p-2 pr-8 border border-gray-300 rounded-md shadow-sm text-left hover:bg-gray-50">
                        <span className="px-3 py-2">{item.name}</span>
                      </AccordionTrigger>

                      <AccordionContent className="flex flex-col gap-4 p-4 border rounded-md bg-gray-50">
                        {/* 第一行：第一个输入框独立显示 */}
                        <div className="flex items-center gap-3">
                          <label htmlFor={`split-${item.idi}`} className="whitespace-nowrap text-left text-sm min-w-[124px]">
                            {t('split')}
                          </label>
                          <div className="flex items-center gap-2 overflow-hidden">
                            <span className="shrink-0"> {t('every')}</span>
                            <div className="relative">
                              <input
                                id={`split-${item.idi}`}
                                type="number"
                                value={fileConfigs[item.idi]?.burst}
                                onChange={(e) => updateConfig(item.idi, 'burst', e.target.value)}
                                placeholder="输入分段大小"
                                className="w-24 shrink-0"
                              />
                              <span className="absolute right-4 top-1/2 transform -translate-y-1/2 text-gray-500">
                                {t('row')}
                              </span>
                            </div>
                            <span className="shrink-0"> {t('segemnt')}</span>
                          </div>
                        </div>

                        {/* 第二行：第二个输入框与勾选框组合 */}
                        <div className="flex items-center gap-4">
                          <div className="flex items-center gap-2">
                            <Checkbox
                              id={`addHeader-${item.idi}`}
                              checked={fileConfigs[item.idi]?.appendh}
                              onCheckedChange={(checked) => updateConfig(item.idi, 'appendh', checked)}
                              className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                            />
                            <label htmlFor={`addHeader-${item.idi}`} className="text-sm text-gray-700">
                              {t("addHeader")}
                            </label>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="shrink-0">{t('bonly')}</span>
                            <div className="relative">
                              <input
                                id={`chunkOverlapStart-${item.idi}`}
                                type="number"
                                value={fileConfigs[item.idi]?.gauge}
                                onChange={(e) => updateConfig(item.idi, 'gauge', e.target.value)}
                                placeholder="起始行"
                                className="w-24 shrink-0"
                              />
                              <span className="absolute top-1/2 right-4 transform -translate-y-1/2 text-gray-500">
                                {t('row')}
                              </span>
                            </div>
                            <span className="shrink-0">{t('arrive')}</span>
                            <div className="relative">
                              <input
                                id={`chunkOverlapEnd-${item.idi}`}
                                type="number"
                                value={fileConfigs[item.idi]?.rowend}
                                onChange={(e) => updateConfig(item.idi, 'rowend', e.target.value)}
                                placeholder="结束行"
                                className="w-24 shrink-0"
                              />
                              <span className="absolute left-16 top-1/2 transform -translate-y-1/2 text-gray-500">
                                {t('row')}
                              </span>
                              <span className="shrink-0">{t('gauge')}</span>
                            </div>
                          </div>
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  </Accordion>
                ))}
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
              <Label htmlFor="split" className="whitespace-nowrap text-sm min-w-[100px]">
                {t('split')}
              </Label>
              <div className="flex items-center gap-2 overflow-hidden">
                <span className="shrink-0">{t('every')}</span>
                <div className="relative">
                  <Input
                    id="split"
                    type="number"
                    value={settings.burst}
                    onChange={(e) => onSettingChange('burst', e.target.value)}
                    placeholder={t('splitSizePlaceholder')}
                    className="w-24 shrink-0"
                  />
                  <span className="absolute right-4 top-1/2 transform -translate-y-1/2 text-gray-500">
                    {t('row')}
                  </span>
                </div>
                <span className="shrink-0">{t('segemnt')}</span>
              </div>
            </div>

            {/* 第二行：第二个输入框与勾选框组合 */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="appendh"
                  checked={settings.appendh}
                  onCheckedChange={(checked) => onSettingChange('appendh', checked)}
                  className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <Label htmlFor="addHeader" className="text-sm text-gray-700">
                  {t('addHeader')}
                </Label>
              </div>
              <div className="flex items-center gap-3">
                <span className="shrink-0">{t('bonly')}</span>
                <div className="relative">     <Input
                  id="chunkOverlap"
                  type="number"
                  value={settings.gauge}
                  onChange={(e) => onSettingChange('gauge', e.target.value)}
                  placeholder={t('chunkOverlapPlaceholder')}
                  className="w-24 shrink-0"
                />
                  <span className="absolute top-1/2 right-4 transform -translate-y-1/2 text-gray-500">
                    {t('row')}
                  </span>
                </div>
                <span className="shrink-0">{t('arrive')}</span>
                <div className="relative">
                  <Input
                    id="chunkOverlap"
                    type="number"
                    value={settings.rowend}
                    onChange={(e) => onSettingChange('rowend', e.target.value)}
                    placeholder={t('chunkOverlapPlaceholder')}
                    className="w-24 shrink-0"
                  />
                  <span className="absolute top-1/2 right-4 transform -translate-y-1/2 text-gray-500">
                    {t('row')}
                  </span>
                </div>

                <span className="shrink-0">{t('gauge')}</span>
              </div>
            </div>
          </div>
        </div>)}


        {/* <div className="flex justify-between items-end ">
          <Button className="h-8" id={'preview-btn'} onClick={handlePreview}>
            {t('previewResults')}
          </Button>
        </div> */}
      </div>

    </TabsContent>
  )
}
