import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getDshPolicy, saveDshPolicy } from '@/controllers/API/dsh'
import { getUsersApi } from '@/controllers/API/user'
import type { User } from '@/types/api/user'
import type { DshPolicy } from '@/types/dsh'
import { PolicyView } from './PolicyView'
import { UsageSummary } from './UsageSummary'
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/controllers/API/dsh', () => ({
    getDshPolicy: vi.fn(),
    saveDshPolicy: vi.fn(),
    isDshRequestRejected: () => false,
}))
vi.mock('@/controllers/API/user', () => ({ getUsersApi: vi.fn() }))
const policy: DshPolicy = {
    tenant_id: 2,
    version: 0,
    models: [],
    quota_sync_state: 'PENDING',
    usage: null,
    available_models: [
        { id: 7, name: 'Verified shared model', is_root_shared: true },
    ],
    available_models_source: 'live',
    last_call_source: 'persisted',
    last_call: {
        request_id: 'call-20',
        model_id: 7,
        status: 'USAGE_UNKNOWN',
        started_at: '2026-09-09T00:00:00Z',
        finished_at: null,
        total_tokens: null,
        projected_at: '2026-09-09T00:00:01Z',
    },
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getUsersApi).mockResolvedValue({
        data: [{ user_id: 20, user_name: 'Child user' } as User],
        total: 1,
    })
    vi.mocked(getDshPolicy).mockResolvedValue(policy)
    vi.mocked(saveDshPolicy).mockRejectedValue(new Error('Uncertain'))
})
describe('policy target and governed model view', () => {
    it('shows usage without a seat and directs authorization to model management', async () => {
        render(<PolicyView />)
        fireEvent.click(await screen.findByText('Child user'))
        await screen.findByText(/call-20/)
        expect(getDshPolicy).toHaveBeenCalledWith('20', undefined, expect.any(AbortSignal))
        expect(screen.getByText('dsh.usageScope')).toBeTruthy()
        expect(screen.queryByText('dsh.save')).toBeNull()
        expect(vi.mocked(getUsersApi).mock.calls[0][0]).not.toHaveProperty('withDepartmentPath')
    })
    it('distinguishes absent persisted history from unavailable history', () => {
        const { rerender } = render(
            <UsageSummary
                usage={null}
                modelNames={{}}
                lastCall={null}
                lastCallSource="persisted"
            />,
        )
        expect(screen.getByText('dsh.noLastCall')).toBeTruthy()
        rerender(
            <UsageSummary
                usage={null}
                modelNames={{}}
                lastCall={null}
                lastCallSource="unavailable"
            />,
        )
        expect(screen.getByText('dsh.lastCallUnavailable')).toBeTruthy()
        expect(screen.queryByText('dsh.noLastCall')).toBeNull()
    })
})
