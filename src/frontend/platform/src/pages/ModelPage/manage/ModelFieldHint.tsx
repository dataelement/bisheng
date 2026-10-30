import { Button, Tooltip } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'

interface ModelFieldHintProps {
    content: string
    className?: string
}

export function ModelFieldHint({ content, className }: ModelFieldHintProps) {
    return <Tooltip content={content}>
        {/* -my-1: the 24px hit area must not make its label row taller than the text. Parent label centers it (inline-flex items-center). */}
        <Button type="button" variant="text" color="default" size="small" iconOnly aria-label={content} className={`-my-1 ${className ?? ''}`}>
            <Outlined.Question className="text-text-3" />
        </Button>
    </Tooltip>
}
