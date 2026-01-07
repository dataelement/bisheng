"use client"

import { useEffect, useRef, useState } from "react"
import { ChevronDown, AlignLeft, AlignCenter, AlignRight, ChevronUp } from "lucide-react"
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
}
const FULL_DEFAULT_STYLE_CONFIG: ComponentStyleConfig = {
  themeColor: "#4ac5ff",
  bgColor: "#ffffff",
  titleFontSize: 14,
  titleBold: false,
  titleItalic: false,
  titleUnderline: false,
  titleAlign: "left",
  axis: "x",
  axisTitle: "",
  axisFontSize: 14,
  axisBold: false,
  axisItalic: false,
  axisUnderline: false,
  axisAlign: "left",
  legendPosition: "bottom",
  legendFontSize: 14,
  legendBold: false,
  legendItalic: false,
  legendUnderline: false,
  legendAlign: "left",
  showLegend: true,
  showAxis: true,
  showDataLabel: true,
  showGrid: true,
  // 指标卡相关字段
  metricFontSize: 14,
  metricBold: false,
  metricItalic: false,
  metricUnderline: false,
  metricAlign: "center",
  showSubtitle: false,
  subtitle: "",
  subtitleFontSize: 14,
  subtitleBold: false,
  subtitleItalic: false,
  subtitleUnderline: false,
  subtitleAlign: "center",
  // X轴和Y轴标题相关
  xAxisTitle: "",
  xAxisFontSize: 14,
  xAxisBold: false,
  xAxisItalic: false,
  xAxisUnderline: false,
  xAxisAlign: "center",
  yAxisTitle: "",
  yAxisFontSize: 14,
  yAxisBold: false,
  yAxisItalic: false,
  yAxisUnderline: false,
  yAxisAlign: "center"
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
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-black">{title}</label>
        <div className="flex items-center gap-2">
          {rightContent}
          {!isOpen && (
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onCollapse}>
              {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
            </Button>
          )}
        </div>
      </div>
      {(isOpen || !collapsed) && children}
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
      {children}
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
  
  // 防抖处理
  if (debounceTimer.current) {
    clearTimeout(debounceTimer.current);
  }
  
  debounceTimer.current = setTimeout(() => {
    onChange(newConfig);
  }, 300);
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
          <div className="flex items-center gap-2">
            <Select
              value={String(localConfig.titleFontSize)}
              onValueChange={(v) => handleChange("titleFontSize", Number(v))}
            >
              <SelectTrigger className="w-20 h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[12, 14, 16, 18, 20].map((v) => (
                  <SelectItem key={v} value={String(v)}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button
              variant="outline"
              size="sm"
              className={localConfig.titleBold ? "bg-gray-200" : ""}
              onClick={() => handleChange("titleBold", !localConfig.titleBold)}
            >
              B
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.titleItalic ? "bg-gray-200" : ""}
              onClick={() => handleChange("titleItalic", !localConfig.titleItalic)}
            >
              I
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.titleUnderline ? "bg-gray-200" : ""}
              onClick={() => handleChange("titleUnderline", !localConfig.titleUnderline)}
            >
              U
            </Button>

            <Button
              variant="outline"
              size="sm"
              className={localConfig.titleAlign === "left" ? "bg-gray-200" : ""}
              onClick={() => handleChange("titleAlign", "left")}
            >
              <AlignLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.titleAlign === "center" ? "bg-gray-200" : ""}
              onClick={() => handleChange("titleAlign", "center")}
            >
              <AlignCenter className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.titleAlign === "right" ? "bg-gray-200" : ""}
              onClick={() => handleChange("titleAlign", "right")}
            >
              <AlignRight className="h-4 w-4" />
            </Button>
          </div>
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
                <div className="flex items-center gap-2">
                  <Select
                    value={String(localConfig.metricFontSize)}
                    onValueChange={(v) => handleChange("metricFontSize", Number(v))}
                  >
                    <SelectTrigger className="w-20 h-9">
                      <SelectValue />
                    </SelectTrigger>
                    
                    <SelectContent>
                      {[12, 14, 16, 18, 20].map((v) => (
                        <SelectItem key={v} value={String(v)}>
                          {v}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.metricBold ? "bg-gray-200" : ""}
                    onClick={() => handleChange("metricBold", !localConfig.metricBold)}
                  >
                    B
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.metricItalic ? "bg-gray-200" : ""}
                    onClick={() => handleChange("metricItalic", !localConfig.metricItalic)}
                  >
                    I
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.metricUnderline ? "bg-gray-200" : ""}
                    onClick={() => handleChange("metricUnderline", !localConfig.metricUnderline)}
                  >
                    U
                  </Button>

                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.metricAlign === "left" ? "bg-gray-200" : ""}
                    onClick={() => handleChange("metricAlign", "left")}
                  >
                    <AlignLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.metricAlign === "center" ? "bg-gray-200" : ""}
                    onClick={() => handleChange("metricAlign", "center")}
                  >
                    <AlignCenter className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.metricAlign === "right" ? "bg-gray-200" : ""}
                    onClick={() => handleChange("metricAlign", "right")}
                  >
                    <AlignRight className="h-4 w-4" />
                  </Button>
                </div>
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
                  <span className="text-xs text-gray-500">显示该项</span>
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
                    <div className="flex items-center gap-2">
                      <Select
                        value={String(localConfig.subtitleFontSize)}
                        onValueChange={(v) => handleChange("subtitleFontSize", Number(v))}
                      >
                        <SelectTrigger className="w-20 h-9">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {[12, 14, 16, 18, 20].map((v) => (
                            <SelectItem key={v} value={String(v)}>
                              {v}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>

                      <Button
                        variant="outline"
                        size="sm"
                        className={localConfig.subtitleBold ? "bg-gray-200" : ""}
                        onClick={() => handleChange("subtitleBold", !localConfig.subtitleBold)}
                      >
                        B
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className={localConfig.subtitleItalic ? "bg-gray-200" : ""}
                        onClick={() => handleChange("subtitleItalic", !localConfig.subtitleItalic)}
                      >
                        I
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className={localConfig.subtitleUnderline ? "bg-gray-200" : ""}
                        onClick={() => handleChange("subtitleUnderline", !localConfig.subtitleUnderline)}
                      >
                        U
                      </Button>

                      <Button
                        variant="outline"
                        size="sm"
                        className={localConfig.subtitleAlign === "left" ? "bg-gray-200" : ""}
                        onClick={() => handleChange("subtitleAlign", "left")}
                      >
                        <AlignLeft className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className={localConfig.subtitleAlign === "center" ? "bg-gray-200" : ""}
                        onClick={() => handleChange("subtitleAlign", "center")}
                      >
                        <AlignCenter className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className={localConfig.subtitleAlign === "right" ? "bg-gray-200" : ""}
                        onClick={() => handleChange("subtitleAlign", "right")}
                      >
                        <AlignRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </FormBlock>
                </>
              )}
            </CollapsibleBlock>
          </> : <>
            <CollapsibleBlock
              title="轴标题"
              collapsed={collapsedSections.axis}
              onCollapse={() => toggleSection('axis')}
            >
              <div className="space-y-3 rounded-md">

                <FormBlock label="X 轴标题内容">
                  <Input
                    placeholder="请输入X轴标题"
                    value={localConfig.xAxisTitle || ""}
                    onChange={(e) => handleChange("xAxisTitle", e.target.value)}
                  />
                </FormBlock>

                <FormBlock label="X 轴标题文本格式">
                  <div className="flex items-center gap-2">
                    <Select
                      value={String(localConfig.xAxisFontSize || 14)}
                      onValueChange={(v) => handleChange("xAxisFontSize", Number(v))}
                    >
                      <SelectTrigger className="w-20 h-9">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {[12, 14, 16, 18].map((v) => (
                          <SelectItem key={v} value={String(v)}>
                            {v}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>

                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.xAxisBold ? "bg-gray-200" : ""}
                      onClick={() => handleChange("xAxisBold", !localConfig.xAxisBold)}
                    >
                      B
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.xAxisItalic ? "bg-gray-200" : ""}
                      onClick={() => handleChange("xAxisItalic", !localConfig.xAxisItalic)}
                    >
                      I
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.xAxisUnderline ? "bg-gray-200" : ""}
                      onClick={() => handleChange("xAxisUnderline", !localConfig.xAxisUnderline)}
                    >
                      U
                    </Button>

                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.xAxisAlign === "left" ? "bg-gray-200" : ""}
                      onClick={() => handleChange("xAxisAlign", "left")}
                    >
                      <AlignLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.xAxisAlign === "center" ? "bg-gray-200" : ""}
                      onClick={() => handleChange("xAxisAlign", "center")}
                    >
                      <AlignCenter className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.xAxisAlign === "right" ? "bg-gray-200" : ""}
                      onClick={() => handleChange("xAxisAlign", "right")}
                    >
                      <AlignRight className="h-4 w-4" />
                    </Button>
                  </div>
                </FormBlock>
              </div>

              {/* Y轴标题区块 */}
              <div className="space-y-3 rounded-md mt-4">
                <FormBlock label="Y 轴标题内容">
                  <Input
                    placeholder="请输入Y轴标题"
                    value={localConfig.yAxisTitle || ""}
                    onChange={(e) => handleChange("yAxisTitle", e.target.value)}
                  />
                </FormBlock>

                <FormBlock label="Y 轴标题文本格式">
                  <div className="flex items-center gap-2">
                    <Select
                      value={String(localConfig.yAxisFontSize || 14)}
                      onValueChange={(v) => handleChange("yAxisFontSize", Number(v))}
                    >
                      <SelectTrigger className="w-20 h-9">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {[12, 14, 16, 18].map((v) => (
                          <SelectItem key={v} value={String(v)}>
                            {v}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>

                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.yAxisBold ? "bg-gray-200" : ""}
                      onClick={() => handleChange("yAxisBold", !localConfig.yAxisBold)}
                    >
                      B
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.yAxisItalic ? "bg-gray-200" : ""}
                      onClick={() => handleChange("yAxisItalic", !localConfig.yAxisItalic)}
                    >
                      I
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.yAxisUnderline ? "bg-gray-200" : ""}
                      onClick={() => handleChange("yAxisUnderline", !localConfig.yAxisUnderline)}
                    >
                      U
                    </Button>

                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.yAxisAlign === "left" ? "bg-gray-200" : ""}
                      onClick={() => handleChange("yAxisAlign", "left")}
                    >
                      <AlignLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.yAxisAlign === "center" ? "bg-gray-200" : ""}
                      onClick={() => handleChange("yAxisAlign", "center")}
                    >
                      <AlignCenter className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className={localConfig.yAxisAlign === "right" ? "bg-gray-200" : ""}
                      onClick={() => handleChange("yAxisAlign", "right")}
                    >
                      <AlignRight className="h-4 w-4" />
                    </Button>
                  </div>
                </FormBlock>
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

              <FormBlock label="文本格式">
                <div className="flex items-center gap-2">
                  <Select
                    value={String(localConfig.legendFontSize)}
                    onValueChange={(v) => handleChange("legendFontSize", Number(v))}
                  >
                    <SelectTrigger className="w-20 h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {[12, 14, 16].map((v) => (
                        <SelectItem key={v} value={String(v)}>
                          {v}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.legendBold ? "bg-gray-200" : ""}
                    onClick={() => handleChange("legendBold", !localConfig.legendBold)}
                  >
                    B
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.legendItalic ? "bg-gray-200" : ""}
                    onClick={() => handleChange("legendItalic", !localConfig.legendItalic)}
                  >
                    I
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.legendUnderline ? "bg-gray-200" : ""}
                    onClick={() => handleChange("legendUnderline", !localConfig.legendUnderline)}
                  >
                    U
                  </Button>

                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.legendAlign === "left" ? "bg-gray-200" : ""}
                    onClick={() => handleChange("legendAlign", "left")}
                  >
                    <AlignLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.legendAlign === "center" ? "bg-gray-200" : ""}
                    onClick={() => handleChange("legendAlign", "center")}
                  >
                    <AlignCenter className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={localConfig.legendAlign === "right" ? "bg-gray-200" : ""}
                    onClick={() => handleChange("legendAlign", "right")}
                  >
                    <AlignRight className="h-4 w-4" />
                  </Button>
                </div>
              </FormBlock>
            </CollapsibleBlock>

            {/* 图表选项 */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-black">图表选项</label>
              </div>
              <div className="grid grid-cols-2 gap-3">
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