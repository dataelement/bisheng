import * as React from "react"
import * as SwitchPrimitives from "@radix-ui/react-switch"
import { cname } from "../utils"

const Switch = React.forwardRef<
    React.ElementRef<typeof SwitchPrimitives.Root>,
    React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, texts = null, ...props }, ref) => (
    <SwitchPrimitives.Root
        className={cname(
            "group peer relative inline-flex h-5 min-w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=unchecked]:bg-input dark:data-[state=unchecked]:bg-gray-950",
            className
        )}
        {...props}
        ref={ref}
    >
        <SwitchPrimitives.Thumb
            className={cname(
                "pointer-events-none block h-3.5 min-w-3.5 w-3.5 rounded-full bg-background dark:bg-[#C0D6FF] shadow-lg ring-0 transition-transform data-[state=checked]:ml-[100%] data-[state=checked]:translate-x-[calc(-50%-8px)] data-[state=unchecked]:translate-x-0 dark:data-[state=unchecked]:bg-[#333437]"
            )}
        />
        {texts && <>
            <span className="text text-xs absolute left-1 text-gray-50 hidden group-data-[state=checked]:block">{texts[0]}</span>
            <span className="text text-xs absolute right-1 text-gray-400 hidden group-data-[state=unchecked]:block">{texts[1]}</span>
        </>}
    </SwitchPrimitives.Root>
))
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }
