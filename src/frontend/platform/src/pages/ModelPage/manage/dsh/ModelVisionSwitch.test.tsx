import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import request from '@/controllers/request'
import { ModelVisionSwitch } from './ModelVisionSwitch'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/request', () => ({ default: { get: vi.fn(), put: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())
afterEach(cleanup)

it('loads persisted capability and saves changes', async () => {
    vi.mocked(request.get).mockResolvedValue({ vision: false })
    vi.mocked(request.put).mockResolvedValue({ vision: true })
    render(<ModelVisionSwitch modelId={42} />)
    const control = screen.getByRole('switch')
    await waitFor(() => expect(control).not.toBeDisabled())
    fireEvent.click(control)
    await waitFor(() => expect(control).toHaveAttribute('aria-checked', 'true'))
    expect(request.put).toHaveBeenCalledWith('/api/v1/dsh/admin/models/42/vision', { vision: true }, { timeout: 15000 })
})

it('retains the confirmed value when saving fails', async () => {
    vi.mocked(request.get).mockResolvedValue({ vision: false })
    vi.mocked(request.put).mockRejectedValue(new Error('failed'))
    render(<ModelVisionSwitch modelId={42} />)
    const control = screen.getByRole('switch')
    await waitFor(() => expect(control).not.toBeDisabled())
    fireEvent.click(control)
    await screen.findByText('model.visionRetry')
    expect(control).toHaveAttribute('aria-checked', 'false')
    expect(control).not.toBeDisabled()
})

it('keeps the switch unavailable when capability could not be read', async () => {
    vi.mocked(request.get).mockRejectedValue(new Error('failed'))
    render(<ModelVisionSwitch modelId={42} />)
    await screen.findByText('model.visionRetry')
    expect(screen.getByRole('switch')).toBeDisabled()
})
