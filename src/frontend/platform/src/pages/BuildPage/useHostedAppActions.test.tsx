import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useHostedAppActions } from './useHostedAppActions'
import { resumeHostedAppApi, type HostedAppActionResult } from '@/controllers/API/hostedApp'

vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({
  bsConfirm: (options: { onOk: (next: () => void) => void }) => options.onOk(() => {}),
}))
vi.mock('@bisheng/ui', () => ({ notification: { open: vi.fn() } }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/controllers/API/hostedApp', () => ({
  resumeHostedAppApi: vi.fn(), stopHostedAppApi: vi.fn(), deleteHostedAppApi: vi.fn(),
  manualPublishHostedAppApi: vi.fn(), getHostedAppErrorMessage: vi.fn(),
}))

describe('hosted app action verdicts', () => {
  it('does not report a capacity refusal as a successful state change', async () => {
    const refusal: HostedAppActionResult = {
      app_id: 'app-a', state: 'pending_capacity', version_id: 'version-a', ok: false, reason: 'capacity',
    }
    vi.mocked(resumeHostedAppApi).mockResolvedValueOnce(refusal)
    const onChanged = vi.fn()
    const { result } = renderHook(() => useHostedAppActions({ onChanged }))
    let changed: boolean | undefined
    await act(async () => { changed = await result.current.resumeApp({ appId: 'app-a', name: 'test' }) })
    expect(changed).toBe(false)
    expect(onChanged).toHaveBeenCalledWith('resume', refusal)
  })
})
