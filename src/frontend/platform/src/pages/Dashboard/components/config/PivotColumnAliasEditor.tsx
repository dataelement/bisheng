"use client"

import { Input } from "@/components/bs-ui/input"
import { getFieldEnums } from "@/controllers/API/dashboard"
import type { PivotColumnAliases } from "../../types/dataConfig"
import { useDeferredValue, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { useQuery } from "react-query"

interface PivotStackDimension {
  fieldId: string
  name: string
}

interface PivotColumnAliasEditorProps {
  datasetCode?: string
  stackDimension?: PivotStackDimension
  value?: PivotColumnAliases
  onChange: (value?: PivotColumnAliases) => void
}

export function PivotColumnAliasEditor({
  datasetCode,
  stackDimension,
  value,
  onChange,
}: PivotColumnAliasEditorProps) {
  const { t } = useTranslation("dashboard")
  const [search, setSearch] = useState("")
  const deferredSearch = useDeferredValue(search.trim().toLowerCase())
  const aliases = value?.fieldId === stackDimension?.fieldId
    ? value.aliases
    : {}

  const { data: enumValues = [], isLoading } = useQuery({
    queryKey: [
      "pivotColumnAliasValues",
      datasetCode,
      stackDimension?.name,
    ],
    queryFn: async () => {
      const response = await getFieldEnums({
        dataset_code: datasetCode!,
        field: stackDimension!.name,
        page: 1,
        pageSize: 200,
      })
      const options = Array.isArray(response.options)
        ? response.options.map((option: { value: unknown }) => String(option.value))
        : []
      const enums = Array.isArray(response.enums)
        ? response.enums.map(String)
        : []
      return Array.from(new Set([...options, ...enums]))
    },
    enabled: Boolean(datasetCode && stackDimension?.name),
    staleTime: 30_000,
  })

  const visibleValues = useMemo(() => {
    const values = Array.from(new Set([
      ...Object.keys(aliases),
      ...enumValues,
    ]))
    if (!deferredSearch) return values
    return values.filter(item => item.toLowerCase().includes(deferredSearch))
  }, [aliases, deferredSearch, enumValues])

  const handleAliasChange = (originalName: string, alias: string) => {
    if (!stackDimension) return
    const nextAliases = { ...aliases }
    if (alias.trim() && alias.trim() !== originalName) {
      nextAliases[originalName] = alias
    } else {
      delete nextAliases[originalName]
    }
    onChange({
      fieldId: stackDimension.fieldId,
      aliases: nextAliases,
    })
  }

  if (!stackDimension) return null

  return (
    <div className="mt-2 space-y-2 rounded-md border bg-muted/20 p-2">
      <div className="text-xs font-medium">
        {t("componentConfigDrawer.pivotColumnAliases.title")}
      </div>
      <div className="text-xs text-muted-foreground">
        {t("componentConfigDrawer.pivotColumnAliases.description")}
      </div>
      <Input
        value={search}
        onChange={event => setSearch(event.target.value)}
        placeholder={t("componentConfigDrawer.pivotColumnAliases.search")}
        className="h-8"
      />
      <div className="max-h-56 space-y-1 overflow-auto">
        {isLoading ? (
          <div className="py-3 text-center text-xs text-muted-foreground">
            {t("componentConfigDrawer.pivotColumnAliases.loading")}
          </div>
        ) : visibleValues.length === 0 ? (
          <div className="py-3 text-center text-xs text-muted-foreground">
            {t("componentConfigDrawer.pivotColumnAliases.empty")}
          </div>
        ) : visibleValues.map(originalName => (
          <div
            key={originalName}
            className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-2"
          >
            <span
              className="truncate text-xs text-foreground"
              title={originalName}
            >
              {originalName}
            </span>
            <Input
              value={aliases[originalName] || ""}
              onChange={event => handleAliasChange(
                originalName,
                event.target.value,
              )}
              placeholder={t(
                "componentConfigDrawer.pivotColumnAliases.aliasPlaceholder",
              )}
              className="h-8"
              maxLength={30}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
