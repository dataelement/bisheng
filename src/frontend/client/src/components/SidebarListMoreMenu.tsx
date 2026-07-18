import * as React from "react";
import {
    ActionMenuContent,
    ActionMenuDivider,
    actionMenuContentClassName,
    actionMenuSurfaceClassName,
} from "~/components/ActionMenu";

/**
 * Legacy entry-point for the unified knowledge-space action-menu look.
 * New code should import from `~/components/ActionMenu` directly; this
 * module preserves the className constants that existing call sites pass
 * to `<DropdownMenuItem className={...}>` and friends.
 */

/** Shared surface (white bg, 8px radius, soft shadow). */
export const knowledgeSpaceDropdownSurfaceClassName = actionMenuSurfaceClassName;

/** Default content frame: 160px wide, p-2, z-[100], + surface. */
export const sidebarListMoreMenuContentClassName = actionMenuContentClassName;

export const sidebarListMoreMenuItemClassName =
    "flex w-full cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] text-sm leading-[22px] text-[#212121] data-[highlighted]:bg-[#f2f3f5] focus:bg-[#f2f3f5]";

export const sidebarListMoreMenuIconClassName = "size-4 shrink-0 text-[#4E5969]";

export const sidebarListMoreMenuLabelClassName = "text-sm leading-[22px] text-[#212121]";

export const sidebarListMoreMenuDangerItemClassName =
    "flex w-full cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] text-sm leading-[22px] text-[#F53F3F] data-[highlighted]:bg-[#F53F3F]/10 data-[highlighted]:text-[#F53F3F] focus:bg-[#F53F3F]/10 focus:text-[#F53F3F]";

export const sidebarListMoreMenuDangerIconClassName = "size-4 shrink-0 text-[#F53F3F]";

export const sidebarListMoreMenuDangerLabelClassName = "text-sm leading-[22px]";

export const SidebarListMoreMenuDivider = ActionMenuDivider;

export const SidebarListMoreMenuContent: typeof ActionMenuContent = ActionMenuContent;
