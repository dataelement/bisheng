import * as React from "react";
import { DropdownMenuContent } from "~/components/ui/DropdownMenu";
import { cn } from "~/utils";

type SidebarListMoreMenuContentProps = React.ComponentPropsWithoutRef<typeof DropdownMenuContent>;

/**
 * 知识空间域内下拉浮层统一外观：白底、8px 圆角、无粗描边、柔和投影（侧栏「⋯」、工具栏筛选等共用）
 */
export const knowledgeSpaceDropdownSurfaceClassName =
    "rounded-[8px] border-0 bg-white shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]";

/** 知识空间 / 订阅频道侧栏列表项「⋯」菜单。
 * 紧凑风格与订阅页面顶部「⋯」(ChannelActionsMenu) 对齐：160px 宽、内边距 8px、
 * 圆角 8px、柔和投影；每项 4px 圆角、6px 横向内边距、紧凑行高。 */
export const sidebarListMoreMenuContentClassName = cn(
    "w-[160px] gap-0 p-2",
    /** 须高于移动端频道抽屉 z-[70]，否则浮层在蒙层下无法点击「成员管理」等项 */
    "z-[100]",
    knowledgeSpaceDropdownSurfaceClassName
);

export const sidebarListMoreMenuItemClassName =
    "flex w-full cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] text-sm leading-[22px] text-[#212121] data-[highlighted]:bg-[#f2f3f5] focus:bg-[#f2f3f5]";

export const sidebarListMoreMenuIconClassName = "size-4 shrink-0 text-[#4E5969]";

export const sidebarListMoreMenuLabelClassName = "text-sm leading-[22px] text-[#212121]";

export const sidebarListMoreMenuDangerItemClassName =
    "flex w-full cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] text-sm leading-[22px] text-[#F53F3F] data-[highlighted]:bg-[#F53F3F]/10 data-[highlighted]:text-[#F53F3F] focus:bg-[#F53F3F]/10 focus:text-[#F53F3F]";

export const sidebarListMoreMenuDangerIconClassName = "size-4 shrink-0 text-[#F53F3F]";

export const sidebarListMoreMenuDangerLabelClassName = "text-sm leading-[22px]";

export function SidebarListMoreMenuDivider() {
    return <div className="mx-1 my-1 h-px bg-[#f2f3f5]" role="separator" />;
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
