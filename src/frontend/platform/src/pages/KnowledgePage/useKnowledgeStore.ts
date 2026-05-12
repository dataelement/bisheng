// useKnowledgeStore.ts
import { create } from 'zustand';

/** A single segment of the directory breadcrumb trail. */
export interface BreadcrumbItem {
    id: number;
    name: string;
}

// Define the store type for the knowledge base editable state
interface KnowledgeStore {
    isEditable: boolean; // State: whether it is editable
    toggleEditable: () => void; // Toggle editability state
    setEditable: (editable: boolean) => void; // Set editability state
    // 1.3
    /** Selected chunk index */
    selectedChunkIndex: number | null;
    setSelectedChunkIndex: (index: number | null) => void;
    /** Selected chunk distance factor */
    selectedChunkDistanceFactor: number;
    setSelectedChunkDistanceFactor: () => void;
    /** Data that needs to be overwritten */
    needCoverData: { index: number, txt: string };
    setNeedCoverData: (data: { index: number, txt: string }) => void;
    /** Selected bbox for the current chunk */
    selectedBbox: { page: number, bbox: [number, number, number, number] }[];
    setSelectedBbox: (data: { page: number, bbox: [number, number, number, number] }[]) => void;
    // Tree navigation state (feature-6)
    /** Currently displayed directory (null = root) */
    currentParentId: number | null;
    /** File currently open in the paragraph preview panel (null = show list) */
    selectedFileId: number | null;
    /** Ordered path from root to the current directory */
    breadcrumbPath: BreadcrumbItem[];
    /** Navigate to a directory and update the breadcrumb. Clears selectedFileId. */
    setCurrentParent: (id: number | null, path: BreadcrumbItem[]) => void;
    /** Set the file being previewed in the right panel. */
    setSelectedFile: (id: number | null) => void;
}

// Create a zustand store to manage the knowledge base editable state
const useKnowledgeStore = create<KnowledgeStore>((set) => ({
    isEditable: false, // Default state is not editable
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
    setSelectedChunkDistanceFactor: () => set({ selectedChunkDistanceFactor: Math.random() / 100 }),
    // Tree navigation (feature-6)
    currentParentId: null,
    selectedFileId: null,
    breadcrumbPath: [],
    setCurrentParent: (id, path) => set({ currentParentId: id, breadcrumbPath: path, selectedFileId: null }),
    setSelectedFile: (id) => set({ selectedFileId: id }),
}));

export { useKnowledgeStore };
export default useKnowledgeStore;
