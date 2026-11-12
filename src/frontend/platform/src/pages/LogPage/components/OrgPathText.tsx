import { Tooltip } from '@bisheng/ui'
import { useLayoutEffect, useRef, useState } from 'react'

interface OrgPathTextProps {
  text: string
}

/**
 * Audit tables size columns from content, so a max-width on the cell does not
 * clip a long organisation path. A fixed one-line box does. The full path is
 * offered only once that box actually clips it.
 */
export function OrgPathText({ text }: OrgPathTextProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const [clipped, setClipped] = useState(false)

  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    const measure = () => setClipped(node.scrollWidth > node.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [text])

  return (
    <Tooltip
      content={text}
      disabled={!clipped}
      contentClassName="max-w-[min(28rem,calc(100vw-2rem))] break-all"
    >
      <span
        ref={ref}
        tabIndex={clipped ? 0 : undefined}
        className="block w-[200px] max-w-full cursor-default truncate"
      >
        {text}
      </span>
    </Tooltip>
  )
}
