// @ts-strict-ignore
import { Button, Input, Select } from '@bisheng/ui';



import { Popover,PopoverContent,PopoverTrigger } from "@/components/bs-ui/popover";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
// The theme-color picker renders color swatches as its options, which the
// shared Select (plain-text labels) cannot show, so it stays on the old one.
import {
Select as LegacySelect,
SelectContent,
SelectItem,
SelectTrigger,
SelectValue,
} from "@/components/bs-ui/select";
import { useComponentEditorStore } from "@/store/dashboardStore";
import { cn } from "@/utils";
import { Checkbox } from "@bisheng/ui";
import { useEffect,useMemo,useState } from "react";
import { SketchPicker } from 'react-color';
import { useTranslation } from "react-i18next";
import { colorSchemes } from "../../colorSchemes";
import { ComponentStyleConfig } from "../../types/dataConfig";
import { CollapsibleBlock,FormBlock,TextFormat,type TextFormatProps } from "./StyleConfigControls";

interface StyleConfigPanelProps {
  FULL_DEFAULT_STYLE_CONFIG: ComponentStyleConfig;
  config: ComponentStyleConfig
  onChange: (newConfig: ComponentStyleConfig) => void
  type?: string
}

// 文本格式组件
function StyleTextFormat(props: TextFormatProps) { return <TextFormat {...props} colorPicker={<SketchPicker
              color={props.color}
              presetColors={[
                '#D9E3F0', '#F47373', '#697689', '#37D67A',
                '#2CCCE4', '#555555', '#dce775', '#ff8a65', '#ba68c8'
              ]}
              onChangeComplete={(e) => props.setColor?.(e.hex)}
            />} />; }
export function StyleConfigPanel({ config, onChange, type, FULL_DEFAULT_STYLE_CONFIG }: StyleConfigPanelProps) {

  const { t } = useTranslation("dashboard")
  const selectLabels = useSelectLabels()

  const editingComponent = useComponentEditorStore(state => state.editingComponent)

  const collapsedSections = useComponentEditorStore(state => state.collapsedSections)
  const setCollapsedSection = useComponentEditorStore(state => state.setCollapsedSection)

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
    if (baseConfig.xAxisTitle === undefined && firstDimension?.fieldName) {
      baseConfig.xAxisTitle = firstDimension.fieldName;
    }

    if (baseConfig.yAxisTitle === undefined && firstMetric?.fieldName) {
      baseConfig.yAxisTitle = firstMetric.fieldName;
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
        },
        title: editingComponent.data_config?.metrics?.[0]?.fieldName ?? "",
      })
    } else {
      updateEditingComponent({
        style_config: {
          ...FULL_DEFAULT_STYLE_CONFIG,
          ...styleConfig,
          title:
            editingComponent.title ?? "",
        },
      })
    }

    setInitialized(true)
  }, [editingComponent?.id])



  const toggleSection = (section: keyof typeof collapsedSections) => {
    setCollapsedSection(section, !collapsedSections[section])
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
            <LegacySelect
              value={localConfig.themeColor || ""}
              onValueChange={(id) => {
                handleChange("themeColor", id); // 直接存 id
              }}
            >
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
            </LegacySelect>
          </FormBlock>
        }

        <FormBlock label={t('styleConfigPanel.labels.bgColor')}>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outlined" className={cn(
                  "w-full h-[32px] p-1 justify-start font-normal",
                  !localConfig.bgColor && "text-muted-foreground"
                )} color="default">
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
          <Input placeholder={t('styleConfigPanel.placeholders.enterTitle')} value={localConfig.title || ""} onChange={(e) => {
              const value = e.target.value
              if (value.length <= 15) {
                handleChange("title", value)
              }
            }} maxLength={15} showCount />
        </FormBlock>
        <FormBlock label={t('styleConfigPanel.labels.textFormat')}>
          <StyleTextFormat
            fontSize={localConfig.titleFontSize}
            setFontSize={(v) => handleChange("titleFontSize", v)}
            bold={localConfig.titleBold || false}
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
                <StyleTextFormat
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
                    <Input placeholder={t('styleConfigPanel.placeholders.enterSubtitle')} value={localConfig.subtitle || ""} onChange={(e) => {
                        const value = e.target.value
                        if (value.length <= 24) {
                          handleChange("subtitle", e.target.value)
                        }
                      }} maxLength={24} showCount />
                  </FormBlock>
                  <FormBlock label={t('styleConfigPanel.labels.textFormat')}>
                    <StyleTextFormat
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
                  <Input placeholder={t('styleConfigPanel.placeholders.enterXAxisTitle')} value={localConfig.xAxisTitle || ""} onChange={(e) => {
                      const value = e.target.value
                      if (value.length <= 15) {
                        handleChange("xAxisTitle", e.target.value)
                      }
                    }} maxLength={15} showCount />
                </FormBlock>

                <FormBlock label={t('styleConfigPanel.labels.xAxisTextFormat')}>
                  <StyleTextFormat
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
                    <Input placeholder={t('styleConfigPanel.placeholders.enterYAxisTitle')} value={localConfig.yAxisTitle || ""} onChange={(e) => {
                        const value = e.target.value
                        if (value.length <= 15) {
                          handleChange("yAxisTitle", e.target.value)
                        }
                      }} maxLength={15} showCount />
                  </FormBlock>

                  <FormBlock label={t('styleConfigPanel.labels.yAxisTextFormat')}>
                    <StyleTextFormat
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
                  {...selectLabels}
                  className="w-full"
                  options={[
                    { value: "top", label: t('styleConfigPanel.positions.top') },
                    { value: "bottom", label: t('styleConfigPanel.positions.bottom') },
                    { value: "left", label: t('styleConfigPanel.positions.left') },
                    { value: "right", label: t('styleConfigPanel.positions.right') },
                  ]}
                  value={localConfig.legendPosition || null}
                  onChange={(v) => {
                    if (v != null) handleChange("legendPosition", v as "top" | "bottom" | "left" | "right")
                  }}
                  aria-label={t('styleConfigPanel.labels.legendPosition')}
                />
              </FormBlock>

              <FormBlock label={t('styleConfigPanel.labels.legendTextFormat')}>
                <StyleTextFormat
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