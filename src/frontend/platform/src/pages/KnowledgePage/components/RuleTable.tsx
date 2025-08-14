import { FileIcon } from "@/components/bs-icons/file";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/bs-ui/accordion";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { cn } from "@/util/utils";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";


const ItemForm = ({ data, setData }) => {
  const { t } = useTranslation('knowledge')

  return <div className="space-y-4 text-sm">
    {/* 第一行：第一个输入框独立显示 */}
    <div className="flex items-center gap-3">
      <Label className="min-w-[124px] text-left text-sm whitespace-nowrap">
        {t('split')}
      </Label>
      <div className="flex items-center gap-2">
        <span>{t('every')}</span>
        <div className="relative">
          <Input
            type="number"
            min={1}
            // max={1000}
            maxLength={6}
            value={data.slice_length}
            onChange={e => setData('slice_length', e.target.value)}
            className="w-28 h-8"
            onBlur={(e) => {
              !e.target.value && setData('slice_length', 10);
            }}
          />
          <span className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400">{t('row')}</span>
        </div>
        <span>{t('segemnt')}</span>
      </div>
    </div>

    {/* 第二行：第二个输入框与勾选框组合 */}
    <div className="flex items-center gap-4">
      <div className="flex items-center gap-2">
        <Checkbox
          checked={data.append_header}
          onCheckedChange={(checked) => setData('append_header', checked)}
        />
        <Label className="text-sm"> {t("addHeader")} </Label>
      </div>
      <div className={cn("flex items-center gap-3", !data.append_header && "opacity-0")}>
        <span>{t('bonly')}</span>
        <div className="relative">
          <Input
            type="number"
            min={1}
            max={1000}
            maxLength={4}
            value={data.header_start_row}
            onChange={e => setData('header_start_row', e.target.value)}
            onBlur={(e) => {
              !e.target.value && setData('header_start_row', 1);
            }}
            className="w-28 h-8"
          />
          <span className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400">{t('row')}</span>
        </div>
        <span>{t('arrive')}</span>
        <div className="relative">
          <Input
            type="number"
            min={1}
            max={1000}
            maxLength={4}
            value={data.header_end_row}
            onChange={e => setData('header_end_row', e.target.value)}
            onBlur={(e) => {
              !e.target.value && setData('header_end_row', 1);
            }}
            className="w-28 h-8"
          />
          <span className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400">{t('row')}</span>
        </div>
        <span>{t('gauge')}</span>
      </div>
    </div>
  </div>
}



export default function RuleTable({
  rules,
  setRules,
  applyEachCell,
  setApplyEachCell,
  cellGeneralConfig,
  setCellGeneralConfig
}) {
  const { t } = useTranslation('knowledge')

  console.log('rules.fileList :>> ', rules.fileList);
  const tableFils = useMemo(() => {
    return rules.fileList.filter(item => item.fileType === 'table')
  }, [rules.fileList])

  return (
    <div className="flex-1 flex flex-col relative max-w-[760px] mx-auto">
      <div
        className="flex flex-col gap-4"
        style={{ gridTemplateColumns: '114px 1fr' }}
      >
        <div className="flex justify-end items-center gap-2">
          <Checkbox checked={applyEachCell} onCheckedChange={setApplyEachCell} />
          <Label htmlFor="setSeparately" className="text-sm text-gray-700"> {t('setSeparately')} </Label>
        </div>

        {applyEachCell ? (
          <div>
            <div className="relative after:absolute after:inset-0 after:bg-gray-100/50 after:z-10 after:pointer-events-none">
              <div className="flex items-center justify-between p-4 border rounded-lg text-sm">
                <h3 className="text-md font-bold shrink-0 text-gray-500">
                  {t('splitSettings')}
                </h3>
                {/* disable head */}
                <div className="flex items-center gap-1 mx-auto">
                  <span className="whitespace-nowrap text-gray-500">{t('every')}</span>
                  <div className="relative">
                    <Input
                      id="split"
                      type="number"
                      value={cellGeneralConfig.slice_length}
                      disabled={true}
                      className="w-[106px] h-8"
                    />
                    <span className="absolute right-7 top-1/2 -translate-y-1/2 text-gray-400">{t('row')}</span>
                  </div>
                  <span className="whitespace-nowrap text-gray-500">{t('segemnt')}</span>
                </div>
                {cellGeneralConfig.append_header ? <div className="flex items-center gap-1 shrink-0">
                  <span className="whitespace-nowrap text-gray-500">{t('bonly')}</span>
                  <div className="relative">
                    <Input
                      id="split"
                      type="number"
                      value={cellGeneralConfig.header_start_row}
                      disabled={true}
                      className="w-24 h-8"
                    />
                    <span className="absolute right-7 top-1/2 -translate-y-1/2 text-gray-400">{t('row')}</span>
                  </div>
                  <span className="whitespace-nowrap text-gray-500">{t('arrive')}</span>
                  <div className="relative">
                    <Input
                      id="split"
                      type="number"
                      value={cellGeneralConfig.header_end_row}
                      disabled={true}
                      className="w-24 h-8"
                    />
                    <span className="absolute right-7 top-1/2 -translate-y-1/2 text-gray-400">{t('row')}</span>
                  </div>
                  <span className="whitespace-nowrap text-gray-500">{t('gauge')}</span>
                </div> : <div className="flex items-center gap-2">
                  <Checkbox disabled={true} />
                  <Label className="text-sm"> {t("addHeader")} </Label>
                </div>
                }
              </div>
            </div>
            {/* splice rule */}
            <div className="space-y-4 mt-4 p-4 border rounded-lg bg-white shadow-sm">
              <h3 className="text-md font-bold text-gray-800 text-left">
                {t('splitMethod')}
              </h3>
              <div className="relative mt-2 pr-2 overflow-y-auto max-h-[440px]">
                <Accordion
                  type="single"
                  collapsible
                  className="w-full mb-4"
                >
                  {tableFils.map((file) => (
                    <AccordionItem key={file.id} value={file.id} className="border border-gray/80 rounded-xl mb-2 hover:border-primary hover:shadow-lg">
                      {/* 下拉触发按钮 */}
                      <AccordionTrigger hoverable className="p-0 cursor-pointer relative overflow-hidden flex flex-row-reverse justify-between">
                        <p className="flex gap-2 p-2 items-center relative">
                          <FileIcon type='xls' className="size-[30px] min-w-8" />
                          <span className="w-80 truncate text-left">{file.fileName.slice(0, 15)}{file.fileName.length > 15 ? '...' : ''}</span>
                        </p>
                      </AccordionTrigger>
                      <AccordionContent className="flex flex-col gap-4 p-4">
                        <ItemForm data={file.excelRule} setData={(key, value) => {
                          setRules((prev) => {
                            return {
                              ...prev,
                              fileList: prev.fileList.map((item) => {
                                return item.id === file.id ? {
                                  ...item,
                                  excelRule: {
                                    ...item.excelRule,
                                    [key]: value
                                  }
                                } : item
                              })
                            }
                          })
                        }} />
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </div>
            </div>
          </div>
        ) : (
          // 全局配置
          <div className="space-y-4 p-4 border rounded-lg">
            <h3 className="text-md font-bold text-gray-800 text-left"> {t('splitSettings')} </h3>
            <div className="flex flex-col gap-4">
              <ItemForm data={cellGeneralConfig} setData={(key, value) => setCellGeneralConfig(prev => ({
                ...prev,
                [key]: value
              }))} />
            </div>
          </div>)}
      </div>
    </div>
  )
}
