import * as React from "react";
import { Outlined } from "bisheng-icons";
import {
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuPortal,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from "~/components/ui/DropdownMenu";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

/**
 * Shared "action menu" look used by knowledge-space dropdowns
 * (sidebar more-menu, toolbar batch-operation, file-card "⋯", etc.):
 * white surface, 12px corner radius (阴影与圆角规范: 下拉面板 = xl),
 * no hard border, soft shadow.
 */
export const actionMenuSurfaceClassName =
    "rounded-xl border-0 bg-white shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]";

/** Default content frame: 160px wide, 8px padding, z-100 so it sits above
 *  any mobile drawer overlays. Width can be overridden via the `width` prop
 *  (or by passing `min-w-*` / `w-*` in className). */
export const actionMenuContentClassName = cn(
    "w-[160px] gap-0 p-2 z-[100]",
    actionMenuSurfaceClassName,
);

// 8px row radius per 基础-阴影与圆角规范 §控件 (32px row = large).
const itemBaseClassName =
    "flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-[5px] text-sm leading-[22px] outline-none transition-colors";

const itemRegularClassName = cn(
    itemBaseClassName,
    "text-text-1 data-[highlighted]:bg-fill-2 focus:bg-fill-2",
);

const itemDangerClassName = cn(
    itemBaseClassName,
    "text-[#F53F3F] data-[highlighted]:bg-[#F53F3F]/10 data-[highlighted]:text-[#F53F3F] focus:bg-[#F53F3F]/10 focus:text-[#F53F3F]",
);

const iconBaseClassName = "size-4 shrink-0";
const iconRegularClassName = cn(iconBaseClassName, "text-text-2");
const iconDangerClassName = cn(iconBaseClassName, "text-[#F53F3F]");

const labelClassName = "min-w-0 truncate text-sm leading-[22px]";

/** Section heading above a group of rows: 12px/20 regular, muted, flush with the
 *  container's 8px padding — it sits 8px left of the row labels (Figma 13198:78112). */
export const actionMenuSectionLabelClassName = "text-xs leading-5 text-text-3";

/** Item-row style tokens, exported so non-DropdownMenuItem rows (e.g. a submenu
 *  trigger or a custom header) can match the same height / radius / typography. */
export const actionMenuItemClassName = itemRegularClassName;
export const actionMenuItemDangerClassName = itemDangerClassName;
export const actionMenuItemIconClassName = iconRegularClassName;
export const actionMenuLabelClassName = labelClassName;

type DropdownMenuContentProps = React.ComponentPropsWithoutRef<
    typeof DropdownMenuContent
>;

interface ActionMenuContentProps extends DropdownMenuContentProps {
    /** Override the default 160px width. Pass any tailwind-compatible value
     *  via className (e.g. `min-w-[200px]`) for more complex sizing. */
    width?: number | string;
}

export const ActionMenuContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuContent>,
    ActionMenuContentProps
>(function ActionMenuContent(
    { className, align = "end", sideOffset = 8, width, style, ...props },
    ref,
) {
    const widthStyle =
        width != null
            ? { width: typeof width === "number" ? `${width}px` : width }
            : undefined;
    return (
        <DropdownMenuContent
            ref={ref}
            align={align}
            sideOffset={sideOffset}
            className={cn(actionMenuContentClassName, className)}
            style={widthStyle ? { ...widthStyle, ...style } : style}
            {...props}
        />
    );
});

type DropdownMenuItemProps = React.ComponentPropsWithoutRef<
    typeof DropdownMenuItem
>;

interface ActionMenuItemProps extends Omit<DropdownMenuItemProps, "children"> {
    /** Leading icon — rendered at 16px in #4E5969 (or #F53F3F when `danger`).
     *  Pass either a lucide / bisheng-icon element, or any ReactNode. */
    icon?: React.ReactNode;
    /** Label text. Use `children` instead when you need richer content. */
    label?: React.ReactNode;
    /** Render in the destructive (red) style. */
    danger?: boolean;
    children?: React.ReactNode;
}

/** Renders a single row of an action menu with the project's unified
 *  height / spacing / typography. */
export const ActionMenuItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuItem>,
    ActionMenuItemProps
>(function ActionMenuItem(
    { icon, label, danger, className, children, ...props },
    ref,
) {
    const resolvedIcon = renderIcon(icon, danger);
    const content = children ?? label;
    return (
        <DropdownMenuItem
            ref={ref}
            className={cn(
                danger ? itemDangerClassName : itemRegularClassName,
                className,
            )}
            {...props}
        >
            {resolvedIcon}
            {typeof content === "string" ? (
                <span className={labelClassName}>{content}</span>
            ) : (
                content
            )}
        </DropdownMenuItem>
    );
});

type DropdownMenuCheckboxItemProps = React.ComponentPropsWithoutRef<
    typeof DropdownMenuCheckboxItem
>;

/** Checkable row of an action menu: same 32px geometry as ActionMenuItem, with
 *  the check in the trailing slot so labels stay flush left (Figma 13198:78111). */
export const ActionMenuCheckboxItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuCheckboxItem>,
    DropdownMenuCheckboxItemProps
>(function ActionMenuCheckboxItem({ className, ...props }, ref) {
    return (
        <DropdownMenuCheckboxItem
            ref={ref}
            indicatorSide="right"
            className={cn(itemRegularClassName, className)}
            {...props}
        />
    );
});

/** Row of an action menu that opens a side panel on hover / arrow-right.
 *  Same geometry as ActionMenuItem; the trailing chevron comes from the primitive. */
export const ActionMenuSub = DropdownMenuSub;

type DropdownMenuSubTriggerProps = React.ComponentPropsWithoutRef<
    typeof DropdownMenuSubTrigger
>;

interface ActionMenuSubTriggerProps
    extends Omit<DropdownMenuSubTriggerProps, "children"> {
    icon?: React.ReactNode;
    label?: React.ReactNode;
    children?: React.ReactNode;
    /** Drops the trailing chevron the DropdownMenuSubTrigger primitive always
     *  appends. It is the primitive's last child, hence the :last-child reach —
     *  the leading `icon` is the first child and is left alone. */
    hideChevron?: boolean;
}

export const ActionMenuSubTrigger = React.forwardRef<
    React.ElementRef<typeof DropdownMenuSubTrigger>,
    ActionMenuSubTriggerProps
>(function ActionMenuSubTrigger(
    { icon, label, className, children, hideChevron, ...props },
    ref,
) {
    const content = children ?? label;
    return (
        <DropdownMenuSubTrigger
            ref={ref}
            className={cn(
                itemRegularClassName,
                "font-normal data-[state=open]:bg-fill-2",
                hideChevron && "[&>svg:last-child]:hidden",
                className,
            )}
            {...props}
        >
            {renderIcon(icon)}
            {typeof content === "string" ? (
                <span className={cn(labelClassName, "flex-1")}>{content}</span>
            ) : (
                content
            )}
        </DropdownMenuSubTrigger>
    );
});

type DropdownMenuSubContentProps = React.ComponentPropsWithoutRef<
    typeof DropdownMenuSubContent
>;

/** Side panel of an ActionMenuSub. Portalled so it escapes the parent menu's
 *  `overflow-hidden`, scrollable once the list outgrows the panel, and centered
 *  on its trigger row rather than aligned to its top edge. */
export const ActionMenuSubContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuSubContent>,
    DropdownMenuSubContentProps & { width?: number | string }
>(function ActionMenuSubContent(
    { className, align = "center", sideOffset = 4, width, style, ...props },
    ref,
) {
    const widthStyle =
        width != null
            ? { width: typeof width === "number" ? `${width}px` : width }
            : undefined;
    return (
        <DropdownMenuPortal>
            <DropdownMenuSubContent
                ref={ref}
                align={align}
                sideOffset={sideOffset}
                collisionPadding={8}
                className={cn(
                    // Same default width as ActionMenuContent, so a submenu and the
                    // menu it hangs off line up unless a call site overrides both.
                    "max-h-[280px] w-[160px] overflow-y-auto p-2 z-[100]",
                    actionMenuSurfaceClassName,
                    className,
                )}
                style={widthStyle ? { ...widthStyle, ...style } : style}
                {...props}
            />
        </DropdownMenuPortal>
    );
});

function renderIcon(icon: React.ReactNode, danger?: boolean): React.ReactNode {
    if (icon == null || icon === false) return null;
    const iconClass = danger ? iconDangerClassName : iconRegularClassName;
    if (React.isValidElement(icon)) {
        const existing = (icon.props as { className?: string }).className;
        return React.cloneElement(icon as React.ReactElement<{ className?: string }>, {
            className: cn(iconClass, existing),
        });
    }
    return icon;
}

interface ActionMenuDividerProps {
    /** 0.5px rule instead of the 1px one: in a short menu (two or three rows) the
     *  full-weight divider reads heavier than the rows it separates. */
    hairline?: boolean;
}

/** Thin horizontal separator spanning the container's inner width (Figma 13198:78128). */
export function ActionMenuDivider({ hairline = false }: ActionMenuDividerProps = {}) {
    return (
        <div
            role="separator"
            className={cn(
                "my-1.5",
                hairline ? "border-t-[0.5px] border-border-base" : "h-px bg-border-base",
            )}
        />
    );
}

/** Placeholder row shown while a menu's items are still being resolved (e.g. a
 *  lazy permission lookup), so the menu doesn't open half-empty and then grow.
 *  Inline-level loading per the Loading spec §3 (packages/ui/docs): 16px mono
 *  ring + text, 8px gap, same 32px row geometry as ActionMenuItem. */
export function ActionMenuLoadingRow({ label }: { label?: string }) {
    const localize = useLocalize();
    return (
        <div
            role="status"
            className="flex h-8 items-center gap-2 px-2 text-sm leading-[22px] text-text-3"
        >
            <Outlined.Loading className="size-4 shrink-0 animate-spin motion-reduce:animate-pulse" aria-hidden />
            <span className={labelClassName}>{label ?? localize("com_list_loading")}</span>
        </div>
    );
}
