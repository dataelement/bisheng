import * as React from "react";
import { Button as SharedButton, buttonVariants as sharedButtonVariants } from "@bisheng/ui";
import type { ButtonProps as SharedButtonProps, ButtonStyleProps } from "@bisheng/ui";
import { cname } from "../utils";

export interface ButtonProps extends Omit<SharedButtonProps, "variant"> {
    variant?: SharedButtonProps["variant"] | "black";
}

// Black was a platform-specific emphasis variant. Use the shared neutral solid
// button instead of keeping a second style implementation.
export function buttonVariants({ variant, ...props }: Omit<ButtonStyleProps, "variant"> & {
    variant?: ButtonProps["variant"];
    className?: string;
} = {}) {
    return sharedButtonVariants(variant === "black"
        ? { ...props, color: "default", variant: "solid" }
        : { ...props, variant });
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
    { variant, loading, disabled, ...props }, ref,
) {
    return <SharedButton {...props} ref={ref} loading={loading} disabled={disabled || loading}
        {...(variant === "black" ? { color: "default", variant: "solid" } : { variant })} />;
});

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
    const [value, setValue] = React.useState(userValue ?? defaultValue ?? min)
    React.useEffect(() => {
        if (userValue !== undefined) setValue(userValue)
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
        <Button ref={ref} type="button" variant="ghost" size={size} disabled={value === min} onClick={valueReduce}>-</Button>
        <span className="min-w-10 block text-center">{value}</span>
        <Button type="button" variant="ghost" size={size} disabled={value === max} onClick={valueAdd}>+</Button>
    </div>)
}
)
ButtonNumber.displayName = "ButtonNumber"


export const LoadButton = React.forwardRef<HTMLButtonElement, ButtonProps>(function LoadButton(props, ref) {
    return <Button {...props} ref={ref} />;
});

export { ButtonNumber };
