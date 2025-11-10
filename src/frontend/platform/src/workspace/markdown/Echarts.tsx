"use client"

import { Copy } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { Button } from "@/components/bs-ui/button"
import { copyText } from "@/utils"
import { loadScript } from "./Mermaid"

export default function ECharts({ option }: { option: string }) {
    const [mode, setMode] = useState<"chart" | "code">("chart")
    const [echartsLib, setEchartsLib] = useState<any>(null)
    const chartRef = useRef<any | null>(null)
    const domRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        loadScript("echarts")
            .then((echarts) => {
                console.log("[v0] ECharts library loaded successfully", echarts)
                setEchartsLib(echarts)
            })
            .catch((error) => {
                console.error("[v0] Failed to load ECharts library:", error)
            })
    }, [])

    useEffect(() => {
        // 等待 echarts 库加载完成
        if (!echartsLib) return

        // 清理旧实例
        if (chartRef.current) {
            chartRef.current.dispose()
            chartRef.current = null
        }

        // 只在图表模式下初始化
        if (domRef.current) {
            // 确保 DOM 已经渲染
            setTimeout(() => {
                if (domRef.current && echartsLib) {
                    chartRef.current = echartsLib.init(domRef.current)
                    const getOption = new Function("myChart", "echarts", `return ${option.trim()}`)
                    try {
                        chartRef.current.setOption(getOption(chartRef.current, echartsLib))
                    } catch (e) {
                        console.error("[v0] ECharts option error:", e)
                    }
                }
            }, 0)
        }

        return () => {
            if (chartRef.current) {
                chartRef.current.dispose()
                chartRef.current = null
            }
        }
    }, [option, echartsLib])

    // 自适应宽度
    useEffect(() => {
        if (mode !== "chart" || !containerRef.current || !chartRef.current) return

        const resizeObserver = new ResizeObserver(() => {
            chartRef.current?.resize()
        })

        if (containerRef.current) {
            resizeObserver.observe(containerRef.current)
        }

        const handleResize = () => {
            chartRef.current?.resize()
        }
        window.addEventListener("resize", handleResize)

        return () => {
            resizeObserver.disconnect()
            window.removeEventListener("resize", handleResize)
        }
    }, [mode])

    useEffect(() => {
        const parentNode = document.querySelector(".bisheng-message")
        if (parentNode && containerRef.current) {
            containerRef.current.style.width = `${parentNode.clientWidth - 60}px`
        }
    }, [])

    const codeStr = useMemo(() => {
        try {
            return JSON.stringify(JSON.parse(option), null, 2)
        } catch (e) {
            return option
        }
    }, [option])

    const [copySuccess, setCopySuccess] = useState(false)
    const handleCopy = async () => {
        try {
            await copyText(option)
            setCopySuccess(true)
            setTimeout(() => setCopySuccess(false), 2000)
        } catch (error) {
            console.error("Copy failed:", error)
        }
    }

    return (
        <div className="my-3 -ml-3.5" ref={containerRef}>
            <div className="shadow-sm rounded-lg bg-muted overflow-hidden">
                {/* 头部切换按钮 */}
                <div className="flex items-center justify-between p-2 relative z-10 bg-muted">
                    <div className="flex gap-1 bg-background rounded-md">
                        <Button
                            onClick={() => setMode("chart")}
                            variant={mode === "chart" ? "default" : "ghost"}
                            className="text-xs h-8"
                        >
                            图表
                        </Button>
                        <Button
                            onClick={() => setMode("code")}
                            variant={mode === "code" ? "default" : "ghost"}
                            className="text-xs h-8"
                        >
                            代码
                        </Button>
                    </div>
                    {mode === "code" && (
                        <div className="flex items-center">
                            <Button onClick={handleCopy} variant="ghost" className="text-xs h-8">
                                <Copy size={16} />
                                {copySuccess ? "已复制" : "复制"}
                            </Button>
                        </div>
                    )}
                </div>

                {/* 内容区域 */}
                <div className="">
                    {!echartsLib && mode === "chart" && (
                        <div className="flex items-center justify-center h-[400px] text-muted-foreground">loading...</div>
                    )}
                    <div ref={domRef} style={{ height: 400 }} className={mode === "chart" && echartsLib ? "block" : "hidden"} />
                    <div className={mode === "code" ? "block relative" : "hidden"}>
                        <pre className="p-4 overflow-x-auto text-sm leading-relaxed max-h-[500px] overflow-y-auto mt-0 bg-transparent">
                            <code className="text-slate-500 font-mono whitespace-pre-wrap break-words">{codeStr}</code>
                        </pre>
                    </div>
                </div>
            </div>
        </div>
    )
}
