"use client"

import { useState } from "react"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"

interface ChartSelectorProps {
  charts: { id: string; name: string; dataset?: string }[]
  onSave?: (selectedCharts: string[], startDate: string, endDate: string) => void
  onCancel?: () => void
}

export default function ChartSelector({ charts, onSave, onCancel }: ChartSelectorProps) {
  const [selectedCharts, setSelectedCharts] = useState<string[]>(charts.map(c => c.id))
  const [startDate, setStartDate] = useState('2025-11-29')
  const [endDate, setEndDate] = useState('2025-12-29')
  const [displayType, setDisplayType] = useState("时间范围")
  const [timeGranularity, setTimeGranularity] = useState("时间范围")
  const [setDefault, setSetDefault] = useState(true)

  const toggleChart = (id: string) => {
    setSelectedCharts(prev =>
      prev.includes(id) ? prev.filter(c => c !== id) : [...prev, id]
    )
  }

  const toggleSelectAll = () => {
    if (selectedCharts.length === charts.length) {
      setSelectedCharts([])
    } else {
      setSelectedCharts(charts.map(c => c.id))
    }
  }

  return (
    <div className="p-4 w-[400px] bg-white border rounded shadow">
      <h3 className="text-lg font-medium mb-3">选择关联图表</h3>

      <div className="space-y-1 mb-4 max-h-64 overflow-y-auto border rounded p-2">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={selectedCharts.length === charts.length}
            onChange={toggleSelectAll}
          />
          <span className="font-medium">全选</span>
        </label>

        {charts.map(chart => (
          <label key={chart.id} className="flex items-center gap-2 pl-4">
            <input
              type="checkbox"
              checked={selectedCharts.includes(chart.id)}
              onChange={() => toggleChart(chart.id)}
            />
            <span>{chart.name} {chart.dataset ? `(${chart.dataset})` : ''}</span>
          </label>
        ))}
      </div>

      <div className="space-y-4 mb-4">
        <div>
          <label className="block text-sm mb-1">展示类型</label>
          <select
            className="w-full border rounded h-9 px-2"
            value={displayType}
            onChange={(e) => setDisplayType(e.target.value)}
          >
            <option value="时间范围">时间范围</option>
            <option value="其他类型">其他类型</option>
          </select>
        </div>

        <div>
          <label className="block text-sm mb-1">时间粒度</label>
          <select
            className="w-full border rounded h-9 px-2"
            value={timeGranularity}
            onChange={(e) => setTimeGranularity(e.target.value)}
          >
            <option value="时间范围">时间范围</option>
            <option value="其他粒度">其他粒度</option>
          </select>
        </div>

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={setDefault}
            onChange={() => setSetDefault(prev => !prev)}
          />
          <span>设置默认值</span>
        </label>

        <div className="flex items-center gap-2">
          <Input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="h-9"/>
          <span className="text-sm text-muted-foreground">至</span>
          <Input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="h-9"/>
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel}>取消</Button>
        <Button onClick={() => onSave?.(selectedCharts, startDate, endDate)}>保存</Button>
      </div>
    </div>
  )
}
