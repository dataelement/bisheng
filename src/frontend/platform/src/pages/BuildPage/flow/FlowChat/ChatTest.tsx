import { Button } from "@/components/bs-ui/button";
import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { GripVertical, Maximize2, Minus, X } from "lucide-react";
import { forwardRef, useContext, useImperativeHandle, useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import ChatPane from "./ChatPane";

// ref
export const ChatTest = forwardRef((props, ref) => {
    const [open, setOpen] = useState(false);
    const [chatId, setChatId] = useState("");
    const [flow, setFlow] = useState<any>(null);
    const [small, setSmall] = useState(false);
    const { appConfig } = useContext(locationContext);
    const { t } = useTranslation('flow');
    const [width, setWidth] = useState(window.innerWidth / 2.5);
    const resizableRef = useRef(null);

    // Expose a `run` method through the `ref` to control the sheet's state
    useImperativeHandle(ref, () => ({
        run: (flow) => {
            setOpen(false);
            setTimeout(() => {
                setOpen(true);  // 通过 `run` 方法打开 `Sheet`
                setSmall(false);

                setFlow(flow);
                setChatId(`test_${generateUUID(16)}`);
            }, 0);
        },
        close() {
            handleClose();
        }
    }));

    const handleClose = () => {
        setOpen(false);

        const event = new CustomEvent('nodeLogEvent', {
            detail: {
                nodeId: '*', action: 'normal', data: []
            }
        });
        window.dispatchEvent(event);
    };

    const handleMouseDown = (e) => {
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
        e.preventDefault();
    };

    const handleMouseMove = (e) => {
        const newWidth = window.innerWidth - e.clientX;
        if (newWidth > 600 && newWidth < window.innerWidth) {
            setWidth(newWidth);
        }
    };

    const handleMouseUp = () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
    };

    useEffect(() => {
        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, []);

    if (!open) return null;

    const host = appConfig.websocketHost || '';
    return (
        <div
            ref={resizableRef}
            className={`${small ? 'bottom-2 right-4 w-52' : 'h-full right-0 bottom-0'} transition-all fixed rounded-2xl bg-[#fff] dark:bg-[#1B1B1B] z-10 border shadow-sm overflow-hidden`}
            style={{ width: small ? '13rem' : `${width}px` }}
        >
            <div className="flex justify-between items-center bg-background-main px-4 py-1">
                <span className="text-sm font-bold">{t('workflowPreview')}</span>
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
            <div className={`h-[calc(100vh-28px)] relative overflow-y-auto ${small ? 'hidden' : ''}`} onKeyDown={(e) => e.stopPropagation()}>
                <ChatPane autoRun chatId={chatId} flow={flow} wsUrl={`${host}${__APP_ENV__.BASE_URL}/api/v1/workflow/chat/${flow?.id}`} />
            </div>
            {!small && <div
                className="absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize flex items-center"
                onMouseDown={handleMouseDown}
            ><GripVertical className="text-gray-400 min-w-3" /></div>}
        </div>
    );
});

export default ChatTest;
