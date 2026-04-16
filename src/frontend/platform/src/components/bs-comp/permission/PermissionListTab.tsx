import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/bs-ui/table"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
  authorizeResource,
  getGrantableRelationModelsApi,
  getResourcePermissions,
  type RelationModel,
} from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Building2, Loader2, RotateCcw, Trash2, User, Users } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { PermissionBadge } from "./PermissionBadge"
import { RelationModelOption, RelationSelect } from "./RelationSelect"
import { PermissionEntry, RelationLevel, ResourceType } from "./types"

const SUBJECT_ICONS = {
  user: User,
  department: Building2,
  user_group: Users,
}

interface PermissionListTabProps {
  resourceType: ResourceType
  resourceId: string
  refreshKey: number
}

const DEFAULT_MODELS: RelationModelOption[] = [
  { id: 'owner', name: '所有者', relation: 'owner' },
  { id: 'manager', name: '可管理', relation: 'manager' },
  { id: 'editor', name: '可编辑', relation: 'editor' },
  { id: 'viewer', name: '可查看', relation: 'viewer' },
]

export function PermissionListTab({ resourceType, resourceId, refreshKey }: PermissionListTabProps) {
  const { t } = useTranslation('permission')
  const { message } = useToast()
  const [entries, setEntries] = useState<PermissionEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [models, setModels] = useState<RelationModelOption[]>([])

  const mergeGrantableWithEntries = useCallback(
    (grantable: RelationModel[], list: PermissionEntry[]): RelationModelOption[] => {
      const opts: RelationModelOption[] = (grantable || []).map((m) => ({
        id: m.id,
        name: m.is_system ? t(`level.${m.relation}`) : m.name,
        relation: m.relation as RelationLevel,
      }))
      const ids = new Set(opts.map((o) => o.id))
      for (const e of list) {
        if (!e.model_id || ids.has(e.model_id)) continue
        ids.add(e.model_id)
        opts.push({
          id: e.model_id,
          name: e.model_name || e.relation,
          relation: e.relation as RelationLevel,
        })
      }
      return opts
    },
    [t],
  )

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(false)
    const res = await captureAndAlertRequestErrorHoc(
      getResourcePermissions(resourceType, resourceId),
      () => { setError(true); return true },
    )
    if (res) {
      setEntries(res)
    }
    setLoading(false)
  }, [resourceType, resourceId])

  useEffect(() => { loadData() }, [loadData, refreshKey])
  useEffect(() => {
    captureAndAlertRequestErrorHoc(
      getGrantableRelationModelsApi(resourceType, resourceId),
      () => true,
    ).then((res) => {
      if (res === false) {
        setModels(DEFAULT_MODELS)
        return
      }
      if (!res) return
      const merged = mergeGrantableWithEntries(res, entries)
      setModels(merged.length ? merged : DEFAULT_MODELS)
    })
  }, [resourceType, resourceId, entries, mergeGrantableWithEntries, refreshKey])

  // Modify permission level inline
  const handleModify = async (entry: PermissionEntry, modelId: string) => {
    const model = models.find((m) => m.id === modelId)
    const newLevel = (model?.relation || 'viewer') as RelationLevel
    if (newLevel === entry.relation && (entry.model_id || entry.relation) === modelId) return
    const res = await captureAndAlertRequestErrorHoc(
      authorizeResource(
        resourceType, resourceId,
        [{ subject_type: entry.subject_type, subject_id: entry.subject_id, relation: newLevel, model_id: modelId }],
        [{ subject_type: entry.subject_type, subject_id: entry.subject_id, relation: entry.relation }],
      ),
    )
    if (res !== false) {
      message({ title: t('success.modify'), variant: 'success' })
      loadData()
    }
  }

  // Revoke permission with confirmation
  const handleRevoke = (entry: PermissionEntry) => {
    bsConfirm({
      desc: t('action.confirmRevoke'),
      onOk(next) {
        captureAndAlertRequestErrorHoc(
          authorizeResource(
            resourceType, resourceId,
            [],
            [{ subject_type: entry.subject_type, subject_id: entry.subject_id, relation: entry.relation }],
          ),
        ).then((res) => {
          if (res !== false) {
            message({ title: t('success.revoke'), variant: 'success' })
            loadData()
          }
        })
        next()
      },
    })
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12">
        <span className="text-sm text-muted-foreground">{t('error.permissionDenied')}</span>
        <button
          className="flex items-center gap-1 text-sm text-primary hover:underline"
          onClick={loadData}
        >
          <RotateCcw className="h-3.5 w-3.5" /> {t('retry', { ns: 'bs' })}
        </button>
      </div>
    )
  }

  if (entries.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        {t('empty.permissions')}
      </div>
    )
  }

  return (
    <div className="max-h-[400px] overflow-y-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[40px]"></TableHead>
            <TableHead>{t('subject.user')}</TableHead>
            <TableHead className="w-[140px]">{t('level.viewer')}</TableHead>
            <TableHead className="w-[60px]"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((entry, idx) => {
            const Icon = SUBJECT_ICONS[entry.subject_type] || User
            const isOwner = entry.relation === 'owner'
            return (
              <TableRow key={`${entry.subject_type}-${entry.subject_id}-${idx}`}>
                <TableCell>
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </TableCell>
                <TableCell className="text-sm">
                  {entry.subject_name ?? `${entry.subject_type}:${entry.subject_id}`}
                  {entry.include_children && (
                    <span className="ml-1 text-xs text-muted-foreground">
                      ({t('includeChildren')})
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  {isOwner ? (
                    <PermissionBadge level="owner" />
                  ) : (
                    <RelationSelect
                      value={entry.model_id || entry.relation}
                      onChange={(v) => handleModify(entry, v)}
                      options={models}
                      className="h-7 w-[110px] text-xs"
                    />
                  )}
                </TableCell>
                <TableCell>
                  {!isOwner && (
                    <button
                      className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                      onClick={() => handleRevoke(entry)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
