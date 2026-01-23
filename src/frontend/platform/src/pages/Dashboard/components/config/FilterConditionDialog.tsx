"use client"

import { useEffect, useState, useMemo, useCallback } from "react"
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
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Badge } from "@/components/bs-ui/badge"
import { generateUUID } from "@/components/bs-ui/utils"
import { getFieldEnums } from "@/controllers/API/dashboard"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { useTranslation } from "react-i18next"

/* ================== 类型定义 ================== */
export type LogicOperator = "and" | "or"
export type FieldType = "string" | "number"
// FilterOperator
export type FilterOperator =
  | "equals"
  | "not_equals"
  | "contains"
  | "not_contains"
  | "greater_than"
  | "greater_than_or_equal"
  | "less_than"
  | "less_than_or_equal"
  | "is_empty"
  | "is_not_empty"
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
  fieldId?: string
  fieldName?: string
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
  dataset_code?: string
}

/* ================== 工具函数 ================== */
const createEmptyCondition = (): FilterCondition => ({
  id: generateUUID(6),
})

const operatorNeedsValue = (op?: FilterOperator) =>
  !op || !["is_empty", "is_not_empty"].includes(op)

const isEnumOperator = (op?: FilterOperator) =>
  op === "enum_in" || op === "enum_not_in"

/* ================== 枚举多选组件 (调用接口版本) ================== */
interface EnumMultiSelectProps {
  fieldCode: string
  selected: string[]
  onChange: (selected: string[]) => void
  placeholder?: string
  dataset_code: string
}

function EnumMultiSelect({
  fieldCode,
  selected,
  onChange,
  placeholder = "",
  dataset_code
}: EnumMultiSelectProps) {
  const { t } = useTranslation("dashboard")
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [values, setValues] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const pageSize = 100

  const fetchEnumValues = async (code: string, pageNum = 1) => {
    setLoading(true)
    try {
      const response = await getFieldEnums({
        dataset_code,
        field: code,
        page: pageNum,
        pageSize
      })
      const result = response.enums || []
      if (pageNum === 1) {
        setValues(result)
      } else {
        setValues(prev => [...prev, ...result])
      }

      setHasMore(result.length === pageSize)
    } catch (error) {
      console.error("获取枚举值失败:", error)
      toast({
        description: t('filterConditionDialog.toast.fetchEnumFailed'),
        variant: "error"
      })
      setValues([])
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    if (isOpen && fieldCode && dataset_code) {
      setPage(1)
      fetchEnumValues(fieldCode, 1)
    }
  }, [isOpen, fieldCode, dataset_code])
  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const element = e.currentTarget
    const isAtBottom = element.scrollHeight - element.scrollTop === element.clientHeight

    if (isAtBottom && hasMore && !loading) {
      const nextPage = page + 1
      setPage(nextPage)
      fetchEnumValues(fieldCode, nextPage)
    }
  }, [hasMore, loading, page, fieldCode, dataset_code])
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
  const handleClearSearch = () => {
    setSearch("")
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
            <span className="text-muted-foreground">{placeholder || t('filterConditionDialog.enumSelect.placeholder')}</span>
          )}
        </div>
        <ChevronDown className={`h-4 w-4 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </Button>

      {isOpen && (
        <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg">
          <div className="p-2 border-b">
            <div className="relative">
              <Input
                placeholder={t('filterConditionDialog.enumSelect.searchPlaceholder')}
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="h-8 pr-8"
                onClick={e => e.stopPropagation()}
              />
              {search && (
                <X
                  className="absolute right-2 top-1/2 transform -translate-y-1/2 h-4 w-4 cursor-pointer text-muted-foreground"
                  onClick={handleClearSearch}
                />
              )}
            </div>
          </div>

          {loading && page === 1 ? (
            <div className="px-3 py-4 text-sm text-muted-foreground text-center">
              {t('filterConditionDialog.enumSelect.loading')}
            </div>
          ) : (
            <>
              {values.length > 0 && (
                <div className="px-3 py-2 border-b">
                  <div className="flex items-center space-x-2 cursor-pointer" onClick={handleToggleAll}>
                    <Checkbox checked={allSelected} />
                    <span className="text-sm">{t('filterConditionDialog.enumSelect.selectAll')}</span>
                  </div>
                </div>
              )}

              <div
                className="max-h-60 overflow-auto"
                onScroll={handleScroll}
              >
                {filteredValues.length > 0 ? (
                  <>
                    {filteredValues.map(value => (
                      <div
                        key={value}
                        className="flex items-center space-x-2 px-3 py-2 hover:bg-muted cursor-pointer"
                        onClick={() => handleToggleValue(value)}
                      >
                        <Checkbox checked={selected.includes(value)} />
                        <span className="text-sm">{value}</span>
                      </div>
                    ))}
                    {loading && page > 1 && (
                      <div className="px-3 py-2 text-sm text-muted-foreground text-center">
                        {t('filterConditionDialog.enumSelect.loadingMore')}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="px-3 py-2 text-sm text-muted-foreground text-center">
                    {search ? t('filterConditionDialog.enumSelect.noMatch') : t('filterConditionDialog.enumSelect.noData')}
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
  fields,
  dataset_code = "",
  dimensions = []
}: Props) {
  const { t } = useTranslation("dashboard")
  const [draft, setDraft] = useState<FilterGroup>({
    logic: "and",
    conditions: [createEmptyCondition()]
  })
  const [initialized, setInitialized] = useState(false)

  const [error, setError] = useState<string | null>(null)
  const getFieldDisplayName = useCallback((fieldCode: string) => {
    const dimension = dimensions.find(dim =>
      dim.fieldId === fieldCode || dim.name === fieldCode
    );

    if (dimension?.displayName) {
      return dimension.displayName;
    }

    // const field = fields.find(f => f.fieldCode === fieldCode);
    return t(fieldCode) || t('filterConditionDialog.placeholders.noName');
  }, [dimensions, fields, t]);
  // 过滤掉时间字段
  const filteredFields = useMemo(() => {
    console.log('原始字段数据:', fields)
    if (!dataset_code || !dimensions || !fields) return []

    return fields.filter(field => {
      if (!field || !field.fieldCode || !field.displayName) {
        console.log('发现无效字段:', field)
        return false
      }
      if (field.isVirtual === true) {
        console.log('过滤虚拟指标:', field.displayName)
        return false
      }
      const lowerCode = field.fieldCode.toLowerCase()
      const lowerName = field.displayName.toLowerCase()
      console.log('检查字段:', field.displayName, 'lowerCode:', lowerCode, 'lowerName:', lowerName)

      // 检查是否包含时间相关关键词
      const isTimeField = lowerCode.includes('time') ||
        lowerCode.includes('date') ||
        lowerName.includes(t('filterConditionDialog.keywords.time')) ||
        lowerName.includes(t('filterConditionDialog.keywords.date'))

      return !isTimeField
    })
  }, [fields, dimensions, dataset_code, t])
  useEffect(() => {
    setInitialized(false)
    setDraft({
      logic: "and",
      conditions: [createEmptyCondition()]
    })
  }, [dataset_code])
  useEffect(() => {
    if (!open) return
    if (fields.length === 0) return

    const safeValue = value || { logic: "and", conditions: [] }

    const newConditions = (safeValue.conditions || []).map(c => {
      let fieldCode = c.fieldCode

      if (!fieldCode && c.fieldId) {
        const field = fields.find(f => f.fieldCode === c.fieldId || f.fieldId === c.fieldId)
        fieldCode = field?.fieldCode || c.fieldId
      }

      const field = fields.find(f => f.fieldCode === fieldCode)
      const isEnum = field?.isEnum || (field?.enumValues?.length > 0)

      let operator: FilterOperator
      if (c.operator) operator = c.operator
      else if (isEnum) operator = "in"  // 修改这里：枚举筛选用 "in"
      else if (field?.fieldType === "string") operator = "equals"
      else operator = "equals"

      // 处理空值操作符的回显
      let valueToSet = c.value ?? (isEnum ? [] : "")

      // 如果是空值操作符，不需要值
      if (c.operator && ["is_empty", "is_not_empty"].includes(c.operator)) {
        valueToSet = ""
      }

      return {
        id: c.id ?? generateUUID(6),
        fieldCode: fieldCode ?? "",
        fieldId: c.fieldId,
        fieldType: field?.fieldType,
        fieldName: field?.displayName,
        operator,
        value: valueToSet,
        filterType: c.filterType || (isEnum ? "enum" : "conditional")
      }
    })

    setDraft({
      logic: safeValue.logic ?? "and",
      conditions: newConditions.length > 0 ? newConditions : [createEmptyCondition()]
    })
    setError(null)
  }, [open, value, fields])




  const isEnumField = useCallback((fieldCode: string) => {
    const field = fields.find(f => f.fieldCode === fieldCode)
    return !!field?.isEnum || (field?.enumValues?.length > 0)
  }, [fields])


  const validate = (): boolean => {
    for (const c of draft.conditions) {
      if (draft.conditions.length === 0) {
        return true
      }
      if (!c.fieldCode) {
        // setError(t('filterConditionDialog.errors.selectField'))
        return true
      }

      if (!c.operator) {
        setError(t('filterConditionDialog.errors.selectOperator'))
        return false
      }

      if (operatorNeedsValue(c.operator)) {
        if (c.filterType === "enum") {
          if (!Array.isArray(c.value) || c.value.length === 0) {
            setError(t('filterConditionDialog.errors.selectEnumValue'))
            return false
          }
        } else {
          if (c.value === undefined || c.value === "") {
            setError(t('filterConditionDialog.errors.enterFilterValue'))
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
        conditions: [createEmptyCondition()]
      }
    })
  }
  const handleFieldChange = (id: string, fieldCode: string) => {
    const field = filteredFields.find(f => f.fieldCode === fieldCode)
    const isEnum = isEnumField(fieldCode)

    let defaultOperator: FilterOperator
    let defaultFilterType: "conditional" | "enum"

    if (isEnum) {
      defaultFilterType = "enum"
      defaultOperator = "in"
    } else {
      defaultFilterType = "conditional"
      defaultOperator = "equals"
    }

    updateCondition(id, {
      fieldCode,
      fieldType: field?.fieldType,
      fieldId: field?.fieldId || fieldCode,
      fieldName: field?.displayName,
      filterType: defaultFilterType,
      operator: defaultOperator,
      value: isEnum ? [] : ""
    })
  }
  const handleFilterTypeChange = (id: string, filterType: "conditional" | "enum") => {
    const condition = draft.conditions.find(c => c.id === id)
    if (!condition || !condition.fieldCode) return

    const isEnum = filterType === "enum"

    updateCondition(id, {
      filterType,
      value: isEnum ? [] : condition.value,
      operator: condition.operator ?? (isEnum ? "enum_in" : "equals")
    })
  }


  const handleOperatorChange = (id: string, operator: FilterOperator) => {
    const condition = draft.conditions.find(c => c.id === id)
    const isEnum = condition?.filterType === "enum"

    if (isEnum) {
      updateCondition(id, { operator, value: [] })
    } else {
      if (!operatorNeedsValue(operator)) {
        updateCondition(id, { operator, value: "" })
      } else {
        updateCondition(id, { operator, value: condition?.value || "" })
      }
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

    // if (validConditions.length === 0) {
    //   setError(t('filterConditionDialog.errors.atLeastOneCondition'))
    //   return
    // }
    if (validConditions.length === 0) {
      onChange({
        logic: "and",
        conditions: []
      })
      toast({
        description: t('filterConditionDialog.toast.saveSuccess'),
        variant: "success"
      })
      onOpenChange(false)
      return
    }
    // 确保返回的数据结构正确

    const transformedConditions = draft.conditions
      .filter(c => c.fieldCode && c.value !== undefined)
      .map(c => {
        // 如果是枚举筛选，直接使用 "in"
        if (c.filterType === "enum") {
          return {
            id: c.id,
            fieldId: c.fieldId,
            fieldCode: c.fieldCode,
            fieldName: c.fieldName,
            operator: "in", // 枚举筛选固定用 in
            value: c.value,
            filterType: c.filterType
          }
        }

        // 条件筛选：使用用户选择的操作符
        return {
          id: c.id,
          fieldId: c.fieldId,
          fieldCode: c.fieldCode,
          fieldName: c.fieldName,
          operator: c.operator, // 使用用户选择的操作符
          value: c.value,
          filterType: c.filterType
        }
      })

    console.log('保存的条件:', transformedConditions)

    onChange({
      logic: draft.logic,
      conditions: transformedConditions
    })
    toast({
      description: t('filterConditionDialog.toast.saveSuccess'),
      variant: "success"
    })

    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[900px] max-h-[70vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('filterConditionDialog.title')}</DialogTitle>
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
            {draft.conditions.length > 0 ? (
              draft.conditions.map((c, index) => {
                return (
                  <div key={c.id} className="relative group">
                    <div className="flex items-center gap-2 p-2">
                      {/* 第一个下拉框：选择字段 */}
                      <Select
                        value={c.fieldCode}
                        onValueChange={v => handleFieldChange(c.id, v)}
                      >
                        <SelectTrigger className="w-[160px] h-8">
                          <SelectValue placeholder={t('filterConditionDialog.placeholders.selectField')} />
                        </SelectTrigger>
                        <SelectContent className=" overflow-y-auto w-[160px]">
                          {filteredFields.length > 0 ? (
                            filteredFields.map(f => {
                              const displayText = getFieldDisplayName(f.fieldCode) || "暂无";
                              return (
                                <SelectItem key={f.fieldCode} value={f.fieldCode} className="truncate">
                                  <span className="truncate block w-[80px]" title={displayText}>
                                    {displayText}
                                  </span>
                                </SelectItem>
                              )
                            })
                          ) : (
                            <div className="px-2 py-4 text-sm text-muted-foreground text-center">
                              {t('filterConditionDialog.filterTypes.noFields')}
                            </div>
                          )}
                        </SelectContent>
                      </Select>

                      {/* 第二个下拉框：筛选类型 */}
                      {c.fieldCode && (
                        <Select
                          value={c.filterType}
                          onValueChange={v => handleFilterTypeChange(c.id, v as "conditional" | "enum")}
                        >
                          <SelectTrigger className="w-[100px] h-8">
                            <SelectValue placeholder={t('filterConditionDialog.placeholders.filterType')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="conditional">{t('filterConditionDialog.filterTypes.conditional')}</SelectItem>
                            {c.fieldType !== "number" && <SelectItem value="enum">{t('filterConditionDialog.filterTypes.enum')}</SelectItem>}
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
                            <SelectTrigger className="w-[160px] h-8">
                              <SelectValue placeholder={t('filterConditionDialog.placeholders.operator')} />
                            </SelectTrigger>
                            <SelectContent>
                              {c.fieldType === "string" ? (
                                <>
                                  <SelectItem value="equals">{t('filterConditionDialog.operators.equals')}</SelectItem>
                                  <SelectItem value="not_equals">{t('filterConditionDialog.operators.notEquals')}</SelectItem>
                                  <SelectItem value="contains">{t('filterConditionDialog.operators.contains')}</SelectItem>
                                  <SelectItem value="not_contains">{t('filterConditionDialog.operators.notContains')}</SelectItem>
                                  <SelectItem value="is_empty">{t('filterConditionDialog.operators.isEmpty')}</SelectItem>
                                  <SelectItem value="is_not_empty">{t('filterConditionDialog.operators.isNotEmpty')}</SelectItem>
                                </>
                              ) : c.fieldType === "number" ? (
                                <>
                                  <SelectItem value="equals">{t('filterConditionDialog.operators.equals')}</SelectItem>
                                  <SelectItem value="not_equals">{t('filterConditionDialog.operators.notEquals')}</SelectItem>
                                  <SelectItem value="greater_than">{t('filterConditionDialog.operators.greaterThan')}</SelectItem>
                                  <SelectItem value="greater_than_or_equal">{t('filterConditionDialog.operators.greaterThanOrEqual')}</SelectItem>
                                  <SelectItem value="less_than">{t('filterConditionDialog.operators.lessThan')}</SelectItem>
                                  <SelectItem value="less_than_or_equal">{t('filterConditionDialog.operators.lessThanOrEqual')}</SelectItem>
                                  <SelectItem value="is_empty">{t('filterConditionDialog.operators.isEmpty')}</SelectItem>
                                  <SelectItem value="is_not_empty">{t('filterConditionDialog.operators.isNotEmpty')}</SelectItem>
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
                                  placeholder={t('filterConditionDialog.placeholders.enterNumber')}
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
                                  placeholder={t('filterConditionDialog.placeholders.enterValue')}
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
                            dataset_code={dataset_code}
                            fieldCode={c.fieldCode}
                            selected={(c.value as string[]) || []}
                            onChange={selected => updateCondition(c.id, { value: selected })}
                            placeholder={t('filterConditionDialog.placeholders.selectEnumValue')}
                          />
                        </div>
                      )}

                      {/* 删除按钮 */}
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => removeCondition(c.id)}
                        className="flex-shrink-0 h-8 w-8 group-hover:opacity-100 opacity-0"
                      >
                        <Trash2 className="h-4 w-4 hover:text-red-600 cursor-pointer" />
                      </Button>
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="text-center py-4 text-muted-foreground">
              </div>
            )}
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
            {t('filterConditionDialog.buttons.addCondition')}
          </Button>
        </div>

        {/* 错误提示 */}
        {error && <div className="text-sm text-destructive">{error}</div>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('filterConditionDialog.buttons.cancel')}
          </Button>
          <Button onClick={handleSave}>
            {t('filterConditionDialog.buttons.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}