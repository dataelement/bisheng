import { create } from "zustand"
import { Dashboard, LayoutItem, DashboardComponent } from "@/controllers/API/dashboard"
import { generateUUID } from "@/components/bs-ui/utils"

interface EditorState {
    // 是否有未保存的修改
    hasUnsavedChanges: boolean
    // 是否正在保存
    isSaving: boolean
    // 当前编辑的dashboard
    currentDashboard: Dashboard | null
    // 选中的组件ID
    selectedComponentId: string | null
    // 布局配置
    layouts: LayoutItem[]

    // 设置修改状态
    setHasUnsavedChanges: (value: boolean) => void
    // 设置保存状态
    setIsSaving: (value: boolean) => void
    // 设置当前dashboard
    setCurrentDashboard: (dashboard: Dashboard | null) => void
    // 设置选中的组件ID
    setSelectedComponentId: (id: string | null) => void
    // 更新布局配置
    setLayouts: (layouts: LayoutItem[]) => void
    // 添加组件到布局
    addComponentToLayout: (componentId: string) => void
    // 从布局中删除组件
    removeComponentFromLayout: (componentId: string) => void
    // 更新组件
    updateComponent: (componentId: string, data: Partial<DashboardComponent>) => void
    // 复制组件
    duplicateComponent: (componentId: string) => void
    // 删除组件
    deleteComponent: (componentId: string) => void
    // 重置状态
    reset: () => void
}

export const useEditorDashboardStore = create<EditorState>((set, get) => ({
    hasUnsavedChanges: false,
    isSaving: false,
    currentDashboard: null,
    selectedComponentId: null,
    layouts: [],

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
        if (!currentDashboard) return

        const updatedComponents = currentDashboard.components.map(c =>
            c.id === componentId ? { ...c, ...data } : c
        )
        set({
            currentDashboard: { ...currentDashboard, components: updatedComponents },
            hasUnsavedChanges: true
        })
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
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString()
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
    reset: () => set({
        hasUnsavedChanges: false,
        isSaving: false,
        currentDashboard: null,
        selectedComponentId: null,
        layouts: []
    }),
}))
