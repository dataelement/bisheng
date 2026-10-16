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
}: {
    icon: React.ReactNode;
    label: string;
    description?: string;
    title?: string;
    onRemove?: () => void;
    onClick?: () => void;
}) => (
    <div
        className={cn(
            "dsh-composer-chip group relative flex h-14 shrink-0 items-center gap-3 rounded-xl bg-fill-1 px-3 text-body-sm text-text-1",
            onClick && "cursor-pointer",
        )}
        style={{ width: 224 }}
        onClick={onClick}
        role={onClick ? "button" : undefined}
        tabIndex={onClick ? 0 : undefined}
        onKeyDown={onClick ? (event) => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onClick(); } } : undefined}
    >
        <span className="flex size-7 shrink-0 items-center justify-center overflow-hidden rounded text-text-2">{icon}</span>
        <span className="min-w-0 flex-1 truncate text-left" title={title ?? label}>
            <span className="block truncate">{label}</span>
            {description && <span className="block truncate text-caption text-text-3">{description}</span>}
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
                className="dsh-resource-remove absolute right-1 top-1 flex size-5 items-center justify-center rounded-full bg-fill-2 text-text-3 opacity-0 hover:text-text-1 group-hover:opacity-100 focus-visible:opacity-100 coarse-pointer:opacity-100"
                aria-label="Remove"
            >
                <Outlined.Close size={12} />
            </button>
        )}
    </div>
);
