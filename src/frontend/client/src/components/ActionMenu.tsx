import * as React from "react";
import {
    DropdownMenuContent,
    DropdownMenuItem,
} from "~/components/ui/DropdownMenu";
import { cn } from "~/utils";

/**
 * Shared "action menu" look used by knowledge-space dropdowns
 * (sidebar more-menu, toolbar batch-operation, file-card "⋯", etc.):
 * white surface, 8px corner radius, no hard border, soft shadow.
 */
export const actionMenuSurfaceClassName =
    "rounded-[8px] border-0 bg-white shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]";

/** Default content frame: 160px wide, 8px padding, z-100 so it sits above
 *  any mobile drawer overlays. Width can be overridden via the `width` prop
 *  (or by passing `min-w-*` / `w-*` in className). */
export const actionMenuContentClassName = cn(
    "w-[160px] gap-0 p-2 z-[100]",
    actionMenuSurfaceClassName,
);

const itemBaseClassName =
    "flex w-full cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] text-sm leading-[22px] outline-none transition-colors";

const itemRegularClassName = cn(
    itemBaseClassName,
    "text-[#212121] data-[highlighted]:bg-[#f2f3f5] focus:bg-[#f2f3f5]",
);

const itemDangerClassName = cn(
    itemBaseClassName,
    "text-[#F53F3F] data-[highlighted]:bg-[#F53F3F]/10 data-[highlighted]:text-[#F53F3F] focus:bg-[#F53F3F]/10 focus:text-[#F53F3F]",
);

const iconBaseClassName = "size-4 shrink-0";
const iconRegularClassName = cn(iconBaseClassName, "text-[#4E5969]");
const iconDangerClassName = cn(iconBaseClassName, "text-[#F53F3F]");

const labelClassName = "min-w-0 truncate text-sm leading-[22px]";

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

/** Thin horizontal separator that aligns with the 8px container padding. */
export function ActionMenuDivider() {
    return <div className="mx-1 my-1 h-px bg-[#f2f3f5]" role="separator" />;
}
