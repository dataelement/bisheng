import { Button } from "@/components/bs-ui/button";
import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { Maximize2, Minus, X } from "lucide-react";
import { forwardRef, useContext, useImperativeHandle, useState } from "react";
import ChatPane from "./ChatPane";

// ref
export const ChatTest = forwardRef((props, ref) => {
    const [open, setOpen] = useState(false)
    const [chatId, setChatId] = useState("")
    const [flow, setFlow] = useState<any>(null)
    const [small, setSmall] = useState(false)
    const { appConfig } = useContext(locationContext)

    // Expose a `run` method through the `ref` to control the sheet's state
    useImperativeHandle(ref, () => ({
        run: (flow) => {
            setOpen(false)
            setTimeout(() => {
                setOpen(true)  // 通过 `run` 方法打开 `Sheet`
                setSmall(false)

                setFlow(flow)
                setChatId(generateUUID(16))
            }, 0);
        }
    }));

    const handleClose = () => {
        setOpen(false)

        const event = new CustomEvent('nodeLogEvent', {
            detail: {
                nodeId: '*', action: 'normal', data: []
            }
        })
        window.dispatchEvent(event)
    }

    if (!open) return null

    const host = appConfig.websocketHost || ''
    return <div
        className={`${small ? 'bottom-2 right-4 w-52' : 'w-1/2 h-full right-0 bottom-0'} transition-all fixed rounded-2xl bg-[#fff] z-10 border shadow-sm overflow-hidden`}
    >
        <div className="flex justify-between items-center bg-background-main px-4 py-1">
            <span className="text-sm font-bold">工作流预览</span>
            <div className="flex gap-2">
                <Button
                    size="icon"
                    variant="outline"
                    className="rounded-md shadow-md size-4 p-0.5"
                    onClick={() => setSmall(!small)}
                >{small ? <Maximize2 /> : <Minus />}</Button>
                <Button
                    size="icon"
                    variant="destructive"
                    className="rounded-md shadow-md size-4 p-0.5"
                    onClick={handleClose}
                ><X /></Button>
            </div>
        </div>
        <div className={`h-[calc(100vh-28px)] overflow-y-auto px-4 ${small ? 'hidden' : ''}`}>
            <ChatPane chatId={chatId} flow={flow} wsUrl={`${host}${__APP_ENV__.BASE_URL}/api/v1/workflow/chat/${flow?.id}`} />
        </div>
    </div>
})
