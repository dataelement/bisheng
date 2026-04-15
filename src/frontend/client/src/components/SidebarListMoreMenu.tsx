import * as React from "react";
import { DropdownMenuContent } from "~/components/ui/DropdownMenu";
import { cn } from "~/utils";

type SidebarListMoreMenuContentProps = React.ComponentPropsWithoutRef<typeof DropdownMenuContent>;

/**
 * 知识空间域内下拉浮层统一外观：白底、8px 圆角、无粗描边、柔和投影（侧栏「⋯」、工具栏筛选等共用）
 */
export const knowledgeSpaceDropdownSurfaceClassName =
    "rounded-[8px] border-0 bg-white shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]";

/** 知识空间 / 订阅频道侧栏列表项「⋯」菜单：在内边距与宽度上与 {@link knowledgeSpaceDropdownSurfaceClassName} 叠加 */
export const sidebarListMoreMenuContentClassName = cn(
    "w-40 gap-0 px-4 py-3",
    /** 须高于移动端频道抽屉 z-[70]，否则浮层在蒙层下无法点击「成员管理」等项 */
    "z-[100]",
    knowledgeSpaceDropdownSurfaceClassName
);

export const sidebarListMoreMenuItemClassName =
    "py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]";

export const sidebarListMoreMenuIconClassName = "size-4 mr-2 shrink-0 text-[#4e5969]";

export const sidebarListMoreMenuLabelClassName = "text-[14px] text-[#1d2129]";

export const sidebarListMoreMenuDangerItemClassName =
    "text-[#f53f3f] py-2 px-0 cursor-pointer focus:bg-[#f2f3f5] focus:text-[#f53f3f]";

export const sidebarListMoreMenuDangerIconClassName = "size-4 mr-2 shrink-0 text-[#f53f3f]";

export const sidebarListMoreMenuDangerLabelClassName = "text-[14px] font-medium";

export function SidebarListMoreMenuDivider() {
    return <div className="mx-2 my-1 h-px bg-[#f2f3f5]" role="separator" />;
}

export const SidebarListMoreMenuContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuContent>,
    SidebarListMoreMenuContentProps
>(function SidebarListMoreMenuContent({ className, align = "end", sideOffset = 8, ...props }, ref) {
    return (
        <DropdownMenuContent
            ref={ref}
            align={align}
            sideOffset={sideOffset}
            className={cn(sidebarListMoreMenuContentClassName, className)}
            {...props}
        />
    );
});
