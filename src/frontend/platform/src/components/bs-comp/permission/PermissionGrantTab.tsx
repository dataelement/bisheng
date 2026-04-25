import { Button } from "@/components/bs-ui/button"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
  authorizeResource,
  getGrantableRelationModelsApi,
  type RelationModel,
} from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { X } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { RelationModelOption, RelationSelect } from "./RelationSelect"
import { SubjectSearchDepartment } from "./SubjectSearchDepartment"
import { SubjectSearchUser } from "./SubjectSearchUser"
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup"
import { GrantItem, RelationLevel, ResourceType, SelectedSubject, SubjectType } from "./types"

const SUBJECT_TYPES: SubjectType[] = ['user', 'department', 'user_group']
const DEFAULT_MODELS: RelationModelOption[] = [
  { id: 'owner', name: '所有者', relation: 'owner' },
  { id: 'viewer', name: '可查看', relation: 'viewer' },
  { id: 'editor', name: '可编辑', relation: 'editor' },
  { id: 'manager', name: '可管理', relation: 'manager' },
]

interface PermissionGrantTabProps {
  resourceType: ResourceType
  resourceId: string
  onSuccess: () => void
  prefetchedGrantableModels?: RelationModel[]
  prefetchedGrantableModelsLoaded?: boolean
  prefetchedUseDefaultModels?: boolean
  skipGrantableModelsRequest?: boolean
}

export function PermissionGrantTab({
  resourceType,
  resourceId,
  onSuccess,
  prefetchedGrantableModels,
  prefetchedGrantableModelsLoaded = false,
  prefetchedUseDefaultModels = false,
  skipGrantableModelsRequest = false,
}: PermissionGrantTabProps) {
  const { t } = useTranslation('permission')
  const { message } = useToast()
  const [subjectType, setSubjectType] = useState<SubjectType>('user')
  const [selected, setSelected] = useState<SelectedSubject[]>([])
  const [modelSource, setModelSource] = useState<{
    relationModels?: RelationModel[]
    fallbackToDefault: boolean
  }>({ fallbackToDefault: true })
  const [selectedModelId, setSelectedModelId] = useState<string>('owner')
  const [includeChildren, setIncludeChildren] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const applyRelationModels = useCallback((relationModels: RelationModel[] | undefined, fallbackToDefault: boolean) => {
    const hasModels = Boolean(relationModels?.length)
    const shouldUseDefault = fallbackToDefault || !hasModels
    setModelSource({
      relationModels,
      fallbackToDefault: shouldUseDefault,
    })
    if (shouldUseDefault) {
      setSelectedModelId(DEFAULT_MODELS[0].id)
      return
    }

    setSelectedModelId(relationModels![0].id)
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
        applyRelationModels(undefined, true)
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
      return modelSource.relationModels.map((m) => ({
        id: m.id,
        name: m.is_system ? t(`level.${m.relation}`) : m.name,
        relation: m.relation as RelationLevel,
      }))
    }

    return DEFAULT_MODELS.map((m) => ({
      ...m,
      name: t(`level.${m.relation}`),
    }))
  }, [modelSource, t])

  const relation = useMemo<RelationLevel>(() => {
    return models.find((m) => m.id === selectedModelId)?.relation || 'viewer'
  }, [models, selectedModelId])

  const availableModels = useMemo(() => {
    if (subjectType === 'user') {
      return models
    }
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

  const handleSubjectTypeChange = (type: SubjectType) => {
    setSubjectType(type)
    setSelected([])
  }

  const removeSelected = (id: number) => {
    setSelected(selected.filter((s) => s.id !== id))
  }

  const handleSubmit = async () => {
    if (selected.length === 0) return

    const grants: GrantItem[] = selected.map((s) => ({
      subject_type: s.type,
      subject_id: s.id,
      relation,
      model_id: selectedModelId,
      ...(s.type === 'department' ? { include_children: includeChildren } : {}),
    }))

    setSubmitting(true)
    const res = await captureAndAlertRequestErrorHoc(
      authorizeResource(resourceType, resourceId, grants, []),
    )
    setSubmitting(false)

    if (res !== false) {
      message({ title: t('success.grant'), variant: 'success' })
      setSelected([])
      onSuccess()
    }
  }

  return (
    <div className="flex min-h-0 flex-col gap-4">
      {/* Subject type selector */}
      <div className="flex gap-1 p-1 bg-muted rounded-md w-fit">
        {SUBJECT_TYPES.map((type) => (
          <button
            key={type}
            className={`px-3 py-1.5 text-sm rounded transition-colors ${
              subjectType === type
                ? 'bg-background shadow text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => handleSubjectTypeChange(type)}
          >
            {t(`subject.${type === 'user_group' ? 'userGroup' : type}`)}
          </button>
        ))}
      </div>

      {/* Subject search based on type */}
      {subjectType === 'user' && (
        <SubjectSearchUser value={selected} onChange={setSelected} />
      )}
      {subjectType === 'department' && (
        <SubjectSearchDepartment
          value={selected}
          onChange={setSelected}
          includeChildren={includeChildren}
          onIncludeChildrenChange={setIncludeChildren}
        />
      )}
      {subjectType === 'user_group' && (
        <SubjectSearchUserGroup value={selected} onChange={setSelected} />
      )}

      {/* Selected subjects preview */}
      {selected.length > 0 && (
        <div className="flex max-h-24 flex-wrap gap-1.5 overflow-y-auto pr-1">
          {selected.map((s) => (
            <span
              key={`${s.type}-${s.id}`}
              className="inline-flex max-w-full items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs"
            >
              <span className="min-w-0 max-w-[min(24rem,100%)] truncate" title={s.name}>
                {s.name}
              </span>
              {s.type === 'department' && s.include_children && (
                <span className="text-muted-foreground">
                  ({t('includeChildren')})
                </span>
              )}
              <button
                className="hover:text-destructive"
                onClick={() => removeSelected(s.id)}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Relation level + submit */}
      <div className="flex items-center gap-3 pt-2 border-t">
        <RelationSelect
          value={selectedModelId}
          onChange={setSelectedModelId}
          options={availableModels}
          className="w-[160px]"
        />
        <Button
          onClick={handleSubmit}
          disabled={selected.length === 0 || submitting}
          className="ml-auto"
        >
          {submitting ? t('action.submit') + '...' : t('action.submit')}
        </Button>
      </div>
    </div>
  )
}
