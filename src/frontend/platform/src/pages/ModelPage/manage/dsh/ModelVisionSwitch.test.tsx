import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ModelVisionSwitch } from './ModelVisionSwitch'
import { saveModelVision } from '@/controllers/API/systemModelSettings'
import type { ModelVisionRow } from '@/controllers/API/modelPricing'
import { showApiError } from '@/controllers/request'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/systemModelSettings', () => ({ saveModelVision: vi.fn() }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
afterEach(cleanup)
const row: ModelVisionRow = {
    model_id: 42, vision: false, effective: false, owner_tenant_id: 1, owner_vision: true,
    source: 'local_restriction', can_edit: true, read_only: false, status: 'available', reason: null,
}

it('saves an explicitly edited capability and refreshes the page batch', async () => {
    vi.mocked(saveModelVision).mockResolvedValue({ ...row, vision: true, effective: true })
    const refresh = vi.fn().mockResolvedValue(undefined)
    render(<ModelVisionSwitch modelId={42} row={row} onSaved={refresh} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    expect(saveModelVision).toHaveBeenCalledWith(42, true)
})

it('retains the confirmed value and reports a save failure once', async () => {
    const failure = new Error('offline')
    vi.mocked(saveModelVision).mockRejectedValue(failure)
    render(<ModelVisionSwitch modelId={42} row={row} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(failure))
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('switch')).not.toBeDisabled()
})

it('does not send requests while capability is unknown or not editable', () => {
    const page = render(<ModelVisionSwitch modelId={42} onSaved={vi.fn()} />)
    expect(screen.getByRole('switch')).toBeDisabled()
    page.rerender(<ModelVisionSwitch modelId={42} row={{ ...row, can_edit: false }} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('switch'))
    expect(saveModelVision).not.toHaveBeenCalled()
})
