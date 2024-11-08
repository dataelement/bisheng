import { Sheet, SheetClose, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { Play } from "lucide-react";
import { forwardRef, useImperativeHandle, useState } from "react";
import ChatPane from "./ChatPane";

// ref

export const TestSheet = forwardRef((props, ref) => {
    const [open, setOpen] = useState(false)
    const [chatId, setChatId] = useState("")
    const [flow, setFlow] = useState<any>(null)

    // Expose a `run` method through the `ref` to control the sheet's state
    useImperativeHandle(ref, () => ({
        run: (flow) => {
            setOpen(true)  // 通过 `run` 方法打开 `Sheet`

            setFlow(flow)
            setChatId('xxxxxxxxx1')
        }
    }));


    return (
        <Sheet open={open} onOpenChange={setOpen}>
            <SheetContent className="sm:max-w-[50%]">
                <SheetHeader>
                    <SheetTitle className="flex items-center p-2 text-md"><Play size={16} /> 工作流预览</SheetTitle>
                </SheetHeader>
                <div className="px-2 py-4 h-[calc(100vh-40px)] bg-[#fff]">
                    <ChatPane chatId={chatId} flow={flow} />
                </div>
                <SheetFooter>
                    <SheetClose asChild>
                        {/* <Button type="submit">Save changes</Button> */}
                    </SheetClose>
                </SheetFooter>
            </SheetContent>
        </Sheet>
    )
})
