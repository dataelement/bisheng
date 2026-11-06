import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import Header from './Header'

vi.mock('@/store/assistantStore', () => ({ useAssistantStore: () => ({ assistantState: { id: 'fixture', name: 'Assistant', status: 0 }, dispatchAssistant: vi.fn() }) }))
vi.mock('@/components/bs-comp/permission/useResourceActions', () => ({ useResourceActions: () => ({ actions: {} }), hasResourceAction: () => false }))
vi.mock('@/components/bs-comp/permission/PermissionDialog', () => ({ PermissionDialog: () => null }))
vi.mock('@/components/bs-comp/cardComponent/avatar', () => ({ default: () => null }))
vi.mock('./EditAssistantDialog', () => ({ default: () => null }))
afterEach(cleanup)
it('switches assistant editor and publishing views through the existing callback', () => {
    const onTabChange = vi.fn()
    render(<MemoryRouter><Header loca={{}} canEdit onSave={vi.fn()} onLine={vi.fn()} onTabChange={onTabChange} /></MemoryRouter>)
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'api.externalPublishing' }), { button: 0, ctrlKey: false })
    expect(onTabChange).toHaveBeenLastCalledWith('api')
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'api.assistantOrchestration' }), { button: 0, ctrlKey: false })
    expect(onTabChange).toHaveBeenLastCalledWith('edit')
})
it('keeps external publishing unavailable to read-only editors', () => {
    render(<MemoryRouter><Header loca={{}} canEdit={false} onSave={vi.fn()} onLine={vi.fn()} onTabChange={vi.fn()} /></MemoryRouter>)
    expect(screen.queryByText('api.externalPublishing')).not.toBeInTheDocument()
    expect(screen.getByText('api.assistantOrchestration')).toBeInTheDocument()
})
