import { cn } from "@/utils";
import { useRef, useState } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "../popover";

export function SelectHoverItem({ children, ...props }) {

    return <div {...props} className="relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700">
        {children}
    </div>
}


export function SelectHover({ triagger, className, children }) {
    const [open, setOpen] = useState(false);
    const timerRef = useRef(null);

    const handleMouseEnter = () => {
        if (timerRef.current) clearTimeout(timerRef.current);
        setOpen(true);
    };

    const handleMouseLeave = () => {
        timerRef.current = setTimeout(() => {
            setOpen(false);
        }, 150);
    };

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                asChild
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
                onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                }}
            >
                <div className="inline-block cursor-pointer">{triagger}</div>
            </PopoverTrigger>

            <PopoverContent
                side="top"
                className={cn("text-popover-foreground w-auto bg-popover dark:bg-[#2A2B2E] shadow-md p-2 relative", className)}
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
            >
                {children}
            </PopoverContent>
        </Popover>
    );
}