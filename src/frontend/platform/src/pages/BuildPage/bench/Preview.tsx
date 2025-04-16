import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent } from "@/components/bs-ui/dialog";
import { useState } from "react";


export default function Preview({ onBeforView }) {

    const [open, setOpen] = useState(false)
    const benchUrl = location.origin + '/workbench/'

    const handleClick = async () => {
        const res = await onBeforView()
        if (res) {
            setOpen(true)
        }
    }

    return <Dialog onOpenChange={setOpen} open={open} >
        <Button variant="outline" onClick={handleClick}>保存并预览</Button>
        <DialogContent className="max-w-[90vw] h-[90vh]">
            <div className="grid gap-4 py-4">
                <iframe src={benchUrl} className="size-full"></iframe>
            </div>
            {/* <DialogFooter>
                <Button type="submit">Save changes</Button>
            </DialogFooter> */}
        </DialogContent>
    </Dialog>
};
