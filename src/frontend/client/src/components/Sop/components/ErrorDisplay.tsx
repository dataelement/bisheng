"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp } from 'lucide-react'

interface TaskErrorDisplayProps {
    title: string
    taskError: string
}

export default function ErrorDisplay({ title, taskError }: TaskErrorDisplayProps) {
    const [isExpanded, setIsExpanded] = useState(false)

    const toggleExpanded = () => {
        setIsExpanded(!isExpanded)
    }

    return (
        <div className="bg-red-100 p-2 rounded-md text-sm text-red-500 mb-2">
            <div
                className={`cursor-pointer ${!isExpanded ? "line-clamp-3" : ""
                    }`}
                onClick={toggleExpanded}
            >
                <span className="">{title}：</span>
                {taskError}
            </div>
            {taskError.length > 150 && (
                <div className="flex items-center justify-center mt-1">
                    <button
                        onClick={toggleExpanded}
                        className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 transition-colors"
                    >
                        {/* {isExpanded ? (
                            <>
                                收起 <ChevronUp className="w-3 h-3" />
                            </>
                        ) : (
                            <>
                                展开 <ChevronDown className="w-3 h-3" />
                            </>
                        )} */}
                    </button>
                </div>
            )}
        </div>
    )
}
