import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { ChevronDown } from "lucide-react";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import type { RelationModelOption } from "./RelationSelect";

interface PermissionLevelMenuProps {
  /** Current level shown on the trigger. */
  label: string;
  options: RelationModelOption[];
  activeId?: string;
  /** When false the level items are hidden — the menu then only offers removal. */
  canChangeLevel: boolean;
  onChange: (modelId: string) => void;
  /** Renders the destructive "移除" item. Omit to hide it. */
  onRemove?: () => void;
  className?: string;
}

/**
 * Level dropdown shared by the member-management list and the create-page
 * authorization draft. Removal lives inside the menu — never as a separate
 * icon button next to it.
 */
export function PermissionLevelMenu({
  label,
  options,
  activeId,
  canChangeLevel,
  onChange,
  onRemove,
  className,
}: PermissionLevelMenuProps) {
  const localize = useLocalize();
  const showLevels = canChangeLevel && options.length > 0;

  if (!showLevels && !onRemove) {
    return (
      <span
        className={cn(
          "inline-flex h-8 w-[96px] shrink-0 items-center justify-end whitespace-nowrap px-2 text-[14px] leading-[22px] text-text-3",
          className,
        )}
      >
        {label}
      </span>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex h-8 w-[96px] items-center justify-end gap-1 rounded-md px-2 text-[14px] leading-[22px] text-text-3 transition-colors hover:bg-fill-1",
            className,
          )}
        >
          <span className="truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-text-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="z-[120] max-h-[240px] w-[100px] overflow-x-hidden overflow-y-auto overscroll-none rounded-lg border-0 bg-white p-1 shadow-[0px_6px_20px_1px_rgba(117,145,212,0.12)] scrollbar-hide [&::-webkit-scrollbar]:!w-0 [&::-webkit-scrollbar]:!h-0"
      >
        {showLevels && options.map((model) => {
          const active = model.id === activeId;
          return (
            <DropdownMenuItem
              key={model.id}
              className={cn(
                "rounded-md px-2 py-[5px] text-[14px] leading-[22px]",
                active
                  ? "bg-blue-500/[0.07] text-blue-500 data-[highlighted]:bg-blue-500/[0.07] data-[highlighted]:text-blue-500"
                  : "text-text-1 data-[highlighted]:bg-fill-1 data-[highlighted]:text-text-1",
              )}
              onSelect={() => onChange(model.id)}
            >
              {model.name}
            </DropdownMenuItem>
          );
        })}
        {showLevels && onRemove && (
          <DropdownMenuSeparator className="my-1 bg-fill-3" />
        )}
        {onRemove && (
          <DropdownMenuItem
            aria-label={localize("com_permission.remove")}
            className="rounded-md px-2 py-[5px] text-[14px] leading-[22px] text-[#F53F3F] data-[highlighted]:bg-[#FFF2F0] data-[highlighted]:text-[#F53F3F]"
            onSelect={() => onRemove()}
          >
            {localize("com_permission.remove")}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
