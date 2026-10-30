import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { HostedAppCard } from '@/pages/BuildPage/HostedAppCard'
vi.mock('react-router-dom',()=>({useNavigate:()=>vi.fn()}))
vi.mock('@/pages/BuildPage/useHostedAppActions',()=>({useHostedAppActions:()=>({stopApp:vi.fn(),resumeApp:vi.fn(),deleteApp:vi.fn()})}))
vi.mock('@/components/bs-comp/cardComponent',()=>({default:({onDelete}:{onDelete?:()=>void})=>onDelete?<button>delete</button>:null}))
it.each([
  [7,false,false,true],
  [8,false,true,true],
  [8,false,false,false],
  [8,true,true,true],
])('allows platform super admins alongside the original owner (%s, %s, %s)',(uid,inactive,admin,allowed)=>{
 render(<HostedAppCard item={{id:'app',name:'App',user_id:7,owner_active:!inactive}} currentUser={{user_id:uid,is_global_super:admin}} isAdmin={admin} canDelete canSwitch={false} canManagePermission={false} onPermission={vi.fn()} onChanged={vi.fn()} />)
 expect(Boolean(screen.queryByRole('button',{name:'delete'}))).toBe(allowed)
})
