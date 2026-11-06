// AC coverage: AC-78, AC-79, AC-81, AC-83.
import { expect,it } from 'vitest'
import { appActionState } from '@/pages/BuildPage/hostedApp/appActions'
import type { HostedAppAction } from '@/controllers/API/hostedApp'

it('separates basic management from private content and never uses owner identity',()=>{
  expect(appActionState(['visible']).management).toBe(false)
  for(const action of ['edit','publish','unpublish','delete','manage_permission'] as const){
    const state=appActionState([action])
    expect(state.management).toBe(true)
    expect(state.edit).toBe(action==='edit')
    expect(state.rebuild).toBe(false)
  }
  expect(appActionState(['edit','publish']).rebuild).toBe(true)
  expect(appActionState(undefined).management).toBe(false)
  expect(appActionState([]).management).toBe(false)
})

it.each(['use', 'unknown'])('does not infer management from unexpected wire action %s', action => {
  const state = appActionState([action as HostedAppAction])
  expect(state).toEqual({ management: false, edit: false, publish: false,
    unpublish: false, delete: false, managePermission: false, rebuild: false })
})


import {render,screen,cleanup} from '@testing-library/react'
import {MemoryRouter,Routes,Route} from 'react-router-dom'
import {vi,afterEach} from 'vitest'
import {HostedAppDetail} from '@/pages/BuildPage/hostedApp'
const fixture=vi.hoisted(()=>({actions:['publish']}))
vi.mock('@/pages/BuildPage/hostedApp/hooks/useHostedApp',()=>({useHostedApp:()=>({app:{app_id:'a',slug:'a',name:'A',state:'stopped',allowed_actions:fixture.actions},loading:false,reload:vi.fn(),reloadInstance:vi.fn()})}))
vi.mock('@/pages/BuildPage/hostedApp/hooks/usePublishStatus',()=>({usePublishStatus:()=>({status:null,reload:vi.fn()})}))
vi.mock('@/pages/BuildPage/hostedApp/Header',()=>({HostedAppHeader:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/tabs/PublishTab',()=>({PublishTab:({settingsSlot}:{settingsSlot:React.ReactNode})=><div>{settingsSlot}</div>}))
vi.mock('@/pages/BuildPage/hostedApp/tabs/DataTab',()=>({DataTab:()=> <span>private-data</span>}))
vi.mock('@/pages/BuildPage/hostedApp/tabs/LogsTab',()=>({LogsTab:()=> <span>private-logs</span>}))
vi.mock('@/pages/BuildPage/hostedApp/tabs/VersionsTab',()=>({VersionsTab:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/publish/VersionDiff',()=>({VersionDiff:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/publish/AppSecretSettings',()=>({AppSecretSettings:()=> <span>private-secrets</span>}))
vi.mock('@/pages/BuildPage/hostedApp/publish/VisibilityScopeSection',()=>({VisibilityScopeSection:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/publish/ApprovalStatusCard',()=>({ApprovalStatusCard:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/publish/VersionListCard',()=>({VersionListCard:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/publish/DangerZoneCard',()=>({DangerZoneCard:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/publish/TierSelectCard',()=>({TierSelectCard:()=>null}))
vi.mock('@/pages/BuildPage/hostedApp/publish/CapabilityListCard',()=>({CapabilityListCard:()=>null}))
afterEach(cleanup)
function detail(){return render(<MemoryRouter initialEntries={['/build/apps/a?tab=data']}><Routes><Route path='/build/apps/:appId' element={<HostedAppDetail/>}/></Routes></MemoryRouter>)}
it('publish-only direct data-tab URL mounts no private data or environment component',()=>{
 fixture.actions=['publish'];detail()
 expect(screen.queryByText('private-data')).toBeNull()
 expect(screen.queryByText('private-secrets')).toBeNull()
 expect(screen.queryByRole('tab',{name:'hostedApp.detail.tabs.data'})).toBeNull()
})
it('edit mounts the requested private tab',()=>{
 fixture.actions=['edit'];detail()
 expect(screen.getByText('private-data')).toBeInTheDocument()
})
it('visible-only direct data-tab URL mounts no private tab or environment component',()=>{
 fixture.actions=['visible'];detail()
 expect(screen.queryByText('private-data')).toBeNull()
 expect(screen.queryByText('private-secrets')).toBeNull()
 expect(screen.queryByRole('tab',{name:'hostedApp.detail.tabs.data'})).toBeNull()
})
