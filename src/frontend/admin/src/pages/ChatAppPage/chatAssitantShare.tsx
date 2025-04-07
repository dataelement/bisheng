// 支持嵌iframe、适配移动端
import { useMemo, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { generateUUID } from "../../utils";
import ChatPanne from "./components/ChatPanne";
import { AppNumType } from "@/types/app";

export default function chatAssitantShare() {
    const { id: assitId } = useParams()

    const wsUrl = `/api/v2/assistant/chat/${assitId}`

    const [data] = useState<any>({ id: assitId, chatId: generateUUID(32), type: AppNumType.ASSISTANT })

    if (!assitId) return <div>请选择会话</div>

    return <ChatPanne customWsHost={wsUrl} version="v2" data={data} />
};
