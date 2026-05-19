import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
  authorizeResource,
  getGrantableRelationModelsApi,
  getResourcePermissions,
  type RelationModel,
} from "@/controllers/API/permission"
import { Portal, Tooltip, TooltipContent, TooltipTrigger } from "@/components/bs-ui/tooltip"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { cn } from "@/utils"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { RelationModelOption, RelationSelect } from "./RelationSelect"
import { SubjectSearchDepartment } from "./SubjectSearchDepartment"
import { SubjectSearchUser } from "./SubjectSearchUser"
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup"
import { GrantItem, PermissionEntry, RelationLevel, ResourceType, SelectedSubject, SubjectType } from "./types"

const SUBJECT_TYPES: SubjectType[] = ['user', 'department', 'user_group']
const DEFAULT_MODELS: RelationModelOption[] = [
  { id: 'owner', name: '所有者', relation: 'owner' },
  { id: 'viewer', name: '可查看', relation: 'viewer' },
  { id: 'editor', name: '可编辑', relation: 'editor' },
  { id: 'manager', name: '可管理', relation: 'manager' },
]

const EMPTY_GRANTED_SUBJECT_IDS: Record<SubjectType, number[]> = {
  user: [],
  department: [],
  user_group: [],
}

// Render selected subjects as chips. Horizontally scrollable with a right-edge fade when overflow occurs.
function SelectedSubjectChips({ subjects, fullText }: { subjects: SelectedSubject[]; fullText: string }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)
  const [hasLeftOverflow, setHasLeftOverflow] = useState(false)
  const [hasRightOverflow, setHasRightOverflow] = useState(false)

  const updateOverflow = useCallback(() => {
    const el = ref.current
    if (!el) return
    setHasLeftOverflow(el.scrollLeft > 1)
    setHasRightOverflow(el.scrollWidth - el.clientWidth - el.scrollLeft > 1)
  }, [])

  useEffect(() => {
    updateOverflow()
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(updateOverflow)
    ro.observe(el)
    return () => ro.disconnect()
  }, [subjects, updateOverflow])

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setOpen(false)
      return
    }
    const el = ref.current
    if (el && el.scrollWidth > el.clientWidth) {
      setOpen(true)
    }
  }

  if (subjects.length === 0) return null

  return (
    <Tooltip open={open} onOpenChange={handleOpenChange} delayDuration={200}>
      <TooltipTrigger asChild>
        <div
          ref={ref}
          onScroll={updateOverflow}
          className="min-w-0 flex flex-1 items-center gap-1 overflow-x-auto scrollbar-hide"
          style={(() => {
            const leftStop = hasLeftOverflow ? '24px' : '0'
            const rightStop = hasRightOverflow ? 'calc(100% - 24px)' : '100%'
            if (!hasLeftOverflow && !hasRightOverflow) return undefined
            const value = `linear-gradient(to right, transparent, black ${leftStop}, black ${rightStop}, transparent)`
            return { maskImage: value, WebkitMaskImage: value }
          })()}
        >
          {subjects.map((subject) => (
            <span
              key={subject.id}
              className="inline-flex shrink-0 items-center rounded-[4px] bg-[#F2F3F5] px-2 py-0.5 text-[14px] leading-[22px] text-[#4E5969]"
            >
              {subject.name}
            </span>
          ))}
        </div>
      </TooltipTrigger>
      <Portal>
        <TooltipContent className="z-[120] text-sm shadow-md" side="top">
          <div className="max-w-96 text-left break-all whitespace-normal">{fullText}</div>
        </TooltipContent>
      </Portal>
    </Tooltip>
  )
}

interface PermissionGrantTabProps {
  resourceType: ResourceType
  resourceId: string
  onSuccess: () => void
  prefetchedGrantableModels?: RelationModel[]
  prefetchedGrantableModelsLoaded?: boolean
  prefetchedUseDefaultModels?: boolean
  skipGrantableModelsRequest?: boolean
  fixedSubjectType?: SubjectType
  includeChildren?: boolean
  onIncludeChildrenChange?: (value: boolean) => void
  hideDepartmentIncludeChildrenControl?: boolean
}

export function PermissionGrantTab({
  resourceType,
  resourceId,
  onSuccess,
  prefetchedGrantableModels,
  prefetchedGrantableModelsLoaded = false,
  prefetchedUseDefaultModels = false,
  skipGrantableModelsRequest = false,
  fixedSubjectType,
  includeChildren: includeChildrenProp,
  onIncludeChildrenChange,
  hideDepartmentIncludeChildrenControl = false,
}: PermissionGrantTabProps) {
  const { t } = useTranslation('permission')
  const { message } = useToast()
  const [subjectType, setSubjectType] = useState<SubjectType>(fixedSubjectType ?? 'user')
  const [selected, setSelected] = useState<SelectedSubject[]>([])
  const [modelSource, setModelSource] = useState<{
    relationModels?: RelationModel[]
    fallbackToDefault: boolean
  }>({ fallbackToDefault: true })
  const [selectedModelId, setSelectedModelId] = useState<string>('viewer')
  const [internalIncludeChildren, setInternalIncludeChildren] = useState(true)
  const [selectedDepartmentSummary, setSelectedDepartmentSummary] = useState<SelectedSubject[]>([])
  const [grantedSubjectIds, setGrantedSubjectIds] = useState<Record<SubjectType, number[]>>(
    EMPTY_GRANTED_SUBJECT_IDS,
  )
  const [submitting, setSubmitting] = useState(false)
  const includeChildren = includeChildrenProp ?? internalIncludeChildren
  const handleIncludeChildrenChange = onIncludeChildrenChange ?? setInternalIncludeChildren

  const applyRelationModels = useCallback((relationModels: RelationModel[] | undefined, fallbackToDefault: boolean) => {
    const hasModels = Boolean(relationModels?.length)
    const shouldUseDefault = fallbackToDefault
    setModelSource({
      relationModels: hasModels ? relationModels : [],
      fallbackToDefault: shouldUseDefault,
    })
    if (shouldUseDefault) {
      setSelectedModelId(DEFAULT_MODELS.find((model) => model.id === 'viewer')?.id ?? DEFAULT_MODELS[0].id)
      return
    }
    if (!hasModels) {
      setSelectedModelId('')
      return
    }

    const preferredModel = relationModels!.find((model) => model.relation === 'viewer') ?? relationModels![0]
    setSelectedModelId(preferredModel.id)
  }, [])

  const applyGrantedPermissions = useCallback((permissions: PermissionEntry[] | undefined) => {
    const next = {
      user: new Set<number>(),
      department: new Set<number>(),
      user_group: new Set<number>(),
    }
    for (const permission of Array.isArray(permissions) ? permissions : []) {
      if (permission.subject_type in next) {
        next[permission.subject_type].add(permission.subject_id)
      }
    }
    setGrantedSubjectIds({
      user: Array.from(next.user),
      department: Array.from(next.department),
      user_group: Array.from(next.user_group),
    })
  }, [])

  useEffect(() => {
    if (skipGrantableModelsRequest) {
      if (!prefetchedGrantableModelsLoaded) return
      applyRelationModels(prefetchedGrantableModels, prefetchedUseDefaultModels)
      return
    }

    captureAndAlertRequestErrorHoc(
      getGrantableRelationModelsApi(resourceType, resourceId),
      () => true,
    ).then((res) => {
      if (res === false) {
        applyRelationModels(undefined, false)
        return
      }
      if (!res) return
      applyRelationModels(res, false)
    })
  }, [
    prefetchedGrantableModels,
    prefetchedGrantableModelsLoaded,
    prefetchedUseDefaultModels,
    resourceId,
    resourceType,
    skipGrantableModelsRequest,
    applyRelationModels,
  ])

  const models = useMemo<RelationModelOption[]>(() => {
    if (!modelSource.fallbackToDefault && modelSource.relationModels?.length) {
      return modelSource.relationModels.map((model) => ({
        id: model.id,
        name: model.is_system ? t(`level.${model.relation}`, { defaultValue: model.relation }) : model.name,
        relation: model.relation as RelationLevel,
      }))
    }

    return DEFAULT_MODELS.map((model) => ({
      ...model,
      name: t(`level.${model.relation}`, { defaultValue: model.relation }),
    }))
  }, [modelSource, t])

  const relation = useMemo<RelationLevel>(() => {
    return models.find((model) => model.id === selectedModelId)?.relation || 'viewer'
  }, [models, selectedModelId])

  const availableModels = useMemo(() => {
    if (subjectType === 'user') return models
    return models.filter((model) => model.relation !== 'owner')
  }, [models, subjectType])

  useEffect(() => {
    if (!availableModels.length) return
    if (availableModels.some((model) => model.id === selectedModelId)) return
    setSelectedModelId(availableModels[0].id)
  }, [availableModels, selectedModelId])

  useEffect(() => {
    setSelected((prev) =>
      prev.map((item) =>
        item.type === 'department'
          ? { ...item, include_children: includeChildren }
          : item,
      ),
    )
  }, [includeChildren])

  useEffect(() => {
    if (!fixedSubjectType) return
    setSubjectType(fixedSubjectType)
    setSelected([])
    setSelectedDepartmentSummary([])
  }, [fixedSubjectType])

  useEffect(() => {
    let cancelled = false
    captureAndAlertRequestErrorHoc(
      getResourcePermissions(resourceType, resourceId),
      () => true,
    ).then((res) => {
      if (cancelled) return
      if (res === false) {
        setGrantedSubjectIds(EMPTY_GRANTED_SUBJECT_IDS)
        return
      }
      applyGrantedPermissions(res)
    })
    return () => {
      cancelled = true
    }
  }, [applyGrantedPermissions, resourceId, resourceType])

  const handleSubjectTypeChange = (type: SubjectType) => {
    setSubjectType(type)
    setSelected([])
    setSelectedDepartmentSummary([])
  }

  const handleSubmit = async () => {
    if (selected.length === 0) return
    if (subjectType !== 'user' && relation === 'owner') {
      message({ title: '部门或用户组无法成为所有者', variant: 'error' })
      return
    }

    const grants: GrantItem[] = selected.map((subject) => ({
      subject_type: subject.type,
      subject_id: subject.id,
      relation,
      model_id: selectedModelId,
      ...(subject.type === 'department' ? { include_children: includeChildren } : {}),
    }))

    setSubmitting(true)
    const res = await captureAndAlertRequestErrorHoc(
      authorizeResource(resourceType, resourceId, grants, []),
    )
    setSubmitting(false)

    if (res !== false) {
      message({ title: t('success.grant'), variant: 'success' })
      setSelected([])
      setSelectedDepartmentSummary([])
      onSuccess()
    }
  }

  const subjectLabel = (type: SubjectType) => {
    const map: Record<SubjectType, string> = {
      user: t('subject.user'),
      department: t('subject.department'),
      user_group: t('subject.userGroup'),
    }
    return map[type]
  }

  const showDepartmentIncludeChildrenControl =
    subjectType === 'department' && !hideDepartmentIncludeChildrenControl
  const selectedSubjectList =
    subjectType === 'department' && selectedDepartmentSummary.length > 0
      ? selectedDepartmentSummary
      : selected
  const selectedSummaryText = selectedSubjectList.map((subject) => subject.name).join('、')

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {!fixedSubjectType && (
        <div className="flex items-center gap-3">
          <div className="flex w-fit gap-1 rounded-md bg-muted p-1">
            {SUBJECT_TYPES.map((type) => (
              <button
                key={type}
                className={`rounded px-3 py-1.5 text-sm transition-colors ${subjectType === type
                  ? 'bg-background text-foreground shadow'
                  : 'text-muted-foreground hover:text-foreground'
                  }`}
                onClick={() => handleSubjectTypeChange(type)}
              >
                {subjectLabel(type)}
              </button>
            ))}
          </div>

          {showDepartmentIncludeChildrenControl && (
            <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm text-[#212121]">
              <Checkbox
                checked={includeChildren}
                onCheckedChange={(value) => handleIncludeChildrenChange(value === true)}
              />
              {t('includeChildren')}
            </label>
          )}
        </div>
      )}

      <div
        className={cn(
          "min-h-0 flex-1 overflow-hidden",
          !fixedSubjectType && "mt-4",
        )}
      >
        {subjectType === 'user' && (
          <SubjectSearchUser
            value={selected}
            onChange={setSelected}
            resourceType={resourceType}
            resourceId={resourceId}
            disabledIds={grantedSubjectIds.user}
          />
        )}
        {subjectType === 'department' && (
          <SubjectSearchDepartment
            value={selected}
            onChange={setSelected}
            resourceType={resourceType}
            resourceId={resourceId}
            includeChildren={includeChildren}
            onIncludeChildrenChange={handleIncludeChildrenChange}
            onSelectionSummaryChange={setSelectedDepartmentSummary}
            showIncludeChildrenToggle={!hideDepartmentIncludeChildrenControl}
            disabledIds={grantedSubjectIds.department}
          />
        )}
        {subjectType === 'user_group' && (
          <SubjectSearchUserGroup
            value={selected}
            onChange={setSelected}
            resourceType={resourceType}
            resourceId={resourceId}
            disabledIds={grantedSubjectIds.user_group}
          />
        )}
      </div>

      <div className="mt-3 flex h-10 shrink-0 items-center gap-4 overflow-hidden">
        <div className="min-w-0 flex flex-1 items-center gap-2 overflow-hidden">
          <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
            {`${t('action.grant')}${subjectLabel(subjectType)}:`}
          </span>
          <SelectedSubjectChips subjects={selectedSubjectList} fullText={selectedSummaryText} />
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
            {t('action.grant')}
          </span>
          <RelationSelect
            value={selectedModelId}
            onChange={setSelectedModelId}
            options={availableModels}
            className="w-[132px]"
          />
        </div>
      </div>

      <div className="mt-3 flex shrink-0 justify-end border-t pt-3">
        <Button
          onClick={handleSubmit}
          disabled={selected.length === 0 || availableModels.length === 0 || submitting}
        >
          {submitting ? t('action.submit') + '...' : t('action.submit')}
        </Button>
      </div>
    </div>
  )
}
