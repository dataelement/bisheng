import { Sheet, SheetClose, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { Play } from "lucide-react";
import { forwardRef, useImperativeHandle, useState } from "react";
import Chat from "./Chat";

// ref

export const TestSheet = forwardRef((props, ref) => {
    const [open, setOpen] = useState(false)

    // Expose a `run` method through the `ref` to control the sheet's state
    useImperativeHandle(ref, () => ({
        run: (flow) => {
            setOpen(true)  // 通过 `run` 方法打开 `Sheet`
            console.log("Flow:", flow); // 这里可以执行其他操作
        }
    }));


    return (
        <Sheet open={open} onOpenChange={setOpen}>
            <SheetContent className="sm:max-w-[520px]">
                <SheetHeader>
                    <SheetTitle className="flex items-center p-2 border-b"><Play /> 工作流预览</SheetTitle>
                </SheetHeader>
                <div className="grid gap-4 px-2 py-4 h-[calc(100vh-40px)]">
                    <Chat
                        useName=''
                        guideWord=''
                        wsUrl={'xxxx'}
                        onBeforSend={() => ({})}
                    ></Chat>
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
