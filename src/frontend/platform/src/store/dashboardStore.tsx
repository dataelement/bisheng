import { create } from "zustand"
import { generateUUID } from "@/components/bs-ui/utils"
import { Dashboard, DashboardComponent, LayoutItem, QueryConfig } from "@/pages/Dashboard/types/dataConfig"

// Chart refresh information
interface ChartRefreshInfo {
    trigger: number;           // Refresh trigger counter
    queryParams: any[];        // Array of associated query component parameters
}

interface EditorState {
    // Whether there are unsaved changes
    hasUnsavedChanges: boolean;
    // Whether currently saving
    isSaving: boolean;
    // Currently edited dashboard
    currentDashboard: Dashboard | null;
    // Layout configuration
    layouts: LayoutItem[];
    // Chart refresh triggers: each chart has its own trigger counter and query params
    chartRefreshTriggers: Record<string, ChartRefreshInfo>;

    // Set modification state
    setHasUnsavedChanges: (value: boolean) => void;
    // Set saving state
    setIsSaving: (value: boolean) => void;
    // Set current dashboard
    setCurrentDashboard: (dashboard: Dashboard | null) => void;
    // Update layout configuration
    setLayouts: (layouts: LayoutItem[]) => void;
    // Add component to layout
    addComponentToLayout: (componentId: string) => void;
    // Remove component from layout
    removeComponentFromLayout: (componentId: string) => void;
    // Update component
    updateComponent: (componentId: string, data: Partial<DashboardComponent>) => void;
    // Duplicate component
    duplicateComponent: (componentId: string) => void;
    // Delete component
    deleteComponent: (componentId: string) => void;
    // Refresh a single chart
    refreshChart: (chartId: string) => void;
    // Refresh charts linked to a query component
    refreshChartsByQuery: (queryComponentId: string) => void;
    // Refresh all charts
    refreshAllCharts: () => void;
    // Initialize auto-refresh on load
    initializeAutoRefresh: () => void;
    // Reset state
    reset: () => void;
}

export const useEditorDashboardStore = create<EditorState>((set, get) => ({
    hasUnsavedChanges: false,
    isSaving: false,
    currentDashboard: null,
    layouts: [],
    chartRefreshTriggers: {},

    setHasUnsavedChanges: (value) => set({ hasUnsavedChanges: value }),
    setIsSaving: (value) => set({ isSaving: value }),
    setCurrentDashboard: (dashboard) => {
        set({
            currentDashboard: dashboard,
            layouts: dashboard?.layout_config?.layouts || [],
            chartRefreshTriggers: {} // Reset triggers when dashboard changes
        })
    },
    setLayouts: (layouts) => {
        set({ layouts, hasUnsavedChanges: true })
    },
    addComponentToLayout: (componentId) => {
        const { layouts } = get()
        // 计算新组件的位置
        const maxY = layouts.length > 0 ? Math.max(...layouts.map(l => l.y + l.h)) : 0
        const newLayout: LayoutItem = {
            i: componentId,
            x: 0,
            y: maxY,
            w: 6,
            h: 4,
            minW: 2,
            minH: 2
        }
        set({ layouts: [...layouts, newLayout], hasUnsavedChanges: true })
    },
    removeComponentFromLayout: (componentId) => {
        const { layouts } = get()
        set({
            layouts: layouts.filter(l => l.i !== componentId),
            hasUnsavedChanges: true
        })
    },
    // Update component in the current dashboard
    updateComponent: (componentId: string, data: Partial<DashboardComponent>) => {
        const { currentDashboard } = get()
        if (!currentDashboard) {
            console.warn('updateComponent: currentDashboard is null')
            return
        }

        console.log('=== updateComponent 被调用 ===')
        console.log('组件ID:', componentId)
        console.log('更新数据:', data)
        console.log('更新前的组件:', currentDashboard.components.find(c => c.id === componentId))
        console.log('所有组件数量:', currentDashboard.components.length)

        const updatedComponents = currentDashboard.components.map(c => {
            if (c.id === componentId) {
                const updated = { ...c, ...data }
                console.log('更新后的组件:', updated)
                return updated
            }
            return c
        })

        console.log('更新后的组件列表:', updatedComponents)

        set({
            currentDashboard: {
                ...currentDashboard,
                components: updatedComponents
            },
            hasUnsavedChanges: true
        })

        // 验证更新是否成功
        const updatedState = get()
        const updatedComponent = updatedState.currentDashboard?.components.find(c => c.id === componentId)
        console.log('store 更新验证:', updatedComponent)
    },
    // Duplicate component
    duplicateComponent: (componentId: string) => {
        const { currentDashboard, layouts } = get()

        const component = currentDashboard.components.find((c) => c.id === componentId)
        const layoutItem = currentDashboard.layout_config.layouts.find((l) => l.i === componentId)
        // Create new component
        const newComponentId = `${component.type}-${generateUUID(8)}`
        const newComponent: DashboardComponent = {
            ...component,
            id: newComponentId,
            created_at: Date.now(),
            updated_at: Date.now()
        }
        // Calculate position below the original component
        const newLayoutItem: LayoutItem = {
            ...layoutItem,
            i: newComponentId,
            y: layoutItem.y + layoutItem.h
        }
        set({
            currentDashboard: {
                ...currentDashboard,
                components: [...currentDashboard.components, newComponent]
            },
            layouts: [...layouts, newLayoutItem],
            hasUnsavedChanges: true
        })
    },
    // Delete component
    deleteComponent: (componentId: string) => {
        const { currentDashboard, layouts } = get()
        if (!currentDashboard) return

        set({
            currentDashboard: {
                ...currentDashboard,
                components: currentDashboard.components.filter(c => c.id !== componentId)
            },
            layouts: layouts.filter(l => l.i !== componentId),
            hasUnsavedChanges: true
        })
    },

    // Refresh a single chart by incrementing its trigger counter
    refreshChart: (chartId: string) => {
        const { currentDashboard, chartRefreshTriggers } = get()
        if (!currentDashboard) return

        // Find all query components associated with this chart 
        const linkedQueryComponents = currentDashboard.components.filter(component => {
            if (component.type === 'query') {
                const queryConfig = component.data_config as QueryConfig
                return queryConfig.linkedComponentIds?.includes(chartId)
            }
            return false
        })

        // Extract query parameters
        const queryParams = linkedQueryComponents.map(queryComponent => {
            const queryConfig = queryComponent.data_config as QueryConfig
            return {
                queryComponentId: queryComponent.id,
                queryConditions: queryConfig.queryConditions
            }
        })

        const currentInfo = chartRefreshTriggers[chartId] || { trigger: 0, queryParams: [] }
        set({
            chartRefreshTriggers: {
                ...chartRefreshTriggers,
                [chartId]: {
                    trigger: currentInfo.trigger + 1,
                    queryParams
                }
            }
        })
    },

    // Refresh all charts linked to a query component
    refreshChartsByQuery: (queryComponentId: string) => {
        const { currentDashboard, chartRefreshTriggers } = get()
        if (!currentDashboard) return

        // Find the query component
        const queryComponent = currentDashboard.components.find(c => c.id === queryComponentId)
        if (!queryComponent || queryComponent.type !== 'query') return

        const queryConfig = queryComponent.data_config as QueryConfig
        const linkedChartIds = queryConfig.linkedComponentIds || []

        // Prepare query parameters (from the current query component)
        const currentQueryParams = [{
            queryComponentId: queryComponent.id,
            queryConditions: queryConfig.queryConditions
        }]

        // Increment trigger for each linked chart and attach query params
        const updatedTriggers = { ...chartRefreshTriggers }
        linkedChartIds.forEach(chartId => {
            // Get other query components that are also associated with this chart
            const otherLinkedQueries = currentDashboard.components.filter(component => {
                if (component.type === 'query' && component.id !== queryComponentId) {
                    const config = component.data_config as QueryConfig
                    return config.linkedComponentIds?.includes(chartId)
                }
                return false
            })

            // Combine all query parameters 
            const allQueryParams = [
                ...currentQueryParams,
                ...otherLinkedQueries.map(qc => ({
                    queryComponentId: qc.id,
                    queryConditions: (qc.data_config as QueryConfig).queryConditions
                }))
            ]

            const currentInfo = updatedTriggers[chartId] || { trigger: 0, queryParams: [] }
            updatedTriggers[chartId] = {
                trigger: currentInfo.trigger + 1,
                queryParams: allQueryParams
            }
        })

        set({ chartRefreshTriggers: updatedTriggers })
    },

    // Refresh all chart components (excluding query components)
    refreshAllCharts: () => {
        const { currentDashboard, chartRefreshTriggers } = get()
        if (!currentDashboard) return

        const updatedTriggers = { ...chartRefreshTriggers }
        currentDashboard.components.forEach(component => {
            // Refresh all non-query components
            if (component.type !== 'query') {
                // Find all query components associated with this chart 
                const linkedQueryComponents = currentDashboard.components.filter(qc => {
                    if (qc.type === 'query') {
                        const queryConfig = qc.data_config as QueryConfig
                        return queryConfig.linkedComponentIds?.includes(component.id)
                    }
                    return false
                })

                // Extract query parameters
                const queryParams = linkedQueryComponents.map(qc => ({
                    queryComponentId: qc.id,
                    queryConditions: (qc.data_config as QueryConfig).queryConditions
                }))

                const currentInfo = updatedTriggers[component.id] || { trigger: 0, queryParams: [] }
                updatedTriggers[component.id] = {
                    trigger: currentInfo.trigger + 1,
                    queryParams
                }
            }
        })

        set({ chartRefreshTriggers: updatedTriggers })
    },

    // Initialize auto-refresh based on query component configuration
    initializeAutoRefresh: () => {
        const { currentDashboard, chartRefreshTriggers } = get()
        if (!currentDashboard) return

        const updatedTriggers = { ...chartRefreshTriggers }

        // Build a mapping from chart ID to query component 
        const chartToQueriesMap: Record<string, any[]> = {}

        // Find all query components
        currentDashboard.components.forEach(component => {
            if (component.type === 'query') {
                const queryConfig = component.data_config as QueryConfig
                if (queryConfig.linkedComponentIds) {
                    const queryParam = {
                        queryComponentId: component.id,
                        queryConditions: queryConfig.queryConditions
                    }

                    // Add query parameters to each associated chart
                    queryConfig.linkedComponentIds.forEach(chartId => {
                        if (!chartToQueriesMap[chartId]) {
                            chartToQueriesMap[chartId] = []
                        }
                        chartToQueriesMap[chartId].push(queryParam)
                    })
                }
            }
        })

        // Set refresh information for each chart 
        Object.entries(chartToQueriesMap).forEach(([chartId, queryParams]) => {
            const currentInfo = updatedTriggers[chartId] || { trigger: 0, queryParams: [] }
            updatedTriggers[chartId] = {
                trigger: currentInfo.trigger + 1,
                queryParams
            }
        })

        set({ chartRefreshTriggers: updatedTriggers })
    },

    reset: () => set({
        hasUnsavedChanges: false,
        isSaving: false,
        currentDashboard: null,
        layouts: [],
        chartRefreshTriggers: {}
    }),
}))


// Shadow Component Editor Store
interface ComponentEditorState {
    // The "Shadow" state: stores a copy of the component currently being edited
    editingComponent: DashboardComponent | null;

    // Internal helper to push changes to the main store
    _internalSync: () => void;

    // Public methods
    updateEditingComponent: (data: Partial<DashboardComponent>) => void;

    /**
     * Entry Point: Triggered when clicking a chart.
     * Checks if a previous draft exists, saves it if necessary, 
     * then clones the new component.
     */
    copyFromDashboard: (componentId: string) => void;

    /**
     * Exit Point: Saves any remaining changes and resets the shadow state.
     */
    clear: (force?: boolean) => void;
}
export const useComponentEditorStore = create<ComponentEditorState>((set, get) => ({
    editingComponent: null,

    /**
     * Private-style helper to synchronize the shadow state 
     * back to the primary Dashboard store.
     */
    _internalSync: () => {
        const { editingComponent } = get();
        if (editingComponent) {
            const dashboardStore = useEditorDashboardStore.getState();
            dashboardStore.updateComponent(editingComponent.id, editingComponent);
        }
    },

    updateEditingComponent: (data) => {
        const { editingComponent } = get();
        if (editingComponent) {
            set({
                editingComponent: { ...editingComponent, ...data }
            });
        }
    },

    copyFromDashboard: (componentId: string) => {
        const { editingComponent, _internalSync } = get();
        const dashboardStore = useEditorDashboardStore.getState();

        // 1. If there is an existing draft, save it first
        if (editingComponent) {
            _internalSync();
        }

        // 2. Find the new component to edit
        const nextComponent = dashboardStore.currentDashboard?.components.find(
            (c) => c.id === componentId
        );

        if (nextComponent) {
            // 3. Create a deep copy for the shadow state
            const deepCopy = JSON.parse(JSON.stringify(nextComponent)) as DashboardComponent;
            set({ editingComponent: deepCopy });
        }
    },

    clear: (force) => {
        const { editingComponent, _internalSync } = get();

        // Save pending changes before closing
        if (!force && editingComponent) {
            _internalSync();
        }

        set({ editingComponent: null });
    },
}));