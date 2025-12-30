"use client"

import { useEffect, useState } from "react"
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

// 内联的折叠区块组件
function CollapsibleBlock({ 
  title, 
  children,
  collapsed,
  onCollapse 
}: {
  title: string
  children: React.ReactNode
  collapsed: boolean
  onCollapse: () => void
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-black">{title}</label>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onCollapse}>
          {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </Button>
      </div>
      {!collapsed && children}
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

export function StyleConfigPanel({ config, onChange }: StyleConfigPanelProps) {
  const [collapsedSections, setCollapsedSections] = useState({
    color: false,
    title: false,
    axis: false,
    legend: false
  })
  
  const [localConfig, setLocalConfig] = useState(config)
  
  // 实时更新到父组件
  useEffect(() => {
    onChange(localConfig)
  }, [localConfig, onChange])

  // 当父组件的 config 变化时同步
  useEffect(() => {
    setLocalConfig(config)
  }, [config])

  const toggleSection = (section: keyof typeof collapsedSections) => {
    setCollapsedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }))
  }

  const handleChange = (key: keyof ComponentStyleConfig, value: any) => {
    setLocalConfig(prev => ({
      ...prev,
      [key]: value
    }))
  }

  return (
    <div className="space-y-6">
      {/* 颜色 */}
      <CollapsibleBlock
        title="颜色"
        collapsed={collapsedSections.color}
        onCollapse={() => toggleSection('color')}
      >
        <FormBlock label="主题颜色">
          <div className="flex items-center gap-2">
            {themeColors.map((color) => (
              <button
                key={color}
                style={{ backgroundColor: color }}
                className={`w-6 h-6 rounded border ${
                  localConfig.themeColor === color ? "border-black" : "border-gray-300"
                }`}
                onClick={() => handleChange("themeColor", color)}
              />
            ))}
          </div>
        </FormBlock>

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
      >
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

      {/* 轴标题 */}
      <CollapsibleBlock 
        title="轴标题" 
        collapsed={collapsedSections.axis}
        onCollapse={() => toggleSection('axis')}
      >
        <FormBlock label="选择轴">
          <Select
            value={localConfig.axis}
            onValueChange={(v) => handleChange("axis", v as "x" | "y")}
          >
            <SelectTrigger className="w-full h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="x">横轴标题</SelectItem>
              <SelectItem value="y">纵轴标题</SelectItem>
            </SelectContent>
          </Select>
        </FormBlock>

        <FormBlock label="标题内容">
          <Input
            placeholder="请输入标题"
            value={localConfig.axisTitle}
            onChange={(e) => handleChange("axisTitle", e.target.value)}
          />
        </FormBlock>

        <FormBlock label="文本格式">
          <div className="flex items-center gap-2">
            <Select
              value={String(localConfig.axisFontSize)}
              onValueChange={(v) => handleChange("axisFontSize", Number(v))}
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
              className={localConfig.axisBold ? "bg-gray-200" : ""}
              onClick={() => handleChange("axisBold", !localConfig.axisBold)}
            >
              B
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.axisItalic ? "bg-gray-200" : ""}
              onClick={() => handleChange("axisItalic", !localConfig.axisItalic)}
            >
              I
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.axisUnderline ? "bg-gray-200" : ""}
              onClick={() => handleChange("axisUnderline", !localConfig.axisUnderline)}
            >
              U
            </Button>

            <Button
              variant="outline"
              size="sm"
              className={localConfig.axisAlign === "left" ? "bg-gray-200" : ""}
              onClick={() => handleChange("axisAlign", "left")}
            >
              <AlignLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.axisAlign === "center" ? "bg-gray-200" : ""}
              onClick={() => handleChange("axisAlign", "center")}
            >
              <AlignCenter className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={localConfig.axisAlign === "right" ? "bg-gray-200" : ""}
              onClick={() => handleChange("axisAlign", "right")}
            >
              <AlignRight className="h-4 w-4" />
            </Button>
          </div>
        </FormBlock>
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
    </div>
  )
}