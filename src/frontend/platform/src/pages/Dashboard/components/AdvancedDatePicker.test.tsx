import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AdvancedDatePicker } from './AdvancedDatePicker'

afterEach(cleanup)
it('keeps relative date and dynamic checkbox values in the existing timestamp payload', () => {
    const onChange = vi.fn()
    render(<AdvancedDatePicker placeholder="Choose dates" onChange={onChange} mode="range" granularity="day" />)
    fireEvent.click(screen.getByRole('button', { name: 'Choose dates' }))
    fireEvent.click(screen.getByRole('button', { name: 'shortcut.last_7' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'dynamicUpdate' }))
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ shortcutKey: 'last_7', isDynamic: true, startTime: expect.any(Number), endTime: expect.any(Number) }))
    const { startTime, endTime } = onChange.mock.calls[0][0] as { startTime: number; endTime: number }
    expect(endTime).toBeGreaterThan(startTime)
    expect(startTime).toBeLessThan(1e11)
})
