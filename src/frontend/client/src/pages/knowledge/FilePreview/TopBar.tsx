import { DownloadIcon, ZoomInIcon, ZoomOutIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "~/components";
import { cn } from "~/utils";

/** 与 `public/assets/channel/grid-three.svg` 同形，描边用 currentColor 以便 active/hover 变色 */
function SidebarToggleIcon({ className }: { className?: string }) {
    return (
        <svg
            className={cn("size-4 shrink-0", className)}
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden
        >
            <path
                d="M13.1 2H2.9C2.40294 2 2 2.40294 2 2.9V13.1C2 13.5971 2.40294 14 2.9 14H13.1C13.5971 14 14 13.5971 14 13.1V2.9C14 2.40294 13.5971 2 13.1 2Z"
                stroke="currentColor"
                strokeWidth="1.33333"
            />
            <path d="M5 2V14" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" />
            <path d="M5 4.90088H2" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" />
            <path d="M5 8H2" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" />
            <path d="M5 11.0991H2" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" />
        </svg>
    );
}

interface TopBarProps {
    fileName: string;
    /** Show sidebar toggle */
    showSidebar?: boolean;
    sidebarOpen?: boolean;
    onToggleSidebar?: () => void;
    /** Show zoom controls */
    showZoom?: boolean;
    zoomLevel?: number;
    onZoomIn?: () => void;
    onZoomOut?: () => void;
    /** Show page navigation */
    showPagination?: boolean;
    currentPage?: number;
    totalPages?: number;
    onPageChange?: (page: number) => void;
    /** Download */
    onDownload?: () => void;
    /** Slot: extra actions rendered at the right side (before download button) */
    actions?: React.ReactNode;
}

export function TopBar({
    fileName,
    showSidebar = false,
    sidebarOpen = false,
    onToggleSidebar,
    showZoom = true,
    zoomLevel = 100,
    onZoomIn,
    onZoomOut,
    showPagination = false,
    currentPage = 1,
    totalPages = 0,
    onPageChange,
    onDownload,
    actions,
}: TopBarProps) {
    const [pageInput, setPageInput] = useState(String(currentPage));
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        setPageInput(String(currentPage));
    }, [currentPage]);

    const handlePageSubmit = useCallback(() => {
        const num = parseInt(pageInput, 10);
        if (!isNaN(num) && num >= 1 && num <= totalPages) {
            onPageChange?.(num);
        } else {
            setPageInput(String(currentPage));
        }
        inputRef.current?.blur();
    }, [pageInput, totalPages, currentPage, onPageChange]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") handlePageSubmit();
        if (e.key === "Escape") {
            setPageInput(String(currentPage));
            inputRef.current?.blur();
        }
    };

    return (
        <div className="flex items-center justify-between px-[24px] py-5 border-b border-[#ececec] bg-white shrink-0 select-none z-50">
            {/* ===== Left: TOC toggle + File name ===== */}
            <div className="flex items-center gap-3 min-w-0 flex-1">
                {showSidebar && (
                    <div className="flex items-center relative shrink-0">
                        <Button
                            variant="ghost"
                            className={cn(
                                "group h-8 w-8 rounded-md border p-1.5",
                                sidebarOpen
                                    ? "border-primary bg-primary/10"
                                    : "border-[#e5e6eb] bg-white hover:bg-[#f7f8fa]"
                            )}
                            onClick={onToggleSidebar}
                        >
                            <SidebarToggleIcon
                                className={cn(
                                    "transition-colors",
                                    sidebarOpen ? "text-primary" : "text-[#86909c] group-hover:text-[#4e5969]"
                                )}
                            />
                        </Button>
                    </div>
                )}
                <span className="text-xl font-semibold text-gray-800 flex-1 break-all">
                    {fileName}
                </span>
            </div>

            {/* ===== Center: Zoom + Pagination ===== */}
            <div className="flex gap-[16px] items-center relative shrink-0 justify-center flex-1">
                {showZoom && (
                    <div className="content-stretch flex gap-[4px] items-center relative shrink-0">
                        <Button onClick={onZoomOut} disabled={zoomLevel <= 25}
                            variant="ghost" className="w-8 h-8 p-2">
                            <ZoomOutIcon className="text-[#64698b]" />
                        </Button>

                        <div className="bg-white border hover:border-[#335cff] cursor-pointer transition-colors border-[#ececec] border-solid content-stretch flex items-center justify-between overflow-clip px-[8px] py-[3px] relative rounded-[6px] shrink-0 w-[88px] h-[32px]">
                            <div className="content-stretch flex gap-[4px] items-center relative shrink-0">
                                <p className="font-['PingFang_SC:Regular',sans-serif] leading-[22px] not-italic relative shrink-0 text-[#212121] text-[14px] whitespace-nowrap">
                                    {zoomLevel}%
                                </p>
                            </div>
                        </div>

                        <Button onClick={onZoomIn} disabled={zoomLevel >= 500}
                            variant="ghost" className="w-8 h-8 p-2">
                            <ZoomInIcon className="text-[#64698b]" />
                        </Button>
                    </div>
                )}

                {showPagination && totalPages > 0 && (
                    <div className="content-stretch flex gap-[4px] items-center relative shrink-0">
                        <div className="bg-[#fbfbfb] content-stretch flex items-center overflow-clip px-[8px] py-[3px] relative rounded-[6px] shrink-0 w-[40px] h-[28px]">
                            <input
                                ref={inputRef}
                                type="text"
                                value={pageInput}
                                onChange={(e) => setPageInput(e.target.value)}
                                onBlur={handlePageSubmit}
                                onKeyDown={handleKeyDown}
                                className="w-full text-center bg-transparent outline-none font-['PingFang_SC:Regular',sans-serif] leading-[22px] text-[#212121] text-[14px]"
                            />
                        </div>
                        <div className="relative shrink-0 size-[12px] flex items-center justify-center text-[#86909c]">
                            /
                        </div>
                        <p className="font-['PingFang_SC:Regular',sans-serif] leading-[22px] text-[#212121] text-[14px] whitespace-nowrap pl-1">
                            {totalPages}
                        </p>
                    </div>
                )}
            </div>

            {/* ===== Right: actions slot + Download ===== */}
            <div className="content-stretch flex gap-[12px] items-center justify-end relative shrink-0 flex-1">
                {actions}
                {onDownload && (
                    <Button onClick={onDownload}
                        variant="outline" className="w-8 h-8 p-2">
                        <DownloadIcon />
                    </Button>
                )}
            </div>
        </div>
    );
}
