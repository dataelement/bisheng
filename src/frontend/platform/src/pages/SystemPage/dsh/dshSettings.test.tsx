import { fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getDshBrowserConfig, saveDshManagementSettings } from '@/controllers/API/dshSettings'
import { getDshLicense } from '@/controllers/API/dsh'
import { SettingsPanel } from './SettingsPanel'
import { DshManagement } from './index'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/dshSettings', () => ({ getDshBrowserConfig: vi.fn(), saveDshManagementSettings: vi.fn() }))
vi.mock('@/controllers/API/dsh', () => ({ getDshLicense: vi.fn() }))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: { role: 'admin' } }) }))
vi.mock('./SeatsView', () => ({ SeatsView: () => <p>seat-content</p> }))
vi.mock('./PolicyView', () => ({ PolicyView: () => null }))
vi.mock('./OperationStatus', () => ({ OperationStatus: () => null }))

beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: false, download_url: null })
})

describe('DSH deployment and business settings', () => {
    it('keeps settings accessible while business is disabled and avoids license/seat calls', async () => {
        render(<DshManagement />)
        await screen.findByText('dsh.accessSettings')
        expect(screen.getByRole('switch')).not.toBeChecked()
        expect(screen.queryByText('seat-content')).toBeNull()
        expect(getDshLicense).not.toHaveBeenCalled()
    })
    it('does not render management when deployment is disabled', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: false, enabled: false, download_url: null })
        render(<DshManagement />)
        await waitFor(() => expect(screen.queryByText('dsh.loading')).toBeNull())
        expect(screen.queryByText('dsh.accessSettings')).toBeNull()
        expect(getDshLicense).not.toHaveBeenCalled()
    })
    it('saves the two typed fields and never submits License settings', async () => {
        vi.mocked(saveDshManagementSettings).mockResolvedValue({ enabled: true, download_url: 'http://downloads.test/dsh' })
        render(<SettingsPanel settings={{ enabled: false, download_url: null }} canEdit />)
        fireEvent.click(screen.getByRole('switch'))
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'http://downloads.test/dsh' } })
        fireEvent.click(screen.getByText('dsh.saveSettings'))
        await screen.findByText('dsh.settingsSaved')
        expect(saveDshManagementSettings).toHaveBeenCalledWith({ enabled: true, download_url: 'http://downloads.test/dsh' })
    })
    it('retains the draft and shows a failure without claiming success', async () => {
        vi.mocked(saveDshManagementSettings).mockRejectedValue(new Error('Invalid URL'))
        render(<SettingsPanel settings={{ enabled: false, download_url: null }} canEdit />)
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'invalid' } })
        fireEvent.click(screen.getByText('dsh.saveSettings'))
        await screen.findByRole('alert')
        expect(screen.getByRole('textbox')).toHaveValue('invalid')
        expect(screen.queryByText('dsh.settingsSaved')).toBeNull()
    })
    it('prevents tenant administrators from editing global settings', () => {
        render(<SettingsPanel settings={{ enabled: false, download_url: null }} canEdit={false} />)
        expect(screen.getByRole('switch')).toBeDisabled()
        expect(screen.getByRole('textbox')).toBeDisabled()
        expect(screen.queryByText('dsh.saveSettings')).toBeNull()
    })
    it('removes active management content on a fresh disabled response', async () => {
        vi.mocked(getDshBrowserConfig).mockResolvedValueOnce({ management_enabled: true, enabled: true, download_url: null })
        vi.mocked(getDshLicense).mockResolvedValue({ status: 'active', seat_limit: 10, assigned: 0, available: 10, as_of: '', expires_at: null, license_id: 'test' })
        render(<DshManagement />)
        await screen.findByText('seat-content')
        await act(async () => { window.dispatchEvent(new Event('dsh-settings-changed')) })
        await waitFor(() => expect(screen.queryByText('seat-content')).toBeNull())
        expect(screen.getByText('dsh.accessSettings')).toBeTruthy()
    })
})
