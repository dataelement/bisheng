import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Checkbox, Tag } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'
import type { AuditDeptNode } from '@/types/api/audit'
import { useAuditDepartmentChildren, useAuditDepartmentRoots } from './useAuditDepartments'

interface SelectionProps {
  checked: ReadonlySet<number>
  onToggle: (id: number) => void
}

interface OrgPanelBodyProps extends SelectionProps {
  tenantId?: number | null
  keyword: string
  includeNone: boolean
  includeUnrecorded: boolean
  onIncludeNone: (value: boolean) => void
  onIncludeUnrecorded: (value: boolean) => void
}

interface DeptRowProps extends SelectionProps {
  dept: AuditDeptNode
  showPath?: boolean
  archived?: boolean
}

function DeptCheckbox({ dept, showPath, archived, checked, onToggle }: DeptRowProps) {
  const { t } = useTranslation()
  return (
    <Checkbox
      checked={checked.has(dept.id)}
      onCheckedChange={() => onToggle(dept.id)}
      wrapperClassName="min-w-0 flex-1"
      label={
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate" title={dept.path_name}>{showPath ? dept.path_name : dept.name}</span>
          {archived && <Tag size="small">{t('log.org.archived')}</Tag>}
        </span>
      }
      description={dept.dept_id}
    />
  )
}

interface TreeNodeProps extends SelectionProps {
  dept: AuditDeptNode
  tenantId?: number | null
  depth: number
}

function TreeNode({ dept, tenantId, depth, checked, onToggle }: TreeNodeProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const children = useAuditDepartmentChildren(tenantId, dept.id, open && dept.has_children)
  const toggleLabel = t(open ? 'log.org.collapse' : 'log.org.expand', { name: dept.name })
  return (
    <li>
      <div className="flex items-start gap-1" style={{ paddingLeft: depth * 16 }}>
        {dept.has_children
          ? (
            <button type="button" aria-label={toggleLabel} aria-expanded={open} onClick={() => setOpen(!open)}
              className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent">
              {open ? <Outlined.Down size={14} aria-hidden /> : <Outlined.Right size={14} aria-hidden />}
            </button>
          )
          : <span className="size-5 shrink-0" />}
        <DeptCheckbox dept={dept} checked={checked} onToggle={onToggle} />
      </div>
      {open && children.isInitialLoading && <p role="status" className="py-1 text-xs text-muted-foreground" style={{ paddingLeft: (depth + 1) * 16 + 20 }}>{t('log.org.loading')}</p>}
      {open && children.isError && (
        <p role="alert" className="py-1 text-xs" style={{ paddingLeft: (depth + 1) * 16 + 20 }}>
          {t('log.org.loadFailed')} <Button size="small" variant="link" onClick={() => void children.refetch()}>{t('log.org.retry')}</Button>
        </p>
      )}
      {open && !!children.data?.active.length && (
        <ul>
          {children.data.active.map(child => (
            <TreeNode key={child.id} dept={child} tenantId={tenantId} depth={depth + 1} checked={checked} onToggle={onToggle} />
          ))}
        </ul>
      )}
    </li>
  )
}

/** Global super outside an admin scope gets one root per tenant (AC-27). */
const groupByTenant = (nodes: AuditDeptNode[]): [number, AuditDeptNode[]][] => {
  const groups = new Map<number, AuditDeptNode[]>()
  nodes.forEach(node => groups.set(node.tenant_id, [...(groups.get(node.tenant_id) ?? []), node]))
  return [...groups.entries()]
}

export function OrgPanelBody({
  tenantId, keyword, checked, onToggle, includeNone, includeUnrecorded, onIncludeNone, onIncludeUnrecorded,
}: OrgPanelBodyProps) {
  const { t } = useTranslation()
  const roots = useAuditDepartmentRoots(tenantId, keyword, true)
  if (roots.isInitialLoading) return <p role="status" className="py-4 text-center text-sm text-muted-foreground">{t('log.org.loading')}</p>
  if (roots.isError || !roots.data) {
    return (
      <div role="alert" className="py-4 text-center text-sm">
        {t('log.org.loadFailed')} <Button size="small" variant="link" onClick={() => void roots.refetch()}>{t('log.org.retry')}</Button>
      </div>
    )
  }
  const { active, archived, show_none: showNone, show_unrecorded: showUnrecorded } = roots.data
  const searching = !!keyword
  const groups = searching ? [] : groupByTenant(active)
  const empty = !active.length && !archived.length && !showNone && !showUnrecorded
  return (
    <div className="flex flex-col gap-3">
      {empty && <p className="py-4 text-center text-sm text-muted-foreground">{t('log.org.empty')}</p>}
      {searching && !!active.length && (
        <ul className="flex flex-col gap-1">
          {active.map(dept => <li key={dept.id}><DeptCheckbox dept={dept} showPath checked={checked} onToggle={onToggle} /></li>)}
        </ul>
      )}
      {!searching && groups.map(([tenant, nodes]) => (
        <div key={tenant}>
          {groups.length > 1 && <p className="pb-1 text-xs font-medium text-muted-foreground">{t('log.org.tenantGroup', { id: tenant })}</p>}
          <ul className="flex flex-col gap-1">
            {nodes.map(dept => <TreeNode key={dept.id} dept={dept} tenantId={tenantId} depth={0} checked={checked} onToggle={onToggle} />)}
          </ul>
        </div>
      ))}
      {!!archived.length && (
        <section aria-label={t('log.org.archivedSection')}>
          <p className="pb-1 text-xs font-medium text-muted-foreground">{t('log.org.archivedSection')}</p>
          <ul className="flex flex-col gap-1">
            {archived.map(dept => <li key={dept.id}><DeptCheckbox dept={dept} showPath archived checked={checked} onToggle={onToggle} /></li>)}
          </ul>
        </section>
      )}
      {(showNone || showUnrecorded) && !searching && (
        <div className="flex flex-col gap-1 border-t pt-2">
          {showNone && <Checkbox checked={includeNone} onCheckedChange={value => onIncludeNone(value === true)} label={t('log.org.none')} />}
          {showUnrecorded && <Checkbox checked={includeUnrecorded} onCheckedChange={value => onIncludeUnrecorded(value === true)} label={t('log.org.unrecorded')} />}
        </div>
      )}
    </div>
  )
}
