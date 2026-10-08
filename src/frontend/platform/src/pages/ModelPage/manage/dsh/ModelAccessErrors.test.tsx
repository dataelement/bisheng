import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import request from '@/controllers/request'
import { getDshModelSubjects, getDshModelUserPermissions, getDshOperation, saveDshPolicy } from '@/controllers/API/dsh'
import { ModelAccessDialog } from './ModelAccessDialog'

vi.mock('@/components/bs-icons/loading/Load.svg?react', () => ({ default: () => <svg /> }))
vi.mock('@/components/bs-ui/toast/use-toast', () => ({ useToast: () => ({ message: vi.fn() }), toast: vi.fn() }))
vi.mock('@/controllers/API/dsh', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/controllers/API/dsh')>(),
    getDshModelSubjects: vi.fn(), getDshModelUserPermissions: vi.fn(),
    getDshOperation: vi.fn(), saveDshPolicy: vi.fn(),
}))
const model = { id: 7, name: 'Model' }
const originalAdapter = request.defaults.adapter

beforeEach(() => {
    vi.resetAllMocks()
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.mocked(getDshModelSubjects).mockResolvedValue({
        tenant_id: 2, model_id: 7, roles: [],
        departments: [{
            subject_type: 'DEPARTMENT', subject_id: 31, name: 'Organization',
            parent_id: null, depth: 0, version: 1, enabled: false, monthly_token_limit: 0,
        }],
    })
    vi.mocked(getDshModelUserPermissions).mockResolvedValue({
        tenant_id: 2, model: { ...model, is_root_shared: false }, next_cursor: null, has_more: false,
        items: [{
            user_id: 20, user_name: 'Alice', direct_version: 0, direct_enabled: false,
            direct_monthly_token_limit: 0, direct_pending_operation_id: null,
            departments: [{ id: 31, name: 'Organization', is_primary: true }],
            roles: [], authorized: false, monthly_token_limit: 0, sources: [], department_match: 'DIRECT',
        }],
    })
})
afterEach(() => {
    request.defaults.adapter = originalAdapter
    vi.unstubAllGlobals()
})

it.each([
    [26112, 'dsh.seatLimitGrantHelp'],
    [26113, 'dsh.seatRevokedGrantHelp'],
    [11001, 'api_errors:11001'],
    [26115, 'api_errors:26115'],
    [26125, 'api_errors:26125'],
    [26130, 'api_errors:26130'],
])('shows department save error %s through the real API and interceptor', async (code, key) => {
    const adapter = vi.fn(async (config) => ({
        status: 200, statusText: 'OK', headers: {}, config,
        data: { status_code: code, status_message: 'Service rejected the request' },
    }))
    request.defaults.adapter = adapter
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Organization · dsh.editQuota' }))
    const input = screen.getByLabelText('Organization · dsh.configuredQuotaWan')
    fireEvent.change(input, { target: { value: '10000' } })
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(key)
    expect(adapter).toHaveBeenCalledOnce()
    expect(adapter.mock.calls[0][0]).toMatchObject({
        url: '/api/v1/dsh/admin/models/7/subjects/DEPARTMENT/31/policy',
        method: 'put', silent: true,
    })
    expect(input).toHaveValue('10000')
    expect(screen.getByRole('button', { name: 'save' })).toBeEnabled()
})

it('preserves an uncertain user operation while surfacing its service error', async () => {
    const failure = { response: { status: 503, data: { error: { code: 'authorization_unavailable' } } } }
    vi.mocked(saveDshPolicy).mockRejectedValue(failure)
    vi.mocked(getDshOperation).mockRejectedValue(failure)
    render(<ModelAccessDialog model={model} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice · dsh.editQuota' }))
    fireEvent.change(screen.getByLabelText('Alice · dsh.configuredQuotaWan'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('api_errors:26125')
    const operationId = vi.mocked(saveDshPolicy).mock.calls[0][3].operation_id
    fireEvent.click(screen.getByRole('button', { name: 'save' }))
    await waitFor(() => expect(getDshOperation).toHaveBeenCalledWith(operationId, '2', expect.any(AbortSignal)))
    expect(await screen.findByRole('alert')).toHaveTextContent('api_errors:26125')
    expect(saveDshPolicy).toHaveBeenCalledOnce()
})
