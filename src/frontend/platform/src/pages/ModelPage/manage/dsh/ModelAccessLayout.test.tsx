import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
    getDshModelSubjects,
    getDshModelUserPermissions,
    getDshOperation,
    saveDshPolicy,
} from '@/controllers/API/dsh'
import { ModelAccessDialog } from './ModelAccessDialog'
import type { DshSubjectPolicyInventory, DshModelUserPermissionPage } from '@/types/dsh'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: { name?: string }) => (options?.name ? `${key}: ${options.name}` : key),
    }),
}))
vi.mock('@/components/bs-icons/loading/Load.svg?react', () => ({ default: () => <svg /> }))
vi.mock('@/controllers/API/dsh', () => ({
    getDshModelSubjects: vi.fn(),
    getDshModelUserPermissions: vi.fn(),
    getDshOperation: vi.fn(),
    getDshModelPolicy: vi.fn(),
    saveDshPolicy: vi.fn(),
    saveDshSubjectPolicy: vi.fn(),
    isDshRequestRejected: () => false,
    isDshSeatLimitReached: () => false,
}))
const model = { id: 7, name: 'Model' }
const inventory: DshSubjectPolicyInventory = {
    tenant_id: 2,
    model_id: 7,
    departments: [
        {
            subject_type: 'DEPARTMENT',
            subject_id: 31,
            name: 'Organization',
            parent_id: null,
            depth: 0,
            version: 0,
            enabled: false,
            monthly_token_limit: 0,
        },
        {
            subject_type: 'DEPARTMENT',
            subject_id: 32,
            name: 'Engineering',
            parent_id: 31,
            depth: 1,
            version: 0,
            enabled: false,
            monthly_token_limit: 0,
        },
        {
            subject_type: 'DEPARTMENT',
            subject_id: 33,
            name: 'Platform',
            parent_id: 32,
            depth: 2,
            version: 0,
            enabled: false,
            monthly_token_limit: 0,
        },
    ],
    roles: [],
}
const userPage: DshModelUserPermissionPage = {
    tenant_id: 2,
    model: { ...model, is_root_shared: true },
    has_more: false,
    next_cursor: null,
    items: [
        {
            user_id: 1,
            user_name: 'User',
            direct_version: 0,
            direct_enabled: false,
            direct_monthly_token_limit: 0,
            direct_pending_operation_id: null,
            departments: [],
            roles: [],
            authorized: false,
            monthly_token_limit: 0,
            department_match: null,
            sources: [],
        },
    ],
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getDshModelSubjects).mockResolvedValue(inventory)
    vi.mocked(getDshModelUserPermissions).mockImplementation(async (_id, query) =>
        query.department_id ? { ...userPage, items: [] } : userPage,
    )
    vi.mocked(getDshOperation).mockRejectedValue(new Error('Pending'))
})
describe('model access layout', () => {
    it('expands roots with nested connectors, keeps descendants collapsed and permits root collapse', async () => {
        render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
        await screen.findByText('Engineering')
        expect(screen.queryByText('Platform')).toBeNull()
        const root = screen.getByRole('button', { name: 'Organization · ▾' })
        expect(root).toHaveAttribute('aria-expanded', 'true')
        const child = screen.getByRole('button', { name: 'Engineering · ▾' })
        expect(child).toHaveAttribute('aria-expanded', 'false')
        expect(screen.getByRole('navigation')).toBeTruthy()
        await waitFor(() =>
            expect(getDshModelUserPermissions).toHaveBeenCalledWith(
                7,
                expect.objectContaining({ department_id: 31, membership: 'DIRECT', include_seats: true }),
                expect.any(AbortSignal),
            ),
        )
        fireEvent.click(root)
        expect(screen.queryByText('Engineering')).toBeNull()
        fireEvent.change(screen.getByRole('textbox', { name: 'dsh.searchDepartmentsAndUsers' }), {
            target: { value: 'Platform' },
        })
        expect(screen.getByText('Organization')).toBeTruthy()
        expect(screen.getByText('Engineering')).toBeTruthy()
        expect(screen.getByText('Platform')).toBeTruthy()
    })
    it('keeps the single scrolling tree inside the bounded dialog', async () => {
        render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
        await screen.findByText('Engineering')
        expect(screen.getByRole('dialog')).toHaveClass('h-[88vh]', 'max-h-[calc(100vh-64px)]', 'min-h-0')
        expect(screen.queryByRole('tab')).toBeNull()
        expect(screen.getByRole('dialog').querySelector('.overflow-auto')).toBeTruthy()
    })
    it('omits pending help while retaining save query for the original pending operation', async () => {
        vi.mocked(getDshModelUserPermissions).mockResolvedValue({
            ...userPage,
            items: [{ ...userPage.items[0], direct_pending_operation_id: 'existing-operation' }],
        })
        render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
        await screen.findByText('Engineering')
        await waitFor(() => expect(screen.getByRole('button', { name: 'save' })).toBeEnabled())
        expect(screen.queryByText('dsh.savePendingHelp')).toBeNull()
        const save = screen.getByRole('button', { name: 'save' })
        expect(save).toBeEnabled()
        fireEvent.click(save)
        await waitFor(() => expect(getDshOperation).toHaveBeenCalled())
        expect(saveDshPolicy).not.toHaveBeenCalled()
    })
})
