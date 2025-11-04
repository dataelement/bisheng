"use client"

import type React from "react"

import { Copy, DownloadIcon, ZoomIn, ZoomOut } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Button, Separator } from "~/components/ui"
import { copyText, formatDate } from "~/utils"
import { useLocalize } from "~/hooks"

// 动态加载 mermaid
export const loadScript = async (fileName) => {
    if (window[fileName]) {
        return window[fileName]
    }

    const script = document.createElement("script")
    script.src = `${__APP_ENV__.BASE_URL}/${fileName}.min.js`
    script.type = "module"

    return new Promise((resolve, reject) => {
        script.onload = () => {
            // 等待 mermaid 初始化
            const checkMermaid = setInterval(() => {
                if (window[fileName]) {
                    clearInterval(checkMermaid)
                    resolve(window[fileName])
                }
            }, 100)
        }
        script.onerror = reject
        document.head.appendChild(script)
    })
}

export default function MermaidBlock({ children }: { children: string }) {
    const ref = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const [mode, setMode] = useState<"chart" | "code">("chart")
    const mermaidRef = useRef<any>(null)
    const localize = useLocalize();

    const [zoom, setZoom] = useState(1)
    const [pan, setPan] = useState({ x: 0, y: 0 })
    const [isDragging, setIsDragging] = useState(false)
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
    const [copySuccess, setCopySuccess] = useState(false)
    const codeRef = useRef<HTMLElement>(null)

    useEffect(() => {
        loadScript('mermaid').then((mermaid) => {
            mermaid.initialize({ startOnLoad: false, theme: "default" })
            mermaidRef.current = mermaid
            if (ref.current) {
                ref.current.innerHTML = children
                mermaidRef.current.run({ nodes: [ref.current] })
            }
        })
    }, [])

    useEffect(() => {
        const parentNode = document.querySelector(".bisheng-message")
        if (parentNode && containerRef.current) {
            containerRef.current.style.width = `${parentNode.clientWidth - 60}px`
        }
    }, [])

    const handleZoomIn = () => {
        setZoom((prev) => Math.min(prev + 0.2, 3))
    }

    const handleZoomOut = () => {
        setZoom((prev) => Math.max(prev - 0.2, 0.5))
    }

    const handleDownload = async () => {
        if (!ref.current) return

        const svgElement = ref.current.querySelector("svg")
        if (!svgElement) return

        try {
            // Clone the SVG to avoid modifying the original
            const clonedSvg = svgElement.cloneNode(true) as SVGElement

            // Get computed styles and inline them to avoid CORS issues
            // const allElements = clonedSvg.querySelectorAll("*")
            // allElements.forEach((el) => {
            //     const computedStyle = window.getComputedStyle(el as Element)
            //     const styleString = Array.from(computedStyle)
            //         .map((key) => `${key}:${computedStyle.getPropertyValue(key)}`)
            //         .join(";")
            //         ; (el as HTMLElement).setAttribute("style", styleString)
            // })

            // Get SVG dimensions
            const bbox = svgElement.getBBox()
            const width = bbox.width || svgElement.clientWidth
            const height = bbox.height || svgElement.clientHeight

            // Set explicit width and height on cloned SVG
            clonedSvg.setAttribute("width", width.toString())
            clonedSvg.setAttribute("height", height.toString())

            // Create canvas
            const canvas = document.createElement("canvas")
            const scale = 2 // Higher resolution
            canvas.width = width * scale
            canvas.height = height * scale
            const ctx = canvas.getContext("2d")

            if (!ctx) return

            // Scale for better quality
            ctx.scale(scale, scale)
            ctx.fillStyle = "white"
            ctx.fillRect(0, 0, width, height)

            // Convert SVG to data URL (not blob URL to avoid CORS)
            const svgData = new XMLSerializer().serializeToString(clonedSvg)
            const svgDataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgData)}`

            // Load image and draw to canvas
            const img = new Image()
            img.onload = () => {
                ctx.drawImage(img, 0, 0)

                // Download
                canvas.toBlob((blob) => {
                    if (blob) {
                        const titleDom = document.querySelector("#app-title")
                        console.log('titleDom :>> ', titleDom);
                        const link = document.createElement("a")
                        link.download = `${titleDom?.innerHTML}_${formatDate(new Date(), 'yyyyMMdd_HHmm')}.png` || `mermaid-diagram-${Date.now()}.png`
                        link.href = URL.createObjectURL(blob)
                        link.click()
                        URL.revokeObjectURL(link.href)
                    }
                })
            }
            img.onerror = (error) => {
                console.error("Image load failed:", error)
            }
            img.src = svgDataUrl
        } catch (error) {
            console.error("Download failed:", error)
        }
    }
    const handleCopy = async () => {
        try {
            await copyText(codeRef.current)
            setCopySuccess(true)
            setTimeout(() => setCopySuccess(false), 2000)
        } catch (error) {
            console.error("Copy failed:", error)
        }
    }

    const handleMouseDown = (e: React.MouseEvent) => {
        // if (zoom > 1) {
        setIsDragging(true)
        setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y })
        // }
    }

    const handleMouseMove = (e: React.MouseEvent) => {
        if (isDragging) {
            setPan({
                x: e.clientX - dragStart.x,
                y: e.clientY - dragStart.y,
            })
        }
    }

    const handleMouseUp = () => {
        setIsDragging(false)
    }

    const handleMouseLeave = () => {
        setIsDragging(false)
    }

    return (
        <div className="w-full my-3" ref={containerRef}>
            <div className="shadow-sm rounded-lg bg-muted overflow-hidden">
                {/* 头部切换按钮 */}
                <div className="flex items-center justify-between p-2 relative z-10 bg-muted">
                    <div className="flex gap-1 bg-background rounded-md">
                        <Button
                            onClick={() => setMode("chart")}
                            variant={mode === "chart" ? "default" : "ghost"}
                            className="text-xs h-8"
                        >
                            {localize('com_ui_chart')}
                        </Button>
                        <Button
                            onClick={() => setMode("code")}
                            variant={mode === "code" ? "default" : "ghost"}
                            className="text-xs h-8"
                        >
                            {localize('com_ui_code')}
                        </Button>
                    </div>
                    {mode === "chart" && (
                        <div className="flex items-center">
                            <Button
                                onClick={handleZoomOut}
                                variant="ghost"
                                size="icon"
                                className="text-xs h-8"
                                disabled={zoom <= 0.5}
                            >
                                <ZoomOut size={16} />
                            </Button>
                            <Button
                                onClick={handleZoomIn}
                                variant="ghost"
                                size="icon"
                                className="text-xs h-8"
                                disabled={zoom >= 3}
                            >
                                <ZoomIn size={16} />
                            </Button>
                            <Separator orientation="vertical" className="h-4 mx-1" />
                            <Button onClick={handleDownload} variant="ghost" className="text-xs h-8">
                                <DownloadIcon size={16} />
                                {localize('com_ui_download')}
                            </Button>
                        </div>
                    )}
                    {mode === "code" && (
                        <div className="flex items-center">
                            <Button onClick={handleCopy} variant="ghost" className="text-xs h-8">
                                <Copy size={16} />
                                {copySuccess ? localize('com_ui_duplicated') : localize('com_ui_duplicate')}
                            </Button>
                        </div>
                    )}
                </div>

                {/* 内容区域 */}
                <div className="">
                    <div
                        ref={ref}
                        className={mode === "chart" ? "flex justify-center mermaid overflow-hidden" : "hidden"}
                        style={{
                            transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
                            transformOrigin: "center center",
                            cursor: (isDragging ? "grabbing" : "grab"),
                            transition: isDragging ? "none" : "transform 0.2s ease-out",
                        }}
                        onMouseDown={handleMouseDown}
                        onMouseMove={handleMouseMove}
                        onMouseUp={handleMouseUp}
                        onMouseLeave={handleMouseLeave}
                    />
                    <div className={mode === "code" ? "block relative" : "hidden"}>
                        <pre className="p-4 overflow-x-auto text-sm leading-relaxed max-h-[500px] overflow-y-auto">
                            <code ref={codeRef} className="text-slate-500 text-foreground font-mono whitespace-pre-wrap break-words">{children}</code>
                        </pre>
                    </div>
                </div>
            </div>
        </div>
    )
}
