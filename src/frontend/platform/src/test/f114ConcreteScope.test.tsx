import { beforeEach,expect,it,vi } from 'vitest'
import { acceptManagementScope,managementRequestScope,requiresManagementScope } from '@/controllers/managementScope'
beforeEach(()=>acceptManagementScope(null))
it('protects only dedicated management writes; shared reads and calls keep their contract',()=>{
  expect(requiresManagementScope('get','/api/v1/apps/a')).toBe(false)
  expect(requiresManagementScope('post','/api/v2/assistant/invoke')).toBe(false)
  expect(requiresManagementScope('post','/api/v1/apps/a/versions/v/preview?purpose=approval')).toBe(false)
  expect(requiresManagementScope('post','/api/v1/apps/a/actions/resume')).toBe(true)
  expect(requiresManagementScope('patch','/api/v1/apps/a/data/tables/t/rows/1')).toBe(true)
})
it('never derives an authorization scope from saved browser storage or global values',()=>{
  vi.stubGlobal('localStorage',{getItem:vi.fn(()=> '999'),setItem:vi.fn()})
  expect(managementRequestScope()).toBeNull()
  acceptManagementScope('3')
  expect(managementRequestScope()).toBe(3)
  acceptManagementScope('global')
  expect(managementRequestScope()).toBe(3)
})
