import { WorkFlow } from '@/types/flow';
import create from 'zustand';

type State = {
    flow: WorkFlow
}

type Actions = {
    setFlow: (flowid: WorkFlow) => void;
    // updateNode: (id: string, data: any) => void;
}

const useFlowStore = create<State & Actions>((set) => ({
    flow: {}, // null
    setFlow: (newFlow) => set({ flow: newFlow }),
    // updateNode: (id, newData) =>
    //     set((state) => ({
    //         nodes: state.nodes.map((node) =>
    //             node.id === id ? { ...node, data: { ...node.data, ...newData } } : node
    //         ),
    //     })),
}));

export default useFlowStore;
