// @ts-strict-ignore
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
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import Tip from "@/components/bs-ui/tooltip/tip";
import { cn } from "@/util/utils";
import { useId, useMemo } from "react";
import { useTranslation } from "react-i18next";


/** Number field. The unit is a sibling span, not an overlay -- the native spinner
 *  sits at the edge of the content box, so anything absolutely positioned inside
 *  ends up fighting it. */
const RowInput = ({ value, onChange, onEmpty, disabled = false, max, maxLength }) => (
  <Input
    type="number"
    min={1}
    max={max}
    maxLength={maxLength}
    value={value}
    disabled={disabled}
    onChange={onChange}
    onBlur={(e) => { !e.target.value && onEmpty() }}
    boxClassName="w-24 shrink-0"
    className="h-8 border-[#ebecf0] bg-white"
  />
)

const ItemForm = ({ data, setData }) => {
  const { t } = useTranslation('knowledge')
  // Rendered once per file in per-table mode, so the checkbox id must be unique.
  const headerCheckboxId = useId()
  const headerEnabled = !!data.append_header

  return <div className="space-y-4 text-sm text-[#0f172a]">
    {/* 分段大小：自动细分的说明收进问号，避免一整行灰字打断表单节奏 */}
    <div className="flex items-center gap-2">
      <span className="shrink-0">{t('maxRowsPerSegment')}</span>
      <RowInput
        value={data.slice_length}
        maxLength={6}
        onChange={e => setData('slice_length', e.target.value)}
        onEmpty={() => setData('slice_length', 10)}
      />
      <span className="shrink-0">{t('row')}</span>
      <QuestionTooltip className="ml-0.5 text-[#94a3b8]" content={t('sliceLengthTooltip')} />
    </div>

    {/* 表头：子设置缩进对齐到勾选框标签，未启用时置灰而非留白 */}
    <div>
      <div className="flex items-center gap-2">
        <Checkbox
          id={headerCheckboxId}
          checked={headerEnabled}
          onCheckedChange={(checked) => setData('append_header', checked)}
        />
        <Label htmlFor={headerCheckboxId} className="cursor-pointer text-sm">
          {t('addHeader')}
        </Label>
      </div>
      {/* Inputs carry their own disabled styling; dim only the surrounding
          text so the two do not compound into an unreadable opacity. */}
      <div
        className={cn(
          "mt-2.5 flex flex-wrap items-center gap-2 pl-6 transition-colors",
          !headerEnabled && "text-muted-foreground"
        )}
      >
        <span className="shrink-0">{t('bonly')}</span>
        <RowInput
          value={data.header_start_row}
          max={1000}
          maxLength={4}
          disabled={!headerEnabled}
          onChange={e => setData('header_start_row', e.target.value)}
          onEmpty={() => setData('header_start_row', 1)}
        />
        <span className="shrink-0">{t('row')}</span>
        <span className="shrink-0">{t('arrive')}</span>
        <RowInput
          value={data.header_end_row}
          max={1000}
          maxLength={4}
          disabled={!headerEnabled}
          onChange={e => setData('header_end_row', e.target.value)}
          onEmpty={() => setData('header_end_row', 1)}
        />
        <span className="shrink-0">{t('row')}</span>
        <span className="shrink-0">{t('gauge')}</span>
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
