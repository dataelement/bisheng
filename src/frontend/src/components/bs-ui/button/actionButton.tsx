import { ChevronDown } from "lucide-react";
import { Button } from ".";
import { Popover, PopoverContent, PopoverTrigger } from "../popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../tooltip";

export default function ActionButton({
    children,
    className = '',
    dropDown = null,
    align = 'center',
    buttonTipContent = null,
    delayDuration = 700,
    variant = "default",
    iconClassName = '',
    ...props
}) {

    return <div className="flex items-center">
        <>
            {buttonTipContent ? <TooltipProvider>
                <Tooltip delayDuration={delayDuration}>
                    <TooltipTrigger asChild>
                        <Button variant={variant} className={`rounded-r-none ${className}`} {...props}>{children}</Button>
                    </TooltipTrigger>
                    <TooltipContent className="bg-[#fff] text-gray-800">
                        {buttonTipContent}
                    </TooltipContent>
                </Tooltip>
            </TooltipProvider> :
                <Button variant={variant} className={`rounded-r-none ${className}`} {...props}>{children}</Button>
            }
        </>
        <Popover>
            <PopoverTrigger asChild>
                <Button
                    size={props.size || 'icon'}
                    variant={variant}
                    className={`rounded-l-none ml-[1px] [&[data-state=open]>svg]:rotate-180 ${iconClassName}`}
                ><ChevronDown className="size-4" /></Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-0" align={align}>
                {dropDown}
            </PopoverContent>
        </Popover>
    </div>
};
