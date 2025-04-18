import { useParams } from "react-router-dom";
import { ResouceContent } from "./ChatAppPage/components/ResouceModal";

export default function ResoucePage() {
    const { cid, mid } = useParams()
    const data = { messageId: mid, chatId: cid, message: 'x' }

    return <ResouceContent data={data} fullScreen setOpen={() => { }} />
};
