import { useState } from "react";
import { Dialog, DialogTrigger } from ".";

// 强制刷新children的 dialog 组件
export default function DialogForceUpdate({ children, trigger }) {

    const [open, setOpen] = useState(false);

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
            {trigger}
        </DialogTrigger>
        {open ? children : null}
    </Dialog>
};
