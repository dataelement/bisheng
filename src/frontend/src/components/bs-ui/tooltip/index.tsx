"use client"

import * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { CircleHelp } from "lucide-react"
import * as React from "react"
import { cname } from "../utils"

const TooltipProvider = TooltipPrimitive.Provider

const Tooltip = TooltipPrimitive.Root

const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
    React.ElementRef<typeof TooltipPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
    <TooltipPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cname(
            "z-50 overflow-hidden rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
            className
        )}
        {...props}
    />
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger }


export const QuestionTooltip = ({ className = '', content }) => (
    <TooltipProvider delayDuration={100}>
        <Tooltip>
            <TooltipTrigger className={className}>
                <CircleHelp className="w-3.5 h-3.5" />
            </TooltipTrigger>
            <TooltipContent>
                <div className="max-w-96 text-left break-all whitespace-normal">{content}</div>
            </TooltipContent>
        </Tooltip>
    </TooltipProvider>
);