"use client"

import type React from "react"
import { useState } from "react"
import { AgentCard } from "./AgentCard"
import { Button } from "~/components"
import { ChevronDown } from "lucide-react"

// Mock data - replace with real data
const mockAgents = {
    assistant: [
        {
            id: "1",
            name: "智能助手",
            description: "为您提供智能对话和问题解答服务，帮助您快速获取信息和解决问题。",
            icon: "🤖",
            category: "assistant",
        },
        {
            id: "2",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "❓",
            category: "assistant",
        },
        {
            id: "3",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🔵",
            category: "assistant",
        },
        {
            id: "4",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🔷",
            category: "assistant",
        },
        {
            id: "5",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟢",
            category: "assistant",
        },
        {
            id: "6",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟣",
            category: "assistant",
        },
        {
            id: "7",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟡",
            category: "assistant",
        },
        {
            id: "8",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟠",
            category: "assistant",
        },
        {
            id: "18",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟠",
            category: "assistant",
        },
    ],
    content: [
        {
            id: "9",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟢",
            category: "content",
        },
        {
            id: "10",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟣",
            category: "content",
        },
        {
            id: "11",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟢",
            category: "content",
        },
        {
            id: "12",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟣",
            category: "content",
        },
        {
            id: "13",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟢",
            category: "content",
        },
        {
            id: "14",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟣",
            category: "content",
        },
        {
            id: "15",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟢",
            category: "content",
        },
        {
            id: "16",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟣",
            category: "content",
        },
    ],
    text: [
        {
            id: "17",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟢",
            category: "text",
        },
        {
            id: "18",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟣",
            category: "text",
        },
        {
            id: "19",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟢",
            category: "text",
        },
        {
            id: "20",
            name: "通用问答助手",
            description: '上海交大，基于"开源"智能问答助手的实现，自动回答各种问题，提供准确的信息和建议，支持多种语言。',
            icon: "🟣",
            category: "text",
        },
    ],
    voice: [
        {
            id: "21",
            name: "语音助手",
            description: "提供语音对话功能，支持语音识别和语音合成。",
            icon: "🎤",
            category: "voice",
        },
        {
            id: "22",
            name: "语音助手",
            description: "提供语音对话功能，支持语音识别和语音合成。",
            icon: "🔊",
            category: "voice",
        },
    ],
    understanding: [
        {
            id: "23",
            name: "内容理解助手",
            description: "帮助理解和分析各种类型的内容。",
            icon: "🧠",
            category: "understanding",
        },
        {
            id: "24",
            name: "内容理解助手",
            description: "帮助理解和分析各种类型的内容。",
            icon: "📖",
            category: "understanding",
        },
    ],
    business: [
        {
            id: "25",
            name: "商务助手",
            description: "协助处理各种商务相关任务。",
            icon: "💼",
            category: "business",
        },
        {
            id: "26",
            name: "商务助手",
            description: "协助处理各种商务相关任务。",
            icon: "📊",
            category: "business",
        },
    ],
    roleplay: [
        {
            id: "27",
            name: "角色扮演助手",
            description: "提供各种角色扮演和模拟对话功能。",
            icon: "🎭",
            category: "roleplay",
        },
        {
            id: "28",
            name: "角色扮演助手",
            description: "提供各种角色扮演和模拟对话功能。",
            icon: "🎪",
            category: "roleplay",
        },
    ],
}

interface AgentGridProps {
    favorites: string[]
    onAddToFavorites: (agentId: string) => void
    onRemoveFromFavorites: (agentId: string) => void
    sectionRefs: React.MutableRefObject<Record<string, HTMLElement | null>>
}

export function AgentGrid({ favorites, onAddToFavorites, onRemoveFromFavorites, sectionRefs }: AgentGridProps) {
    const [visibleCounts, setVisibleCounts] = useState<Record<string, number>>({})

    const allAgents = Object.values(mockAgents).flat()
    const favoriteAgents = allAgents.filter((agent) => favorites.includes(agent.id))

    const loadMore = (category: string) => {
        setVisibleCounts((prev) => ({
            ...prev,
            [category]: (prev[category] || 8) + 8,
        }))
    }

    const sections = [
        { id: "favorites", name: "常用", agents: favoriteAgents },
        { id: "assistant", name: "助手", agents: mockAgents.assistant },
        { id: "content", name: "内容创作", agents: mockAgents.content },
        { id: "text", name: "文本创作", agents: mockAgents.text },
        { id: "voice", name: "语音对话", agents: mockAgents.voice },
        { id: "understanding", name: "内容理解", agents: mockAgents.understanding },
        { id: "business", name: "商务助手", agents: mockAgents.business },
        { id: "roleplay", name: "角色扮演", agents: mockAgents.roleplay },
    ]

    return (
        <div className="space-y-8">
            {sections.map((section) => {
                const visibleCount = visibleCounts[section.id] || 8
                const visibleAgents = section.agents.slice(0, visibleCount)
                const hasMore = section.agents.length > visibleCount

                return (
                    <section
                        key={section.id}
                        className="relative"
                        ref={(el) => {
                            sectionRefs.current[section.id] = el
                        }}
                    >
                        {section.id != 'favorites' && <h2 className="text-base font-medium mb-2 text-blue-600">{section.name}</h2>}
                        <div className="grid grid-cols-4 gap-2">
                            {visibleAgents.map((agent) => (
                                <AgentCard
                                    key={agent.id}
                                    agent={agent}
                                    isFavorite={favorites.includes(agent.id)}
                                    showRemove={section.id === "favorites"}
                                    onAddToFavorites={() => onAddToFavorites(agent.id)}
                                    onRemoveFromFavorites={() => onRemoveFromFavorites(agent.id)}
                                />
                            ))}
                        </div>
                        {hasMore && (
                            <div className="flex justify-end mt-6">
                                <Button
                                    variant="default"
                                    onClick={() => loadMore(section.id)}
                                    className="h-7 px-2 text-xs"
                                >
                                    <ChevronDown size={14}/>
                                    展示更多
                                </Button>
                            </div>
                        )}
                    </section>
                )
            })}
        </div>
    )
}
