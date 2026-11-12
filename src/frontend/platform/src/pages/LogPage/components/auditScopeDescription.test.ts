import { expect, it } from 'vitest'
import type { AuditScope } from '@/controllers/API/log'
import zh from '../../../../public/locales/zh-Hans/bs.json'
import { auditScopeDescription } from './auditScopeDescription'

const scopeCopy = zh.log.scope
const copy: Record<string, string> = {
  'log.scope.summary': scopeCopy.summary,
  'log.scope.allTenants': scopeCopy.allTenants,
  'log.scope.tenant': scopeCopy.tenant,
  'log.scope.allOrganizations': scopeCopy.allOrganizations,
  'log.scope.subtree': scopeCopy.subtree,
  'log.scope.exact': scopeCopy.exact,
  'log.scope.noOrganization': scopeCopy.noOrganization,
  'log.scope.separator': scopeCopy.separator,
}

const t = (key: string, opts?: Record<string, unknown>) =>
  Object.entries(opts ?? {}).reduce(
    (text, [name, value]) => text.replaceAll(`{{${name}}}`, String(value)),
    copy[key],
  )

const scope = (patch: Partial<AuditScope>): AuditScope => ({
  tenant_id: null,
  tenant_name: null,
  unrestricted_organization: false,
  organizations: [],
  ...patch,
})

it('names every tenant and organization when the reader is not limited', () => {
  expect(auditScopeDescription(scope({ unrestricted_organization: true }), t)).toBe(
    t('log.scope.summary', {
      tenant: t('log.scope.allTenants'),
      organization: t('log.scope.allOrganizations'),
    }),
  )
})

it('names the tenant and each authorized department', () => {
  const tenantName = 'child-tenant'
  const parent = 'research'
  const leaf = 'finance'
  expect(
    auditScopeDescription(
      scope({
        tenant_id: 60,
        tenant_name: tenantName,
        organizations: [
          { name: parent, includes_descendants: true },
          { name: leaf, includes_descendants: false },
        ],
      }),
      t,
    ),
  ).toBe(
    t('log.scope.summary', {
      tenant: t('log.scope.tenant', { name: tenantName }),
      organization: [t('log.scope.subtree', { name: parent }), t('log.scope.exact', { name: leaf })].join(
        t('log.scope.separator'),
      ),
    }),
  )
})

it('says when the authorized range contains no department', () => {
  const tenantName = 'child-tenant'
  expect(auditScopeDescription(scope({ tenant_id: 60, tenant_name: tenantName }), t)).toBe(
    t('log.scope.summary', {
      tenant: t('log.scope.tenant', { name: tenantName }),
      organization: t('log.scope.noOrganization'),
    }),
  )
})
