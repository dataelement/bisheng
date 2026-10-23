import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppSecretSettings } from './AppSecretSettings'

const { save, rebuild, confirm, row } = vi.hoisted(() => ({ save: vi.fn(), rebuild: vi.fn(), confirm: vi.fn(), row: { name: 'COLOR', present: true, mask: '••••••', updated_at: '2026-10-24T00:00:00', approved_reference: true, pending_reference: false } }))
vi.mock('../hooks/useAppSecrets', () => ({ useAppSecrets: () => ({ data: { revision: 1, items: [row], runtime: { comparison: 'different', changed_names: ['COLOR'], running_version_id: 'v1', route_epoch: 3, rebuild_operation: null } }, save, rebuild, remove: vi.fn(), refresh: vi.fn(), loading: false, busy: false }) }))
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: confirm }))
vi.mock('@bisheng/ui', () => ({ Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props} />, Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />, Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> }))

describe('environment settings', () => {
  beforeEach(() => { row.present = true; row.updated_at = '2026-10-24T00:00:00'; vi.clearAllMocks() })
  it('allows deleting a saved empty value without treating an absent declaration as stored', () => {
    row.present = false
    const { unmount } = render(<AppSecretSettings appId="a" canManage />)
    expect(screen.getByText('hostedApp.secrets.remove')).toBeInTheDocument()
    unmount()
    row.updated_at = ''
    render(<AppSecretSettings appId="a" canManage />)
    expect(screen.queryByText('hostedApp.secrets.remove')).not.toBeInTheDocument()
  })
  it('replacing starts an empty draft; saving is separate from rebuilding', () => {
    render(<AppSecretSettings appId="a" canManage />)
    fireEvent.click(screen.getByText('hostedApp.secrets.replace'))
    expect(screen.getByLabelText('hostedApp.secrets.value')).toHaveValue('')
    expect(rebuild).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('hostedApp.secrets.cancel'))
    expect(screen.queryByLabelText('hostedApp.secrets.value')).not.toBeInTheDocument()
  })
  it('opens confirmation without calling rebuild and gives administrators no write buttons', () => {
    const { unmount } = render(<AppSecretSettings appId="a" canManage />)
    fireEvent.click(screen.getByText('hostedApp.secrets.rebuild'))
    expect(confirm).toHaveBeenCalled()
    expect(rebuild).not.toHaveBeenCalled()
    unmount()
    render(<AppSecretSettings appId="a" canManage={false} />)
    expect(screen.queryByText('hostedApp.secrets.replace')).not.toBeInTheDocument()
    expect(screen.queryByText('hostedApp.secrets.rebuild')).not.toBeInTheDocument()
  })
})
