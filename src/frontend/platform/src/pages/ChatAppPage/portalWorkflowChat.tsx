import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { generateUUID } from "../../utils";
import { AppNumType } from "@/types/app";
import ChatPanne from "./components/ChatPanne";

export default function PortalWorkflowChat() {
  const { id: workflowId } = useParams();

  const wsUrl = useMemo(() => {
    if (!workflowId) return "";
    return `/api/v2/workflow/chat/${workflowId}?`;
  }, [workflowId]);

  const [data] = useState<any>({
    id: workflowId,
    chatId: generateUUID(32),
    type: AppNumType.FLOW,
  });

  if (!workflowId) {
    return <div className="flex h-full w-full items-center justify-center text-sm text-gray-500">请选择 workflow</div>;
  }

  return (
    <div className="h-screen w-screen overflow-hidden bg-white">
      <ChatPanne customWsHost={wsUrl} version="v2" data={data} portalMode />
    </div>
  );
}
