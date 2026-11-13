import { RadioCard, RadioGroup, Switch } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

// Match the client settings compositions without importing client state or routing.
interface SpaceSettingsSectionHeaderProps {
  kind: "basic" | "advanced" | "permission";
  title: string;
}
export function SpaceSettingsSectionHeader({
  kind,
  title,
}: SpaceSettingsSectionHeaderProps) {
  const Icon = {
    basic: Outlined.Layer,
    advanced: Outlined.Setting,
    permission: Outlined.PeopleSafe,
  }[kind];
  return (
    <div className="flex h-8 items-center gap-2 rounded-md bg-fill-1 px-3 text-body-sm font-medium text-text-1">
      <Icon className="size-4 text-blue-500" />
      <h3>{title}</h3>
    </div>
  );
}

interface SpaceSettingsSwitchRowProps {
  label: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  required?: boolean;
}
export function SpaceSettingsSwitchRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
  required,
}: SpaceSettingsSwitchRowProps) {
  return (
    <div className="flex min-h-[22px] items-center justify-between gap-4">
      <div className="flex min-w-0 items-center gap-2 text-body">
        <span className="shrink-0 font-medium text-text-1">
          {required && <span className="mr-1 text-danger">*</span>}
          {label}
        </span>
        {description && (
          <span className="truncate text-text-3" title={description}>
            {description}
          </span>
        )}
      </div>
      <Switch
        size="small"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
      />
    </div>
  );
}

interface SpaceSettingsAccessSelectorProps {
  value: "private" | "shared";
  onValueChange: (value: "private" | "shared") => void;
  label: string;
  privateLabel: string;
  privateDescription: string;
  sharedLabel: string;
  sharedDescription: string;
  disabled: boolean;
  privateDisabled: boolean;
}
export function SpaceSettingsAccessSelector({
  value,
  onValueChange,
  label,
  privateLabel,
  privateDescription,
  sharedLabel,
  sharedDescription,
  disabled,
  privateDisabled,
}: SpaceSettingsAccessSelectorProps) {
  return (
    <RadioGroup
      aria-label={label}
      value={value}
      disabled={disabled}
      onValueChange={(next) => {
        if (next === "private" || next === "shared") onValueChange(next);
      }}
      className="grid grid-cols-2 gap-2 max-[560px]:grid-cols-1"
    >
      <RadioCard
        value="private"
        aria-label={privateLabel}
        label={privateLabel}
        description={privateDescription}
        disabled={privateDisabled}
      />
      <RadioCard
        value="shared"
        aria-label={sharedLabel}
        label={sharedLabel}
        description={sharedDescription}
      />
    </RadioGroup>
  );
}
