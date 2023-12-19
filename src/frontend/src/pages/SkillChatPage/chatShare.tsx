// 嵌iframe、适配移动端
import { useEffect, useState ,useCallback} from "react";
import { useLocation, useParams } from "react-router-dom";
import { getFlowFromDatabase } from "../../controllers/API";
import { FlowType } from "../../types/flow";
import { generateUUID } from "../../utils";
import ChatPanne from "./components/ChatPanne";

export default function chatShare() {
    const { id: flowId } = useParams()
    const location = useLocation();
    const searchParams = new URLSearchParams(location.search);
    const libId = searchParams.get('lib')
    // 
    const [flow, setFlow] = useState<FlowType>(null)
    const [chatId, setChatId] = useState<string>('')
    useEffect(() => {
        flowId && getFlowFromDatabase(flowId).then(node => {
            setFlow(null)
            // 会话ID
            // 预留 websoket 重连时间
            node && setTimeout(() => {
                setFlow(node)
                setChatId(generateUUID(32))
            }, 200);
        })
    }, [flowId])
    
    const handleReload = useCallback(()=>{
        flowId && getFlowFromDatabase(flowId).then(node => {
            setFlow(null)
            // 会话ID
            // 预留 websoket 重连时间
            node && setTimeout(() => {
                setFlow(node)
                setChatId(generateUUID(32))
            }, 200);
        })
    },[flowId])
    if (!flowId) return <div>请选择技能</div>

    return flow ? <ChatPanne version='v2' libId={libId} chatId={chatId} flow={flow}  onReload={handleReload}/> : null
};
