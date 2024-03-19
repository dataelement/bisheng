// 嵌iframe、适配移动端
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { getFlowApi } from "../../controllers/API/flow";
import { FlowType } from "../../types/flow";
import { generateUUID } from "../../utils";
import ChatPanne from "./components/ChatPanne";

export default function chatShare() {
    const { id: flowId } = useParams()
    const location = useLocation();
    const searchParams = new URLSearchParams(location.search);
    const libId = searchParams.get('lib')
    const tweak = searchParams.get('tweak')

    const queryString = useMemo(() => {
        const params = [];

        if (libId) params.push(`knowledge_id=${libId}`);
        if (tweak) params.push(`tweak=${tweak}`);

        return params.length > 0 ? `&${params.join('&')}` : '';
    }, [libId, tweak])

    // 
    const [flow, setFlow] = useState<FlowType>(null)
    const [chatId, setChatId] = useState<string>('')
    useEffect(() => {
        flowId && getFlowApi(flowId).then(node => {
            // 会话ID
            setFlow(node)
            setChatId(generateUUID(32))
        })
    }, [flowId])

    if (!flowId) return <div>请选择技能</div>

    return flow ? <ChatPanne version='v2' queryString={queryString} chatId={chatId} flow={flow} /> : null
};
