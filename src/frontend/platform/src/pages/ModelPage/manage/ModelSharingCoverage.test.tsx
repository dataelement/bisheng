import { fireEvent, render, screen } from '@/test/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { getModelSharingStatus } from '@/controllers/API/systemModelSettings'
import { ModelSharingCoverage } from './ModelSharingCoverage'

vi.mock('@/controllers/API/systemModelSettings', () => ({ getModelSharingStatus: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, params?: { count?: number }) =>
    params?.count === undefined ? key : `${key}:${params.count}` }) }))
afterEach(() => vi.clearAllMocks())

it('loads coverage only on demand and reports actual legacy recipients', async () => {
    vi.mocked(getModelSharingStatus).mockResolvedValue({
        enabled: null, version: 0, shared_child_ids: [19, 60], expected_child_ids: [], missing_child_ids: [], active_plan: null,
    })
    render(<ModelSharingCoverage serverId={337} />)
    expect(getModelSharingStatus).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'model.sharingCoverage' }))
    expect(await screen.findByText('model.sharingUnknown')).toBeVisible()
    expect(screen.getByText('model.sharingExistingCount:2')).toBeVisible()
})

it('keeps pending operation and missing recipients visible without submitting a mutation', async () => {
    vi.mocked(getModelSharingStatus).mockResolvedValue({
        enabled: true, version: 1, shared_child_ids: [19], expected_child_ids: [19, 69], missing_child_ids: [69],
        active_plan: { id: 'pending-plan', state: 'PREPARING', operation: 'model_share_server' },
    })
    render(<ModelSharingCoverage serverId={358} />)
    fireEvent.click(screen.getByRole('button', { name: 'model.sharingCoverage' }))
    expect(await screen.findByText('model.sharingMissing:1')).toBeVisible()
    expect(screen.getByText('model.sharingPending')).toBeVisible()
})
