import { Button } from "@/components/bs-ui/button"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { authorizeResource, getGrantableRelationModelsApi } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { X } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
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
}

export function PermissionGrantTab({ resourceType, resourceId, onSuccess }: PermissionGrantTabProps) {
  const { t } = useTranslation('permission')
  const { message } = useToast()
  const [subjectType, setSubjectType] = useState<SubjectType>('user')
  const [selected, setSelected] = useState<SelectedSubject[]>([])
  const [models, setModels] = useState<RelationModelOption[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string>('viewer')
  const [includeChildren, setIncludeChildren] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    captureAndAlertRequestErrorHoc(
      getGrantableRelationModelsApi(resourceType, resourceId),
      () => true,
    ).then((res) => {
      if (res === false) {
        setModels(DEFAULT_MODELS)
        setSelectedModelId('viewer')
        return
      }
      if (!res) return
      const options: RelationModelOption[] = (res || [])
        .map((m) => ({
          id: m.id,
          name: m.is_system ? t(`level.${m.relation}`) : m.name,
          relation: m.relation as RelationLevel,
        }))
      if (options.length) {
        setModels(options)
        setSelectedModelId(options[0].id)
      } else {
        setModels(DEFAULT_MODELS)
        setSelectedModelId('viewer')
      }
    })
  }, [resourceType, resourceId])

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
    <div className="flex flex-col gap-4">
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
        <div className="flex flex-wrap gap-1.5">
          {selected.map((s) => (
            <span
              key={`${s.type}-${s.id}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-muted rounded-md"
            >
              {s.name}
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
