import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import type { DimensionItem, MetricFormat } from './DimensionBlock'
import { MetricFormatDialog } from './MetricFormatDialog'

afterEach(cleanup)
const metric: DimensionItem = { id: 'metric-1', name: 'Revenue', displayName: 'Revenue', originalName: 'Revenue', sort: null, fieldType: 'metric' }
function Dialog({ save }: { save: (id: string, format: MetricFormat) => void }) {
    const [format, setFormat] = useState<MetricFormat | null>({ type: 'number', decimalPlaces: 0, thousandSeparator: true, unit: '1000', suffix: 'USD' })
    const [editing, setEditing] = useState<DimensionItem | null>(metric)
    const [open, setOpen] = useState(true)
    return <MetricFormatDialog {...{ formatDialogOpen: open, setFormatDialogOpen: setOpen, editingMetric: editing, setEditingMetric: setEditing, localFormat: format, setLocalFormat: setFormat, onFormatChange: save }} />
}
it('keeps percentage format rules and the saved schema', () => {
    const save = vi.fn()
    render(<Dialog save={save} />)
    fireEvent.click(screen.getByRole('radio', { name: 'dimensionBlock.dialog.formatTypes.percent' }))
    fireEvent.click(screen.getByRole('button', { name: 'chartSelector.buttons.save' }))
    expect(save).toHaveBeenCalledWith('metric-1', { type: 'percent', decimalPlaces: 2, thousandSeparator: false, unit: undefined, suffix: 'USD' })
})
it('preserves decimal bounds and storage defaults', () => {
    const save = vi.fn()
    render(<Dialog save={save} />)
    fireEvent.click(screen.getByRole('radio', { name: 'dimensionBlock.dialog.formatTypes.storage' }))
    fireEvent.input(screen.getByRole('spinbutton'), { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'chartSelector.buttons.save' }))
    expect(save).toHaveBeenCalledWith('metric-1', expect.objectContaining({ type: 'storage', decimalPlaces: 5, unit: 'B' }))
})
