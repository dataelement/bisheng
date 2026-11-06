import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SystemModelConfig from './SystemModelConfig'

const { readScope, getTenants } = vi.hoisted(() => ({
    readScope: vi.fn(() => ({ scope: { scope_tenant_id: null } })),
    getTenants: vi.fn().mockResolvedValue({ data: [] }),
}))
vi.mock('@/contexts/userContext', async () => {
    const { createContext } = await import('react')
    return { userContext: createContext({ user: { is_child_admin: true } }) }
})
vi.mock('@/hooks/useAdminScope', () => ({ useAdminScope: readScope }))
vi.mock('@/controllers/API/tenant', () => ({ getTenantsApi: getTenants }))
vi.mock('./tabs/WorkbenchModel', () => ({ default: () => <div>workbench settings</div> }))
vi.mock('./tabs/KnowledgeModel', () => ({ KnowledgeModel: () => <div>knowledge settings</div> }))
vi.mock('./tabs/AssisModel', () => ({ default: () => <div>assistant settings</div> }))
vi.mock('./tabs/EvaluationModel', () => ({ default: () => <div>evaluation settings</div> }))
vi.mock('./tabs/WorkflowModel', () => ({ default: () => <div>workflow settings</div> }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('system model settings navigation', () => {
    it('keeps the requested tab and notifies the page when switching panels', () => {
        const onTabChange = vi.fn()
        render(<SystemModelConfig data={[]} defaultTab="knowledge" onBack={vi.fn()} onTabChange={onTabChange} />)
        expect(screen.getByText('knowledge settings')).toBeVisible()
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'model.assistantModel' }), { button: 0, ctrlKey: false })
        expect(onTabChange).toHaveBeenCalledWith('assis')
        expect(screen.getByText('assistant settings')).toBeVisible()
        expect(screen.queryByText('knowledge settings')).not.toBeInTheDocument()
    })
    it('does not issue super-admin requests for a child admin and keeps the back action', () => {
        const onBack = vi.fn()
        render(<SystemModelConfig data={[]} onBack={onBack} />)
        expect(readScope).toHaveBeenCalledWith({ enabled: false })
        expect(getTenants).not.toHaveBeenCalled()
        fireEvent.click(screen.getByRole('button', { name: 'back' }))
        expect(onBack).toHaveBeenCalledOnce()
    })
})
