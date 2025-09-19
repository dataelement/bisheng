"use client"

import { SettingsIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { Button } from "~/components"
import { useAuthContext, useLocalize } from "~/hooks"
import MarkLabel from "./MarkLabel"
import { getHomeLabelApi } from "~/api/apps"

interface Category {
    value: string
    label: string,
    selected: boolean
}

interface AgentNavigationProps {
    onCategoryChange: (categoryId: string) => void
    onRefresh: () => void
}

export function AgentNavigation({ onCategoryChange, onRefresh }: AgentNavigationProps) {
    const { user } = useAuthContext();
    const localize = useLocalize();

    const [isLabelModalOpen, setIsLabelModalOpen] = useState(false)
    const [activeCategory, setActiveCategory] = useState<string>("favorites")

    const [categories, setCategories] = useState<Category[]>([])

    const fetchCategoryTags = async () => {
        const tags = await getHomeLabelApi()
        // tags.data.unshift({ id: "favorites", name: "常用", selected: true })
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


    const handleCloseLabelModal = async (shouldClose) => {
        if (shouldClose) {
            setIsLabelModalOpen(false)
        } else {
            setIsLabelModalOpen(shouldClose)
        }
        await fetchCategoryTags()
        onRefresh();
    }

    return (
        <nav className="flex items-center gap-2 flex-wrap">
            <Button
                variant={activeCategory === 'favorites' ? "default" : "outline"}
                onClick={() => {
                    onCategoryChange('favorites')
                    setActiveCategory('favorites')
                }}
                className="text-xs h-8 font-normal"
            >{localize('com_app_common')}</Button>
            {categories.map((category) => (
                <Button
                    key={category.value}
                    variant={activeCategory === category.value ? "default" : "outline"}
                    onClick={() => {
                        onCategoryChange(category.value)
                        setActiveCategory(category.value)
                    }}
                    className="text-xs h-8 font-normal"
                >
                    {category.label}
                </Button>

            ))}
            <Button
                variant={activeCategory === 'uncategorized' ? "default" : "outline"}
                onClick={() => {
                    onCategoryChange('uncategorized')
                    setActiveCategory('uncategorized')
                }}
                className="text-xs h-8 font-normal"
            >{localize('com_app_uncategorized')}</Button>
            {/* edit label  */}
            {user?.role === 'admin' && (
                <Button size={'icon'} variant={"outline"} className="h-8" onClick={() => setIsLabelModalOpen(true)}>
                    <SettingsIcon size={18} />
                </Button>
            )}

            <MarkLabel
                open={isLabelModalOpen}
                home={categories}
                onClose={handleCloseLabelModal}
            />
        </nav>
    )
}
