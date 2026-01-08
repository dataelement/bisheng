"use client"

import { useEffect, useRef, useState } from "react"
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

const themeColors = ["#4ac5ff", "#3dd598", "#f7ba0b", "#ff7d4d", "#5c6bc0"]

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
  setColor?: (color: string) => void
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
  setColor
}: TextFormatProps) {
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
      flex items-center gap-1
      w-[244px] h-8
      px-1
      border rounded-md
      overflow-hidden
    "
  >
    {/* 字号 */}
    <Select
      value={String(fontSize)}
      onValueChange={(v) => setFontSize(Number(v))}
    >
      <SelectTrigger className="w-[56px] h-7 px-2 text-xs border-0 ">
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
      <div className="relative shrink-0 mr-2">
        <Input
          type="color"
          className="absolute inset-0 opacity-0 cursor-pointer"
          value={color}
          onChange={(e) => setColor(e.target.value)}
        />
        <div
          className="w-6 h-6 rounded"
          style={{ backgroundColor: color }}
        />
      </div>
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
    <div className="flex">
      <IconBtn active={bold} onClick={() => setBold(!bold)}>
        <Bold className="w-3.5 h-3.5" />
      </IconBtn>
      <IconBtn active={italic} onClick={() => setItalic(!italic)}>
        <Italic className="w-3.5 h-3.5" />
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
      className={`w-7 h-7 px-0 rounded-none ${
        active ? "bg-gray-200" : ""
      }`}
    >
      {children}
    </Button>
  )
}

const FULL_DEFAULT_STYLE_CONFIG: ComponentStyleConfig = {
  themeColor: "#4ac5ff",
  bgColor: "#ffffff",

  title: "",
  titleFontSize: 14,
  titleBold: false,
  titleItalic: false,
  titleUnderline: false,
  titleAlign: "left",
  titleColor: "#000000",

  xAxisTitle: "",
  xAxisFontSize: 14,
  xAxisBold: false,
  xAxisItalic: false,
  xAxisUnderline: false,
  xAxisAlign: "center",
  xAxisColor: "#000000",

  yAxisTitle: "",
  yAxisFontSize: 14,
  yAxisBold: false,
  yAxisItalic: false,
  yAxisUnderline: false,
  yAxisAlign: "center",
  yAxisColor: "#000000",

  legendPosition: "bottom",
  legendFontSize: 14,
  legendBold: false,
  legendItalic: false,
  legendUnderline: false,
  legendAlign: "left",
  legendColor: "#000000",

  showSubtitle: false,
  subtitle: "",
  subtitleFontSize: 14,
  subtitleBold: false,
  subtitleItalic: false,
  subtitleUnderline: false,
  subtitleAlign: "center",
  subtitleColor: "#000000",

  metricFontSize: 14,
  metricBold: false,
  metricItalic: false,
  metricUnderline: false,
  metricAlign: "center",
  metricColor: "#000000",

  showLegend: true,
  showAxis: true,
  showDataLabel: true,
  showGrid: true,
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
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between bg-gray-50 rounded-md h-[28px] w-[244px]">
        <div className="flex items-center">
          <div className="h-3 w-[3px] bg-blue-500 ml-2 rounded-[2px]"></div>
          <label className="text-sm font-medium text-black ml-2">{title}</label>
        </div>
        <div className="flex items-center gap-2 mr-2">
          {rightContent}
          {!isOpen && (
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onCollapse}>
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

export function StyleConfigPanel({ config, onChange, type }: StyleConfigPanelProps) {
  const [collapsedSections, setCollapsedSections] = useState({
    color: false,
    title: false,
    axis: false,
    legend: false
  })

  const [localConfig, setLocalConfig] = useState(() => ({
    ...FULL_DEFAULT_STYLE_CONFIG,
    ...config
  }))

  const debounceTimer = useRef<NodeJS.Timeout>()

  useEffect(() => {
    if (JSON.stringify(config) !== JSON.stringify(localConfig)) {
      setLocalConfig(prev => ({
        ...FULL_DEFAULT_STYLE_CONFIG,
        ...config
      }))
    }
  }, [config])

  const toggleSection = (section: keyof typeof collapsedSections) => {
    setCollapsedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }))
  }

  const handleChange = (key: keyof ComponentStyleConfig, value: any) => {
    const newConfig = {
      ...localConfig,
      [key]: value
    };
    setLocalConfig(newConfig);
 onChange(newConfig) 
  };
  return (
    <div className="space-y-6">
      {/* 颜色 */}
      <CollapsibleBlock
        title="颜色"
        isOpen={type === 'metric'}
        collapsed={collapsedSections.color}
        onCollapse={() => toggleSection('color')}
      >
        {type !== 'metric' &&
          <FormBlock label="主题颜色">
            <div className="flex items-center gap-2">
              {themeColors.map((color) => (
                <button
                  key={color}
                  style={{ backgroundColor: color }}
                  className={`w-6 h-6 rounded border ${localConfig.themeColor === color ? "border-black" : "border-gray-300"
                    }`}
                  onClick={() => handleChange("themeColor", color)}
                />
              ))}
            </div>
          </FormBlock>}

        <FormBlock label="背景颜色">
          <Input
            type="color"
            className="h-9 p-1"
            value={localConfig.bgColor}
            onChange={(e) => handleChange("bgColor", e.target.value)}
          />
        </FormBlock>
      </CollapsibleBlock>

      {/* 标题 */}
      <CollapsibleBlock
        title="标题"
        collapsed={collapsedSections.title}
        onCollapse={() => toggleSection('title')}
        isOpen={type === 'metric'}
      >
        <FormBlock label="标题内容">
          <Input
            placeholder="请输入标题"
            value={localConfig.title || ""}
            onChange={(e) => handleChange("title", e.target.value)}
          />
        </FormBlock>
        <FormBlock label="文本格式">
          <TextFormat
            fontSize={localConfig.titleFontSize}
            setFontSize={(v) => handleChange("titleFontSize", v)}
            bold={localConfig.titleBold}
            setBold={(v) => handleChange("titleBold", v)}
            italic={localConfig.titleItalic}
            setItalic={(v) => handleChange("titleItalic", v)}
            strikethrough={localConfig.titleUnderline} // 使用 strikethrough 代替 underline
            setStrikethrough={(v) => handleChange("titleUnderline", v)}
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
              title="指标数值"
              collapsed={false}
              onCollapse={() => { }}
            >
              <FormBlock label="文本格式">
                <TextFormat
                  fontSize={localConfig.metricFontSize || 14}
                  setFontSize={(v) => handleChange("metricFontSize", v)}
                  bold={localConfig.metricBold || false}
                  setBold={(v) => handleChange("metricBold", v)}
                  italic={localConfig.metricItalic || false}
                  setItalic={(v) => handleChange("metricItalic", v)}
                  strikethrough={localConfig.metricUnderline || false}
                  setStrikethrough={(v) => handleChange("metricUnderline", v)}
                  align={localConfig.metricAlign || "center"}
                  setAlign={(v) => handleChange("metricAlign", v)}
                   color={localConfig.metricColor || localConfig.themeColor}
  setColor={(v) => handleChange("metricColor", v)}
                />
              </FormBlock>
            </CollapsibleBlock>
            <CollapsibleBlock
              title="副标题"
              isOpen
              collapsed={false}
              onCollapse={() => { }}
              rightContent={
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={localConfig.showSubtitle || false}
                    onCheckedChange={(v) => handleChange("showSubtitle", v)}
                  />
                  <span className="text-xs text-gray-500">显示</span>
                </div>
              }
            >
              {localConfig.showSubtitle && (
                <>
                  <FormBlock label="文本内容">
                    <Input
                      placeholder="请输入副标题"
                      value={localConfig.subtitle || ""}
                      onChange={(e) => handleChange("subtitle", e.target.value)}
                    />
                  </FormBlock>
                  <FormBlock label="文本格式">
                    <TextFormat
                      fontSize={localConfig.subtitleFontSize || 14}
                      setFontSize={(v) => handleChange("subtitleFontSize", v)}
                      bold={localConfig.subtitleBold || false}
                      setBold={(v) => handleChange("subtitleBold", v)}
                      italic={localConfig.subtitleItalic || false}
                      setItalic={(v) => handleChange("subtitleItalic", v)}
                      strikethrough={localConfig.subtitleUnderline || false}
                      setStrikethrough={(v) => handleChange("subtitleUnderline", v)}
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
              title="轴标题"
              collapsed={collapsedSections.axis}
              onCollapse={() => toggleSection('axis')}
            >
              <div className="space-y-3">
                <FormBlock label="X 轴标题内容">
                  <Input
                    placeholder="请输入X轴标题"
                    value={localConfig.xAxisTitle || ""}
                    onChange={(e) => handleChange("xAxisTitle", e.target.value)}
                  />
                </FormBlock>

                <FormBlock label="X 轴文本格式">
                  <TextFormat
                    fontSize={localConfig.xAxisFontSize || 14}
                    setFontSize={(v) => handleChange("xAxisFontSize", v)}
                    bold={localConfig.xAxisBold || false}
                    setBold={(v) => handleChange("xAxisBold", v)}
                    italic={localConfig.xAxisItalic || false}
                    setItalic={(v) => handleChange("xAxisItalic", v)}
                    strikethrough={localConfig.xAxisUnderline || false}
                    setStrikethrough={(v) => handleChange("xAxisUnderline", v)}
                    align={localConfig.xAxisAlign || "center"}
                    setAlign={(v) => handleChange("xAxisAlign", v)}
                   color={localConfig.xAxisColor || localConfig.themeColor}
                    setColor={(v) => handleChange("xAxisColor", v)}
                  />
                </FormBlock>

                <div className="pt-2 border-t">
                  <FormBlock label="Y 轴标题内容">
                    <Input
                      placeholder="请输入Y轴标题"
                      value={localConfig.yAxisTitle || ""}
                      onChange={(e) => handleChange("yAxisTitle", e.target.value)}
                    />
                  </FormBlock>

                  <FormBlock label="Y 轴文本格式">
                    <TextFormat
                      fontSize={localConfig.yAxisFontSize || 14}
                      setFontSize={(v) => handleChange("yAxisFontSize", v)}
                      bold={localConfig.yAxisBold || false}
                      setBold={(v) => handleChange("yAxisBold", v)}
                      italic={localConfig.yAxisItalic || false}
                      setItalic={(v) => handleChange("yAxisItalic", v)}
                      strikethrough={localConfig.yAxisUnderline || false}
                      setStrikethrough={(v) => handleChange("yAxisUnderline", v)}
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
              title="图例"
              collapsed={collapsedSections.legend}
              onCollapse={() => toggleSection('legend')}
            >
              <FormBlock label="图例位置">
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
                    <SelectItem value="top">顶部</SelectItem>
                    <SelectItem value="bottom">底部</SelectItem>
                    <SelectItem value="left">左侧</SelectItem>
                    <SelectItem value="right">右侧</SelectItem>
                  </SelectContent>
                </Select>
              </FormBlock>

              <FormBlock label="图例文本格式">
                <TextFormat
                  fontSize={localConfig.legendFontSize}
                  setFontSize={(v) => handleChange("legendFontSize", v)}
                  bold={localConfig.legendBold}
                  setBold={(v) => handleChange("legendBold", v)}
                  italic={localConfig.legendItalic}
                  setItalic={(v) => handleChange("legendItalic", v)}
                  strikethrough={localConfig.legendUnderline}
                  setStrikethrough={(v) => handleChange("legendUnderline", v)}
                  align={localConfig.legendAlign}
                  setAlign={(v) => handleChange("legendAlign", v)}
                 color={localConfig.legendColor || localConfig.themeColor}
  setColor={(v) => handleChange("legendColor", v)}
                />
              </FormBlock>
            </CollapsibleBlock>

            {/* 图表选项 */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-black">图表选项</label>
              </div>
              <div className="grid grid-cols-2 gap-3 w-[244px]">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showLegend}
                    onCheckedChange={(v) => handleChange("showLegend", v)}
                  />
                  图例
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showAxis}
                    onCheckedChange={(v) => handleChange("showAxis", v)}
                  />
                  坐标轴
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showDataLabel}
                    onCheckedChange={(v) => handleChange("showDataLabel", v)}
                  />
                  数据标签
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={localConfig.showGrid}
                    onCheckedChange={(v) => handleChange("showGrid", v)}
                  />
                  网格线
                </label>
              </div>
            </div>
          </>
      }
    </div>
  )
}