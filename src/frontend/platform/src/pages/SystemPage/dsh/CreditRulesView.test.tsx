import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { CreditRulesView } from './CreditRulesView'
import { getCreditRules, getPolicySubjects, saveCreditRule } from '@/controllers/API/dshUnified'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/dshUnified', () => ({ getCreditRules: vi.fn(), getPolicySubjects: vi.fn(), saveCreditRule: vi.fn() }))
vi.mock('@/components/bs-comp/selectComponent/Users', () => ({ default: () => null }))
vi.mock('@/utils/dshRequestError', () => ({ getDshRequestErrorKey: () => 'dsh.conflict' }))
beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
    Element.prototype.hasPointerCapture = vi.fn(() => false)
    Element.prototype.releasePointerCapture = vi.fn()
    vi.mocked(getCreditRules).mockResolvedValue([])
    vi.mocked(getPolicySubjects).mockResolvedValue([{ kind: 'DEPARTMENT', id: 10, name: 'Engineering', depth: 0 }])
    vi.mocked(saveCreditRule).mockResolvedValue({ subject_type: 'DEPARTMENT', subject_id: 10, version: 1, enabled: true, monthly_credits: '500' })
})
it('sets a model-independent allowance and renders the saved rule', async () => {
    render(<CreditRulesView />)
    fireEvent.keyDown(await screen.findByRole('combobox', { name: 'dsh.unified.selectSubject' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Engineering' }))
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.save' }))
    await waitFor(() => expect(saveCreditRule).toHaveBeenCalledWith({ kind: 'DEPARTMENT', id: 10 }, { version: 0, enabled: true, monthly_credits: '500' }))
    expect(await screen.findByText('dsh.unified.DEPARTMENT · Engineering')).toBeInTheDocument()
})
it('keeps the exact credit draft on conflict and rejects excessive precision', async () => {
    vi.mocked(saveCreditRule).mockRejectedValue(new Error('conflict'))
    render(<CreditRulesView />)
    fireEvent.keyDown(await screen.findByRole('combobox', { name: 'dsh.unified.selectSubject' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Engineering' }))
    const input = screen.getByLabelText('dsh.unified.monthlyCredits')
    fireEvent.change(input, { target: { value: '0.0000001' } })
    expect(screen.getByRole('button', { name: 'dsh.unified.save' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '0.000001' } })
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.conflict')
    expect(input).toHaveValue('0.000001')
})
