import { expect, it } from 'vitest'
import type { AuditScope } from '@/controllers/API/log'
import { auditScopeDescription } from './auditScopeDescription'

const copy: Record<string, string> = {
  'log.scope.summary': '当前范围：{{tenant}}，{{organization}}',
  'log.scope.allTenants': '全部租户',
  'log.scope.tenant': '租户「{{name}}」',
  'log.scope.allOrganizations': '全部组织',
  'log.scope.subtree': '{{name}}及其下级',
  'log.scope.exact': '仅「{{name}}」',
  'log.scope.noOrganization': '没有可查看的组织',
  'log.scope.separator': '、',
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
    '当前范围：全部租户，全部组织',
  )
})

it('names the tenant and each authorized department', () => {
  expect(
    auditScopeDescription(
      scope({
        tenant_id: 60,
        tenant_name: '测试子租户1',
        organizations: [
          { name: '研发部', includes_descendants: true },
          { name: '财务部', includes_descendants: false },
        ],
      }),
      t,
    ),
  ).toBe('当前范围：租户「测试子租户1」，研发部及其下级、仅「财务部」')
})

it('says when the authorized range contains no department', () => {
  expect(auditScopeDescription(scope({ tenant_id: 60, tenant_name: '测试子租户1' }), t)).toBe(
    '当前范围：租户「测试子租户1」，没有可查看的组织',
  )
})
