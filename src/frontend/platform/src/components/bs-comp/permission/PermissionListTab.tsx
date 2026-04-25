import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/bs-ui/table"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import {
  authorizeResource,
  getGrantableRelationModelsApi,
  getResourcePermissions,
  type RelationModel,
} from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Building2, Loader2, RotateCcw, Trash2, User, Users } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { buildDepartmentPathLabelMap } from "./departmentPathUtils"
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
  prefetchedGrantableModels?: RelationModel[]
  prefetchedGrantableModelsLoaded?: boolean
  prefetchedUseDefaultModels?: boolean
  skipGrantableModelsRequest?: boolean
}

const DEFAULT_MODELS: RelationModelOption[] = [
  { id: 'owner', name: '所有者', relation: 'owner' },
  { id: 'manager', name: '可管理', relation: 'manager' },
  { id: 'editor', name: '可编辑', relation: 'editor' },
  { id: 'viewer', name: '可查看', relation: 'viewer' },
]

const LIST_SUBJECT_TYPES = ['user', 'department', 'user_group'] as const
type ListSubjectType = (typeof LIST_SUBJECT_TYPES)[number]

export function PermissionListTab({
  resourceType,
  resourceId,
  refreshKey,
  prefetchedGrantableModels,
  prefetchedGrantableModelsLoaded = false,
  prefetchedUseDefaultModels = false,
  skipGrantableModelsRequest = false,
}: PermissionListTabProps) {
  const { t } = useTranslation('permission')
  const { message } = useToast()
  const [entries, setEntries] = useState<PermissionEntry[]>([])
  const [listTab, setListTab] = useState<ListSubjectType>('user')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [grantableModels, setGrantableModels] = useState<RelationModel[]>(prefetchedGrantableModels || [])
  const [useDefaultModels, setUseDefaultModels] = useState(prefetchedUseDefaultModels)
  const [deptPathById, setDeptPathById] = useState<Map<number, string>>(() => new Map())
  const [userSelectedTab, setUserSelectedTab] = useState(false)

  useEffect(() => {
    captureAndAlertRequestErrorHoc(getDepartmentTreeApi()).then((res) => {
      if (res && Array.isArray(res)) {
        setDeptPathById(buildDepartmentPathLabelMap(res))
      }
    })
  }, [refreshKey])

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

  const filteredEntries = useMemo(
    () => entries.filter((e) => e.subject_type === listTab),
    [entries, listTab],
  )
  const ownerEntryCount = useMemo(
    () => entries.filter((entry) => entry.subject_type === 'user' && entry.relation === 'owner').length,
    [entries],
  )

  /** 换资源时回到「用户」Tab；不在用户操作切换时强行改 tab（空 tab 也要能停留并展示空态） */
  useEffect(() => {
    setListTab('user')
    setUserSelectedTab(false)
  }, [resourceId])

  useEffect(() => {
    if (userSelectedTab || entries.length === 0 || filteredEntries.length > 0) return
    const firstNonEmptyTab = LIST_SUBJECT_TYPES.find((st) =>
      entries.some((entry) => entry.subject_type === st),
    )
    if (firstNonEmptyTab) setListTab(firstNonEmptyTab)
  }, [entries, filteredEntries.length, userSelectedTab])

  useEffect(() => {
    if (skipGrantableModelsRequest) {
      if (!prefetchedGrantableModelsLoaded) return
      setGrantableModels(prefetchedGrantableModels || [])
      setUseDefaultModels(prefetchedUseDefaultModels)
      return
    }

    captureAndAlertRequestErrorHoc(
      getGrantableRelationModelsApi(resourceType, resourceId),
      () => true,
    ).then((res) => {
      if (res === false) {
        setUseDefaultModels(true)
        return
      }
      if (!res) return
      setUseDefaultModels(false)
      setGrantableModels(res)
    })
  }, [
    prefetchedGrantableModels,
    prefetchedGrantableModelsLoaded,
    prefetchedUseDefaultModels,
    refreshKey,
    resourceId,
    resourceType,
    skipGrantableModelsRequest,
  ])

  const models = useMemo<RelationModelOption[]>(() => {
    if (useDefaultModels) return DEFAULT_MODELS

    const opts: RelationModelOption[] = grantableModels.map((m) => ({
      id: m.id,
      name: m.is_system ? t(`level.${m.relation}`) : m.name,
      relation: m.relation as RelationLevel,
    }))
    const ids = new Set(opts.map((o) => o.id))
    for (const e of entries) {
      if (!e.model_id || ids.has(e.model_id)) continue
      ids.add(e.model_id)
      opts.push({
        id: e.model_id,
        name: e.model_name || e.relation,
        relation: e.relation as RelationLevel,
      })
    }
    return opts.length ? opts : DEFAULT_MODELS
  }, [entries, grantableModels, t, useDefaultModels])

  // Modify permission level inline
  const handleModify = async (entry: PermissionEntry, modelId: string) => {
    const model = models.find((m) => m.id === modelId)
    const newLevel = (model?.relation || 'viewer') as RelationLevel
    if (newLevel === entry.relation && (entry.model_id || entry.relation) === modelId) return
    const res = await captureAndAlertRequestErrorHoc(
      authorizeResource(
        resourceType, resourceId,
        [{
          subject_type: entry.subject_type,
          subject_id: entry.subject_id,
          relation: newLevel,
          model_id: modelId,
          ...(entry.subject_type === 'department'
            ? { include_children: Boolean(entry.include_children) }
            : {}),
        }],
        [{
          subject_type: entry.subject_type,
          subject_id: entry.subject_id,
          relation: entry.relation,
          ...(entry.subject_type === 'department'
            ? { include_children: Boolean(entry.include_children) }
            : {}),
        }],
      ),
      () => {
        if (entry.relation !== 'owner') return false
        message({ title: t('error.lastOwner'), variant: 'error' })
        return true
      },
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
            [{
              subject_type: entry.subject_type,
              subject_id: entry.subject_id,
              relation: entry.relation,
              ...(entry.subject_type === 'department'
                ? { include_children: Boolean(entry.include_children) }
                : {}),
            }],
          ),
          () => {
            if (entry.relation !== 'owner') return false
            message({ title: t('error.lastOwner'), variant: 'error' })
            return true
          },
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

  const subjectColumnLabel =
    listTab === 'user_group'
      ? t('subject.userGroup')
      : listTab === 'department'
        ? t('subject.department')
        : t('subject.user')

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="flex gap-1 p-1 bg-muted rounded-md w-fit">
        {LIST_SUBJECT_TYPES.map((st) => (
          <button
            key={st}
            type="button"
            className={`px-3 py-1.5 text-sm rounded transition-colors ${
              listTab === st
                ? 'bg-background shadow text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => {
              setUserSelectedTab(true)
              setListTab(st)
            }}
          >
            {t(`subject.${st === 'user_group' ? 'userGroup' : st}`)}
          </button>
        ))}
      </div>
      <div className="min-h-0 max-h-[clamp(160px,calc(100vh-14rem),400px)] overflow-y-auto overflow-x-hidden">
        {filteredEntries.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            {t('list.emptyForSubject')}
          </div>
        ) : (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[40px]"></TableHead>
            <TableHead>{subjectColumnLabel}</TableHead>
            <TableHead className="w-[140px]">{t('level.viewer')}</TableHead>
            <TableHead className="w-[60px]"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filteredEntries.map((entry, idx) => {
            const Icon = SUBJECT_ICONS[entry.subject_type] || User
            const isOwner = entry.relation === 'owner'
            const canManageOwnerEntry = isOwner && ownerEntryCount > 1
            const subjectLabel =
              entry.subject_type === 'department'
                ? (deptPathById.get(entry.subject_id)
                  ?? entry.subject_name
                  ?? `${entry.subject_type}:${entry.subject_id}`)
                : (entry.subject_name ?? `${entry.subject_type}:${entry.subject_id}`)
            return (
              <TableRow key={`${entry.subject_type}-${entry.subject_id}-${idx}`}>
                <TableCell>
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </TableCell>
                <TableCell className="max-w-[min(28rem,55vw)] text-sm">
                  <div className="flex min-w-0 flex-wrap items-baseline gap-x-1 gap-y-0.5">
                    <span className="min-w-0 truncate" title={subjectLabel}>
                      {subjectLabel}
                    </span>
                    {entry.include_children && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        ({t('includeChildren')})
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  {!isOwner || canManageOwnerEntry ? (
                    <RelationSelect
                      value={entry.model_id || entry.relation}
                      onChange={(v) => handleModify(entry, v)}
                      options={models}
                      className="h-7 w-[110px] text-xs"
                    />
                  ) : (
                    <span className="text-sm text-muted-foreground">{t('level.owner')}</span>
                  )}
                </TableCell>
                <TableCell>
                  {(!isOwner || canManageOwnerEntry) && (
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
        )}
      </div>
    </div>
  )
}
