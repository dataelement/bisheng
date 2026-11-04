import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
function selectScope(name: string) {
    fireEvent.click(screen.getByRole('radio', { name }))
}
async function addDepartment() {
    await waitFor(() => expect(screen.getByRole('button', { name: 'dsh.unified.addCredits' })).toBeEnabled())
    selectScope('dsh.byDepartment')
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.addCredits' }))
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'dsh.unified.selectSubject' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Engineering' }))
}
it('adds an allowance in the selected scope', async () => {
    render(<CreditRulesView />)
    await addDepartment()
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.save' }))
    await waitFor(() => expect(saveCreditRule).toHaveBeenCalledWith({ kind: 'DEPARTMENT', id: 10 }, { version: 0, enabled: true, monthly_credits: '500' }))
    expect(await screen.findByText('Engineering')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).toBeNull()
})
it('keeps the exact credit draft on conflict and rejects excessive precision', async () => {
    vi.mocked(saveCreditRule).mockRejectedValue(new Error('conflict'))
    render(<CreditRulesView />)
    await addDepartment()
    const input = screen.getByLabelText('dsh.unified.monthlyCredits')
    fireEvent.change(input, { target: { value: '0.01' } })
    expect(screen.getByRole('button', { name: 'dsh.unified.save' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '0.1' } })
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.conflict')
    expect(input).toHaveValue('0.1')
})
it('separates scopes and saves edits within their original row', async () => {
    vi.mocked(getCreditRules).mockResolvedValue([
        { subject_type: 'USER', subject_id: 2, name: 'Alice', version: 4, enabled: true, monthly_credits: '1000' },
        { subject_type: 'DEPARTMENT', subject_id: 10, name: 'Engineering', version: 1, enabled: true, monthly_credits: '5000' },
        { subject_type: 'ROLE', subject_id: 20, name: 'Editors', version: 1, enabled: true, monthly_credits: '8000' },
    ])
    vi.mocked(saveCreditRule).mockResolvedValue({ subject_type: 'USER', subject_id: 2, version: 5, enabled: true, monthly_credits: '10000' })
    render(<CreditRulesView />)
    const row = await screen.findByRole('row', { name: /Alice/ })
    expect(screen.queryByText('Engineering')).toBeNull()
    expect(screen.queryByText('Editors')).toBeNull()
    fireEvent.click(within(row).getByRole('button', { name: 'dsh.unified.edit' }))
    fireEvent.change(within(row).getByRole('textbox'), { target: { value: '10000' } })
    fireEvent.click(within(row).getByRole('button', { name: 'dsh.unified.save' }))
    await waitFor(() => expect(saveCreditRule).toHaveBeenCalledWith({ kind: 'USER', id: 2 }, { version: 4, enabled: true, monthly_credits: '10000' }))
    await waitFor(() => expect(within(row).queryByRole('textbox')).toBeNull())
    expect(within(row).getByText('10000')).toBeInTheDocument()
    selectScope('dsh.byDepartment')
    expect(screen.getByText('Engineering')).toBeInTheDocument()
    expect(screen.queryByText('Alice')).toBeNull()
    selectScope('dsh.byRole')
    expect(screen.getByText('Editors')).toBeInTheDocument()
    expect(screen.queryByText('Engineering')).toBeNull()
})
it('cancels a row edit without changing the saved allowance', async () => {
    vi.mocked(getCreditRules).mockResolvedValue([{ subject_type: 'USER', subject_id: 2, name: 'Alice', version: 4, enabled: true, monthly_credits: '1000' }])
    render(<CreditRulesView />)
    fireEvent.click(await screen.findByRole('button', { name: 'dsh.unified.edit' }))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '5000' } })
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.cancel' }))
    expect(screen.getByText('1000')).toBeInTheDocument()
    expect(saveCreditRule).not.toHaveBeenCalled()
})

// Allowance bounds and decimal precision match the backend input contract.
it.each(['1000000.1', '1000001', '9999999999999'])('blocks an overflowing credit allowance %s before saving', async credits => {
    render(<CreditRulesView />)
    await addDepartment()
    const input = screen.getByLabelText('dsh.unified.monthlyCredits')
    fireEvent.change(input, { target: { value: credits } })
    expect(input).toHaveValue(credits)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('dsh.unified.creditRangeHint')
    expect(screen.getByRole('button', { name: 'dsh.unified.save' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.save' }))
    expect(saveCreditRule).not.toHaveBeenCalled()
})
it('saves the exact maximum and recovers from an overflowing draft', async () => {
    render(<CreditRulesView />)
    await addDepartment()
    const input = screen.getByLabelText('dsh.unified.monthlyCredits')
    fireEvent.change(input, { target: { value: '1000000.1' } })
    expect(screen.getByRole('button', { name: 'dsh.unified.save' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '1000000' } })
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByRole('button', { name: 'dsh.unified.save' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.save' }))
    await waitFor(() => expect(saveCreditRule).toHaveBeenCalledWith({ kind: 'DEPARTMENT', id: 10 }, {
        version: 0, enabled: true, monthly_credits: '1000000',
    }))
})

it('preserves an existing user allowance when an overflowing edit is cancelled', async () => {
    vi.mocked(getCreditRules).mockResolvedValue([{ subject_type: 'USER', subject_id: 2, name: 'Alice', version: 4, enabled: true, monthly_credits: '5000000' }])
    render(<CreditRulesView />)
    fireEvent.click(await screen.findByRole('button', { name: 'dsh.unified.edit' }))
    const input = screen.getByRole('textbox', { name: 'dsh.unified.monthlyCredits' })
    fireEvent.change(input, { target: { value: '9999999999999' } })
    expect(input).toHaveValue('9999999999999')
    expect(screen.getByRole('alert')).toHaveTextContent('dsh.unified.creditRangeHint')
    expect(screen.getByRole('alert')).toHaveClass('text-destructive')
    expect(screen.getByRole('button', { name: 'dsh.unified.save' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.cancel' }))
    expect(screen.getByText('5000000')).toBeInTheDocument()
    expect(saveCreditRule).not.toHaveBeenCalled()
})
