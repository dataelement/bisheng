import { CaretDownIcon } from "@radix-ui/react-icons";
import { Button } from ".";
import { Popover, PopoverContent, PopoverTrigger } from "../popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../tooltip";

export default function ActionButton({
    children,
    className = '',
    dropDown = null,
    align = 'center',
    buttonTipContent = null,
    ...props
}) {

    return <div className="flex items-center">
        <>
            {buttonTipContent ? <TooltipProvider>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <Button className={`rounded-r-none ${className}`} {...props}>{children}</Button>
                    </TooltipTrigger>
                    <TooltipContent className="bg-[#fff] text-gray-800">
                        {buttonTipContent}
                    </TooltipContent>
                </Tooltip>
            </TooltipProvider> :
                <Button className={`rounded-r-none ${className}`} {...props}>{children}</Button>
            }
        </>
        <Popover>
            <PopoverTrigger asChild>
                <Button size="icon" className="rounded-l-none ml-[1px] [&[data-state=open]>svg]:rotate-180"><CaretDownIcon /></Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-0" align={align}>
                {dropDown}
            </PopoverContent>
        </Popover>
    </div>
};
