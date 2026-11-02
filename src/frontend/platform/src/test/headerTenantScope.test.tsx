import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import type { User } from '@/types/api/user'
import { HeaderTenantScope } from '@/components/HeaderTenantScope'
const mocks = vi.hoisted(() => ({ setScope: vi.fn(), tenants: vi.fn() }))
vi.mock('@/hooks/useAdminScope', () => ({ useAdminScope: () => ({ scope: { scope_tenant_id: 2 }, loading: false, setScope: mocks.setScope }) }))
vi.mock('@/controllers/API/tenant', () => ({ getTenantsApi: mocks.tenants }))
// Keep the production option values and onChange contract visible in this test.
vi.mock('@bisheng/ui', () => ({ notification: { open: vi.fn() }, Select: ({ options, value, onChange, ...props }: { options: {value: string | number; label: string}[]; value: string | number; onChange: (value: string) => void; 'aria-labelledby'?: string }) => <select aria-labelledby={props['aria-labelledby']} value={value} onChange={e => onChange(e.target.value)}>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select> }))
const user = { is_global_super: true } as User
beforeEach(() => {
 vi.clearAllMocks()
 mocks.tenants.mockResolvedValue({ data: [{id:1,tenant_name:'Root',status:'active'}, {id:2,tenant_name:'Child',status:'active'}, {id:null,tenant_name:'Invalid',status:'active'}],total:2 })
 mocks.setScope.mockResolvedValue(undefined)
})
function wrapper({children}: {children: React.ReactNode}) {return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>}
it('only shows the switcher to verified global administrators', () => {
 render(<HeaderTenantScope user={{is_global_super:false} as User} />, {wrapper})
 expect(screen.queryByRole('combobox')).toBeNull()
 expect(mocks.tenants).not.toHaveBeenCalled()
})
it('only offers concrete tenants and reloads effect-owned modules after selection', async () => {
 const refresh=vi.fn()
 render(<HeaderTenantScope user={user} onScopeChange={refresh} />, {wrapper})
 await screen.findByRole('option',{name:'Child'})
 expect(screen.queryByRole('option',{name:'tenant.adminScope.global'})).toBeNull()
 expect(screen.queryByRole('option',{name:'Invalid'})).toBeNull()
 fireEvent.change(screen.getByRole('combobox'),{target:{value:'1'}})
 await waitFor(()=>expect(mocks.setScope).toHaveBeenCalledWith(1))
 expect(refresh).toHaveBeenCalledOnce()
})
