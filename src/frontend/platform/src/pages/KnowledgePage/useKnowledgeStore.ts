// useKnowledgeStore.ts
import {create} from 'zustand';

// 定义知识库可编辑状态的 store 类型
interface KnowledgeStore {
    isEditable: boolean; // 状态：是否可编辑
    toggleEditable: () => void; // 切换编辑状态
    setEditable: (editable: boolean) => void; // 设置编辑状态
    // 1.3
    /** 选中的chunk index */
    selectedChunkIndex: number | null;
    setSelectedChunkIndex: (index: number | null) => void;
    /** 选中的chunk距离因子 */
    selectedChunkDistanceFactor: number;
    setSelectedChunkDistanceFactor: () => void;
    /** 需要覆盖的数据 */
    needCoverData: { index: number, txt: string };
    setNeedCoverData: (data: { index: number, txt: string }) => void;
    /** 当前chunk选中的bbox */
    selectedBbox: { page: number, bbox: [number, number, number, number] }[];
    setSelectedBbox: (data: { page: number, bbox: [number, number, number, number] }[]) => void;
}

// 创建 zustand store 来管理知识库是否可编辑的状态
const useKnowledgeStore = create<KnowledgeStore>((set) => ({
    isEditable: false, // 默认状态为不可编辑
    toggleEditable: () => set((state) => ({ isEditable: !state.isEditable })),
    setEditable: (editable) => set({ isEditable: editable }),
    // v1.3
    selectedChunkIndex: -1,
    setSelectedChunkIndex: (index) => set({ selectedChunkIndex: index }),
    needCoverData: { index: -1, txt: '' },
    setNeedCoverData: (data) => set({ needCoverData: data }),
    selectedBbox: [],
    setSelectedBbox: (data) => set({ selectedBbox: data }),
    selectedChunkDistanceFactor: 0,
    setSelectedChunkDistanceFactor: () => set({ selectedChunkDistanceFactor: Math.random() / 100 })
}));

export default useKnowledgeStore;
