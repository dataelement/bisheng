// @ts-strict-ignore
import { checkAppEditPermission, getFlowApi, getWorkflowManagementEditorFlow } from "@/controllers/API/flow";
import { showApiError } from "@/controllers/request";
import { flowVersionCompatible } from "@/util/flowCompatible";
import { workflowManagementReturnTarget } from "@/utils/workflowManagement";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import Panne from "./Panne";
import useFlowStore from "./flowStore";


export default function FlowPage() {
    // const { flow, setFlow } = useContext(TabsContext);
    const { id } = useParams();
    const returnTarget = workflowManagementReturnTarget(useLocation().search);

    // useEffect(() => {
    //     if (id && flow?.id !== id) {
    //         // 切换技能重新加载flow数据
    //         getFlowApi(id).then(_flow => setFlow('flow_init', _flow))
    //     }
    // }, [])

    const { flow, setFlow, clearRunCache, clearNotifications } = useFlowStore()
    const [checking, setChecking] = useState(true)

    useEffect(() => {
        let active = true;
        setChecking(true);
        const flowInit = async () => {
            if (!returnTarget) await checkAppEditPermission(id, 10);
            const f = await (returnTarget ? getWorkflowManagementEditorFlow(id) : getFlowApi(id));
            if (!active) return;
            clearRunCache();

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
            });
        };
        void flowInit().catch(error => {
            if (active) showApiError(error);
        }).finally(() => {
            if (active) setChecking(false);
        });

        return () => {
            active = false;
            setFlow(null);
            clearRunCache();
            clearNotifications()
        }
    }, [id, returnTarget, setFlow, clearRunCache, clearNotifications])

    const [copyFlow, preFlow] = useMemo(() => {
        if (flow?.id === id) {
            // const copyFlow = cloneDeep(flow)
            // 版本兼容
            const newFlow = flowVersionCompatible(flow)
            return [newFlow, JSON.stringify(newFlow || null)] as const
        }
        return []
    }, [flow, id])

    if (checking) return null

    return (
        <div className="flow-page-positioning">
            {copyFlow && <Panne flow={copyFlow} preFlow={preFlow} />}
        </div>
    );
}

