import { locationContext } from "@/contexts/locationContext";
import { ChatMessageType } from "@/types/chat";
import { MagnifyingGlassIcon, Pencil2Icon, ReloadIcon } from "@radix-ui/react-icons";
import { useContext } from "react";
import { useMessageStore } from "./messageStore";

export default function MessageUser({ useName, data }: { data: ChatMessageType }) {
    const msg = data.message[data.chatKey]

    const { appConfig } = useContext(locationContext)
    const running = useMessageStore(state => state.running)

    const handleSearch = () => {
        window.open(appConfig.dialogQuickSearch + encodeURIComponent(msg))
    }

    const handleResend = (send) => {
        const myEvent = new CustomEvent('userResendMsgEvent', {
            detail: {
                send,
                message: msg
            }
        });
        document.dispatchEvent(myEvent);
    }

    return <div className="flex justify-end w-full py-1">
        <div className="w-fit min-h-8 rounded-2xl px-6 py-4 max-w-[90%] bg-[#EEF2FF]">
            {useName && <p className="text-primary text-xs mb-2 text-right">{useName}</p>}
            <div className="flex gap-2 ">
                <div className="text-[#0D1638] text-sm break-all whitespace-break-spaces">{msg}</div>
                <div className="w-6 h-6 min-w-6"><img src="/user.png" alt="" /></div>
            </div>
            {/* 附加信息 */}
            <div className="flex justify-between mt-2">
                <span></span>
                <div className="flex gap-2 text-gray-400 cursor-pointer self-end">
                    {!running && <Pencil2Icon className="hover:text-gray-500" onClick={() => handleResend(false)} />}
                    {!running && <ReloadIcon className="hover:text-gray-500" onClick={() => handleResend(true)} />}
                    {appConfig.dialogQuickSearch && <MagnifyingGlassIcon className="hover:text-gray-500" onClick={handleSearch} />}
                </div>
            </div>
        </div>
    </div>
};
