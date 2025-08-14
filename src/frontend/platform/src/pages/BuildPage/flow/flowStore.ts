import { copyReportTemplate } from '@/controllers/API/workflow';
import { WorkFlow } from '@/types/flow';
import {create} from 'zustand';

type State = {
    flow: WorkFlow
    fitView: boolean,
    runCache: {
        [nodeId: string]: {
            [key: string]: string
        }
    }
}

type Actions = {
    setFlow: (flowid: WorkFlow) => void;
    uploadFlow: (file?: File) => void;
    setFitView: () => void;
    // updateNode: (id: string, data: any) => void;
    setRunCache: (nodeId: string, keyInput: { key: string, value: string }) => void;
    clearRunCache: () => void;
}

const useFlowStore = create<State & Actions & { notifications: Notification[]; addNotification: (notification: Notification) => void; clearNotifications: () => void }>((set) => ({
    flow: null,
    fitView: false,
    runCache: {},
    notifications: [], // 消息队列
    setFlow: (newFlow) => set({ flow: newFlow }),
    setFitView: () => set((state) => ({ fitView: !state.fitView })),
    uploadFlow(file?: File) { // 导入工作流
       
    },
    // 添加消息到队列
    addNotification: (notification) =>
        set((state) => ({
            notifications: [notification, ...state.notifications,]
        })),
    // 清空消息队列
    clearNotifications: () => set({ notifications: [] }),
    // 运行缓存
    setRunCache: (nodeId, keyInput) => {
        set((state) => ({
            runCache: {
                ...state.runCache,
                [nodeId]: keyInput
            }
        }));
    },
    clearRunCache: () => set({ runCache: {} })
}));

type Notification = {
    title: string;
    description: string;
    type: "success" | "error" | "info" | "warning"; // 消息类型
};


export default useFlowStore;



