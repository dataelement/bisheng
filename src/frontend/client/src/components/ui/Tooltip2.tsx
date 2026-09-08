"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { cn } from "~/utils"

function TooltipProvider({
    delayDuration = 0,
    ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
    return (
        <TooltipPrimitive.Provider
            data-slot="tooltip-provider"
            delayDuration={delayDuration}
            {...props}
        />
    )
}

function Tooltip({
    ...props
}: React.ComponentProps<typeof TooltipPrimitive.Root>) {
    return (
        <TooltipProvider>
            <TooltipPrimitive.Root data-slot="tooltip" {...props} />
        </TooltipProvider>
    )
}

function TooltipTrigger({
    ...props
}: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
    return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

function TooltipContent({
    className,
    sideOffset = 0,
    children,
    noArrow = false,
    arrowClassName,
    ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content> & {
    noArrow?: boolean
    /** Recolor the arrow alongside a `className` that changes the panel background. */
    arrowClassName?: string
}) {
    return (
        <TooltipPrimitive.Portal>
            <TooltipPrimitive.Content
                data-slot="tooltip-content"
                sideOffset={sideOffset}
                className={cn(
                    // z-tooltip (1300), not z-50: this content is portalled to
                    // document.body, so it competes with whatever the page put
                    // on top — a dropdown panel at z-[220] hid the WeChat
                    // copy-link guide entirely. The design tokens already rank
                    // tooltip above modal/popover/toast; use that rank.
                    "bg-black text-white animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-tooltip w-fit origin-(--radix-tooltip-content-transform-origin) rounded-md px-3 py-1.5 text-xs",
                    className
                )}
                {...props}
            >
                {children}
                {!noArrow && <TooltipPrimitive.Arrow className={cn("bg-black fill-black z-tooltip size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px]", arrowClassName)} />}
            </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
    )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
