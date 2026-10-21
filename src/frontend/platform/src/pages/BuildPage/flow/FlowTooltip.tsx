import { Tooltip,type TooltipProps } from '@bisheng/ui'
import type { ReactNode } from 'react'

interface FlowTooltipProps extends Omit<TooltipProps, 'side' | 'content'> {
    content: ReactNode
    side?: TooltipProps['side'] | 'top-right'
    styleClasses?: string
    delayDuration?: number
    asChild?: boolean
}

export function FlowTooltip({ content, children, side, align, styleClasses, delayDuration, asChild, ...props }: FlowTooltipProps) {
    void styleClasses
    void delayDuration
    void asChild
    return <Tooltip {...props} content={content} disabled={props.disabled || !content}
        side={side === 'top-right' ? 'top' : side} align={side === 'top-right' ? 'end' : align}>
        {children}
    </Tooltip>
}
