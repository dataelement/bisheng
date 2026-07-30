"use client"

import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { getDatasets } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { useEffect, useMemo, useState } from "react"
import { useQuery } from "react-query"

import {
  ChartType,
  DashboardComponent,
  DimensionFilterConfig,
  DimensionFilterField,
} from "../../types/dataConfig"

interface DimensionFilterConfiguratorProps {
  component: DashboardComponent
  onSave: (datasetCode: string, config: DimensionFilterConfig) => void
  onCancel: () => void
}

export function DimensionFilterConfigurator({
  component,
  onSave,
  onCancel,
}: DimensionFilterConfiguratorProps) {
  const currentDashboard = useEditorDashboardStore(state => state.currentDashboard)
  const { data: datasets = [] } = useQuery({
    queryKey: ["datasets"],
    queryFn: getDatasets,
  })
  const initialConfig = component.data_config as DimensionFilterConfig
  const [datasetCode, setDatasetCode] = useState(component.dataset_code || "")
  const [fields, setFields] = useState<DimensionFilterField[]>(initialConfig.fields || [])
  const [linkedComponentIds, setLinkedComponentIds] = useState<string[]>(
    initialConfig.linkedComponentIds || []
  )

  useEffect(() => {
    setDatasetCode(component.dataset_code || "")
    setFields(initialConfig.fields || [])
    setLinkedComponentIds(initialConfig.linkedComponentIds || [])
  }, [component.id])

  const dataset = useMemo(
    () => datasets.find(item => item.dataset_code === datasetCode),
    [datasetCode, datasets]
  )
  const dimensions = dataset?.schema_config?.dimensions || []
  const selectableDimensions = useMemo(() => {
    const byField = new Map(
      dimensions.map((dimension: any) => [dimension.field, dimension])
    )
    const labelFields = new Set<string>()
    return dimensions
      .map((dimension: any) => {
        const field = String(dimension.field || "")
        const candidates = [
          field.endsWith("_id") ? `${field.slice(0, -3)}_name` : "",
          field.endsWith("_code") ? `${field.slice(0, -5)}_name` : "",
          `${field}_name`,
        ].filter(Boolean)
        const labelDimension = candidates
          .map(candidate => byField.get(candidate))
          .find(Boolean) as any
        if (labelDimension) labelFields.add(labelDimension.field)
        return {
          ...dimension,
          labelFieldId: labelDimension?.field,
          displayName: labelDimension?.name || dimension.name,
        }
      })
      .filter((dimension: any) => !labelFields.has(dimension.field))
  }, [dimensions])
  const targetCharts = (currentDashboard?.components || []).filter(target =>
    ![ChartType.Query, ChartType.DimensionFilter].includes(target.type)
    && target.dataset_code === datasetCode
  )

  const toggleField = (field: any) => {
    setFields(current => {
      const exists = current.some(item => item.fieldId === field.field)
      if (exists) {
        return current.filter(item => item.fieldId !== field.field)
      }
      if (current.length >= 6) return current
      return [
        ...current,
        {
          id: `${field.field}-${Date.now()}`,
          fieldId: field.field,
          labelFieldId: field.labelFieldId,
          fieldName: field.name,
          displayName: field.displayName,
          defaultValues: [],
        },
      ]
    })
  }

  const toggleTarget = (componentId: string) => {
    setLinkedComponentIds(current =>
      current.includes(componentId)
        ? current.filter(id => id !== componentId)
        : [...current, componentId]
    )
  }

  return (
    <div className="flex h-full w-[360px] flex-col border-l border-border bg-background">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold">维度筛选配置</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          最多选择 6 个维度；各维度之间按“且”自由组合。
        </p>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        <section className="space-y-2">
          <label className="text-sm font-medium">数据集</label>
          <Select
            value={datasetCode}
            onValueChange={value => {
              setDatasetCode(value)
              setFields([])
              setLinkedComponentIds([])
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder="选择数据集" />
            </SelectTrigger>
            <SelectContent>
              {datasets.map(item => (
                <SelectItem key={item.dataset_code} value={item.dataset_code}>
                  {item.dataset_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </section>

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">筛选维度</label>
            <span className="text-xs text-muted-foreground">{fields.length}/6</span>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto rounded-md border border-border p-2">
            {selectableDimensions.map((dimension: any) => {
              const checked = fields.some(field => field.fieldId === dimension.field)
              return (
                <label
                  key={dimension.field}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent/50"
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={() => toggleField(dimension)}
                  />
                  <span className="truncate" title={dimension.name}>
                    {dimension.name}
                  </span>
                </label>
              )
            })}
            {!dimensions.length && (
              <p className="py-4 text-center text-xs text-muted-foreground">
                请先选择数据集
              </p>
            )}
          </div>
        </section>

        <section className="space-y-2">
          <label className="text-sm font-medium">作用图表</label>
          <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border p-2">
            {targetCharts.map(target => (
              <label
                key={target.id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent/50"
              >
                <Checkbox
                  checked={linkedComponentIds.includes(target.id)}
                  onCheckedChange={() => toggleTarget(target.id)}
                />
                <span className="truncate" title={target.title}>
                  {target.title || "未命名图表"}
                </span>
              </label>
            ))}
            {!targetCharts.length && (
              <p className="py-4 text-center text-xs text-muted-foreground">
                当前数据集暂无可关联图表
              </p>
            )}
          </div>
        </section>
      </div>

      <div className="flex gap-2 border-t border-border p-4">
        <Button
          className="flex-1"
          variant="outline"
          onClick={onCancel}
        >
          取消
        </Button>
        <Button
          className="flex-1"
          disabled={!datasetCode || fields.length === 0}
          onClick={() => onSave(datasetCode, { fields, linkedComponentIds })}
        >
          更新筛选预览
        </Button>
      </div>
    </div>
  )
}
