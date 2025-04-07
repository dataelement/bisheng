// useKnowledgeStore.ts
import create from 'zustand';

// 定义知识库可编辑状态的 store 类型
interface KnowledgeStore {
    isEditable: boolean; // 状态：是否可编辑
    toggleEditable: () => void; // 切换编辑状态
    setEditable: (editable: boolean) => void; // 设置编辑状态
}

// 创建 zustand store 来管理知识库是否可编辑的状态
const useKnowledgeStore = create<KnowledgeStore>((set) => ({
    isEditable: false, // 默认状态为不可编辑
    toggleEditable: () => set((state) => ({ isEditable: !state.isEditable })),
    setEditable: (editable) => set({ isEditable: editable }),
}));

export default useKnowledgeStore;
