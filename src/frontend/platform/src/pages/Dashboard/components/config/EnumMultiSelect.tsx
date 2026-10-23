import { Input } from '@bisheng/ui';
import { showApiError } from "@/controllers/request";
import { Outlined } from "bisheng-icons";
import { useCallback,useEffect,useMemo,useRef,useState } from "react";



import { getFieldEnums } from "@/controllers/API/dashboard";
import { Checkbox,Tag } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
interface EnumMultiSelectProps {
  fieldCode: string
  selected: string[]
  onChange: (selected: string[]) => void
  placeholder?: string
  dataset_code: string
}

export function EnumMultiSelect({
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
  const pageSize = 20
  const [searchMode, setSearchMode] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)
  const [, setFetchedValues] = useState<string[]>([])

  const searchRef = useRef(search)
  const translationRef = useRef(t)
  translationRef.current = t
  const fetchEnumValues = useCallback(async (code: string, pageNum = 1, searchText = "") => {
    const isSearch = !!searchText.trim()
    const currentLoading = isSearch ? setSearchLoading : setLoading

    currentLoading(true)
    try {
      const response = await getFieldEnums({
        dataset_code,
        field: code,
        page: pageNum,
        pageSize,
        keyword: searchText
      })
      const result = response.enums || []

      if (pageNum === 1) {
        setValues(result)
        if (searchText) {
          setFetchedValues(result)
        }
      } else {
        setValues(prev => {
          const newValues = [...prev, ...result]
          if (searchText) {
            setFetchedValues(newValues)
          }
          return newValues
        })
      }
      setHasMore(result.length === pageSize)

      if (isSearch) {
        setSearchMode(true)
      }
    } catch (error) {
      showApiError(error)
    } finally {
      currentLoading(false)
    }
  }, [dataset_code])

  const handleSearch = useCallback((searchText: string) => {
    setSearch(searchText)
    searchRef.current = searchText
    if (searchText.trim()) {
      setPage(1)
      setFetchedValues([])
      fetchEnumValues(fieldCode, 1, searchText)
    } else {
      setSearchMode(false)
      setPage(1)
      setFetchedValues([])
      fetchEnumValues(fieldCode, 1, "")
    }
  }, [fieldCode, fetchEnumValues])

  useEffect(() => {
    if (isOpen && fieldCode && dataset_code && !searchRef.current) {
      setPage(1)
      fetchEnumValues(fieldCode, 1, "")
    }
  }, [isOpen, fieldCode, dataset_code, fetchEnumValues])

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const element = e.currentTarget
    const isAtBottom = element.scrollHeight - element.scrollTop <= element.clientHeight + 10

    if (isAtBottom && hasMore && !loading && !searchLoading) {
      const nextPage = page + 1
      setPage(nextPage)
      fetchEnumValues(fieldCode, nextPage, search)
    }
  }, [hasMore, loading, searchLoading, page, fieldCode, fetchEnumValues, search])

  const filteredValues = useMemo(() => {
    if (!search.trim()) return values
    return values.filter(value =>
      value.toLowerCase().includes(search.toLowerCase())
    )
  }, [values, search])

  const allSelected = useMemo(() => {
    const currentValues = filteredValues
    return currentValues.length > 0 && currentValues.every(val => selected.includes(val))
  }, [selected, filteredValues])
  const handleToggleAll = () => {
    const currentValues = filteredValues

    if (currentValues.length === 0) return

    const allSelected = currentValues.every(val => selected.includes(val))

    if (allSelected) {

      const newSelected = selected.filter(val => !currentValues.includes(val))
      onChange(newSelected)
    } else {

      const valuesToAdd = currentValues.filter(val => !selected.includes(val))
      const newSelected = [...selected, ...valuesToAdd]
      onChange(newSelected)
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
    searchRef.current = ""
    if (searchMode) {
      setPage(1)
      fetchEnumValues(fieldCode, 1, "")
      setSearchMode(false)
    }
  }

  return (
    <div className="relative flex-1">
      <div
        className="w-full min-h-8 border border-input bg-background rounded-md flex items-center justify-between px-3 py-1 cursor-pointer hover:bg-accent hover:text-accent-foreground"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex flex-1 min-h-0 overflow-hidden mr-2">
          {selected.length > 0 ? (
            <div className="flex-1 overflow-y-auto" style={{ maxHeight: '80px' }}>
              <div className="flex flex-wrap gap-1 py-0.5">
                {selected.map(value => (
                  <Tag size="small" key={value} closable maxWidth={112}
                    closeLabel={t('removeSelectedValue', { value })}
                    onClose={e => handleRemoveTag(value, e)}>{value}</Tag>
                ))}
              </div>
            </div>
          ) : (
            <span className="text-sm text-gray-500 py-0.5">{placeholder || t('filterConditionDialog.enumSelect.placeholder')}</span>
          )}
        </div>
        <Outlined.Down className={`h-4 w-4 transition-transform flex-shrink-0 ${isOpen ? "rotate-180" : ""}`} />
      </div>

      {isOpen && (
        <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg top-full">
          <div className="p-2 border-b">
            <div className="relative">
              <Input placeholder={t('filterConditionDialog.enumSelect.searchPlaceholder')} value={search} onChange={e => handleSearch(e.target.value)} onClick={e => e.stopPropagation()} className={"h-8 pr-8"} />
              {search && (
                <Outlined.Close
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
                    <Checkbox aria-label={t("chartSelector.selectAll")} checked={allSelected} />
                    <span className="text-sm">{allSelected ? t("chartSelector.unSelectAll") : t("chartSelector.selectAll")}</span>
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
                        <Checkbox aria-label={value} checked={selected.includes(value)} />
                        <span className="text-sm">{value}</span>
                      </div>
                    ))}
                    {(loading || searchLoading) && page > 1 && (
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
