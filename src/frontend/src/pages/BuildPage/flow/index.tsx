import { TabsContext } from "@/contexts/tabsContext";
import { getFlowApi } from "@/controllers/API/flow";
import cloneDeep from "lodash-es/cloneDeep";
import { useContext, useEffect, useMemo } from "react";
import { useParams } from "react-router-dom";
import Panne from "./Panne";
import useFlowStore from "./flowStore";

export default function FlowPage() {
    // const { flow, setFlow } = useContext(TabsContext);
    // const { id } = useParams();

    // useEffect(() => {
    //     if (id && flow?.id !== id) {
    //         // 切换技能重新加载flow数据
    //         getFlowApi(id).then(_flow => setFlow('flow_init', _flow))
    //     }
    // }, [])

    // const [copyFlow, preFlow] = useMemo(() => {
    //     if (flow?.id === id) {
    //         const copyFlow = cloneDeep(flow)
    //         return [copyFlow, JSON.stringify(copyFlow?.data || null)] as const
    //     }
    //     return []
    // }, [flow, id])


    const { flow, setFlow } = useFlowStore()

    const _flow = useEffect(() => {
        const str = localStorage.getItem('flow_tmp')
        const f = str ? JSON.parse(str) : flow
        setFlow(f)
        return f
    }, [])
    return (
        <div className="flow-page-positioning">
            {flow && <Panne flow={flow} />}
        </div>
    );
}
