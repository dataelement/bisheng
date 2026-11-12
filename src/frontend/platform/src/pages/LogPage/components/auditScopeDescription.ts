import type { AuditScope } from '@/controllers/API/log'

type Translate = (key: string, opts?: Record<string, unknown>) => string

/** One sentence for the audit-page banner. Filters never change this boundary. */
export function auditScopeDescription(scope: AuditScope, t: Translate): string {
  const tenant = scope.tenant_id == null
    ? t('log.scope.allTenants')
    : t('log.scope.tenant', { name: scope.tenant_name || String(scope.tenant_id) })
  const organization = scope.unrestricted_organization
    ? t('log.scope.allOrganizations')
    : scope.organizations.length
      ? scope.organizations
          .map((org) =>
            org.includes_descendants
              ? t('log.scope.subtree', { name: org.name })
              : t('log.scope.exact', { name: org.name }),
          )
          .join(t('log.scope.separator'))
      : t('log.scope.noOrganization')
  return t('log.scope.summary', { tenant, organization })
}
