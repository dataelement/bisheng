import { create } from "zustand"
import { generateUUID } from "@/components/bs-ui/utils"
import { ChartType, createDefaultDataConfig, Dashboard, DashboardComponent, LayoutItem, QueryConfig } from "@/pages/Dashboard/types/dataConfig"
import { DatePickerValue } from "@/pages/Dashboard/components/AdvancedDatePicker";
import { cloneDeep, isEqual } from "lodash-es";
import { getDefaultMetricStyle } from "@/pages/Dashboard/colorSchemes";

// Chart refresh information
interface ChartRefreshInfo {
    trigger: number;           // Refresh trigger counter
    queryParams: any[];        // Array of associated query component parameters
}
interface HistoryState {
    past: Array<{ currentDashboard: any, layouts: any[] }>;
    future: Array<{ currentDashboard: any, layouts: any[] }>;
}

interface EditorState {
    // Whether there are unsaved changes
    hasUnsavedChanges: boolean;
    lastChangeTime: number;
    // Whether currently saving
    isSaving: boolean;
    // Currently edited dashboard
    currentDashboard: Dashboard | null;
    currentDashboardId: string;
    // Layout configuration
    layouts: LayoutItem[];
    // Chart refresh triggers: each chart has its own trigger counter and query params
    chartRefreshTriggers: Record<string, ChartRefreshInfo>;
    queryComponentParams: Record<string, DatePickerValue>;
    // history
    history: HistoryState;

    undo: () => void;
    redo: () => void;
    saveSnapshot: () => void;
    // Set modification state
    setHasUnsavedChanges: (value: boolean) => void;
    // Set saving state
    setIsSaving: (value: boolean) => void;
    // Set current dashboard
    setCurrentDashboard: (dashboard: Dashboard | null) => void;
    setCurrentDashboardId: (id: string) => void;
    updateCurrentDashboard: (dashboard: Dashboard) => void;
    // Update layout configuration
    setLayouts: (layouts: LayoutItem[]) => void;
    // Add component to layout
    addComponentToLayout: (component: { title: string, type: ChartType }) => void;
    // Remove component from layout
    removeComponentFromLayout: (componentId: string) => void;
    // Update component
    updateComponent: (componentId: string, data: Partial<DashboardComponent>) => void;
    // Duplicate component
    duplicateComponent: (component: DashboardComponent) => void;
    // Delete component
    deleteComponent: (componentId: string) => void;
    // Refresh a single chart
    refreshChart: (chartId: string) => void;
    // Refresh charts linked to a query component
    refreshChartsByQuery: (queryComponent: DashboardComponent, filter: DatePickerValue) => void;
    // Refresh all charts
    refreshAllCharts: () => void;
    // Initialize auto-refresh on load
    initializeAutoRefresh: () => void;
    // Reset state
    reset: () => void;
    setQueryComponentParams: (id: string, params: DatePickerValue) => void;
}

let isInternalOperation = false; // Flag to prevent snapshot loops
export const useEditorDashboardStore = create<EditorState>((set, get) => ({
    hasUnsavedChanges: false,
    lastChangeTime: 0,
    isSaving: false,
    currentDashboard: null,
    currentDashboardId: '',
    layouts: [],
    chartRefreshTriggers: {},
    queryComponentParams: {},
    // Initialize history stacks
    history: {
        past: [],
        future: []
    },

    setHasUnsavedChanges: (value) => set({ hasUnsavedChanges: value }),
    setIsSaving: (value) => set({ isSaving: value }),
    setCurrentDashboard: (dashboard) => {
        set({
            currentDashboard: dashboard,
            layouts: dashboard?.layout_config?.layouts || [],
            chartRefreshTriggers: {} // Reset triggers when dashboard changes
        })
    },
    setCurrentDashboardId: (id) => set({ currentDashboardId: id }),
    updateCurrentDashboard: (dashboard) => {
        set({ currentDashboard: dashboard })
    },
    setLayouts: (newLayouts) => {
        const { layouts, saveSnapshot } = get()
        // This prevents double snapshots from ReactGridLayout callbacks
        if (isInternalOperation || isEqual(layouts, newLayouts)) {
            set({ layouts: newLayouts })
            return
        }

        debugLog('layouts')

        saveSnapshot();
        set({
            layouts: newLayouts,
            hasUnsavedChanges: true,
            lastChangeTime: Date.now()
        })
    },
    addComponentToLayout: (component) => {
        const { layouts, saveSnapshot } = get()
        saveSnapshot()
        const componentId = generateUUID(6);
        // 计算新组件的位置
        const maxY = layouts.length > 0 ? Math.max(...layouts.map(l => l.y + l.h)) : 0
        const newLayout: LayoutItem = {
            i: componentId,
            x: 0,
            y: maxY,
            w: ChartType.Metric === component.type ? 4 : 8,
            h: [ChartType.Query, ChartType.Metric].includes(component.type) ? 2 : 5,
            minW: 2,
            minH: 2,
            maxH: 24,
            maxW: 24
        }

        debugLog('addComponent')
        set({
            layouts: [...layouts, newLayout],
            hasUnsavedChanges: true,
            lastChangeTime: Date.now(),
            currentDashboard: {
                ...get().currentDashboard!,
                components: [...get().currentDashboard!.components, {
                    ...component,
                    id: componentId,
                    dashboard_id: get().currentDashboard?.id || '',
                    dataset_code: '',
                    data_config: createDefaultDataConfig(component.type),
                    style_config: component.type === ChartType.Metric ? getDefaultMetricStyle('', '') : {},
                    create_time: '',
                    update_time: ''
                }]
            }
        })
        useComponentEditorStore.getState().copyFromDashboard(componentId)

        isInternalOperation = true
        setTimeout(() => isInternalOperation = false, 100)
    },
    removeComponentFromLayout: (componentId) => {
        const { layouts, saveSnapshot } = get()
        saveSnapshot()

        debugLog('removeComponent')
        set({
            layouts: layouts.filter(l => l.i !== componentId),
            hasUnsavedChanges: true,
            lastChangeTime: Date.now()
        })

        isInternalOperation = true
        setTimeout(() => isInternalOperation = false, 100)
    },
    // Update component in the current dashboard
    updateComponent: (componentId: string, data: Partial<DashboardComponent>) => {
        const { currentDashboard } = get()
        if (!currentDashboard) {
            console.warn('updateComponent: currentDashboard is null')
            return
        }

        const updatedComponents = currentDashboard.components.map(c => {
            if (c.id === componentId) {
                const updated = { ...c, ...data }
                return updated
            }
            return c
        })

        debugLog('updateComponent')

        set({
            currentDashboard: {
                ...currentDashboard,
                components: updatedComponents
            },
            // hasUnsavedChanges: true,
            lastChangeTime: Date.now()
        })
    },
    // Duplicate component
    duplicateComponent: (component: DashboardComponent) => {
        get().saveSnapshot();

        const { currentDashboard, layouts } = get()

        const layoutItem = layouts.find((l) => l.i === component.id)
        // Create new component
        const newComponentId = generateUUID(6)
        const newComponent: DashboardComponent = {
            ...component,
            id: newComponentId,
            create_time: '',
            update_time: ''
        }
        // Calculate position below the original component
        const newLayoutItem: LayoutItem = {
            ...layoutItem,
            i: newComponentId,
            y: layoutItem.y + layoutItem.h
        }

        debugLog('copyComponent')
        set({
            currentDashboard: {
                ...currentDashboard,
                components: [...currentDashboard.components, newComponent]
            },
            layouts: [...layouts, newLayoutItem],
            hasUnsavedChanges: true,
            lastChangeTime: Date.now()
        })

        isInternalOperation = true
        setTimeout(() => isInternalOperation = false, 100)
    },
    // Delete component
    deleteComponent: (componentId: string) => {
        const { currentDashboard, layouts } = get()
        if (!currentDashboard) return
        get().saveSnapshot();

        debugLog('deleteComponent')
        set({
            currentDashboard: {
                ...currentDashboard,
                components: currentDashboard.components.filter(c => c.id !== componentId)
            },
            layouts: layouts.filter(l => l.i !== componentId),
            hasUnsavedChanges: true,
            lastChangeTime: Date.now()
        })

        isInternalOperation = true
        setTimeout(() => isInternalOperation = false, 100)
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

    setQueryComponentParams: (id, params) => set((state) => ({
        queryComponentParams: {
            ...state.queryComponentParams,
            [id]: params
        }
    })),
    // Refresh all charts linked to a query component
    refreshChartsByQuery: (queryComponent: DashboardComponent, filter: DatePickerValue) => {
        const { currentDashboard, chartRefreshTriggers, queryComponentParams } = get()
        if (!currentDashboard) return

        // Find the query component
        if (!queryComponent || queryComponent.type !== 'query') return

        const queryConfig = queryComponent.data_config as QueryConfig
        const linkedChartIds = queryConfig.linkedComponentIds || []
        // test all components
        // const linkedChartIds = currentDashboard.components.map(e => e.id)

        // Prepare query parameters (from the current query component)
        const currentQueryParams = [{
            queryComponentId: queryComponent.id,
            queryComponentParams: filter
        }]

        // Increment trigger for each linked chart and attach query params
        const updatedTriggers = { ...chartRefreshTriggers }
        linkedChartIds.forEach(chartId => {
            // Get other query components that are also associated with this chart
            const otherLinkedQueries = currentDashboard.components.filter(component => {
                if (component.type === 'query' && component.id !== queryComponent.id) {
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
                    queryComponentParams: queryComponentParams[qc.id]
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
        chartRefreshTriggers: {},
        history: { past: [], future: [] }
    }),

    // Save a snapshot of the current state before an action occurs
    saveSnapshot: () => {
        const { currentDashboard, layouts, history } = get()
        // Prevent recording if the change was triggered by Undo/Redo
        if (isInternalOperation || !currentDashboard) return

        // Use structuredClone for deep copy to prevent reference sharing
        const snapshot = {
            currentDashboard: cloneDeep(currentDashboard),
            layouts: cloneDeep(layouts)
        }

        set({
            history: {
                // Keep the last 50 steps to prevent memory issues
                past: [...history.past, snapshot].slice(-50),
                future: [] // Clear future when a new action is performed
            }
        })
    },

    undo: () => {
        const { history, currentDashboard, layouts } = get()
        if (history.past.length === 0) return

        const previous = history.past[history.past.length - 1]
        const newPast = history.past.slice(0, -1)

        isInternalOperation = true
        // Store current state in future stack for redo
        const currentSnapshot = {
            currentDashboard: cloneDeep(currentDashboard),
            layouts: cloneDeep(layouts)
        }

        set({
            currentDashboard: previous.currentDashboard,
            layouts: previous.layouts,
            history: {
                past: newPast,
                future: [currentSnapshot, ...history.future]
            },
            hasUnsavedChanges: true,
            lastChangeTime: Date.now()
        })
        setTimeout(() => isInternalOperation = false, 100)
    },

    redo: () => {
        const { history, currentDashboard, layouts } = get()
        if (history.future.length === 0) return

        const next = history.future[0]
        const newFuture = history.future.slice(1)

        isInternalOperation = true
        // Store current state in past stack for undo
        const currentSnapshot = {
            currentDashboard: cloneDeep(currentDashboard),
            layouts: cloneDeep(layouts)
        }

        set({
            currentDashboard: next.currentDashboard,
            layouts: next.layouts,
            history: {
                past: [...history.past, currentSnapshot],
                future: newFuture
            },
            hasUnsavedChanges: true,
            lastChangeTime: Date.now()
        })
        setTimeout(() => isInternalOperation = false, 100)
    }
}))


// Shadow Component Editor Store
interface ComponentEditorState {
    // The "Shadow" state: stores a copy of the component currently being edited
    editingComponent: DashboardComponent | null;
    hasChange: boolean;

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
    hasChange: false,

    /**
     * Private-style helper to synchronize the shadow state 
     * back to the primary Dashboard store.
     */
    _internalSync: () => {
        const { hasChange, editingComponent } = get();
        if (hasChange && editingComponent) {
            const dashboardStore = useEditorDashboardStore.getState();
            dashboardStore.updateComponent(editingComponent.id, editingComponent);
        }
    },

    updateEditingComponent: (data) => {
        const { editingComponent } = get();
        if (editingComponent) {
            set({
                editingComponent: { ...editingComponent, ...data },
                hasChange: true
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
            set({ editingComponent: deepCopy, hasChange: false });
        }
    },

    clear: (force) => {
        const { editingComponent, _internalSync } = get();
        if (!editingComponent) return;

        // Save pending changes before closing
        if (!force && editingComponent) {
            _internalSync();
        }

        set({ editingComponent: null, hasChange: true });
    },
}));


const debugLog = (msg: string) => {
    console.log('【savechange】 :>> ', msg);
}