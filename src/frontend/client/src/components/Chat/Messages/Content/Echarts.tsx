import * as echarts from 'echarts';
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "~/components/ui";

export default function ECharts({ option }: { option: string }) {
    const [mode, setMode] = useState<'chart' | 'code'>('chart');
    const chartRef = useRef<echarts.ECharts | null>(null);
    const domRef = useRef<HTMLDivElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // <CHANGE> 修复切换模式时的初始化和清理逻辑
    useEffect(() => {
        // 清理旧实例
        if (chartRef.current) {
            chartRef.current.dispose();
            chartRef.current = null;
        }

        // 只在图表模式下初始化
        if (domRef.current) {
            // 确保 DOM 已经渲染
            setTimeout(() => {
                if (domRef.current) {
                    chartRef.current = echarts.init(domRef.current);
                    const getOption = new Function('myChart', 'echarts', `return ${option}`);
                    try {
                        chartRef.current.setOption(getOption(chartRef.current, echarts));
                    } catch (e) {
                        console.error('[v0] ECharts option error:', e);
                    }
                }
            }, 0);
        }

        return () => {
            if (chartRef.current) {
                chartRef.current.dispose();
                chartRef.current = null;
            }
        };
    }, [option]);

    // 自适应宽度
    useEffect(() => {
        if (mode !== 'chart' || !containerRef.current || !chartRef.current) return;

        const resizeObserver = new ResizeObserver(() => {
            chartRef.current?.resize();
        });

        if (containerRef.current) {
            resizeObserver.observe(containerRef.current);
        }

        const handleResize = () => {
            chartRef.current?.resize();
        };
        window.addEventListener('resize', handleResize);

        return () => {
            resizeObserver.disconnect();
            window.removeEventListener('resize', handleResize);
        };
    }, [mode]);

    useEffect(() => {
        const parentNode = document.querySelector('.bisheng-message');
        if (parentNode && containerRef.current) {
            containerRef.current.style.width = `${parentNode.clientWidth - 60}px`;
        }
    }, [])

    const codeStr = useMemo(() => {
        try {
            return JSON.stringify(JSON.parse(option), null, 2);
        }
        catch (e) {
            return option;
        }
    }, [option]);

    return (
        <div className="w-full my-3 -ml-3.5" ref={containerRef}>
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
                    <div
                        ref={domRef}
                        style={{ height: 400 }}
                        className={mode === 'chart' ? 'block' : 'hidden'}
                    />
                    <div className={mode === 'code' ? 'block relative' : 'hidden'}>
                        <pre className="p-4 overflow-x-auto text-sm leading-relaxed max-h-[500px] overflow-y-auto">
                            <code className="text-foreground font-mono whitespace-pre-wrap break-words">
                                {codeStr}
                            </code>
                        </pre>
                    </div>
                </div>
            </div>
        </div>
    );
};