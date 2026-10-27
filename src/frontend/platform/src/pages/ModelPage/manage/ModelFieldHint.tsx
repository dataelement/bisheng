import { Button, Tooltip } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'

interface ModelFieldHintProps {
    content: string
    className?: string
}

export function ModelFieldHint({ content, className }: ModelFieldHintProps) {
    return <Tooltip content={content}>
        <Button type="button" variant="ghost" size="icon" aria-label={content} className={className}>
            <Outlined.Question className="text-text-3" />
        </Button>
    </Tooltip>
}
