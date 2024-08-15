import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cname } from "../utils"
import { LoadIcon } from "@/components/bs-icons"
const buttonVariants = cva(
    "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
    {
        variants: {
            variant: {
                default:
                    "bg-primary text-primary-foreground shadow hover:bg-primary/90",
                destructive:
                    "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
                outline:
                    "border border-input shadow-sm hover:bg-accent hover:text-accent-foreground",
                secondary:
                    "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
                ghost: "hover:bg-accent hover:text-accent-foreground",
                link: "text-primary no-underline hover:underline",
                black: "bg-black-button text-primary-foreground shadow hover:bg-black-button/85"
            },
            size: {
                default: "h-9 px-4 py-2",
                sm: "h-8 rounded-md px-3 text-xs",
                lg: "h-10 rounded-md px-8",
                icon: "h-9 w-9",
            },
        },
        defaultVariants: {
            variant: "default",
            size: "default",
        },
    }
)

export interface ButtonProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
    asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant, size, asChild = false, ...props }, ref) => {
        const Comp = asChild ? Slot : "button"
        return (
            <Comp
                className={cname(buttonVariants({ variant, size, className }))}
                ref={ref}
                {...props}
            />
        )
    }
)
Button.displayName = "Button"


const ButtonNumber = React.forwardRef<HTMLButtonElement, {
    className?: string,
    defaultValue?: number,
    value?: number,
    max?: number,
    min?: number,
    step?: number,
    size?: "default" | "sm" | "lg" | "icon",
    onChange?: (value: number) => void
}>(({ className, value: userValue, defaultValue, max = 100, min = 0, step = 1, size = 'sm', onChange }, ref) => {
    if (max <= min) {
        throw new Error('max must be greater than min');
    }
    const [value, setValue] = React.useState(defaultValue)
    React.useEffect(() => {
        setValue(userValue)
    }, [userValue])

    const getDecimalCount = (value: number) => {
        return (String(value).split('.')[1] || '').length;
    }
    const roundValue = (value: number, decimalCount: number) => {
        const rounder = Math.pow(10, decimalCount);
        return Math.round(value * rounder) / rounder;
    }
    const valueAdd = () => {
        const sum = roundValue(value + step, getDecimalCount(step))
        const updateValue = sum > max ? max : sum
        setValue(updateValue)
        onChange?.(updateValue)
    }
    const valueReduce = () => {
        const sum = roundValue(value - step, getDecimalCount(step))
        const updateValue = sum < min ? min : sum
        setValue(updateValue)
        onChange?.(updateValue)
    }
    return (<div className={cname("flex items-center border input-border bg-gray-50 dark:bg-background-login rounded-md", className)}>
        <Button variant="ghost" size={size} disabled={value === min} onClick={valueReduce}>-</Button>
        <span className="min-w-10 block text-center">{value}</span>
        <Button variant="ghost" size={size} disabled={value === max} onClick={valueAdd}>+</Button>
    </div>)
}
)
ButtonNumber.displayName = "ButtonNumber"

const LoadButton = React.forwardRef<HTMLButtonElement, ButtonProps & { loading?: boolean }>(
    ({ loading = false, disabled = false, ...props }, ref) => {
        return <Button {...props} disabled={loading || disabled} ref={ref}>{loading && <LoadIcon className="mr-1" />}{props.children}</Button>
    }
)

export { Button, ButtonNumber, LoadButton, buttonVariants }