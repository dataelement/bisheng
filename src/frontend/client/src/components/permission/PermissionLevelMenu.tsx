import { Dropdown, DropdownItem, DropdownSeparator } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
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
    <Dropdown
      align="end"
      menu={
        <>
          {showLevels && options.map((model) => (
            <DropdownItem
              key={model.id}
              checked={model.id === activeId}
              onSelect={() => onChange(model.id)}
            >
              {model.name}
            </DropdownItem>
          ))}
          {showLevels && onRemove && <DropdownSeparator />}
          {onRemove && (
            <DropdownItem danger onSelect={() => onRemove()}>
              {localize("com_permission.remove")}
            </DropdownItem>
          )}
        </>
      }
    >
      <button
        type="button"
        className={cn(
          "inline-flex h-8 w-[96px] items-center justify-end gap-1 rounded-md px-2 text-[14px] leading-[22px] text-text-3 transition-colors hover:bg-fill-1",
          className,
        )}
      >
        <span className="truncate">{label}</span>
        <Outlined.Down className="size-3.5 shrink-0 text-text-3" />
      </button>
    </Dropdown>
  );
}
