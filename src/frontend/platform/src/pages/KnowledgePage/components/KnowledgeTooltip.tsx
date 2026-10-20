import { Button,Tooltip,type TooltipProps } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'
import { Children,isValidElement,type ReactNode } from 'react'

interface KnowledgeTooltipProps extends TooltipProps {
    styleClasses?: string
    asChild?: boolean
    delayDuration?: number
}

// Preserve empty-description behavior while using the shared tooltip shell.
export function KnowledgeTooltip({ content, disabled, children, styleClasses, asChild, delayDuration, ...props }: KnowledgeTooltipProps) {
    void styleClasses
    void asChild
    void delayDuration
    return <Tooltip {...props} content={content} disabled={disabled || !content}>{children}</Tooltip>
}

interface KnowledgeHintProps {
    content: ReactNode
    className?: string
    error?: boolean
}

function hintText(content: ReactNode): string {
    if (typeof content === 'string' || typeof content === 'number') return String(content)
    if (isValidElement<{ children?: ReactNode }>(content)) return Children.toArray(content.props.children).map(hintText).join(' ')
    return ''
}

export function KnowledgeHint({ content, className, error }: KnowledgeHintProps) {
    return <Tooltip content={content}>
        <Button type="button" variant="ghost" size="small" iconOnly aria-label={hintText(content)}
            className={className} color={error ? 'danger' : 'default'}>
            <Outlined.Question className={error ? undefined : "text-text-3"} />
        </Button>
    </Tooltip>
}
