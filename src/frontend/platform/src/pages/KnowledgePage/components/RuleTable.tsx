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
import Tip from "@/components/bs-ui/tooltip/tip";
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



interface RuleTableProps {
  rules: any;
  setRules: (updater: any) => void;
  applyEachCell: boolean;
  setApplyEachCell: (checked: boolean) => void;
  cellGeneralConfig: any;
  setCellGeneralConfig: (updater: any) => void;
  showPreview?: boolean;
}

export default function RuleTable({
  rules,
  setRules,
  applyEachCell,
  setApplyEachCell,
  cellGeneralConfig,
  setCellGeneralConfig,
  showPreview,
}: RuleTableProps) {
  const { t } = useTranslation('knowledge')
  const mediumTitleStyle = useMemo(() => ({
    fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC", sans-serif',
    fontWeight: 500
  }), []);

  const tableFils = useMemo(() => {
    return rules.fileList.filter(item => item.fileType === 'table')
  }, [rules.fileList])
  const tableFileIds = useMemo(() => tableFils.map(file => String(file.id)), [tableFils]);

  return (
    <div className="flex-1 flex flex-col relative min-w-0">
      <div
        className="flex flex-col gap-4"
        style={{ gridTemplateColumns: '114px 1fr' }}
      >
        <div className="flex items-center gap-2 text-left">
          <h3 className="text-[16px] text-[#0f172a]" style={mediumTitleStyle}>
            {t('splitSettings')}
          </h3>
          <div className="flex items-center gap-2">
            <Checkbox id="setSeparately" checked={applyEachCell} onCheckedChange={setApplyEachCell} />
            <Label htmlFor="setSeparately" className="text-sm text-[#212121]">{t('setSeparately')}</Label>
          </div>
        </div>

        {applyEachCell ? (
          <div className="text-left">
            <Accordion
              key={`table-separate-${tableFileIds.join('-')}`}
              type="multiple"
              defaultValue={tableFileIds}
              className="space-y-3"
            >
              {tableFils.map((file) => (
                <AccordionItem
                  key={file.id}
                  value={String(file.id)}
                  className="overflow-hidden rounded-[10px] border border-[#e4e8ee] bg-white"
                >
                  <AccordionTrigger className="flex flex-row-reverse items-center justify-between gap-3 px-4 py-3 text-[14px] font-normal text-[#0f172a] hover:no-underline">
                    <Tip content={file.fileName} align="start">
                      <div className="flex min-w-0 items-center gap-2 text-left">
                        <FileIcon type='xls' className="size-[30px] min-w-8" />
                        <span className="min-w-0 truncate">{file.fileName}</span>
                      </div>
                    </Tip>
                  </AccordionTrigger>
                  <AccordionContent className="px-4 pb-4 pt-0">
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
        ) : (
          // 全局配置
          <div className="space-y-4 text-left">
            <div className="space-y-4 rounded-lg border p-4">
              <div className="flex flex-col gap-4">
                <ItemForm data={cellGeneralConfig} setData={(key, value) => setCellGeneralConfig(prev => ({
                  ...prev,
                  [key]: value
                }))} />
              </div>
            </div>
          </div>)}
      </div>
    </div>
  )
}
