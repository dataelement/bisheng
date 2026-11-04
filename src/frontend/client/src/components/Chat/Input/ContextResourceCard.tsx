import { Outlined } from "bisheng-icons";
import { cn } from "~/utils";

/** Compact context resource with a theme-aware surface and optional remove action. */
export const ContextResourceCard = ({
    icon,
    label,
    description,
    title,
    onRemove,
    onClick,
    thumbnail = false,
}: {
    icon: React.ReactNode;
    label: string;
    description?: string;
    title?: string;
    onRemove?: () => void;
    onClick?: () => void;
    thumbnail?: boolean;
}) => (
    <div
        className={cn(
            "dsh-composer-chip group",
            thumbnail && "dsh-composer-thumbnail",
            onClick && "cursor-pointer",
        )}
        data-composer-resource={onRemove ? "" : undefined}
        onClick={(event) => { if (onRemove) event.currentTarget.focus(); onClick?.(); }}
        role={onClick ? "button" : undefined}
        tabIndex={onRemove || onClick ? 0 : undefined}
        onKeyDown={onClick ? (event) => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onClick(); } } : undefined}
    >
        <span className="dsh-resource-icon">{icon}</span>
        <span className="dsh-resource-body" title={title ?? label}>
            <span className="dsh-resource-name">{label}</span>
            {description && <span className="dsh-resource-meta">{description}</span>}
        </span>
        {onRemove && (
            <button
                type="button"
                // Stop propagation so removing a card never triggers the card's
                // own click (e.g. opening the image preview).
                onClick={(e) => { e.stopPropagation(); onRemove(); }}
                // Hover-reveal on hover-capable pointers; always visible where the
                // pointer can't hover (touch) — gated by CSS hover capability, not
                // screen width, so a small-screen PC still gets the hover behaviour.
                className="dsh-resource-remove"
                data-composer-remove
                aria-label="Remove"
            >
                <Outlined.Close size={12} />
            </button>
        )}
    </div>
);
