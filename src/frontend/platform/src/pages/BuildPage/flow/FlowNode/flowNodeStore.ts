// Used for communication between nodes 
import { create } from 'zustand';

type Value = {
    action: 'u' | 'd'
    node: {
        id: string;
        name: string;
    } | null
    question: {
        id: string;
        name: string;
    } | null
}

interface Store {
    value: Value | null;
    setValue: (newValue: Value | null) => void;
}

const useStore = create<Store>((set) => ({
    value: null,
    setValue: (newValue) => set({ value: newValue })
}));

// Modify variable name
export const useUpdateVariableState = () => {
    const value = useStore((state) => state.value);
    const setValue = useStore((state) => state.setValue);

    return [value, setValue] as const;
};