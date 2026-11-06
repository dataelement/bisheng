// Pure rendering rules for the system-audit table and its CSV export
// (F056 AC-17 / AC-21 / AC-29 / AC-32). Kept free of React so the table cell,
// the export row and the tests all read the same functions — a column that
// renders one way on screen and another in the file is the kind of drift a
// compliance reviewer notices first.

import type { AuditAppOption, AuditRow } from "@/types/api/audit"

export type { AuditAppOption, AuditRow }

export type Translate = (key: string, opts?: Record<string, unknown>) => string

/** Structured v2 action → camelCase `log.eventTypeEnum` leaf key (see log.ts). */
type ActionKeyFn = (action: string) => string

export const renderSystemId = (log: AuditRow, t: Translate): string => {
    if (log.system_id) return t(`log.systemIdEnum.${log.system_id}`)
    if (log.action) {
        const ns = String(log.action).split('.')[0]
        return t(`log.systemIdEnum.${ns}`, { defaultValue: ns })
    }
    return '-'
}

export const renderEventType = (log: AuditRow, t: Translate, actionToKey: ActionKeyFn): string => {
    if (log.event_type) return t(`log.eventTypeEnum.${log.event_type}`)
    if (log.action) {
        const key = actionToKey(log.action)
        return t(`log.eventTypeEnum.${key}`, { defaultValue: log.action })
    }
    return '-'
}

export const renderObjectType = (log: AuditRow, t: Translate): string => {
    if (log.object_type) return t(`log.objectTypeEnum.${log.object_type}`)
    if (log.target_type) return t(`log.objectTypeEnum.${log.target_type}`, { defaultValue: log.target_type })
    return t('log.objectTypeEnum.none')
}

/**
 * Object cell. For a hosted-application row: name snapshot + identifier, a
 * "deleted" marker when the application is gone (AC-21), and the version the
 * event was about when the writer recorded one. Everything else keeps the
 * legacy `object_name` / `target_id` fallback.
 */
export const renderObjectName = (log: AuditRow, t: Translate): string => {
    if (!log.app_id) return log.object_name || log.target_id || t('log.objectTypeEnum.none')
    const name = log.app_name || log.object_name || log.app_id
    const parts = [log.app_slug ? `${name} (${log.app_slug})` : name]
    if (log.version_no) parts.push(t('log.versionLabel', { no: log.version_no }))
    if (log.app_state === 'deleted') parts.push(t('log.deletedSuffix'))
    return parts.join(' · ')
}

export interface OperatorCell {
    /** Who acted: user name, or service-account name with its key mask. */
    primary: string
    /** Only for service accounts: the kind plus the application owner (AC-17). */
    secondary: string | null
}

export const renderOperator = (log: AuditRow, t: Translate): OperatorCell => {
    const name = log.operator_name || (log.operator_id === 0 ? 'system' : String(log.operator_id))
    if (log.operator_kind !== 'service_account') return { primary: name, secondary: null }
    const primary = log.operator_key_mask ? `${name} (${log.operator_key_mask})` : name
    const owner = log.app_owner_name ? ` · ${t('log.appOwner')}: ${log.app_owner_name}` : ''
    return { primary, secondary: `${t('log.serviceAccount')}${owner}` }
}

/** Label for the object-application selector: `name (slug)` + deleted marker. */
export const appOptionLabel = (app: AuditAppOption, t: Translate): string => {
    const base = `${app.name} (${app.slug})`
    return app.state === 'deleted' ? `${base} · ${t('log.deletedSuffix')}` : base
}

/**
 * Selector rows must never carry an empty value — a Radix `SelectItem` with
 * `''` takes the whole page down (root AGENTS.md).
 */
export const toAppOptions = (apps: AuditAppOption[], t: Translate): { label: string; value: string }[] =>
    apps.filter(app => !!app.id).map(app => ({ label: appOptionLabel(app, t), value: app.id }))

export interface CsvOptions {
    /** Add the tenant column (global super on a multi-tenant deployment, AC-30). */
    withTenant: boolean
}

/** Header row + one row per log, in the table's column order (AC-32). */
export const buildAuditCsv = (
    logs: AuditRow[],
    t: Translate,
    actionToKey: ActionKeyFn,
    { withTenant }: CsvOptions,
): string[][] => {
    const header = [
        t('log.auditId'),
        t('log.username'),
        t('log.operationTime'),
        t('log.systemModule'),
        t('log.operationAction'),
        t('log.objectType'),
        t('log.operationObject'),
        t('log.appSlug'),
        ...(withTenant ? [t('log.tenant')] : []),
        t('log.ipAddress'),
        t('log.remark'),
        t('log.reason'),
    ]
    const rows = logs.map(log => {
        const operator = renderOperator(log, t)
        return [
            log.id,
            operator.secondary ? `${operator.primary} · ${operator.secondary}` : operator.primary,
            (log.create_time || '').replace('T', ' '),
            renderSystemId(log, t),
            renderEventType(log, t, actionToKey),
            renderObjectType(log, t),
            renderObjectName(log, t),
            log.app_slug || '',
            ...(withTenant ? [log.tenant_name || (log.tenant_id != null ? String(log.tenant_id) : '')] : []),
            log.ip_address || '',
            log.note || '',
            log.reason || '',
        ]
    })
    return [header, ...rows]
}
