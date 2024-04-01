import { LoadIcon } from "@/components/bs-icons/loading";
import { ToastIcon } from "@/components/bs-icons/toast";
import { cname } from "@/components/bs-ui/utils";
import { CaretDownIcon } from "@radix-ui/react-icons";
import { useState } from "react";

export default function RunLog({ data }) {
    const [open, setOpen] = useState(false)

    return <div className="rounded-sm border">
        <div className="flex justify-between items-center px-4 py-2 shadow-xl cursor-pointer" onClick={() => setOpen(!open)}>
            <div className="flex items-center font-bold gap-2 text-sm">
                {
                    data.end ? <ToastIcon type='success' /> :
                        <LoadIcon className="text-primary duration-300" />
                }
                <span>工具开发</span>
            </div>
            <CaretDownIcon className={open && 'rotate-180'} />
        </div>
        <div className={cname('bg-gray-100 px-4 py-2 text-gray-500 overflow-hidden', open ? 'h-auto' : 'h-0 p-0')}>
            <p>{data.thought}</p>
        </div>
    </div>
};
