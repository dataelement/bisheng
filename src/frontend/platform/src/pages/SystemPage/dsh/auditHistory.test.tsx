import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getDshAuditRecords } from '@/controllers/API/dshAudit'
import type { DshAuditRecord } from '@/types/dshAudit'
import { AuditHistory } from './AuditHistory'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }) }))
vi.mock('@/controllers/API/dshAudit', () => ({ getDshAuditRecords: vi.fn() }))

const record: DshAuditRecord = {
    id: 'operation:1', created_at: '2026-09-16T01:00:00Z', action: 'UPDATE_POLICY', status: 'FAILED',
    actor_id: 1, actor_name: 'admin', target_type: 'USER', target_id: 2, target_name: 'alice', model_id: 4, model_name: 'qwen',
    before_values: { monthly_token_limit: 100 }, after_values: {}, requested_values: { monthly_token_limit: 200 }, result_code: 'quota_sync_failed',
}
const page = { data: [record], page_size: 20, has_more: false, next_cursor: null }

beforeEach(() => { vi.resetAllMocks(); vi.mocked(getDshAuditRecords).mockResolvedValue(page) })

describe('persisted DSH audit history', () => {
    it('centers the result header and every status badge in the same column', async () => {
        const statuses = ['SUCCEEDED', 'FAILED', 'PENDING', 'PROCESSING'] as const
        vi.mocked(getDshAuditRecords).mockResolvedValue({
            ...page,
            data: statuses.map((status) => ({ ...record, id: `operation:${status}`, status })),
        })
        render(<AuditHistory />)
        await screen.findByText('dsh.SUCCEEDED')
        expect(screen.getByRole('columnheader', { name: 'dsh.auditHistory.result' })).toHaveClass('text-center')
        for (const status of statuses) {
            expect(screen.getByText(`dsh.${status}`).closest('td')).toHaveClass('text-center')
        }
    })

    it('loads on first open, remount and refresh, and shows failed submitted values separately', async () => {
        const first = render(<AuditHistory />)
        await screen.findByText('alice')
        expect(screen.getByText('2026/09/16 09:00:00')).toBeTruthy()
        expect(screen.getByText('dsh.FAILED')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'dsh.auditHistory.details' }))
        expect(screen.getByText('dsh.auditHistory.requested')).toBeTruthy()
        expect(screen.getByText('100')).toBeTruthy()
        expect(screen.getByText('200')).toBeTruthy()
        const signal = vi.mocked(getDshAuditRecords).mock.calls[0][1]
        first.unmount()
        expect(signal?.aborted).toBe(true)
        render(<AuditHistory />)
        await screen.findByText('alice')
        fireEvent.click(screen.getByRole('button', { name: 'dsh.refresh' }))
        await waitFor(() => expect(getDshAuditRecords).toHaveBeenCalledTimes(3))
        await screen.findByText('alice')
    })

    it('loads both policy sources and resets paging when a type filter changes', async () => {
        vi.mocked(getDshAuditRecords).mockResolvedValueOnce({ ...page, has_more: true, next_cursor: 'next' })
            .mockResolvedValueOnce({ ...page, data: [{ ...record, id: 'subject:2', action: 'UPDATE_ROLE_POLICY', target_type: 'ROLE', target_name: 'reviewers' }] })
            .mockResolvedValue(page)
        render(<AuditHistory />)
        await screen.findByText('alice')
        fireEvent.click(screen.getByRole('button', { name: 'dsh.next' }))
        await screen.findByText('reviewers')
        expect(getDshAuditRecords).toHaveBeenLastCalledWith({ limit: 20, cursor: 'next' }, expect.any(AbortSignal))
        fireEvent.click(screen.getByRole('combobox', { name: 'dsh.action' }))
        fireEvent.click(await screen.findByRole('option', { name: 'dsh.auditHistory.actions.UPDATE_DEPARTMENT_POLICY' }))
        await waitFor(() => expect(getDshAuditRecords).toHaveBeenLastCalledWith({ limit: 20, cursor: undefined, action: 'UPDATE_DEPARTMENT_POLICY' }, expect.any(AbortSignal)))
        expect(screen.queryByRole('button', { name: 'dsh.previous' })).toBeNull()
    })

    it('distinguishes query failure from a true empty page and permits retry', async () => {
        vi.mocked(getDshAuditRecords).mockRejectedValueOnce(new Error('unavailable')).mockResolvedValue({ ...page, data: [] })
        render(<AuditHistory />)
        expect(await screen.findByRole('alert')).toHaveTextContent('dsh.auditHistory.loadError')
        expect(screen.queryByText('dsh.auditHistory.empty')).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'dsh.refresh' }))
        await screen.findByText('dsh.auditHistory.empty')
        expect(screen.queryByRole('alert')).toBeNull()
    })

    it('keeps deleted targets visible by ID and labels background operations', async () => {
        vi.mocked(getDshAuditRecords).mockResolvedValue({ ...page, data: [{ ...record, target_name: null, actor_id: null, actor_name: null, model_name: null, action: 'SYNC_PROFILE' }] })
        render(<AuditHistory />)
        await screen.findByText('dsh.auditHistory.system')
        expect(screen.getByText('#2')).toBeTruthy()
        expect(screen.getByText('#4')).toBeTruthy()
    })
})
