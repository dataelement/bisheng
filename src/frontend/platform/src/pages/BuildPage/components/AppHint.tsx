import { Button,Tooltip } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'
import { Children,isValidElement,type ReactNode } from 'react'

interface AppHintProps {
    content: ReactNode
    className?: string
}

function contentText(content: ReactNode): string {
    if (typeof content === 'string' || typeof content === 'number') return String(content)
    if (Array.isArray(content)) return content.map(contentText).join(' ')
    if (isValidElement<{ children?: ReactNode }>(content)) return Children.toArray(content.props.children).map(contentText).join(' ')
    return ''
}

export function AppHint({ content, className }: AppHintProps) {
    return <Tooltip content={content} disabled={!content}>
        <Button type="button" variant="ghost" size="small" iconOnly className={className} aria-label={contentText(content)}>
            <Outlined.Question className="text-text-3" />
        </Button>
    </Tooltip>
}
