"use client"

import { SettingsIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { useAuthContext, useLocalize } from "~/hooks"
import MarkLabel from "./MarkLabel"
import { getHomeLabelApi } from "~/api/apps"
import { cn } from "~/utils"

interface Category {
    value: string
    label: string,
    selected: boolean
}

interface AgentNavigationProps {
    onCategoryChange: (categoryId: number | string) => void
    onRefresh: () => void
}

export function AgentNavigation({ onCategoryChange, onRefresh }: AgentNavigationProps) {
    const { user } = useAuthContext();
    const localize = useLocalize();

    const [isLabelModalOpen, setIsLabelModalOpen] = useState(false)
    const [activeCategory, setActiveCategory] = useState<number | string>(-1)

    const [categories, setCategories] = useState<Category[]>([])

    const fetchCategoryTags = async () => {
        const tags = await getHomeLabelApi()
        setCategories(tags.data.map(tag => ({
            label: tag.name,
            value: tag.id,
            selected: true
        })))
    }

    // Initial data load
    useEffect(() => {
        fetchCategoryTags()
    }, [])

    const handleCloseLabelModal = async (shouldClose: boolean) => {
        if (shouldClose) {
            setIsLabelModalOpen(false)
        } else {
            setIsLabelModalOpen(shouldClose)
        }
        await fetchCategoryTags()
        onRefresh();
    }

    const renderTab = (id: number | string, label: string) => {
        const isActive = activeCategory === id;
        return (
            <div
                key={id}
                onClick={() => {
                    onCategoryChange(id);
                    setActiveCategory(id);
                }}
                className={cn(
                    "flex items-center justify-center px-[16px] py-[5px] relative rounded-[6px] shrink-0 cursor-pointer transition-all",
                    isActive
                        ? "backdrop-blur-[4px] bg-[rgba(51,92,255,0.2)] border border-[#335cff] border-solid"
                        : "hover:bg-gray-100 border border-transparent"
                )}
            >
                <p className={cn(
                    "font-['PingFang_SC'] text-[14px] leading-[22px] whitespace-nowrap",
                    isActive ? "text-[#335cff]" : "text-[#212121]"
                )}>
                    {label}
                </p>
            </div>
        )
    };

    return (
        <nav className="flex items-center gap-[8px] flex-wrap">
            {renderTab(-1, "精选")}
            {categories.map((category) => renderTab(category.value, category.label))}
            {renderTab('uncategorized', localize('com_app_uncategorized') || '未分类')}
            
            {/* edit label  */}
            {user?.role === 'admin' && (
                <button
                    onClick={() => setIsLabelModalOpen(true)}
                    className="flex items-center justify-center p-[6px] relative rounded-[6px] shrink-0 hover:bg-gray-100 transition-colors ml-1"
                >
                    <SettingsIcon size={16} className="text-[#666]" />
                </button>
            )}

            <MarkLabel
                open={isLabelModalOpen}
                home={categories}
                onClose={handleCloseLabelModal}
            />
        </nav>
    )
}
