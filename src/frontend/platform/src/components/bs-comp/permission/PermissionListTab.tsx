import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/bs-ui/table"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { authorizeResource, getResourcePermissions } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Building2, Loader2, RotateCcw, Trash2, User, Users } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { PermissionBadge } from "./PermissionBadge"
import { RelationSelect } from "./RelationSelect"
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

export function PermissionListTab({ resourceType, resourceId, refreshKey }: PermissionListTabProps) {
  const { t } = useTranslation('permission')
  const { message } = useToast()
  const [entries, setEntries] = useState<PermissionEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

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

  // Modify permission level inline
  const handleModify = async (entry: PermissionEntry, newLevel: RelationLevel) => {
    if (newLevel === entry.relation) return
    const res = await captureAndAlertRequestErrorHoc(
      authorizeResource(
        resourceType, resourceId,
        [{ subject_type: entry.subject_type, subject_id: entry.subject_id, relation: newLevel }],
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
                      value={entry.relation}
                      onChange={(v) => handleModify(entry, v)}
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
