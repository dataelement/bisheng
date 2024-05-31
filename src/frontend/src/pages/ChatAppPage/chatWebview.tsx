// 嵌iframe、适配移动端(企业接入)
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ChatPanne from "./components/ChatPanne";

export default function ChatPro() {
    const { id: flowId, uid } = useParams()
    // uid 是 query
    const [data, setData] = useState<any>(null)
    // c41f9bb3-966e-4ded-9f3f-9077f70bc707
    useEffect(() => {

        // sdk 获取用户
        const userId = uid // 'xxx'
        setData({ id: flowId, chatId: flowId + '-' + userId, type: 'flow' })
    }, [])

    if (!data) return null

    return <ChatPanne data={data} />
};
