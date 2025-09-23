"use client"

import { Earth } from "lucide-react"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "~/components/ui/Sheet"

interface SearchResultItem {
    content: string
    suffix: string
    title: string
}

interface SearchResultsSheetProps {
    isOpen: boolean
    onClose: () => void
    data: SearchResultItem[]
    searchQuery: string
}

export function WebSearchSheet({ isOpen, onClose, data = [], searchQuery }: SearchResultsSheetProps) {

    return (
        <Sheet open={isOpen} onOpenChange={onClose}>
            <SheetContent side="right" className="w-[600px] sm:w-[700px] sm:max-w-[700px] p-0">
                <SheetHeader className="p-4 border-b border-border">
                    <div className="flex items-center gap-3">
                        <Earth className="w-5 h-5 text-muted-foreground" />
                        <SheetTitle className="text-lg font-semibold text-foreground">网页搜索</SheetTitle>
                    </div>
                    <SheetDescription className="text-left">
                        <div className="flex items-center gap-2 text-sm text-muted-foreground mt-2">
                            <span>🔍检索问题:</span>
                            <span className="font-medium text-foreground">"{searchQuery}"</span>
                        </div>
                    </SheetDescription>
                </SheetHeader>

                {/* Results Content */}
                <div className="flex-1 h-[calc(100vh-120px)] overflow-y-auto">
                    <div className="p-4 space-y-4">
                        {data.map((item, index) => (
                            <div
                                key={index}
                                className="border-b overflow-hidden hover:border-blue-500 transition-colors duration-200 cursor-pointer"
                            >
                                {/* Content - always expanded as per design */}
                                <div className="p-4 bg-card">
                                    <div className="mb-3 flex items-center gap-2">
                                        <div className="">
                                            <img src={item.thumbnail} className="max-w-12 max-h-12" alt="" />
                                        </div>
                                        <h4 className="text-sm font-medium text-foreground">{item.title}</h4>
                                    </div>
                                    <div className="font-normal text-sm text-[#303133] leading-6 break-all">
                                        <a href={item.url} target="_blank" rel="noopener noreferrer">
                                            <p className="line-clamp-2 overflow-hidden text-ellipsis">{item.content}</p>
                                        </a>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    )
}
