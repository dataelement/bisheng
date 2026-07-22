import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { Switch } from "@/components/bs-ui/switch"
import type {
  DeveloperTokenFileSyncDynamicSource,
  DeveloperTokenFileSyncMode,
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule as FileSyncRule,
} from "@/controllers/API/developerToken"
import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  changeFileSyncRuleMode,
  createEmptyFileSyncRule,
} from "./developerTokenFileSyncRuleValidation"

const UNSET_VALUE = "__unset__"

interface DeveloperTokenFileSyncRuleProps {
  value: FileSyncRule | null
  onChange: (value: FileSyncRule | null) => void
  options: DeveloperTokenFileSyncOptions | null
  loading: boolean
  error: string | null
  onSearchSpaces: (keyword: string) => void
}

export default function DeveloperTokenFileSyncRule({
  value,
  onChange,
  options,
  loading,
  error,
  onSearchSpaces,
}: DeveloperTokenFileSyncRuleProps) {
  const { t } = useTranslation()
  const [spaceKeyword, setSpaceKeyword] = useState("")
  const selectedCategory = useMemo(
    () => options?.categories.find((item) => item.code === value?.category.code),
    [options, value?.category.code]
  )
  const selectedChildren = selectedCategory?.children || []
  const categoryOptionMissing = Boolean(value?.category.code && !selectedCategory)
  const subcategoryOptionMissing = Boolean(
    value?.category.subcategory_code
      && !selectedChildren.some((item) => item.code === value.category.subcategory_code)
  )
  const categoryStale = Boolean(
    value
      && options
      && (categoryOptionMissing || subcategoryOptionMissing)
  )
  const businessOptionMissing = Boolean(
    value?.business_domain.mode === "fixed"
      && value.business_domain.code
      && !options?.business_domains.some((item) => item.code === value.business_domain.code)
  )
  const businessStale = Boolean(businessOptionMissing && options)
  const targetOptionMissing = Boolean(
    value?.target_space.mode === "fixed"
      && value.target_space.knowledge_id
      && !options?.knowledge_spaces.data.some((item) => item.id === value.target_space.knowledge_id)
  )
  const targetStale = Boolean(
    targetOptionMissing
      && options
      && options.knowledge_spaces.total <= options.knowledge_spaces.data.length
      && !spaceKeyword.trim()
  )
  const hasDynamicDimension = Boolean(
    value
      && (value.business_domain.mode === "dynamic" || value.target_space.mode === "dynamic")
  )

  const handleEnabledChange = (enabled: boolean) => {
    onChange(enabled ? createEmptyFileSyncRule() : null)
  }

  if (!value) {
    return (
      <section className="space-y-2 rounded-md border p-3 md:col-span-2">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="font-medium">{t("system.developerToken.fileSync.title")}</span>
          <Switch
            aria-label={t("system.developerToken.fileSync.enabled")}
            checked={false}
            onCheckedChange={handleEnabledChange}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          {t("system.developerToken.fileSync.disabledHelp")}
        </p>
      </section>
    )
  }

  const handleCategoryChange = (code: string) => {
    onChange({
      ...value,
      category: {
        code: code === UNSET_VALUE ? "" : code,
        subcategory_code: "",
      },
    })
  }

  const handleModeChange = (
    field: "businessDomain" | "targetSpace",
    mode: DeveloperTokenFileSyncMode
  ) => onChange(changeFileSyncRuleMode(value, field, mode))

  return (
    <section className="space-y-3 rounded-md border p-3 md:col-span-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{t("system.developerToken.fileSync.title")}</span>
        <Switch
          aria-label={t("system.developerToken.fileSync.enabled")}
          checked
          onCheckedChange={handleEnabledChange}
        />
      </div>

      {loading && (
        <p className="text-xs text-muted-foreground">
          {t("system.developerToken.fileSync.optionsLoading")}
        </p>
      )}
      {error && (
        <p className="text-xs text-destructive">
          {t("system.developerToken.fileSync.optionsError")}
        </p>
      )}
      {!loading && !error && !options && (
        <p className="text-xs text-muted-foreground">
          {t("system.developerToken.fileSync.selectBindingFirst")}
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t("system.developerToken.fileSync.category")} stale={categoryStale}>
          <Select
            name="file-sync-category"
            value={value.category.code || UNSET_VALUE}
            onValueChange={handleCategoryChange}
          >
            <SelectTrigger aria-label={t("system.developerToken.fileSync.category")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UNSET_VALUE}>{t("system.developerToken.fileSync.select")}</SelectItem>
              {categoryOptionMissing && (
                <SelectItem value={value.category.code}>{value.category.code}</SelectItem>
              )}
              {(options?.categories || []).map((item) => (
                <SelectItem key={item.code} value={item.code}>
                  {item.label} ({item.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label={t("system.developerToken.fileSync.subcategory")}>
          <Select
            name="file-sync-subcategory"
            value={value.category.subcategory_code || UNSET_VALUE}
            onValueChange={(code) => onChange({
              ...value,
              category: {
                ...value.category,
                subcategory_code: code === UNSET_VALUE ? "" : code,
              },
            })}
          >
            <SelectTrigger aria-label={t("system.developerToken.fileSync.subcategory")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UNSET_VALUE}>{t("system.developerToken.fileSync.select")}</SelectItem>
              {subcategoryOptionMissing && (
                  <SelectItem value={value.category.subcategory_code}>
                    {value.category.subcategory_code}
                  </SelectItem>
                )}
              {selectedChildren.map((item) => (
                <SelectItem key={item.code} value={item.code}>
                  {item.label} ({item.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <ModeField
          label={t("system.developerToken.fileSync.businessDomain")}
          modeName="file-sync-business-mode"
          mode={value.business_domain.mode}
          onModeChange={(mode) => handleModeChange("businessDomain", mode)}
        >
          {value.business_domain.mode === "fixed" && (
            <Field stale={businessStale}>
              <Select
                name="file-sync-business-domain"
                value={value.business_domain.code || UNSET_VALUE}
                onValueChange={(code) => onChange({
                  ...value,
                  business_domain: {
                    ...value.business_domain,
                    code: code === UNSET_VALUE ? null : code,
                  },
                })}
              >
                <SelectTrigger aria-label={t("system.developerToken.fileSync.businessDomain")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNSET_VALUE}>{t("system.developerToken.fileSync.select")}</SelectItem>
                  {businessOptionMissing && value.business_domain.code && (
                    <SelectItem value={value.business_domain.code}>{value.business_domain.code}</SelectItem>
                  )}
                  {(options?.business_domains || []).map((item) => (
                    <SelectItem key={item.code} value={item.code}>
                      {item.name} ({item.code})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
        </ModeField>

        <ModeField
          label={t("system.developerToken.fileSync.targetSpace")}
          modeName="file-sync-target-mode"
          mode={value.target_space.mode}
          onModeChange={(mode) => handleModeChange("targetSpace", mode)}
        >
          {value.target_space.mode === "fixed" && (
            <div className="space-y-2">
              <Field stale={targetStale}>
                <Select
                  name="file-sync-target-space"
                  value={value.target_space.knowledge_id?.toString() || UNSET_VALUE}
                  onValueChange={(id) => onChange({
                    ...value,
                    target_space: {
                      ...value.target_space,
                      knowledge_id: id === UNSET_VALUE ? null : Number(id),
                    },
                  })}
                >
                  <SelectTrigger aria-label={t("system.developerToken.fileSync.targetSpace")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNSET_VALUE}>{t("system.developerToken.fileSync.select")}</SelectItem>
                    {targetOptionMissing && value.target_space.knowledge_id && (
                      <SelectItem value={String(value.target_space.knowledge_id)}>
                        {value.target_space.knowledge_id}
                      </SelectItem>
                    )}
                    {(options?.knowledge_spaces.data || []).map((item) => (
                      <SelectItem key={item.id} value={String(item.id)}>
                        {item.name} ({item.id})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <div className="flex gap-2">
                <Input
                  value={spaceKeyword}
                  placeholder={t("system.developerToken.fileSync.spaceSearchPlaceholder")}
                  onChange={(event) => setSpaceKeyword(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") onSearchSpaces(spaceKeyword.trim())
                  }}
                />
                <Button type="button" variant="outline" onClick={() => onSearchSpaces(spaceKeyword.trim())}>
                  {t("system.developerToken.fileSync.searchSpace")}
                </Button>
              </div>
            </div>
          )}
        </ModeField>

        {hasDynamicDimension && (
          <Field label={t("system.developerToken.fileSync.dynamicSource")}>
            <Select
              name="file-sync-dynamic-source"
              value={value.dynamic_source || UNSET_VALUE}
              onValueChange={(source) => onChange({
                ...value,
                dynamic_source: source === UNSET_VALUE
                  ? null
                  : source as DeveloperTokenFileSyncDynamicSource,
              })}
            >
              <SelectTrigger aria-label={t("system.developerToken.fileSync.dynamicSource")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNSET_VALUE}>{t("system.developerToken.fileSync.select")}</SelectItem>
                <SelectItem value="department_id">
                  {t("system.developerToken.fileSync.sources.departmentId")}
                </SelectItem>
                <SelectItem value="responsible_person_id">
                  {t("system.developerToken.fileSync.sources.responsiblePersonId")}
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>
        )}
      </div>
    </section>
  )
}

function Field({
  label,
  stale = false,
  children,
}: {
  label?: string
  stale?: boolean
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-1 text-sm">
      {label && <div>{label}</div>}
      {children}
      {stale && (
        <div className="text-xs text-destructive">{t("system.developerToken.fileSync.stale")}</div>
      )}
    </div>
  )
}

function ModeField({
  label,
  modeName,
  mode,
  onModeChange,
  children,
}: {
  label: string
  modeName: string
  mode: DeveloperTokenFileSyncMode
  onModeChange: (mode: DeveloperTokenFileSyncMode) => void
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-2 text-sm">
      <div>{label}</div>
      <Select
        name={modeName}
        value={mode}
        onValueChange={(next) => onModeChange(next as DeveloperTokenFileSyncMode)}
      >
        <SelectTrigger aria-label={label}><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="fixed">{t("system.developerToken.fileSync.modes.fixed")}</SelectItem>
          <SelectItem value="dynamic">{t("system.developerToken.fileSync.modes.dynamic")}</SelectItem>
        </SelectContent>
      </Select>
      {children}
    </div>
  )
}
