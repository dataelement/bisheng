import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
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
    if (normalizedCode) return normalizedCode;
    const normalizedParent = normalizeEncodingCode(fallbackParentCode || "");
    const parent = groups.find((group) => group.code === normalizedParent);
    if (parent) return `${parent.label} / ${placeholder}`;
    return placeholder;
}

export function PortalFileCategoryDropdown({
    groups,
    value,
    fallbackParentCode,
    placeholder = "--",
    disabled = false,
    clearable = false,
    ariaLabel,
    onChange,
    onClick,
}: PortalFileCategoryDropdownProps) {
    const rootRef = useRef<HTMLDivElement | null>(null);
    const [open, setOpen] = useState(false);
    const selected = useMemo(() => findPortalFileSubcategory(groups, value), [groups, value]);
    const normalizedFallbackParentCode = normalizeEncodingCode(fallbackParentCode || "");
    const activeCategoryCode = selected?.parentCode ?? (normalizedFallbackParentCode || null);
    const [expandedCategoryCode, setExpandedCategoryCode] = useState<string | null>(activeCategoryCode);
    const expandedCode = expandedCategoryCode ?? activeCategoryCode;
    const displayText = getPortalFileCategoryDisplayText(groups, value, fallbackParentCode, placeholder);
    const hasValue = Boolean(normalizeEncodingCode(value || ""));

    useEffect(() => {
        if (!open) return undefined;
        const handlePointerDown = (event: PointerEvent) => {
            const root = rootRef.current;
            if (!root || root.contains(event.target as Node)) return;
            setOpen(false);
        };
        document.addEventListener("pointerdown", handlePointerDown, true);
        return () => document.removeEventListener("pointerdown", handlePointerDown, true);
    }, [open]);

    return (
        <div ref={rootRef} className={s.uploadCategoryDropdown} onClick={onClick}>
            <button
                type="button"
                className={`${s.uploadCategoryTrigger} ${hasValue && clearable ? s.uploadCategoryTriggerClearable : ""}`}
                aria-label={`${ariaLabel} 当前选择：${displayText}`}
                aria-haspopup="tree"
                aria-expanded={open}
                disabled={disabled}
                onClick={() => setOpen((current) => !current)}
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
            {open ? (
                <div className={s.uploadCategoryMenu} role="tree" aria-label={ariaLabel}>
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
                                    <span>{group.code} / {group.label}</span>
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
                                                {child.code} / {child.label}
                                            </button>
                                        ))}
                                    </div>
                                ) : null}
                            </div>
                        );
                    })}
                </div>
            ) : null}
        </div>
    );
}
