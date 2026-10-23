import { Outlined } from "bisheng-icons";
import { useLocalize } from "~/hooks";

/** Placeholder row shown while a menu's items are still being resolved (e.g. a
 *  lazy permission lookup), so the menu doesn't open half-empty and then grow.
 *  Inline-level loading per the Loading spec §3 (packages/ui/docs): 16px mono
 *  ring + text, 8px gap, same 32px row geometry as a `DropdownItem`. */
export function ActionMenuLoadingRow({ label }: { label?: string }) {
    const localize = useLocalize();
    return (
        <div
            role="status"
            className="flex h-8 items-center gap-2 px-2 text-sm leading-[22px] text-text-3"
        >
            <Outlined.Loading className="size-4 shrink-0 animate-spin motion-reduce:animate-pulse" aria-hidden />
            <span className="min-w-0 truncate text-sm leading-[22px]">{label ?? localize("com_list_loading")}</span>
        </div>
    );
}
