import { Button } from "../button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../tooltip";

export function SelectHoverItem({ children, ...props }) {

    return <div {...props} className="relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700">
        {children}
    </div>
}

export function SelectHover({ triagger, children }) {

    return <TooltipProvider delayDuration={100}>
        <Tooltip>
            <TooltipTrigger asChild>
                {triagger}
            </TooltipTrigger>
            <TooltipContent className="text-popover-foreground bg-popover dark:bg-[#2A2B2E] shadow-md">
                {children}
            </TooltipContent>
        </Tooltip>
    </TooltipProvider>
};
