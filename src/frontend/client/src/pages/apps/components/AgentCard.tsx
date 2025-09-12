"use client"

import { Plus, X } from "lucide-react"
import { useState } from "react"
import { Button } from "~/components"
import AppAvator from "~/components/Avator"
import { Card, CardContent } from "~/components/ui/Card"

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "~/components/ui/tooltip2"

interface Agent {
    id: string
    name: string
    description: string
    flow_type: number
    logo: string
    category: string
}

interface AgentCardProps {
    agent: Agent
    isFavorite: boolean
    showRemove?: boolean // 决定显示移除还是添加按钮
    onAddToFavorites: () => void
    onRemoveFromFavorites: () => void
    onClick: (e: React.MouseEvent<HTMLDivElement>) => void
}

export function AgentCard({
    agent,
    showRemove = false,
    onClick,
    onAddToFavorites,
    onRemoveFromFavorites,
}: AgentCardProps) {
    const [isHovered, setIsHovered] = useState(false)

    return (
        <TooltipProvider>
            {/* 核心调整：固定高度为 150px，flex 垂直布局确保内部元素适配 */}
            <Card
                className={`relative cursor-pointer rounded-md transition-all duration-200 border-none bg-[#F7F9FC] hover:bg-[#EDEFF6]
                           h-[150px] py-1 flex flex-col overflow-hidden`}
                onMouseEnter={() => setIsHovered(true)}
                onMouseLeave={() => setIsHovered(false)}
                onClick={onClick}
            >
                <CardContent className="p-0 flex flex-col flex-1">  {/* flex-1 让内容区填充满卡片 */}
                    <div className="flex flex-col flex-1 px-4 py-2">
                        {/* 1. 名称+图标区域：固定高度 40px，避免名称长度影响整体高度 */}
                        <div className="flex gap-2 items-center h-10 mb-1">  {/* 高度压缩为 40px（h-10） */}
                            <AppAvator
                                id={agent.name}
                                url={agent.logo}
                                flowType={agent.flow_type}
                                className="size-6 min-w-6"
                            />
                            <h3 className="leading-5 pl-1 align-middle truncate text-sm font-medium">  {/* 名称文字缩小，过长截断 */}
                                {agent.name}
                            </h3>
                        </div>

                        {/* 2. 描述区域：占满剩余空间，最多显示 2 行（适配 150px 高度） */}
                        <div className="flex-1 overflow-hidden">
                            <p className="text-sm text-[#64748b] leading-5 break-words line-clamp-2">  {/* 文字缩小为 xs，最多 2 行 */}
                                {agent.description}  {/* 空描述兜底，避免高度塌陷 */}
                            </p>
                        </div>
                    </div>

                    {/* 操作按钮：位置不变，不影响高度统一 */}
                    {isHovered && (
                        <div className="absolute top-2 right-2">
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        size="sm"
                                        variant={showRemove ? "destructive" : "default"}
                                        className={`w-6 h-6 p-0 ${showRemove ? "bg-red-500 hover:bg-red-600" : "bg-blue-600 hover:bg-blue-700"}`}
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            showRemove ? onRemoveFromFavorites() : onAddToFavorites()
                                        }}
                                    >
                                        {showRemove ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="text-xs">{showRemove ? "从常用应用删除" : "添加到常用应用"}</p>
                                </TooltipContent>
                            </Tooltip>
                        </div>
                    )}
                </CardContent>
            </Card>
        </TooltipProvider>
    )
}