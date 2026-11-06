import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useComponentEditorStore } from '@/store/dashboardStore'
import { ChartType, type DashboardComponent } from '../../types/dataConfig'
import { StyleConfigPanel } from './StyleConfigPanel'
import { FULL_DEFAULT_STYLE_CONFIG } from './dashboardStyleDefaults'

vi.mock('react-color', () => ({ SketchPicker: ({ onChangeComplete }: { onChangeComplete: (color: { hex: string }) => void }) => <button onClick={() => onChangeComplete({ hex: '#123456' })}>Pick color</button> }))
vi.mock('./StyleConfigControls', async (importOriginal) => {
    const original = await importOriginal<typeof import('./StyleConfigControls')>()
    return { ...original, TextFormat: ({ colorPicker }: { colorPicker?: React.ReactNode }) => <div>{colorPicker}</div> }
})
afterEach(() => { cleanup(); useComponentEditorStore.setState({ editingComponent: null }) })

it.each([
    { type: ChartType.Metric, fields: ['titleColor', 'metricColor', 'subtitleColor'] },
    { type: ChartType.Bar, fields: ['titleColor', 'xAxisColor', 'yAxisColor', 'legendColor'] },
])('retains working color pickers for every $type text format', ({ type, fields }) => {
    const style = { ...FULL_DEFAULT_STYLE_CONFIG, showSubtitle: true, showLegend: true }
    const component: DashboardComponent = { id: 'color-test', dashboard_id: '7', dataset_code: 'dataset-1', create_time: '', update_time: '', title: 'Colors', type, style_config: style, data_config: { dimensions: [], metrics: [], fieldOrder: [], filters: [], resultLimit: { limitType: 'all' }, isConfigured: false } }
    useComponentEditorStore.setState({ editingComponent: component, collapsedSections: { color: false, title: false, axis: false, legend: false, chartOptions: false } })
    const onChange = vi.fn()
    render(<StyleConfigPanel config={style} onChange={onChange} type={type} FULL_DEFAULT_STYLE_CONFIG={FULL_DEFAULT_STYLE_CONFIG} />)
    const pickers = screen.getAllByText('Pick color')
    expect(pickers).toHaveLength(fields.length)
    pickers.forEach((picker, index) => {
        fireEvent.click(picker)
        expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ [fields[index]]: '#123456' }))
    })
})
