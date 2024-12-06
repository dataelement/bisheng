import { WorkFlow } from '@/types/flow';
import create from 'zustand';

type State = {
    flow: WorkFlow
    fitView: boolean
}

type Actions = {
    setFlow: (flowid: WorkFlow) => void;
    uploadFlow: (file?: File) => void;
    // updateNode: (id: string, data: any) => void;
}

const useFlowStore = create<State & Actions & { notifications: Notification[]; addNotification: (notification: Notification) => void; clearNotifications: () => void }>((set) => ({
    flow: null,
    fitView: false,
    notifications: [], // 消息队列
    setFlow: (newFlow) => set({ flow: newFlow }),
    uploadFlow(file?: File) {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".json";
        input.onchange = (e: Event) => {
            if ((e.target as HTMLInputElement).files[0].type === "application/json") {
                const currentfile = (e.target as HTMLInputElement).files[0];
                currentfile.text().then((text) => {
                    let flow = JSON.parse(text);
                    set((state) => ({
                        flow: {
                            ...state.flow,
                            edges: flow.edges,
                            nodes: flow.nodes,
                            viewport: flow.viewport
                        },
                        fitView: !state.fitView
                    }));
                });
            }
        };
        input.click();
    },
    // 添加消息到队列
    addNotification: (notification) =>
        set((state) => ({
            notifications: [...state.notifications, notification]
        })),
    // 清空消息队列
    clearNotifications: () => set({ notifications: [] })
}));

type Notification = {
    title: string;
    description: string;
    type: "success" | "error" | "info" | "warning"; // 消息类型
};


export default useFlowStore;



