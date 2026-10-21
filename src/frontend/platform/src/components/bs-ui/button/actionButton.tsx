// @ts-strict-ignore
import { Tooltip as SharedTooltip, TooltipProvider as SharedTooltipProvider } from '@bisheng/ui';
import { Button } from '@bisheng/ui';
import { ChevronDown } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "../popover";


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
            {buttonTipContent ? <SharedTooltipProvider delayDuration={delayDuration}><SharedTooltip  content={buttonTipContent} ><Button variant={variant} className={`rounded-r-none ${className}`} {...props}>{children}</Button></SharedTooltip></SharedTooltipProvider> :
                <Button variant={variant} className={`rounded-r-none ${className}`} {...props}>{children}</Button>
            }
        </>
        <Popover>
            <PopoverTrigger asChild>
                <Button size={props.size || 'icon'} variant={variant} className={`rounded-l-none ml-[1px] [&[data-state=open]>svg]:rotate-180 ${iconClassName}`}><ChevronDown className="size-4" /></Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-0" align={align}>
                {dropDown}
            </PopoverContent>
        </Popover>
    </div>
};
