import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { Switch } from "@/components/bs-ui/switch"
import { Input } from "@/components/bs-ui/input"
import type {
  DeveloperTokenFileSyncDynamicSource,
  DeveloperTokenFileSyncFolderDynamicSource,
  DeveloperTokenFileSyncFolderMode,
  DeveloperTokenFileSyncMode,
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule as FileSyncRule,
  DeveloperTokenFileSyncTargetDisplay,
} from "@/controllers/API/developerToken"
import { useMemo } from "react"
import { useTranslation } from "react-i18next"
import {
  changeFileSyncFolderMode,
  changeFileSyncRuleMode,
  createEmptyFileSyncRule,
  normalizeFolderPath,
} from "./developerTokenFileSyncRuleValidation"
import DeveloperTokenFileSyncTargetTree from "./DeveloperTokenFileSyncTargetTree"

const UNSET_VALUE = "__unset__"

interface DeveloperTokenFileSyncRuleProps {
  value: FileSyncRule | null
  onChange: (value: FileSyncRule | null) => void
  options: DeveloperTokenFileSyncOptions | null
  loading: boolean
  error: string | null
  onSearchSpaces: (keyword: string) => void
  targetDisplay?: DeveloperTokenFileSyncTargetDisplay | null
  boundUserId?: number | null
}

export default function DeveloperTokenFileSyncRule({
  value,
  onChange,
  options,
  loading,
  error,
  onSearchSpaces,
  targetDisplay = null,
  boundUserId = null,
}: DeveloperTokenFileSyncRuleProps) {
  const { t } = useTranslation()
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
      {!loading && !error && !options && boundUserId && (
        <p className="text-xs text-muted-foreground">
          {t("system.developerToken.fileSync.optionsLoading")}
        </p>
      )}
      {!loading && !error && !options && !boundUserId && (
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

        <div className="border-y py-3 md:col-span-2">
          <ModeField
            inlineControls
            label={t("system.developerToken.fileSync.businessDomain")}
            modeName="file-sync-business-mode"
            mode={value.business_domain.mode}
            onModeChange={(mode) => handleModeChange("businessDomain", mode as DeveloperTokenFileSyncMode)}
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
            {value.business_domain.mode === "dynamic" && (
              <DynamicSourceField
                hideLabel
                name="file-sync-business-dynamic-source"
                value={value.business_domain.dynamic_source}
                onChange={(dynamic_source) => onChange({
                  ...value,
                  business_domain: { ...value.business_domain, dynamic_source },
                })}
              />
            )}
          </ModeField>
        </div>

        <ModeField
          className="md:col-span-2"
          inlineControls
          label={t("system.developerToken.fileSync.targetSpace")}
          modeName="file-sync-target-mode"
          mode={value.target_space.mode}
          onModeChange={(mode) => handleModeChange("targetSpace", mode as DeveloperTokenFileSyncMode)}
        >
          {value.target_space.mode === "fixed" && (
            <Field>
              {options ? (
                <DeveloperTokenFileSyncTargetTree
                  tenantId={options.tenant_id}
                  userId={options.user_id}
                  groups={options.target_space_groups.data}
                  value={value.target_space}
                  display={targetDisplay}
                  folderMode="none"
                  loading={false}
                  error={null}
                  onChange={(target) => onChange({
                    ...value,
                    target_space: {
                      mode: "fixed",
                      knowledge_id: target.knowledge_id,
                      folder_id: null,
                      dynamic_source: null,
                      folder_mode: value.target_space.folder_mode ?? "none",
                      folder_path: value.target_space.folder_path ?? null,
                      parent_folder_path: value.target_space.parent_folder_path ?? null,
                      folder_dynamic_source: value.target_space.folder_dynamic_source ?? null,
                    },
                  })}
                  onSearchSpaces={onSearchSpaces}
                />
              ) : (
                <div className="text-xs text-muted-foreground">
                  {t("system.developerToken.fileSync.selectBindingFirst")}
                </div>
              )}
            </Field>
          )}
          {value.target_space.mode === "dynamic" && (
            <DynamicSourceField
              hideLabel
              name="file-sync-target-dynamic-source"
              value={value.target_space.dynamic_source}
              onChange={(dynamic_source) => onChange({
                ...value,
                target_space: { ...value.target_space, dynamic_source },
              })}
            />
          )}
        </ModeField>

        <ModeField
          className="md:col-span-2"
          inlineControls
          label={t("system.developerToken.fileSync.targetFolder")}
          modeName="file-sync-folder-mode"
          mode={value.target_space.folder_mode || "none"}
          onModeChange={(mode) => onChange(changeFileSyncFolderMode(value, mode as DeveloperTokenFileSyncFolderMode))}
          modeOptions={[
            { value: "none", label: t("system.developerToken.fileSync.folderModes.none") },
            { value: "fixed", label: t("system.developerToken.fileSync.folderModes.fixed") },
            { value: "dynamic", label: t("system.developerToken.fileSync.folderModes.dynamic") },
          ]}
        >
          {value.target_space.folder_mode === "fixed" && (
            <Field label={t("system.developerToken.fileSync.folderPath")}>
              <Input
                name="file-sync-folder-path"
                value={value.target_space.folder_path ?? ""}
                placeholder={t("system.developerToken.fileSync.folderPathPlaceholder")}
                onChange={(event) => onChange({
                  ...value,
                  target_space: {
                    ...value.target_space,
                    folder_mode: "fixed",
                    folder_path: normalizeFolderPath(event.target.value),
                    folder_id: null,
                    parent_folder_path: null,
                    folder_dynamic_source: null,
                  },
                })}
              />
            </Field>
          )}
          {value.target_space.folder_mode === "dynamic" && value.target_space.mode === "fixed" && (
            <Field label={t("system.developerToken.fileSync.parentFolderPath")}>
              <Input
                name="file-sync-parent-folder-path"
                value={value.target_space.parent_folder_path ?? ""}
                placeholder={t("system.developerToken.fileSync.parentFolderPathPlaceholder")}
                onChange={(event) => onChange({
                  ...value,
                  target_space: {
                    ...value.target_space,
                    folder_mode: "dynamic",
                    parent_folder_path: normalizeFolderPath(event.target.value),
                    folder_path: null,
                    folder_id: null,
                  },
                })}
              />
            </Field>
          )}
          {value.target_space.folder_mode === "dynamic" && (
            <FolderDynamicSourceField
              value={value.target_space.folder_dynamic_source}
              onChange={(folder_dynamic_source) => onChange({
                ...value,
                target_space: { ...value.target_space, folder_dynamic_source },
              })}
            />
          )}
        </ModeField>
      </div>
    </section>
  )
}

function FolderDynamicSourceField({
  value,
  onChange,
}: {
  value: DeveloperTokenFileSyncFolderDynamicSource | null | undefined
  onChange: (value: DeveloperTokenFileSyncFolderDynamicSource | null) => void
}) {
  const { t } = useTranslation()
  return (
    <Field label={t("system.developerToken.fileSync.folderDynamicSource")}>
      <Select
        name="file-sync-folder-dynamic-source"
        value={value || UNSET_VALUE}
        onValueChange={(source) => onChange(
          source === UNSET_VALUE ? null : source as DeveloperTokenFileSyncFolderDynamicSource,
        )}
      >
        <SelectTrigger aria-label={t("system.developerToken.fileSync.folderDynamicSource")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={UNSET_VALUE}>{t("system.developerToken.fileSync.select")}</SelectItem>
          <SelectItem value="department_name">
            {t("system.developerToken.fileSync.folderSources.departmentName")}
          </SelectItem>
          <SelectItem value="caller_main_department_name">
            {t("system.developerToken.fileSync.folderSources.callerMainDepartmentName")}
          </SelectItem>
        </SelectContent>
      </Select>
    </Field>
  )
}

function DynamicSourceField({
  hideLabel = false,
  name,
  value,
  onChange,
}: {
  hideLabel?: boolean
  name: string
  value: DeveloperTokenFileSyncDynamicSource | null | undefined
  onChange: (value: DeveloperTokenFileSyncDynamicSource | null) => void
}) {
  const { t } = useTranslation()
  return (
    <Field label={hideLabel ? undefined : t("system.developerToken.fileSync.dynamicSource")}>
      <Select
        name={name}
        value={value || UNSET_VALUE}
        onValueChange={(source) => onChange(
          source === UNSET_VALUE ? null : source as DeveloperTokenFileSyncDynamicSource,
        )}
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
  className,
  inlineControls = false,
  label,
  modeName,
  mode,
  onModeChange,
  modeOptions,
  children,
}: {
  className?: string
  inlineControls?: boolean
  label: string
  modeName: string
  mode: string
  onModeChange: (mode: string) => void
  modeOptions?: Array<{ value: string; label: string; disabled?: boolean }>
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  const options = modeOptions ?? [
    { value: "fixed", label: t("system.developerToken.fileSync.modes.fixed") },
    { value: "dynamic", label: t("system.developerToken.fileSync.modes.dynamic") },
  ]
  const modeSelect = (
    <Select
      name={modeName}
      value={mode}
      onValueChange={onModeChange}
    >
      <SelectTrigger aria-label={label}><SelectValue /></SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  return (
    <div className={`space-y-2 text-sm${className ? ` ${className}` : ""}`}>
      <div>{label}</div>
      {inlineControls ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <div className="shrink-0 sm:w-52">{modeSelect}</div>
          <div className="min-w-0 flex-1">{children}</div>
        </div>
      ) : (
        <>
          {modeSelect}
          {children}
        </>
      )}
    </div>
  )
}
