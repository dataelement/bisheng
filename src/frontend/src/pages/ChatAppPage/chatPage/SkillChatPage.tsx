// 嵌iframe、适配移动端
import { useContext, useMemo, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import ChatPanne from "../components/ChatPanne";
import { userContext } from "@/contexts/userContext";

export default function SkillChatPage() {
    const { id: flowId } = useParams()
    const { user } = useContext(userContext);

    const [data] = useState<any>({ id: flowId, chatId: `${flowId}_${user.user_id}`, type: 'flow' })

    if (!flowId) return <div>请选择会话</div>

    return <ChatPanne data={data} />
};
