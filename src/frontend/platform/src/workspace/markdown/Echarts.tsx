import { Button } from '@bisheng/ui';

import { Copy } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { LoadingState } from "@/components/bs-icons/loading/LoadingState"

import { copyText } from "@/utils"
import { loadScript } from "./Mermaid"

export default function ECharts({ option }: { option: string }) {
    const { t } = useTranslation("shared")
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
        // Wait until the chart library is available.
        if (!echartsLib) return

        // Dispose the previous chart instance.
        if (chartRef.current) {
            chartRef.current.dispose()
            chartRef.current = null
        }

        // Initialize the chart only when its canvas is mounted.
        if (domRef.current) {
            // Wait until the canvas has rendered.
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

    // Keep the chart responsive to its container.
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
                {/* Chart and code view controls. */}
                <div className="flex items-center justify-between p-2 relative z-10 bg-muted">
                    <div className="flex gap-1 bg-background rounded-md">
                        <Button onClick={() => setMode("chart")} variant={mode === "chart" ? "default" : "ghost"} className="text-xs h-8">
                            {t("app_chat.chart")}
                        </Button>
                        <Button onClick={() => setMode("code")} variant={mode === "code" ? "default" : "ghost"} className="text-xs h-8">
                            {t("app_chat.code")}
                        </Button>
                    </div>
                    {mode === "code" && (
                        <div className="flex items-center">
                            <Button onClick={handleCopy} variant="text" className="text-xs h-8" color="default">
                                <Copy size={16} />
                                {t(copySuccess ? "app_chat.copied" : "app_chat.copy")}
                            </Button>
                        </div>
                    )}
                </div>

                {/* Active chart or source view. */}
                <div className="">
                    {!echartsLib && mode === "chart" && (
                        <LoadingState className="h-[400px]" />
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
