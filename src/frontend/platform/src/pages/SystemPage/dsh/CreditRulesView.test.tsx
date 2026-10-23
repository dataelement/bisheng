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
function switchTab(name: string) {
    fireEvent.mouseDown(screen.getByRole('tab', { name }), { button: 0, ctrlKey: false })
}
async function addDepartment() {
    await waitFor(() => expect(screen.getByRole('button', { name: 'dsh.unified.addCredits' })).toBeEnabled())
    switchTab('dsh.unified.DEPARTMENT')
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
    fireEvent.change(input, { target: { value: '0.0000001' } })
    expect(screen.getByRole('button', { name: 'dsh.unified.save' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '0.000001' } })
    fireEvent.click(screen.getByRole('button', { name: 'dsh.unified.save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('dsh.conflict')
    expect(input).toHaveValue('0.000001')
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
    switchTab('dsh.unified.DEPARTMENT')
    expect(screen.getByText('Engineering')).toBeInTheDocument()
    expect(screen.queryByText('Alice')).toBeNull()
    switchTab('dsh.unified.ROLE')
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
