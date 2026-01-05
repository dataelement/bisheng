"use client"

import { useEffect, useState, useMemo } from "react"
import { Plus, Trash2, ChevronDown, X, RefreshCcw } from "lucide-react"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem
} from "@/components/bs-ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter
} from "@/components/bs-ui/dialog"
import { Checkbox } from "@/components/bs-ui/checkbox"
import { Badge } from "@/components/bs-ui/badge"

/* ================== 类型定义 ================== */
export type LogicOperator = "and" | "or"
export type FieldType = "string" | "number"
export type FilterOperator =
  | "eq"
  | "neq"
  | "contains"
  | "not_contains"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "is_null"
  | "not_null"
  | "enum_in"
  | "enum_not_in"

export interface DatasetField {
  fieldCode: string
  displayName: string
  fieldType: FieldType
  role: "dimension" | "metric"
  enumValues?: string[]
  isEnum?: boolean
}

export interface FilterCondition {
  id: string
  fieldCode?: string
  fieldType?: FieldType
  operator?: FilterOperator
  value?: string | number | string[]
  filterType?: "conditional" | "enum"
}

export interface FilterGroup {
  logic: LogicOperator
  conditions: FilterCondition[]
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  value: FilterGroup | null
  onChange: (value: FilterGroup) => void
  fields: DatasetField[]
}

/* ================== 工具函数 ================== */
const createEmptyCondition = (): FilterCondition => ({
  id: crypto.randomUUID()
})

const operatorNeedsValue = (op?: FilterOperator) =>
  !op || !["is_null", "not_null"].includes(op)

const isEnumOperator = (op?: FilterOperator) =>
  op === "enum_in" || op === "enum_not_in"

/* ================== 枚举多选组件 (调用接口版本) ================== */
interface EnumMultiSelectProps {
  fieldCode: string
  selected: string[]
  onChange: (selected: string[]) => void
  placeholder?: string
}

function EnumMultiSelect({
  fieldCode,
  selected,
  onChange,
  placeholder = "请选择"
}: EnumMultiSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [values, setValues] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  const fetchEnumValues = async (code: string) => {
    setLoading(true)
    try {
      await new Promise(resolve => setTimeout(resolve, 300))
      const mockData: Record<string, string[]> = {
        "category": ["电子产品", "服装", "食品", "图书", "家居"],
        "status": ["进行中", "已完成", "已取消", "待处理"],
        "priority": ["高", "中", "低"],
        "region": ["华北", "华东", "华南", "华中", "西北", "西南", "东北"]
      }
      setValues(mockData[code] || ["选项1", "选项2", "选项3"])
    } catch (error) {
      console.error("获取枚举值失败:", error)
      setValues([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen && fieldCode) {
      fetchEnumValues(fieldCode)
    }
  }, [isOpen, fieldCode])

  const filteredValues = useMemo(() => {
    if (!search.trim()) return values
    return values.filter(value =>
      value.toLowerCase().includes(search.toLowerCase())
    )
  }, [values, search])

  const allSelected = selected.length === values.length && values.length > 0
  const handleToggleAll = () => {
    if (allSelected) {
      onChange([])
    } else {
      onChange([...values])
    }
  }

  const handleToggleValue = (value: string) => {
    const newSelected = selected.includes(value)
      ? selected.filter(v => v !== value)
      : [...selected, value]
    onChange(newSelected)
  }

  const handleRemoveTag = (value: string, e: React.MouseEvent) => {
    e.stopPropagation()
    onChange(selected.filter(v => v !== value))
  }

  return (
    <div className="relative flex-1">
      <Button
        type="button"
        variant="outline"
        className="w-full h-8 justify-between px-3"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex flex-wrap flex-1 gap-1 overflow-hidden">
          {selected.length > 0 ? (
            selected.map(value => (
              <Badge
                key={value}
                variant="secondary"
                className="flex items-center gap-1 px-2 py-0 text-xs h-5"
              >
                {value}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={e => handleRemoveTag(value, e)}
                />
              </Badge>
            ))
          ) : (
            <span className="text-muted-foreground">{placeholder}</span>
          )}
        </div>
        <ChevronDown className={`h-4 w-4 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </Button>

      {isOpen && (
        <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg">
          <div className="p-2 border-b">
            <Input
              placeholder="搜索..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="h-8"
              onClick={e => e.stopPropagation()}
            />
          </div>

          {loading ? (
            <div className="px-3 py-4 text-sm text-muted-foreground text-center">
              加载中...
            </div>
          ) : (
            <>
              <div className="px-3 py-2 border-b">
                <div className="flex items-center space-x-2 cursor-pointer" onClick={handleToggleAll}>
                  <Checkbox checked={allSelected} />
                  <span className="text-sm">全选</span>
                </div>
              </div>

              <div className="max-h-60 overflow-auto">
                {filteredValues.length > 0 ? (
                  filteredValues.map(value => (
                    <div
                      key={value}
                      className="flex items-center space-x-2 px-3 py-2 hover:bg-muted cursor-pointer"
                      onClick={() => handleToggleValue(value)}
                    >
                      <Checkbox checked={selected.includes(value)} />
                      <span className="text-sm">{value}</span>
                    </div>
                  ))
                ) : (
                  <div className="px-3 py-2 text-sm text-muted-foreground text-center">
                    暂无数据
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {isOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setIsOpen(false)}
        />
      )}
    </div>
  )
}

/* ================== 主组件 ================== */
export function FilterConditionDialog({
  open,
  onOpenChange,
  value,
  onChange,
  fields
}: Props) {
  const [draft, setDraft] = useState<FilterGroup>({
    logic: "and",
    conditions: [createEmptyCondition()]
  })
  const [error, setError] = useState<string | null>(null)

  // 过滤掉时间字段
  const filteredFields = useMemo(() => {
    return fields.filter(field => {
      const lowerCode = field.fieldCode.toLowerCase()
      const lowerName = field.displayName.toLowerCase()
      return !lowerCode.includes('time') && 
             !lowerCode.includes('date') && 
             !lowerName.includes('时间') && 
             !lowerName.includes('日期')
    })
  }, [fields])

  useEffect(() => {
    if (open) {
      const safeValue = value || { logic: "and", conditions: [] }
      const safeConditions = Array.isArray(safeValue.conditions) 
        ? safeValue.conditions 
        : []
      
      setDraft({
        logic: safeValue.logic ?? "and",
        conditions: safeConditions.length > 0 ? safeConditions : [createEmptyCondition()]
      })
      setError(null)
    }
  }, [open, value])

  const isEnumField = (fieldCode: string): boolean => {
    const field = filteredFields.find(f => f.fieldCode === fieldCode)
    return !!field?.isEnum || (field?.enumValues && field.enumValues.length > 0)
  }

  const validate = (): boolean => {
    for (const c of draft.conditions) {
      if (!c.fieldCode) {
        setError("请选择字段")
        return false
      }
      
      if (!c.operator) {
        setError("请选择操作符")
        return false
      }
      
      if (operatorNeedsValue(c.operator)) {
        if (c.filterType === "enum") {
          if (!Array.isArray(c.value) || c.value.length === 0) {
            setError("请选择枚举值")
            return false
          }
        } else {
          if (c.value === undefined || c.value === "") {
            setError("请填写筛选值")
            return false
          }
        }
      }
    }
    setError(null)
    return true
  }

  const updateCondition = (id: string, patch: Partial<FilterCondition>) => {
    setDraft(prev => ({
      ...prev,
      conditions: prev.conditions.map(c => (c.id === id ? { ...c, ...patch } : c))
    }))
  }

  const addCondition = () => {
    setDraft(prev => ({
      ...prev,
      conditions: [...prev.conditions, createEmptyCondition()]
    }))
  }

  const removeCondition = (id: string) => {
    setDraft(prev => {
      const newConditions = prev.conditions.filter(c => c.id !== id)
      return {
        ...prev,
        conditions: newConditions.length === 0 ? [createEmptyCondition()] : newConditions
      }
    })
  }

  const handleFieldChange = (id: string, fieldCode: string) => {
    const field = filteredFields.find(f => f.fieldCode === fieldCode)
    const isEnum = isEnumField(fieldCode)
    
    let defaultOperator: FilterOperator
    if (isEnum) {
      defaultOperator = "enum_in"
    } else if (field?.fieldType === "string") {
      defaultOperator = "eq"
    } else {
      defaultOperator = "eq"
    }
    
    updateCondition(id, {
      fieldCode,
      fieldType: field?.fieldType,
      filterType: isEnum ? "enum" : "conditional",
      operator: defaultOperator,
      value: isEnum ? [] : undefined
    })
  }

  const handleFilterTypeChange = (id: string, filterType: "conditional" | "enum") => {
    const condition = draft.conditions.find(c => c.id === id)
    if (!condition || !condition.fieldCode) return
    
    const field = filteredFields.find(f => f.fieldCode === condition.fieldCode)
    const isEnum = filterType === "enum"
    
    let defaultOperator: FilterOperator
    if (isEnum) {
      defaultOperator = "enum_in"
    } else if (field?.fieldType === "string") {
      defaultOperator = "eq"
    } else {
      defaultOperator = "eq"
    }
    
    updateCondition(id, {
      filterType,
      operator: defaultOperator,
      value: isEnum ? [] : undefined
    })
  }

  const handleOperatorChange = (id: string, operator: FilterOperator) => {
    const condition = draft.conditions.find(c => c.id === id)
    const isEnum = condition?.filterType === "enum"
    
    if (isEnum) {
      updateCondition(id, { operator, value: [] })
    } else {
      updateCondition(id, { operator, value: undefined })
    }
  }

  const handleToggleLogic = () => {
    setDraft(prev => ({
      ...prev,
      logic: prev.logic === "and" ? "or" : "and"
    }))
  }

  const handleSave = () => {
    if (!validate()) return
    
    const validConditions = draft.conditions.filter(c => c.fieldCode)
    
    if (validConditions.length === 0) {
      setError("请至少配置一个有效的筛选条件")
      return
    }
    
    // 确保返回的数据结构正确
    onChange({
      logic: draft.logic,
      conditions: validConditions.map(c => ({
        id: c.id,
        fieldCode: c.fieldCode,
        fieldType: c.fieldType,
        operator: c.operator,
        value: c.value,
        filterType: c.filterType
      }))
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[900px] max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>筛选条件配置</DialogTitle>
        </DialogHeader>

      <div className="relative">
        {/* 全局 AND / OR + 竖虚线 */}
        {draft.conditions.length > 1 && (
          <>
            {/* 完整的垂直虚线 - 从顶部横线到底部横线 */}
            <div className="absolute left-3 top-6 bottom-6 w-[1px] border-l border-dashed border-gray-300"></div>
            
            {/* 顶部横线 */}
            <div className="absolute left-3 top-6 w-3 h-[1px] border-t border-dashed border-gray-300"></div>
            
            {/* 底部横线 */}
            <div className="absolute left-3 bottom-6 w-3 h-[1px] border-t border-dashed border-gray-300"></div>

            {/* AND / OR徽章 */}
            <div className="absolute -left-4 top-1/2 -translate-y-1/2 z-10">
              <Badge
                variant="outline"
                className="px-2 py-1 text-xs cursor-pointer bg-[#E6ECF6] border-primary/30 text-primary"
                onClick={handleToggleLogic}
              >
                {draft.logic}
                <RefreshCcw size={10} className="ml-1" />
              </Badge>
            </div>
          </>
        )}

        <div className="space-y-4 pl-8">
          {/* 条件列表 */}
          {draft.conditions.map((c, index) => {
            return (
              <div key={c.id} className="relative group">
                <div className="flex items-center gap-2 p-2">
                  {/* 第一个下拉框：选择字段 */}
                  <Select
                    value={c.fieldCode}
                    onValueChange={v => handleFieldChange(c.id, v)}
                  >
                    <SelectTrigger className="w-[160px] h-8">
                      <SelectValue placeholder="选择字段" />
                    </SelectTrigger>
                    <SelectContent>
                      {filteredFields.map(f => (
                        <SelectItem key={f.fieldCode} value={f.fieldCode}>
                          {f.displayName}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* 第二个下拉框：筛选类型 */}
                  {c.fieldCode && (
                    <Select
                      value={c.filterType}
                      onValueChange={v => handleFilterTypeChange(c.id, v as "conditional" | "enum")}
                    >
                      <SelectTrigger className="w-[100px] h-8">
                        <SelectValue placeholder="筛选类型" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="conditional">条件筛选</SelectItem>
                        <SelectItem value="enum">枚举筛选</SelectItem>
                      </SelectContent>
                    </Select>
                  )}

                  {/* 条件筛选的操作符和值输入 */}
                  {c.fieldCode && c.filterType === "conditional" && (
                    <>
                      {/* 操作符 */}
                      <Select
                        value={c.operator}
                        onValueChange={v => handleOperatorChange(c.id, v as FilterOperator)}
                      >
                        <SelectTrigger className="w-[120px] h-8">
                          <SelectValue placeholder="操作符" />
                        </SelectTrigger>
                        <SelectContent>
                          {c.fieldType === "string" ? (
                            <>
                              <SelectItem value="eq">等于</SelectItem>
                              <SelectItem value="neq">不等于</SelectItem>
                              <SelectItem value="contains">包含</SelectItem>
                              <SelectItem value="not_contains">不包含</SelectItem>
                              <SelectItem value="is_null">为空</SelectItem>
                              <SelectItem value="not_null">不为空</SelectItem>
                            </>
                          ) : c.fieldType === "number" ? (
                            <>
                              <SelectItem value="eq">等于</SelectItem>
                              <SelectItem value="neq">不等于</SelectItem>
                              <SelectItem value="gt">大于</SelectItem>
                              <SelectItem value="gte">大于等于</SelectItem>
                              <SelectItem value="lt">小于</SelectItem>
                              <SelectItem value="lte">小于等于</SelectItem>
                              <SelectItem value="is_null">为空</SelectItem>
                              <SelectItem value="not_null">不为空</SelectItem>
                            </>
                          ) : null}
                        </SelectContent>
                      </Select>

                      {/* 值输入 */}
                      {c.operator && operatorNeedsValue(c.operator) && (
                        <>
                          {c.fieldType === "number" ? (
                            <Input
                              className="flex-1 min-w-[120px] h-8"
                              type="number"
                              step="any"
                              placeholder="请输入数值"
                              value={c.value ?? ""}
                              onChange={e =>
                                updateCondition(c.id, {
                                  value: e.target.value === "" ? "" : Number(e.target.value)
                                })
                              }
                            />
                          ) : (
                            <Input
                              className="flex-1 min-w-[120px] h-8"
                              type="text"
                              placeholder="请输入值"
                              value={c.value ?? ""}
                              onChange={e =>
                                updateCondition(c.id, {
                                  value: e.target.value
                                })
                              }
                            />
                          )}
                        </>
                      )}
                    </>
                  )}

                  {/* 枚举筛选的下拉选择框 */}
                  {c.fieldCode && c.filterType === "enum" && (
                    <div className="flex-1">
                      <EnumMultiSelect
                        fieldCode={c.fieldCode}
                        selected={(c.value as string[]) || []}
                        onChange={selected => updateCondition(c.id, { value: selected })}
                        placeholder="请选择枚举值"
                      />
                    </div>
                  )}

                  {/* 删除按钮 */}
                  {draft.conditions.length > 1 && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => removeCondition(c.id)}
                      className="flex-shrink-0 h-8 w-8 group-hover:opacity-100 opacity-0"
                    >
                      <Trash2 className="h-4 w-4 hover:text-red-600 cursor-pointer" />
                    </Button>
                  )}
                </div>
              </div>
            )
          })}

        
        </div>
      </div>
            {/* 添加条件按钮 */}
          <div>
            <Button 
              variant="outline" 
              className="border-primary text-primary hover:bg-primary/10 h-8"
              onClick={addCondition}
            >
              <Plus className="h-3 w-3 mr-1" />
              添加条件
            </Button>
          </div>

          {/* 错误提示 */}
          {error && <div className="text-sm text-destructive">{error}</div>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}