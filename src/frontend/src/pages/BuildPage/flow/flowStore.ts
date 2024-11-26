import { WorkFlow } from '@/types/flow';
import create from 'zustand';

type State = {
    flow: WorkFlow
}

type Actions = {
    setFlow: (flowid: WorkFlow) => void;
    uploadFlow: (file?: File) => void;
    // updateNode: (id: string, data: any) => void;
}

const useFlowStore = create<State & Actions>((set) => ({
    flow:  null,
    setFlow: (newFlow) => set({ flow: newFlow }),
    // upload flow by json
    uploadFlow(file?: File) {
        // if (file) {
        //   file.text().then((text) => {
        //     let flow: FlowType = JSON.parse(text);
        //     paste(
        //       { nodes: flow.data.nodes, edges: flow.data.edges },
        //       { x: 10, y: 10 },
        //       true
        //     );
        //   });
        // } else {
        // create a file input
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".json";
        input.onchange = (e: Event) => {
            if (
                (e.target as HTMLInputElement).files[0].type === "application/json"
            ) {
                const currentfile = (e.target as HTMLInputElement).files[0];
                currentfile.text().then((text) => {
                    let flow = JSON.parse(text);
                    set((state) => ({
                        flow: {
                            ...state.flow,
                            edges: flow.edges,
                            nodes: flow.nodes
                        }
                    }));
                });
            }
        };
        // trigger the file input click event to open the file dialog
        input.click();
    }
    //   }
}));

export default useFlowStore;
