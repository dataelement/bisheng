"use client"

import { Tabs } from "@bisheng/ui"
import { BoltIcon } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useAuthContext, useLocalize } from "~/hooks"
import MarkLabel from "./MarkLabel"
import { getHomeLabelApi } from "~/api/apps"

interface Category {
    value: number
    label: string
}

export type AppCategoryId = number | 'all' | 'uncategorized'

interface AgentNavigationProps {
    onCategoryChange: (categoryId: AppCategoryId) => void
    onRefresh: () => void
    /**
     * A keyword search is running. Search results span every category, so no
     * tab is highlighted while one is active — clicking a tab ends the search
     * (the parent clears the keyword) and the highlight comes back.
     */
    searchActive?: boolean
}

export function AgentNavigation({ onCategoryChange, onRefresh, searchActive = false }: AgentNavigationProps) {
    const { user } = useAuthContext();
    const localize = useLocalize();

    const [isLabelModalOpen, setIsLabelModalOpen] = useState(false)
    const [activeCategory, setActiveCategory] = useState<AppCategoryId>('all')

    const [categories, setCategories] = useState<Category[]>([])
    const activeCategoryRef = useRef<AppCategoryId>('all')

    const selectCategory = useCallback((id: AppCategoryId) => {
        activeCategoryRef.current = id
        setActiveCategory(id)
        onCategoryChange(id)
    }, [onCategoryChange])

    const fetchCategoryTags = useCallback(async () => {
        try {
            const { data } = await getHomeLabelApi() as { data: { id: number; name: string }[] }
            const next = data.map(tag => ({
                label: tag.name,
                value: tag.id,
            }))
            setCategories(next)

            // The tag editor can remove the selected category.
            const current = activeCategoryRef.current
            if (typeof current === 'number' && !next.some((category) => category.value === current)) {
                selectCategory('all')
            }
        } catch (error) {
            console.error("Failed to load app categories:", error)
        }
    }, [selectCategory])

    useEffect(() => {
        selectCategory('all')
        fetchCategoryTags()
    }, [fetchCategoryTags, selectCategory])

    const handleCloseLabelModal = async (shouldClose: boolean) => {
        if (shouldClose) {
            setIsLabelModalOpen(false)
        } else {
            setIsLabelModalOpen(shouldClose)
        }
        await fetchCategoryTags()
        onRefresh();
    }

    const handleTabChange = (key: string) => {
        selectCategory(key === 'all' || key === 'uncategorized' ? key : Number(key))
    }

    return (
        <>
            <Tabs
                aria-label={localize('com_nav_app_center')}
                activeKey={searchActive ? '' : String(activeCategory)}
                onChange={handleTabChange}
                items={[
                    { key: 'all', label: localize('com_app.all') },
                    ...categories.map(({ value, label }) => ({ key: String(value), label })),
                    { key: 'uncategorized', label: localize('com_app_uncategorized') },
                ]}
                extra={user?.role === 'admin' ? (
                    <button
                        type="button"
                        aria-label={localize('com_label_settings_title')}
                        onClick={() => setIsLabelModalOpen(true)}
                        className="mr-2 flex shrink-0 items-center justify-center rounded-md p-1.5 hover:bg-gray-100 transition-colors"
                    >
                        <BoltIcon size={16} className="text-[#666]" />
                    </button>
                ) : undefined}
            />
            <MarkLabel
                open={isLabelModalOpen}
                home={categories}
                onClose={handleCloseLabelModal}
            />
        </>
    )
}
