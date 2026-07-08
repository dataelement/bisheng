import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import type {
    PortalFileCategoryGroupOption,
    PortalFileSubcategoryOption,
} from "../types";
import { normalizeEncodingCode } from "../uploadMetadata";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalFileCategoryDropdownProps {
    groups: PortalFileCategoryGroupOption[];
    value?: string | null;
    fallbackParentCode?: string | null;
    placeholder?: string;
    disabled?: boolean;
    clearable?: boolean;
    variant?: "default" | "fileTable";
    ariaLabel: string;
    onChange: (option: PortalFileSubcategoryOption | null) => void | Promise<void>;
    onClick?: (event: MouseEvent<HTMLDivElement>) => void;
}

export function findPortalFileSubcategory(
    groups: PortalFileCategoryGroupOption[],
    code?: string | null,
): PortalFileSubcategoryOption | null {
    const normalized = normalizeEncodingCode(code || "");
    if (!normalized) return null;
    for (const group of groups) {
        const option = group.children.find((child) => child.code === normalized);
        if (option) return option;
    }
    return null;
}

export function getPortalFileCategoryDisplayText(
    groups: PortalFileCategoryGroupOption[],
    code?: string | null,
    fallbackParentCode?: string | null,
    placeholder = "--",
) {
    const selected = findPortalFileSubcategory(groups, code);
    if (selected) return `${selected.parentLabel} / ${selected.label}`;
    const normalizedCode = normalizeEncodingCode(code || "");
    const normalizedParent = normalizeEncodingCode(fallbackParentCode || "");
    const parent = groups.find((group) => group.code === normalizedParent);
    if (parent) return `${parent.label} / ${placeholder}`;
    if (normalizedCode) return placeholder;
    return placeholder;
}

export function PortalFileCategoryDropdown({
    groups,
    value,
    fallbackParentCode,
    placeholder = "--",
    disabled = false,
    clearable = false,
    variant = "default",
    ariaLabel,
    onChange,
    onClick,
}: PortalFileCategoryDropdownProps) {
    const rootRef = useRef<HTMLDivElement | null>(null);
    const triggerRef = useRef<HTMLButtonElement | null>(null);
    const menuRef = useRef<HTMLDivElement | null>(null);
    const [open, setOpen] = useState(false);
    const [floatingMenuStyle, setFloatingMenuStyle] = useState<CSSProperties>();
    const selected = useMemo(() => findPortalFileSubcategory(groups, value), [groups, value]);
    const normalizedFallbackParentCode = normalizeEncodingCode(fallbackParentCode || "");
    const activeCategoryCode = selected?.parentCode ?? (normalizedFallbackParentCode || null);
    const [expandedCategoryCode, setExpandedCategoryCode] = useState<string | null>(activeCategoryCode);
    const expandedCode = expandedCategoryCode ?? activeCategoryCode;
    const displayText = getPortalFileCategoryDisplayText(groups, value, fallbackParentCode, placeholder);
    const hasValue = Boolean(normalizeEncodingCode(value || ""));
    const useFloatingMenu = variant === "fileTable";

    const updateFloatingMenuStyle = useCallback(() => {
        if (!useFloatingMenu || typeof window === "undefined") return;
        const trigger = triggerRef.current;
        if (!trigger) return;
        const rect = trigger.getBoundingClientRect();
        const viewportMargin = 12;
        const gap = 4;
        const minWidth = 280;
        const maxWidth = Math.max(minWidth, window.innerWidth - viewportMargin * 2);
        const width = Math.min(Math.max(rect.width, minWidth), maxWidth);
        const left = Math.min(
            Math.max(rect.left, viewportMargin),
            Math.max(viewportMargin, window.innerWidth - viewportMargin - width),
        );
        const availableBelow = window.innerHeight - rect.bottom - viewportMargin - gap;
        const availableAbove = rect.top - viewportMargin - gap;
        const openAbove = availableBelow < 180 && availableAbove > availableBelow;
        const availableHeight = Math.max(160, openAbove ? availableAbove : availableBelow);
        const maxHeight = Math.min(320, availableHeight);
        const top = openAbove
            ? Math.max(viewportMargin, rect.top - gap - maxHeight)
            : Math.min(rect.bottom + gap, window.innerHeight - viewportMargin - maxHeight);

        setFloatingMenuStyle({
            position: "fixed",
            top,
            left,
            width,
            maxHeight,
        });
    }, [useFloatingMenu]);

    useEffect(() => {
        if (!open) return undefined;
        const handlePointerDown = (event: PointerEvent) => {
            const root = rootRef.current;
            const menu = menuRef.current;
            if (!root || root.contains(event.target as Node) || menu?.contains(event.target as Node)) return;
            setOpen(false);
        };
        document.addEventListener("pointerdown", handlePointerDown, true);
        return () => document.removeEventListener("pointerdown", handlePointerDown, true);
    }, [open]);

    useEffect(() => {
        if (!open || !useFloatingMenu) return undefined;
        updateFloatingMenuStyle();
        window.addEventListener("resize", updateFloatingMenuStyle);
        window.addEventListener("scroll", updateFloatingMenuStyle, true);
        return () => {
            window.removeEventListener("resize", updateFloatingMenuStyle);
            window.removeEventListener("scroll", updateFloatingMenuStyle, true);
        };
    }, [open, updateFloatingMenuStyle, useFloatingMenu]);

    const rootClassName = [
        s.uploadCategoryDropdown,
        variant === "fileTable" ? s.fileTableCategoryDropdown : "",
        open && variant === "fileTable" ? s.fileTableCategoryDropdownOpen : "",
    ].filter(Boolean).join(" ");
    const triggerClassName = [
        s.uploadCategoryTrigger,
        hasValue && clearable ? s.uploadCategoryTriggerClearable : "",
        variant === "fileTable" ? s.fileTableCategoryTrigger : "",
    ].filter(Boolean).join(" ");
    const menuClassName = [
        s.uploadCategoryMenu,
        variant === "fileTable" ? s.fileTableCategoryMenu : "",
    ].filter(Boolean).join(" ");

    const menu = open ? (
        <div
            ref={menuRef}
            className={menuClassName}
            role="tree"
            aria-label={ariaLabel}
            style={useFloatingMenu ? floatingMenuStyle : undefined}
        >
            {groups.map((group) => {
                const expanded = expandedCode === group.code;
                return (
                    <div key={group.code} className={s.uploadCategoryGroup}>
                        <button
                            type="button"
                            className={s.uploadCategoryGroupButton}
                            aria-expanded={expanded}
                            disabled={disabled}
                            onClick={() => setExpandedCategoryCode(expanded ? null : group.code)}
                        >
                            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                            <span>{group.label}</span>
                        </button>
                        {expanded ? (
                            <div className={s.uploadCategoryChildren} role="group">
                                {group.children.map((child) => (
                                    <button
                                        key={child.code}
                                        type="button"
                                        className={`${s.uploadCategoryChildButton} ${selected?.code === child.code ? s.uploadCategoryChildButtonActive : ""}`}
                                        disabled={disabled}
                                        onClick={() => {
                                            void onChange(child);
                                            setExpandedCategoryCode(child.parentCode);
                                            setOpen(false);
                                        }}
                                    >
                                        <span>{child.parentLabel} / {child.label}</span>
                                    </button>
                                ))}
                            </div>
                        ) : null}
                    </div>
                );
            })}
        </div>
    ) : null;

    return (
        <div ref={rootRef} className={rootClassName} onClick={onClick}>
            <button
                ref={triggerRef}
                type="button"
                className={triggerClassName}
                aria-label={`${ariaLabel} 当前选择：${displayText}`}
                aria-haspopup="tree"
                aria-expanded={open}
                disabled={disabled}
                onClick={() => {
                    if (!open) updateFloatingMenuStyle();
                    setOpen((current) => !current);
                }}
            >
                <span>{displayText}</span>
                <ChevronDown size={16} />
            </button>
            {hasValue && clearable ? (
                <button
                    type="button"
                    className={s.uploadCategoryClearButton}
                    aria-label={`清空${ariaLabel}选择`}
                    disabled={disabled}
                    onClick={(event) => {
                        event.stopPropagation();
                        void onChange(null);
                        setExpandedCategoryCode(null);
                        setOpen(false);
                    }}
                >
                    <X size={14} />
                </button>
            ) : null}
            {menu && useFloatingMenu && typeof document !== "undefined" ? createPortal(menu, document.body) : menu}
        </div>
    );
}
