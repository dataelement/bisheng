import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RuntimeAuditCell } from '@/pages/LogPage/runtime/RuntimeAuditCell'

describe('runtime audit identity and missing-value presentation', () => {
  it('shows an execution user name and never substitutes the app owner', () => {
    const view = render(<RuntimeAuditCell kind="model" field="subject_name"
      row={{ subject_kind: 'user', subject_id: 3, subject_name: 'Current user', actor_name: 'Caller' }} />)
    expect(screen.getByText('Current user')).toBeVisible()
    view.rerender(<RuntimeAuditCell kind="model" field="subject_name"
      row={{ subject_kind: 'app_self', subject_id: null, actor_name: 'Owner is not the visitor' }} />)
    expect(screen.getByText('log.runtime.values.app_self')).toBeVisible()
    expect(screen.queryByText('Owner is not the visitor')).not.toBeInTheDocument()
    view.rerender(<RuntimeAuditCell kind="model" field="subject_name"
      row={{ subject_kind: 'service_account', subject_id: 8, subject_name: null }} />)
    expect(screen.getByText('log.runtime.accountWithId')).toBeVisible()
  })

  it('distinguishes no result, an unrecorded value and a real zero', () => {
    const view = render(<RuntimeAuditCell kind="capability" field="chunk_count"
      row={{ result: 'refused', chunk_count: null }} />)
    expect(screen.getByText('log.runtime.noResult')).toBeVisible()
    view.rerender(<RuntimeAuditCell kind="capability" field="chunk_count"
      row={{ result: 'success', chunk_count: 0 }} />)
    expect(screen.getByText('0')).toBeVisible()
    view.rerender(<RuntimeAuditCell kind="model" field="total_tokens" row={{ total_tokens: null }} />)
    expect(screen.getByText('log.runtime.notRecorded')).toBeVisible()
  })
})
