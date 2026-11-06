import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FinetuneHead from './FinetuneHead'

vi.mock('@/controllers/API', () => ({ getAllServicesApi: vi.fn().mockResolvedValue([
    { id: null, server_name: 'Invalid service' }, { id: '', server_name: 'Empty service' },
]) }))
afterEach(cleanup)

describe('fine-tuning filters', () => {
    it('keeps a selected status when clicked again instead of sending an empty filter', async () => {
        const onFilter = vi.fn()
        render(<FinetuneHead onFilter={onFilter} onSearch={vi.fn()} rtClick={vi.fn()} onCreate={vi.fn()} />)
        const option = screen.getByRole('radio', { name: 'finetune.successful' })
        fireEvent.click(option)
        expect(onFilter).toHaveBeenLastCalledWith({ type: '4', rt: 'all' })
        fireEvent.click(option)
        expect(option).toHaveAttribute('aria-checked', 'true')
        expect(onFilter.mock.calls.every(([filter]) => filter.type !== '')).toBe(true)
        await waitFor(() => expect(screen.getByRole('combobox')).toBeVisible())
    })
})
