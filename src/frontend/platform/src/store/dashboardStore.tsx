import { create } from "zustand"
import { generateUUID } from "@/components/bs-ui/utils"
import { Dashboard, DashboardComponent, LayoutItem } from "@/pages/Dashboard/types/dataConfig"

interface EditorState {
    // Whether there are unsaved changes
    hasUnsavedChanges: boolean;
    // Whether currently saving
    isSaving: boolean;
    // Currently edited dashboard
    currentDashboard: Dashboard | null;
    // Selected component ID
    selectedComponentId: string | null;
    // Layout configuration
    layouts: LayoutItem[];
    // Query trigger (triggers re-query for all charts when changed)
    queryTrigger: number;

    // Set modification state
    setHasUnsavedChanges: (value: boolean) => void;
    // Set saving state
    setIsSaving: (value: boolean) => void;
    // Set current dashboard
    setCurrentDashboard: (dashboard: Dashboard | null) => void;
    // Set selected component ID
    setSelectedComponentId: (id: string | null) => void;
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
    // Trigger query
    triggerQuery: () => void;
    // Reset state
    reset: () => void;
}

export const useEditorDashboardStore = create<EditorState>((set, get) => ({
    hasUnsavedChanges: false,
    isSaving: false,
    currentDashboard: null,
    selectedComponentId: null,
    layouts: [],
    queryTrigger: 0,

    setHasUnsavedChanges: (value) => set({ hasUnsavedChanges: value }),
    setIsSaving: (value) => set({ isSaving: value }),
    setCurrentDashboard: (dashboard) => {
        set({
            currentDashboard: dashboard,
            layouts: dashboard?.layout_config?.layouts || []
        })
    },
    setSelectedComponentId: (id) => set({ selectedComponentId: id }),
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
            hasUnsavedChanges: true,
            selectedComponentId: null
        })
    },
    // Trigger query for all charts
    triggerQuery: () => {
        set((state) => ({ queryTrigger: state.queryTrigger + 1 }))
    },
    reset: () => set({
        hasUnsavedChanges: false,
        isSaving: false,
        currentDashboard: null,
        selectedComponentId: null,
        layouts: [],
        queryTrigger: 0
    }),
}))
