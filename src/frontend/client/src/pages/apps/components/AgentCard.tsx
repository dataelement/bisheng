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
    showRemove?: boolean // New prop to determine if showing remove or add button
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
            <Card
                className={`relative p-0 cursor-pointer rounded-md transition-all duration-200 border-none bg-[#F7F9FC] hover:bg-[#EDEFF6]`}
                onMouseEnter={() => setIsHovered(true)}
                onMouseLeave={() => setIsHovered(false)}
                onClick={onClick}
            >
                <CardContent className="p-0">
                    <div className="">
                        <div className="flex gap-2 items-center p-5 pb-2 font-semibold leading-none tracking-tight truncate-doubleline">
                            <AppAvator id={agent.name} url={agent.logo} flowType={agent.flow_type} />
                            <h3 className="leading-5 align-middle">{agent.name}</h3>
                        </div>
                        <div className="p-5 pt-0 h-fit max-h-[60px] overflow-auto scrollbar-hide mb-4">
                            <p className="text-sm text-[#64748b] break-all">{agent.description}</p>
                        </div>
                    </div>

                    {/* Action Button */}
                    {isHovered && (
                        <div className="absolute top-2 right-2">
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        size="sm"
                                        variant={showRemove ? "destructive" : "default"}
                                        className={`w-6 h-6 p-0 ${showRemove ? "bg-red-500 hover:bg-red-600" : "bg-blue-600 hover:bg-blue-700"
                                            }`}
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            if (showRemove) {
                                                onRemoveFromFavorites()
                                            } else {
                                                onAddToFavorites()
                                            }
                                        }}
                                    >
                                        {showRemove ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p>{showRemove ? "从常用应用删除" : "添加到常用应用"}</p>
                                </TooltipContent>
                            </Tooltip>
                        </div>
                    )}
                </CardContent>
            </Card>
        </TooltipProvider>
    )
}
