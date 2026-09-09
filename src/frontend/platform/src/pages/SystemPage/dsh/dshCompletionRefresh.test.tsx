import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { getDshLicense } from '@/controllers/API/dsh'
import type { DshOperation, DshOperationRef } from '@/types/dsh'
import { DshManagement } from './index'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/dsh', () => ({ getDshLicense: vi.fn() }))
vi.mock('./PolicyView', () => ({ PolicyView: () => null }))
vi.mock('./OperationStatus', () => ({ OperationStatus: () => null }))
vi.mock('./SeatsView', () => ({ SeatsView: ({ revision, onOperation }: { revision: number; onOperation: (ref: DshOperationRef, result: DshOperation) => void }) => (
    <button onClick={() => onOperation({ operation_id: 'revoke-20', tenant_id: '2' }, { operation_id: 'revoke-20', action: 'REVOKE', status: 'SUCCEEDED' } as DshOperation)}>success-{revision}</button>
) }))
describe('seat terminal refresh', () => {
    it('refreshes license and seats once per successful operation, including duplicate result delivery', async () => {
        vi.mocked(getDshLicense).mockResolvedValue({ status: 'active', seat_limit: 10, assigned: 1, available: 9, as_of: '2026-09-09T00:00:00Z', license_id: 'fixture', expires_at: null })
        render(<DshManagement />)
        await waitFor(() => expect(getDshLicense).toHaveBeenCalledTimes(1))
        fireEvent.click(screen.getByText('success-0'))
        await waitFor(() => expect(getDshLicense).toHaveBeenCalledTimes(2))
        fireEvent.click(screen.getByText('success-1'))
        await screen.findByText('success-1')
        expect(getDshLicense).toHaveBeenCalledTimes(2)
    })
})
