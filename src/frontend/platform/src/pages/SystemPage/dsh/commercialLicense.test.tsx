import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CommercialLicenseDialog } from './CommercialLicenseDialog'
import { licenseStatusKey } from './licensePresentation'
import { copyText } from '@/utils'
import type { DshLicense } from '@/types/dsh'

vi.mock('@/utils', () => ({ copyText: vi.fn().mockResolvedValue(undefined) }))
vi.mock('react-i18next', async () => {
    const { createInstance } = await import('i18next')
    const { default: messages } = await import('../../../../public/locales/en-US/bs.json')
    const instance = createInstance()
    await instance.init({ lng: 'en', resources: { en: { translation: messages } } })
    return { useTranslation: () => ({ t: instance.t.bind(instance) }) }
})
const license: DshLicense = { status: 'active', source: 'builtin', assigned: 1, seat_limit: 10, available: 9, as_of: '', expires_at: null, license_id: 'builtin-dsh-10' }

describe('commercial License request', () => {
    it('prepares the same complete request for preview, email and clipboard', async () => {
        render(<CommercialLicenseDialog open onOpenChange={vi.fn()} license={license} tenantName="Acme" />)
        const preview = screen.getByRole('textbox', { name: 'DSH Enterprise License Request' }) as HTMLTextAreaElement
        expect(preview.value).toContain('Please help us obtain a commercial License.')
        expect(preview.value).toContain('Company: Acme')
        expect(preview.value).toContain('Seats required: [Please fill in]')
        expect(preview.value).toContain(window.location.origin)
        const link = screen.getByRole('link', { name: 'bisheng@dataelem.com' })
        const email = new URL(link.getAttribute('href')!)
        expect(email.pathname).toBe('bisheng@dataelem.com')
        expect(email.searchParams.get('body')).toBe(preview.value)
        fireEvent.click(screen.getByRole('button', { name: 'Copy request' }))
        await waitFor(() => expect(copyText).toHaveBeenCalledWith(preview.value))
    })
    it.each([
        ['builtin', 'active', 'free'],
        ['signed', 'active', 'commercial'],
        ['signed', 'expired', 'expired'],
        ['signed', 'invalid', 'invalid'],
        [undefined, 'active', 'active'],
    ] as const)('derives edition from source %s and state %s', (source, status, expected) => {
        expect(licenseStatusKey({ ...license, source, status })).toBe(expected)
    })
})
