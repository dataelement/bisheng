import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useComponentEditorStore } from '@/store/dashboardStore'
import { ChartType, type DashboardComponent } from '../../types/dataConfig'
import { useComponentConfigController } from './ComponentConfigDrawer'
import { FULL_DEFAULT_STYLE_CONFIG } from './dashboardStyleDefaults'

vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: [], isLoading: false }) }))
afterEach(() => { cleanup(); useComponentEditorStore.setState({ editingComponent: null, hasChange: false }) })
it('keeps existing graph fields, result limits and chart data during controller extraction', async () => {
    const component: DashboardComponent = { id: 'chart-1', dashboard_id: 'board-1', title: 'Chart', type: ChartType.Bar, dataset_code: 'dataset-1', create_time: '', update_time: '', style_config: FULL_DEFAULT_STYLE_CONFIG,
        data_config: { dimensions: [{ fieldId: 'country', fieldCode: 'country', fieldName: 'Country', sort: null, timeGranularity: null }], metrics: [{ fieldId: 'revenue', fieldCode: 'revenue', fieldName: 'Revenue', aggregation: 'sum', sort: null, isVirtual: false, numberFormat: { type: 'number', decimalPlaces: 0, thousandSeparator: false } }], fieldOrder: [], filters: [], resultLimit: { limitType: 'limited', limit: 100 }, isConfigured: true } }
    useComponentEditorStore.setState({ editingComponent: component })
    const { result } = renderHook(() => useComponentConfigController())
    await waitFor(() => expect(result.current.valueDimensions).toHaveLength(1))
    act(() => { result.current.setLimitType('limit'); result.current.setLimitValue('25') })
    act(() => result.current.handleUpdateChart({ isTrusted: false }))
    const saved = useComponentEditorStore.getState().editingComponent!
    expect(saved.dataset_code).toBe('dataset-1')
    expect(saved.data_config).toMatchObject({ resultLimit: { limitType: 'limited', limit: 25 }, dimensions: [expect.objectContaining({ fieldId: 'country' })], metrics: [expect.objectContaining({ fieldId: 'revenue', aggregation: 'sum' })] })
})

it('keeps the saved chart binding until the selected dataset has matching fields', async () => {
    const component: DashboardComponent = {
        id: 'chart-1', dashboard_id: 'board-1', title: 'Chart', type: ChartType.Metric,
        dataset_code: 'knowledge', create_time: '', update_time: '', style_config: FULL_DEFAULT_STYLE_CONFIG,
        data_config: {
            dimensions: [], fieldOrder: [], filters: [], isConfigured: true, resultLimit: { limitType: 'all' },
            metrics: [{ fieldId: 'knowledge_count', fieldCode: 'knowledge_count', fieldName: 'Knowledge count',
                aggregation: 'sum', sort: null, isVirtual: false,
                numberFormat: { type: 'number', decimalPlaces: 0, thousandSeparator: false } }],
        },
    }
    useComponentEditorStore.setState({ editingComponent: component })
    const { result } = renderHook(() => useComponentConfigController())
    await waitFor(() => expect(result.current.valueDimensions).toHaveLength(1))

    act(() => result.current.handleDatasetChange('users'))
    act(() => result.current.handleUpdateChart({ isTrusted: false }))
    expect(useComponentEditorStore.getState().editingComponent).toEqual(component)

    act(() => result.current.setDatasetFields([
        { fieldCode: 'user_count', displayName: 'Users', fieldType: 'number', role: 'metric' },
    ]))
    act(() => result.current.chartState.setValueDimensions(dims =>
        dims.map(dim => ({ ...dim, fieldId: 'user_count', fieldCode: 'user_count' })),
    ))
    act(() => result.current.handleUpdateChart({ isTrusted: false }))
    expect(useComponentEditorStore.getState().editingComponent).toMatchObject({
        dataset_code: 'users',
        data_config: { metrics: [expect.objectContaining({ fieldId: 'user_count' })] },
    })
})
