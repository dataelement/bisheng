"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { ChevronDown, AlignLeft, AlignCenter, AlignRight, ChevronUp, Bold, Italic, Underline, Strikethrough } from "lucide-react"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { ComponentStyleConfig } from "../../types/dataConfig"
import { useTranslation } from "react-i18next"
import { colorSchemes } from "../../colorSchemes"
import { useComponentEditorStore } from "@/store/dashboardStore"
import { SketchPicker } from 'react-color';
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { cn } from "@/utils"

interface StyleConfigPanelProps {
  config: ComponentStyleConfig
  onChange: (newConfig: ComponentStyleConfig) => void
  type?: string
}

// 文本格式组件
interface TextFormatProps {
  fontSize: number
  setFontSize: (size: number) => void
  bold: boolean
  setBold: (bold: boolean) => void
  italic: boolean
  setItalic: (italic: boolean) => void
  strikethrough: boolean
  setStrikethrough: (strikethrough: boolean) => void
  align: "left" | "center" | "right"
  setAlign: (align: "left" | "center" | "right") => void
  color?: string
  setColor?: (color: string) => void,
  underline?: boolean
  setUnderline?: (underline: boolean) => void
}

function TextFormat({
  fontSize,
  setFontSize,
  bold,
  setBold,
  italic,
  setItalic,
  strikethrough,
  setStrikethrough,
  align,
  setAlign,
  color = "#000000",
  setColor,
  underline = false,
  setUnderline = () => { }
}: TextFormatProps) {
  const { t } = useTranslation("dashboard")

  const alignIcon =
    align === "left" ? (
      <AlignLeft className="w-3.5 h-3.5" />
    ) : align === "center" ? (
      <AlignCenter className="w-3.5 h-3.5" />
    ) : (
      <AlignRight className="w-3.5 h-3.5" />
    )
  return (
    <div
      className="
      flex items-center
      w-[244px] h-8
      border rounded-md
      overflow-hidden
    "
    >
      {/* 字号 */}
      <Select
        value={String(fontSize)}
        onValueChange={(v) => setFontSize(Number(v))}
      >
        <SelectTrigger className="w-[50px] h-7 px-2 text-xs border-0 ">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {[10, 12, 14, 16, 18, 20, 24].map((v) => (
            <SelectItem key={v} value={String(v)} className="text-xs">
              {v}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* 颜色 */}
      {setColor && (
        <Select
        >
          <SelectTrigger className="w-[50px] h-7 px-2 text-xs border-0 ">
            <div className="size-4 border-[#EBECF0]">
              <div
                className="h-full w-full rounded shadow-sm border"
                style={{ backgroundColor: color }}
              />
            </div>
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="border-none shadow-none">
            <SketchPicker
              color={color}
              presetColors={[
                '#D9E3F0', '#F47373', '#697689', '#37D67A',
                '#2CCCE4', '#555555', '#dce775', '#ff8a65', '#ba68c8'
              ]}
              onChangeComplete={(e) => setColor(e.hex)}
            />
          </SelectContent>
        </Select>

        //   <div className="relative shrink-0 mr-2">
        //   <Input
        //     type="color"
        //     className="absolute inset-0 opacity-0 cursor-pointer"
        //     value={color}
        //     onChange={(e) => setColor(e.target.value)}
        //   />
        //   <div
        //     className="w-6 h-6 rounded"
        //     style={{ backgroundColor: color }}
        //   />
        // </div>
      )}

      {/* 对齐 */}
      <Select
        value={align}
        onValueChange={(v) => setAlign(v as "left" | "center" | "right")}
      >
        <SelectTrigger className="w-10 h-7 px-1 border-0 shadow-none">
          <SelectValue asChild>{alignIcon}</SelectValue>
        </SelectTrigger>

        <SelectContent>
          <SelectItem value="left" className="flex justify-center">
            <AlignLeft className="w-4 h-4" />
          </SelectItem>
          <SelectItem value="center" className="flex justify-center">
            <AlignCenter className="w-4 h-4" />
          </SelectItem>
          <SelectItem value="right" className="flex justify-center">
            <AlignRight className="w-4 h-4" />
          </SelectItem>
        </SelectContent>
      </Select>

      {/* 样式 */}
      <div className="flex w-[102px]">
        <IconBtn active={bold} onClick={() => setBold(!bold)}>
          <Bold className="w-3.5 h-3.5" />
        </IconBtn>
        <IconBtn active={italic} onClick={() => setItalic(!italic)}>
          <Italic className="w-3.5 h-3.5" />
        </IconBtn>
        <IconBtn active={underline} onClick={() => setUnderline(!underline)}>
          <Underline className="w-3.5 h-3.5" />
        </IconBtn>
        <IconBtn
          active={strikethrough}
          onClick={() => setStrikethrough(!strikethrough)}
        >
          <Strikethrough className="w-3.5 h-3.5" />
        </IconBtn>
      </div>
    </div>
  )

}

/** 小按钮统一组件 */
function IconBtn({
  active,
  children,
  onClick
}: {
  active?: boolean
  children: React.ReactNode
  onClick: () => void
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onClick}
      className={`w-7 h-7 px-0 rounded-none ${active ? "bg-blue-100 text-blue-600" : ""}`}
    >
      {children}
    </Button>
  )
}




// 内联的折叠区块组件
function CollapsibleBlock({
  title,
  children,
  isOpen = false,
  collapsed,
  onCollapse,
  rightContent
}: {
  title: string
  children: React.ReactNode
  isOpen: boolean
  collapsed: boolean
  onCollapse: () => void
  rightContent?: React.ReactNode
}) {
  const { t } = useTranslation("dashboard")

  return (
    <div className="space-y-3">
      <div
        className="flex items-center justify-between bg-gray-50 rounded-md h-[28px] w-[244px] cursor-pointer"
        onClick={onCollapse}
      >
        <div className="flex items-center">
          <div className="h-3 w-[3px] bg-blue-500 ml-2 rounded-[2px]"></div>
          <label className="text-sm font-medium text-black ml-2">{title}</label>
        </div>
        <div className="flex items-center gap-2 mr-2">
          {rightContent}
          {!isOpen && (
            <Button variant="ghost" size="icon" className="h-6 w-6">
              {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
            </Button>
          )}
        </div>
      </div>
      {(isOpen || !collapsed) && (
        <div className="w-[244px]">
          {children}
        </div>
      )}
    </div>
  )
}

// 内联的表单区块组件
function FormBlock({ label, children }: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">{label}</label>
      <div className="w-[244px]">
        {children}
      </div>
    </div>
  )
}

export function StyleConfigPanel({ config, onChange, type, FULL_DEFAULT_STYLE_CONFIG }: StyleConfigPanelProps) {

  const { t } = useTranslation("dashboard")

  const [collapsedSections, setCollapsedSections] = useState({
    color: false,
    title: true,
    axis: true,
    legend: true,
    chartOptions: false
  })

  const editingComponent = useComponentEditorStore(state => state.editingComponent)

  const updateEditingComponent = useComponentEditorStore(state => state.updateEditingComponent)
  const firstDimension = editingComponent?.data_config?.dimensions?.[0]
  const firstMetric = editingComponent?.data_config?.metrics?.[0]
  const localConfig = useMemo(() => {
    const componentConfig = editingComponent?.style_config || config

    // 准备基础配置
    const baseConfig = {
      ...FULL_DEFAULT_STYLE_CONFIG,
      ...config,
      ...componentConfig,
      themeColor: (() => {
        const id =
          componentConfig.themeColor ??
          config.themeColor

        // 如果不存在 or 不合法 → 用第一个
        return colorSchemes.some(s => s.id === id)
          ? id
          : colorSchemes[0].id
      })(),
    }
    // if (baseConfig.title === "") {
    //   baseConfig.title = editingComponent?.data_config?.metrics?.[0]?.fieldName
    // }
    // 如果轴标题为空，设置默认值
    if (!baseConfig.xAxisTitle && firstDimension?.fieldName) {
      baseConfig.xAxisTitle = firstDimension.fieldName
    }

    if (!baseConfig.yAxisTitle && firstMetric?.fieldName) {
      baseConfig.yAxisTitle = firstMetric.fieldName
    }

    return baseConfig
  }, [editingComponent?.style_config, config, firstDimension, firstMetric])
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    if (!editingComponent || initialized) return

    const styleConfig = editingComponent.style_config ?? {}

    if (styleConfig.title === undefined && editingComponent.type === "metric") {
      updateEditingComponent({
        style_config: {
          ...FULL_DEFAULT_STYLE_CONFIG,
          ...styleConfig,
          title:
            editingComponent.data_config?.metrics?.[0]?.fieldName ?? "",
        },
      })
    }

    setInitialized(true)
  }, [editingComponent, initialized, updateEditingComponent])



  const toggleSection = (section: keyof typeof collapsedSections) => {
    setCollapsedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }))
  }

  const handleChange = (key: keyof ComponentStyleConfig, value: any) => {
    if (!editingComponent) return

    const newConfig = {
      ...localConfig,
      [key]: value
    }

    // 只更新全局状态
    // updateEditingComponent({
    //   style_config: newConfig
    // })

    // 通知父组件
    onChange(newConfig)
  }

  return (
    <div className="space-y-6">
      {/* 颜色 */}
      <CollapsibleBlock
        title={t('styleConfigPanel.sections.color')}
        isOpen={type === 'metric'}
        collapsed={collapsedSections.color}
        onCollapse={() => toggleSection('color')}
      >
        {type !== 'metric' &&
          <FormBlock label={t('styleConfigPanel.labels.themeColor')}>
            <Select
              value={localConfig.themeColor || ""}
              onValueChange={(id) => {
                handleChange("themeColor", id); // 直接存 id
              }}
            >
              {console.log(colorSchemes[0].colors.light, 43242342)}
              <SelectTrigger className="w-full h-8">
                <SelectValue>
                  <div className="flex gap-[1px]">
                    {(colorSchemes.find(s => s.id === localConfig.themeColor)?.colors.light.slice(0, 5) || [colorSchemes[0].colors.light]).map((color, idx) => (
                      <div
                        key={idx}
                        className={`
                w-4 h-4
                ${idx === 0 ? 'rounded-l-sm' : ''}
                ${idx === 4 ? 'rounded-r-sm' : ''}
              `}
                        style={{ backgroundColor: color }}
                      />
                    ))}
                  </div>
                </SelectValue>
              </SelectTrigger>

              <SelectContent className="max-h-[300px] overflow-y-auto">
                {colorSchemes.map((scheme) => (
                  <SelectItem key={scheme.id} value={scheme.id}>
                    <div className="flex gap-[1px]">
                      {scheme.colors.light.slice(0, 5).map((color, idx) => (
                        <div
                          key={idx}
                          className={`
                  w-4 h-4 border border-gray-200
                  ${idx === 0 ? 'rounded-l-sm' : ''}
                  ${idx === 4 ? 'rounded-r-sm' : ''}
                `}
                          style={{ backgroundColor: color }}
                        />
                      ))}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormBlock>
        }

        <FormBlock label={t('styleConfigPanel.labels.bgColor')}>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className={cn(
                  "w-full h-[32px] p-1 justify-start font-normal",
                  !localConfig.bgColor && "text-muted-foreground"
                )}
              >
                <div className="size-5">
                  <div
                    className="h-full w-full border rounded-[4px]"
                    style={{ backgroundColor: localConfig.bgColor }}
                  />
                </div>
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0 border-none shadow-none bg-transparent">
              <SketchPicker
                color={localConfig.bgColor}
                presetColors={[
                  '#D9E3F0', '#F47373', '#697689', '#37D67A',
                  '#2CCCE4', '#555555', '#dce775', '#ff8a65', '#ba68c8'
                ]}
                onChangeComplete={(e) => handleChange("bgColor", e.hex)}
              />
            </PopoverContent>
          </Popover>
          {/* <Input
            type="color"
            className="h-9 p-1"
            value={localConfig.bgColor}
            onChange={(e) => handleChange("bgColor", e.target.value)}
          /> */}
        </FormBlock>
      </CollapsibleBlock>

      {/* 标题 */}
      <CollapsibleBlock
        title={t('styleConfigPanel.sections.title')}
        collapsed={collapsedSections.title}
        onCollapse={() => toggleSection('title')}
        isOpen={type === 'metric'}
      >
        <FormBlock label={type === 'metric' ? t('styleConfigPanel.labels.textContent') : t('styleConfigPanel.labels.titleContent')}>
          <Input
            placeholder={t('styleConfigPanel.placeholders.enterTitle')}
            value={localConfig.title || ""}
            onChange={(e) => handleChange("title", e.target.value)}
          />
        </FormBlock>
        <FormBlock label={t('styleConfigPanel.labels.textFormat')}>
          <TextFormat
            fontSize={localConfig.titleFontSize}
            setFontSize={(v) => handleChange("titleFontSize", v)}
            bold={localConfig.titleBold}
            setBold={(v) => handleChange("titleBold", v)}
            italic={localConfig.titleItalic}
            setItalic={(v) => handleChange("titleItalic", v)}
            underline={localConfig.titleUnderline || false}
            setUnderline={(v) => handleChange("titleUnderline", v)}
            strikethrough={localConfig.titleStrikethrough || false}
            setStrikethrough={(v) => handleChange("titleStrikethrough", v)}
            align={localConfig.titleAlign}
            setAlign={(v) => handleChange("titleAlign", v)}
            color={localConfig.titleColor || localConfig.themeColor}
            setColor={(v) => handleChange("titleColor", v)}
          />
        </FormBlock>
      </CollapsibleBlock>

      {
        type === 'metric' ?
          <>
            <CollapsibleBlock
              isOpen
              title={t('styleConfigPanel.sections.metricValue')}
              collapsed={false}
              onCollapse={() => { }}
            >
              <FormBlock label={t('styleConfigPanel.labels.textFormat')}>
                <TextFormat
                  fontSize={localConfig.metricFontSize || 14}
                  setFontSize={(v) => handleChange("metricFontSize", v)}
                  bold={localConfig.metricBold || false}
                  setBold={(v) => handleChange("metricBold", v)}
                  italic={localConfig.metricItalic || false}
                  setItalic={(v) => handleChange("metricItalic", v)}
                  underline={localConfig.metricUnderline || false}
                  setUnderline={(v) => handleChange("metricUnderline", v)}
                  strikethrough={localConfig.metricStrikethrough || false}
                  setStrikethrough={(v) => handleChange("metricStrikethrough", v)}
                  align={localConfig.metricAlign || "center"}
                  setAlign={(v) => handleChange("metricAlign", v)}
                  color={localConfig.metricColor || localConfig.themeColor}
                  setColor={(v) => handleChange("metricColor", v)}
                />
              </FormBlock>
            </CollapsibleBlock>
            <CollapsibleBlock
              title={t('styleConfigPanel.sections.subtitle')}
              isOpen
              collapsed={false}
              onCollapse={() => { }}
              rightContent={
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={localConfig.showSubtitle || false}
                    onCheckedChange={(v) => handleChange("showSubtitle", v)}
                  />
                  <span className="text-xs text-gray-500">{t('styleConfigPanel.buttons.show')}</span>
                </div>
              }
            >
              {localConfig.showSubtitle && (
                <>
                  <FormBlock label={t('styleConfigPanel.labels.textContent')}>
                    <Input
                      placeholder={t('styleConfigPanel.placeholders.enterSubtitle')}
                      value={localConfig.subtitle || ""}
                      onChange={(e) => handleChange("subtitle", e.target.value)}
                    />
                  </FormBlock>
                  <FormBlock label={t('styleConfigPanel.labels.textFormat')}>
                    <TextFormat
                      fontSize={localConfig.subtitleFontSize || 14}
                      setFontSize={(v) => handleChange("subtitleFontSize", v)}
                      bold={localConfig.subtitleBold || false}
                      setBold={(v) => handleChange("subtitleBold", v)}
                      italic={localConfig.subtitleItalic || false}
                      setItalic={(v) => handleChange("subtitleItalic", v)}
                      underline={localConfig.subtitleUnderline || false}
                      setUnderline={(v) => handleChange("subtitleUnderline", v)}
                      strikethrough={localConfig.subtitleStrikethrough || false}
                      setStrikethrough={(v) => handleChange("subtitleStrikethrough", v)}
                      align={localConfig.subtitleAlign || "center"}
                      setAlign={(v) => handleChange("subtitleAlign", v)}
                      color={localConfig.subtitleColor || localConfig.themeColor}
                      setColor={(v) => handleChange("subtitleColor", v)}
                    />
                  </FormBlock>
                </>
              )}
            </CollapsibleBlock>
          </> : <>
            {/* 轴标题 */}
            <CollapsibleBlock
              title={t('styleConfigPanel.sections.axisTitle')}
              collapsed={collapsedSections.axis}
              onCollapse={() => toggleSection('axis')}
            >
              <div className="space-y-3">
                <FormBlock label={t('styleConfigPanel.labels.xAxisTitleContent')}>
                  <Input
                    placeholder={t('styleConfigPanel.placeholders.enterXAxisTitle')}
                    value={localConfig.xAxisTitle || ""}
                    onChange={(e) => handleChange("xAxisTitle", e.target.value)}
                  />
                </FormBlock>

                <FormBlock label={t('styleConfigPanel.labels.xAxisTextFormat')}>
                  <TextFormat
                    fontSize={localConfig.xAxisFontSize || 14}
                    setFontSize={(v) => handleChange("xAxisFontSize", v)}
                    bold={localConfig.xAxisBold || false}
                    setBold={(v) => handleChange("xAxisBold", v)}
                    italic={localConfig.xAxisItalic || false}
                    setItalic={(v) => handleChange("xAxisItalic", v)}
                    underline={localConfig.xAxisUnderline || false}
                    setUnderline={(v) => handleChange("xAxisUnderline", v)}
                    strikethrough={localConfig.xAxisStrikethrough || false}
                    setStrikethrough={(v) => handleChange("xAxisStrikethrough", v)}
                    align={localConfig.xAxisAlign || "center"}
                    setAlign={(v) => handleChange("xAxisAlign", v)}
                    color={localConfig.xAxisColor || localConfig.themeColor}
                    setColor={(v) => handleChange("xAxisColor", v)}
                  />
                </FormBlock>

                <div className="pt-2 border-t">
                  <FormBlock label={t('styleConfigPanel.labels.yAxisTitleContent')}>
                    <Input
                      placeholder={t('styleConfigPanel.placeholders.enterYAxisTitle')}
                      value={localConfig.yAxisTitle || ""}
                      onChange={(e) => handleChange("yAxisTitle", e.target.value)}
                    />
                  </FormBlock>

                  <FormBlock label={t('styleConfigPanel.labels.yAxisTextFormat')}>
                    <TextFormat
                      fontSize={localConfig.yAxisFontSize || 14}
                      setFontSize={(v) => handleChange("yAxisFontSize", v)}
                      bold={localConfig.yAxisBold || false}
                      setBold={(v) => handleChange("yAxisBold", v)}
                      italic={localConfig.yAxisItalic || false}
                      setItalic={(v) => handleChange("yAxisItalic", v)}
                      underline={localConfig.yAxisUnderline || false}
                      setUnderline={(v) => handleChange("yAxisUnderline", v)}
                      strikethrough={localConfig.yAxisStrikethrough || false}
                      setStrikethrough={(v) => handleChange("yAxisStrikethrough", v)}
                      align={localConfig.yAxisAlign || "center"}
                      setAlign={(v) => handleChange("yAxisAlign", v)}
                      color={localConfig.yAxisColor || localConfig.themeColor}
                      setColor={(v) => handleChange("yAxisColor", v)}
                    />
                  </FormBlock>
                </div>
              </div>
            </CollapsibleBlock>

            {/* 图例 */}
            <CollapsibleBlock
              title={t('styleConfigPanel.sections.legend')}
              collapsed={collapsedSections.legend}
              onCollapse={() => toggleSection('legend')}
            >
              <FormBlock label={t('styleConfigPanel.labels.legendPosition')}>
                <Select
                  value={localConfig.legendPosition}
                  onValueChange={(v) =>
                    handleChange("legendPosition", v as "top" | "bottom" | "left" | "right")
                  }
                >
                  <SelectTrigger className="w-full h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="top">{t('styleConfigPanel.positions.top')}</SelectItem>
                    <SelectItem value="bottom">{t('styleConfigPanel.positions.bottom')}</SelectItem>
                    <SelectItem value="left">{t('styleConfigPanel.positions.left')}</SelectItem>
                    <SelectItem value="right">{t('styleConfigPanel.positions.right')}</SelectItem>
                  </SelectContent>
                </Select>
              </FormBlock>

              <FormBlock label={t('styleConfigPanel.labels.legendTextFormat')}>
                <TextFormat
                  fontSize={localConfig.legendFontSize}
                  setFontSize={(v) => handleChange("legendFontSize", v)}
                  bold={localConfig.legendBold}
                  setBold={(v) => handleChange("legendBold", v)}
                  italic={localConfig.legendItalic}
                  setItalic={(v) => handleChange("legendItalic", v)}
                  underline={localConfig.legendUnderline}
                  setUnderline={(v) => handleChange("legendUnderline", v)}
                  strikethrough={localConfig.legendStrikethrough || false}
                  setStrikethrough={(v) => handleChange("legendStrikethrough", v)}
                  align={localConfig.legendAlign}
                  setAlign={(v) => handleChange("legendAlign", v)}
                  color={localConfig.legendColor || localConfig.themeColor}
                  setColor={(v) => handleChange("legendColor", v)}
                />
              </FormBlock>
            </CollapsibleBlock>
            {console.log(editingComponent, editingComponent?.type, 454545454)}
            {/* 图表选项 */}
            <CollapsibleBlock
              title={t('styleConfigPanel.sections.chartOptions')}
              isOpen={false}
              collapsed={collapsedSections.chartOptions}
              onCollapse={() => toggleSection('chartOptions')}
            >
              <div className="grid grid-cols-2 gap-3 w-[244px]">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showLegend}
                    onCheckedChange={(v) => handleChange("showLegend", v)}
                  />
                  {t('styleConfigPanel.options.legend')}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showDataLabel}
                    onCheckedChange={(v) => handleChange("showDataLabel", v)}
                  />
                  {t('styleConfigPanel.options.dataLabel')}
                </label>
                {editingComponent.type !== "donut" && editingComponent.type !== "pie" && <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showAxis}
                    onCheckedChange={(v) => handleChange("showAxis", v)}
                  />
                  {t('styleConfigPanel.options.axis')}
                </label>}


                {editingComponent.type !== "donut" && editingComponent.type !== "pie" && <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showGrid}
                    onCheckedChange={(v) => handleChange("showGrid", v)}
                  />
                  {t('styleConfigPanel.options.gridLine')}
                </label>}
              </div>
            </CollapsibleBlock>
          </>
      }
    </div>
  )
}