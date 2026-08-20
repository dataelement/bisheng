// @ts-strict-ignore
"use client"

import { BoltIcon } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
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

const UNCATEGORIZED = 'uncategorized'

export function AgentNavigation({ onCategoryChange, onRefresh }: AgentNavigationProps) {
    const { user } = useAuthContext();
    const localize = useLocalize();

    const [isLabelModalOpen, setIsLabelModalOpen] = useState(false)
    // Nothing is selected until the tags come back — the first one is the
    // default, and which one that is isn't known before then.
    const [activeCategory, setActiveCategory] = useState<number | string | null>(null)
    const [showRightShadow, setShowRightShadow] = useState(false)

    const [categories, setCategories] = useState<Category[]>([])
    const tabsScrollRef = useRef<HTMLDivElement>(null)
    const activeCategoryRef = useRef<number | string | null>(null)

    const selectCategory = useCallback((id: number | string) => {
        activeCategoryRef.current = id
        setActiveCategory(id)
        onCategoryChange(id)
    }, [onCategoryChange])

    const fetchCategoryTags = useCallback(async () => {
        const tags = await getHomeLabelApi()
        const next: Category[] = tags.data.map(tag => ({
            label: tag.name,
            value: tag.id,
            selected: true
        }))
        setCategories(next)

        // Keep the current tab if it survived (the tag list is editable from
        // here), otherwise fall back to the first tag — or to Uncategorized,
        // which is the only tab left when no tags are configured at all.
        const current = activeCategoryRef.current
        const stillListed = current === UNCATEGORIZED || next.some((category) => category.value === current)
        if (current === null || !stillListed) {
            selectCategory(next[0]?.value ?? UNCATEGORIZED)
        }
    }, [selectCategory])

    // Initial data load
    useEffect(() => {
        fetchCategoryTags()
    }, [fetchCategoryTags])

    const updateShadow = useCallback(() => {
        const el = tabsScrollRef.current
        if (!el) return
        const hasOverflow = el.scrollWidth > el.clientWidth + 1
        const atRightEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1
        setShowRightShadow(hasOverflow && !atRightEnd)
    }, [])

    useEffect(() => {
        updateShadow()
    }, [categories, user?.role, updateShadow])

    useEffect(() => {
        window.addEventListener('resize', updateShadow)
        return () => window.removeEventListener('resize', updateShadow)
    }, [updateShadow])

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
            <button
                key={id}
                type="button"
                onClick={() => selectCategory(id)}
                className={cn(
                    "flex shrink-0 items-center whitespace-nowrap border-b-2 px-2 py-[5px] font-['PingFang_SC'] text-[14px] leading-[22px] transition-colors",
                    isActive
                        ? "border-blue-500 text-blue-500"
                        : "border-transparent text-text-1 fine-pointer:hover:text-blue-500",
                )}
            >
                {label}
            </button>
        )
    };

    return (
        <nav className="flex w-full min-w-0 items-center gap-2">
            <div className="relative min-w-0 flex-1">
                <div
                    ref={tabsScrollRef}
                    onScroll={updateShadow}
                    className="flex w-full min-w-0 items-center gap-[8px] overflow-x-auto whitespace-nowrap scrollbar-hide"
                >
                    {categories.map((category) => renderTab(category.value, category.label))}
                    {renderTab(UNCATEGORIZED, localize('com_app_uncategorized'))}
                </div>

                {showRightShadow && (
                    <div className="pointer-events-none absolute right-0 top-0 h-full w-8 bg-gradient-to-l from-white to-transparent" />
                )}
            </div>

            {/* edit label  */}
            {user?.role === 'admin' && (
                <button
                    onClick={() => setIsLabelModalOpen(true)}
                    className="flex items-center justify-cente mr-2 p-[6px] relative rounded-md shrink-0 hover:bg-gray-100 transition-colors"
                >
                    <BoltIcon size={16} className="text-[#666]" />
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
