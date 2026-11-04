import { fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getDshBrowserConfig, saveDshManagementSettings } from '@/controllers/API/dshSettings'
import { getModelListApi } from '@/controllers/API/finetune'
import { toast } from '@bisheng/ui'
import { SettingsPanel } from './SettingsPanel'
import { DshManagement } from './index'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, values?: Record<string, unknown>) => key === 'dsh.seatSummary' ? `Seats ${values?.assigned} / ${values?.limit}` : key }) }))
vi.mock('@/controllers/API/dshSettings', () => ({ getDshBrowserConfig: vi.fn(), saveDshManagementSettings: vi.fn() }))
vi.mock('@/controllers/API/finetune', () => ({ getModelListApi: vi.fn() }))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: { role: 'admin' } }) }))
vi.mock('./CreditRulesView', () => ({ CreditRulesView: () => <p>credit-content</p> }))
vi.mock('./PolicyView', () => ({ PolicyView: () => <p>usage-content</p> }))
vi.mock('./OperationStatus', () => ({ OperationStatus: () => null }))
vi.mock('@/pages/ModelPage/manage/tabs/WorkbenchModel', () => ({ default: () => <p>model-content</p> }))

beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(toast, 'show').mockImplementation(() => '')
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: false, download_url: null, launch_url: 'dsh-desktop://login' })
    vi.mocked(getModelListApi).mockResolvedValue([])
})

describe('DSH deployment and business settings', () => {
    it('opens credit settings by default and displays usage in its own section', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: null, launch_url: 'dsh-desktop://login' })
        const { rerender } = render(<DshManagement />)
        expect(await screen.findByText('credit-content')).toBeInTheDocument()
        expect(screen.queryByText('usage-content')).toBeNull()
        rerender(<DshManagement section="usage" />)
        expect(screen.getByText('usage-content')).toBeInTheDocument()
        expect(screen.queryByText('credit-content')).toBeNull()
    })
    it('opens the shared model permissions section', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: null, launch_url: 'dsh-desktop://login' })
        render(<DshManagement section="models" />)
        expect(await screen.findByText('model-content')).toBeInTheDocument()
        expect(screen.queryByText('credit-content')).toBeNull()
    })
    it('keeps settings accessible while business is disabled and avoids license/seat calls', async () => {
        render(<DshManagement />)
        await screen.findByRole('textbox', { name: /dsh.launchAddress/ })
        expect(screen.queryByRole('switch')).toBeNull()
        expect(screen.queryByText('credit-content')).toBeNull()
    })
    it('does not render management when deployment is disabled', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: false, enabled: false, download_url: null, launch_url: 'dsh-desktop://login' })
        render(<DshManagement />)
        await waitFor(() => expect(screen.queryByText('dsh.loading')).toBeNull())
        expect(screen.queryByText('dsh.accessSettings')).toBeNull()
    })
    it('saves the typed fields and never submits License settings', async () => {
        vi.mocked(saveDshManagementSettings).mockResolvedValue({ enabled: true, download_url: 'http://downloads.test/dsh', launch_url: 'dsh-desktop-test://login' })
        render(<SettingsPanel settings={{ enabled: false, download_url: null, launch_url: 'dsh-desktop://login' }} canEdit />)
        expect(screen.getByRole('textbox', { name: /dsh.downloadAddress/ })).toBeDisabled()
        expect(screen.getByRole('textbox', { name: /dsh.launchAddress/ })).toBeDisabled()
        fireEvent.click(screen.getByRole('button', { name: 'dsh.editSettings' }))
        expect(screen.getByRole('textbox', { name: /dsh.downloadAddress/ })).toBeEnabled()
        expect(saveDshManagementSettings).not.toHaveBeenCalled()
        fireEvent.change(screen.getByRole('textbox', { name: /dsh.downloadAddress/ }), { target: { value: 'http://downloads.test/dsh' } })
        fireEvent.change(screen.getByRole('textbox', { name: /dsh.launchAddress/ }), { target: { value: 'dsh-desktop-test://login' } })
        fireEvent.click(screen.getByText('dsh.saveSettings'))
        await waitFor(() => expect(toast.show).toHaveBeenCalledWith({ type: 'success', message: 'dsh.settingsSaved' }))
        expect(screen.queryByText('dsh.settingsSaved')).toBeNull()
        expect(screen.getByRole('button', { name: 'dsh.editSettings' })).toBeEnabled()
        expect(screen.getByRole('textbox', { name: /dsh.downloadAddress/ })).toBeDisabled()
        expect(saveDshManagementSettings).toHaveBeenCalledWith({ enabled: true, download_url: 'http://downloads.test/dsh', launch_url: 'dsh-desktop-test://login' })
    })
    it('retains the draft and shows a failure without claiming success', async () => {
        vi.mocked(saveDshManagementSettings).mockRejectedValue(new Error('Invalid URL'))
        render(<SettingsPanel settings={{ enabled: false, download_url: null, launch_url: 'dsh-desktop://login' }} canEdit />)
        expect(screen.getByRole('textbox', { name: /dsh.downloadAddress/ })).toBeDisabled()
        expect(screen.getByRole('textbox', { name: /dsh.launchAddress/ })).toBeDisabled()
        fireEvent.click(screen.getByRole('button', { name: 'dsh.editSettings' }))
        expect(screen.getByRole('textbox', { name: /dsh.downloadAddress/ })).toBeEnabled()
        expect(saveDshManagementSettings).not.toHaveBeenCalled()
        fireEvent.change(screen.getByRole('textbox', { name: /dsh.downloadAddress/ }), { target: { value: 'invalid' } })
        fireEvent.click(screen.getByText('dsh.saveSettings'))
        await screen.findByRole('alert')
        expect(screen.getByRole('textbox', { name: /dsh.downloadAddress/ })).toHaveValue('invalid')
        expect(screen.queryByText('dsh.settingsSaved')).toBeNull()
    })
    it('prevents tenant administrators from editing global settings', () => {
        render(<SettingsPanel settings={{ enabled: false, download_url: null, launch_url: 'dsh-desktop://login' }} canEdit={false} />)
        expect(screen.queryByRole('switch')).toBeNull()
        expect(screen.getByRole('textbox', { name: /dsh.downloadAddress/ })).toBeDisabled()
        expect(screen.queryByText('dsh.saveSettings')).toBeNull()
    })
    it('removes active management content on a fresh disabled response', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValueOnce({ management_enabled: true, enabled: true, download_url: null, launch_url: 'dsh-desktop://login' })
        render(<DshManagement />)
        await screen.findByText('credit-content')
        await act(async () => { window.dispatchEvent(new Event('dsh-settings-changed')) })
        await waitFor(() => expect(screen.queryByText('credit-content')).toBeNull())
        expect(screen.getByRole('textbox', { name: /dsh.launchAddress/ })).toBeTruthy()
    })
})
