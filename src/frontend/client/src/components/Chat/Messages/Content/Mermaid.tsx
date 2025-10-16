import mermaid from 'mermaid'
import { useEffect, useRef, useState } from 'react'
import { Button } from '~/components/ui';

// 初始化 mermaid
mermaid.initialize({ startOnLoad: false, theme: 'default' })

export default function MermaidBlock({ children }: { children: string }) {
    const ref = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null);
    const [mode, setMode] = useState<'chart' | 'code'>('chart');

    useEffect(() => {
        if (ref.current) {
            // 清空之前的内容
            ref.current.innerHTML = children
            // 渲染 mermaid
            mermaid.run({ nodes: [ref.current] })
        }
    }, [children])

    useEffect(() => {
        const parentNode = document.querySelector('.bisheng-message');
        if (parentNode && containerRef.current) {
            containerRef.current.style.width = `${parentNode.clientWidth - 60}px`;
        }
    }, [])

    return <div className="w-full my-3 -ml-3.5" ref={containerRef}>
        <div className="border shadow-sm rounded-lg overflow-hidden bg-card p-2">
            {/* 头部切换按钮 */}
            <div className="flex items-center justify-between px-4 py-2 bg-muted/50 rounded-xl">
                <div className="flex gap-1 bg-background rounded-md">
                    <Button
                        onClick={() => setMode('chart')}
                        variant={mode === 'chart' ? 'default' : 'ghost'}
                        className="text-xs h-8"
                    >
                        图表
                    </Button>
                    <Button
                        onClick={() => setMode('code')}
                        variant={mode === 'code' ? 'default' : 'ghost'}
                        className="text-xs h-8"
                    >
                        代码
                    </Button>
                </div>
            </div>

            {/* 内容区域 */}
            <div className="bg-background">
                <div ref={ref} className={mode === 'chart' ? 'flex justify-center mermaid' : 'hidden'} />
                <div className={mode === 'code' ? 'block relative' : 'hidden'}>
                    <pre className="p-4 overflow-x-auto text-sm leading-relaxed max-h-[500px] overflow-y-auto">
                        <code className="text-foreground font-mono whitespace-pre-wrap break-words">
                            {children}
                        </code>
                    </pre>
                </div>
            </div>
        </div>
    </div>
}