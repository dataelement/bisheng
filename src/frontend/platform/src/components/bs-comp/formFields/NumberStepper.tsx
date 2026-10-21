import * as React from 'react';
import { Button, cn } from '@bisheng/ui';
export const ButtonNumber = React.forwardRef<HTMLButtonElement, {
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
    return (<div className={cn("flex items-center border input-border bg-gray-50 dark:bg-background-login rounded-md", className)}>
        <Button ref={ref} type="button" variant="text" size={size} disabled={value === min} onClick={valueReduce} color="default">-</Button>
        <span className="min-w-10 block text-center">{value}</span>
        <Button type="button" variant="text" size={size} disabled={value === max} onClick={valueAdd} color="default">+</Button>
    </div>)
}
)
ButtonNumber.displayName = "ButtonNumber"
