import { getFlowApi } from "@/controllers/API/flow";
import { cloneDeep } from "lodash-es";
import { useEffect, useMemo } from "react";
import { useParams } from "react-router-dom";
import Panne from "./Panne";
import useFlowStore from "./flowStore";


export default function FlowPage() {
    // const { flow, setFlow } = useContext(TabsContext);
    const { id } = useParams();

    // useEffect(() => {
    //     if (id && flow?.id !== id) {
    //         // 切换技能重新加载flow数据
    //         getFlowApi(id).then(_flow => setFlow('flow_init', _flow))
    //     }
    // }, [])

    const { flow, setFlow } = useFlowStore()

    useEffect(() => {
        getFlowApi(id).then(f => {
            if (f.data) {
                const { data, ..._flow } = f
                return setFlow({
                    ..._flow,
                    nodes: data.nodes,
                    edges: data.edges,
                    viewport: data.viewport
                })
            }
            // default
            setFlow({
                ...f,
                nodes: [],
                edges: [],
                viewport: {
                    x: 0,
                    y: 0,
                    zoom: 1
                },
                version_list: []
            })
        })
        return () => setFlow(null)
    }, [])

    const [copyFlow, preFlow] = useMemo(() => {
        if (flow?.id === id) {
            // const copyFlow = cloneDeep(flow)
            return [flow, JSON.stringify(flow || null)] as const
        }
        return []
    }, [flow, id])

    return (
        <div className="flow-page-positioning">
            {copyFlow && <Panne flow={copyFlow} preFlow={preFlow} />}
        </div>
    );
}

