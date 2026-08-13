import { Button } from "@bisheng/ui";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { Outlined } from "bisheng-icons";
import type { ComponentType, ReactNode } from "react";
import { Switch } from "~/components/ui/Switch";
import { TruncatedTooltip } from "./TruncatedTooltip";

export type SettingsSectionKind = "basic" | "advanced" | "permission";

interface SettingsSectionHeaderProps {
  kind: SettingsSectionKind;
  title: string;
}

const SECTION_ICONS: Record<
  SettingsSectionKind,
  ComponentType<{ className?: string }>
> = {
  basic: Outlined.Layer,
  advanced: Outlined.Setting,
  permission: Outlined.PeopleSafe,
};

export function SettingsSectionHeader({
  kind,
  title,
}: SettingsSectionHeaderProps) {
  const Icon = SECTION_ICONS[kind];
  return (
    <div className="flex h-8 items-center gap-2 rounded-md bg-fill-1 px-3 text-body-sm font-medium text-text-1">
      <Icon className="size-4 text-blue-500" />
      <span>{title}</span>
    </div>
  );
}

interface AccessModeSelectorProps {
  value: "private" | "shared";
  onValueChange: (value: "private" | "shared") => void;
  privateLabel: string;
  privateDescription: string;
  sharedLabel: string;
  sharedDescription: string;
  disabled?: boolean;
}

export function AccessModeSelector({
  value,
  onValueChange,
  privateLabel,
  privateDescription,
  sharedLabel,
  sharedDescription,
  disabled,
}: AccessModeSelectorProps) {
  const options = [
    {
      value: "private" as const,
      label: privateLabel,
      description: privateDescription,
    },
    {
      value: "shared" as const,
      label: sharedLabel,
      description: sharedDescription,
    },
  ];

  return (
    <RadioGroup.Root
      value={value}
      disabled={disabled}
      onValueChange={(next) => onValueChange(next as "private" | "shared")}
      className="grid grid-cols-2 gap-2 max-[560px]:grid-cols-1"
    >
      {options.map((option) => (
        <label
          key={option.value}
          className="flex min-h-12 cursor-pointer items-center gap-2 rounded-xl border border-border-base px-3 text-body text-text-1 transition-colors hover:bg-fill-1 has-[[data-state=checked]]:bg-blue-500/[0.07] has-[[data-disabled]]:cursor-not-allowed has-[[data-disabled]]:opacity-60 has-[[data-disabled]]:hover:bg-transparent"
        >
          <RadioGroup.Item
            value={option.value}
            className="flex size-4 shrink-0 items-center justify-center rounded-full border-2 border-border-deep data-[state=checked]:border-blue-500 data-[state=checked]:bg-blue-500"
          >
            <RadioGroup.Indicator className="size-1 rounded-full bg-fill-1" />
          </RadioGroup.Item>
          <span className="shrink-0 whitespace-nowrap font-medium">{option.label}</span>
          <TruncatedTooltip
            content={option.description}
            className="min-w-0 truncate text-text-3"
          >
            {option.description}
          </TruncatedTooltip>
        </label>
      ))}
    </RadioGroup.Root>
  );
}

interface SettingsSwitchRowProps {
  label: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  required?: boolean;
  children?: ReactNode;
}

export function SettingsSwitchRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
  required,
  children,
}: SettingsSwitchRowProps) {
  return (
    <div className="flex min-h-[22px] items-center justify-between gap-4">
      <div className="flex min-w-0 items-center gap-2 text-body">
        <span className="shrink-0 font-medium text-text-1">
          {required && <span className="mr-1 text-danger">*</span>}
          {label}
        </span>
        {description && (
          <span className="truncate text-text-3">{description}</span>
        )}
        {children}
      </div>
      <Switch
        variant="tool"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
      />
    </div>
  );
}

interface SettingsFooterProps {
  cancelLabel: string;
  submitLabel: string;
  onCancel: () => void;
  onSubmit: () => void;
  submitting?: boolean;
  disabled?: boolean;
  centered?: boolean;
}

export function SettingsFooter({
  cancelLabel,
  submitLabel,
  onCancel,
  onSubmit,
  submitting,
  disabled,
  centered,
}: SettingsFooterProps) {
  return (
    <footer
      className={`flex h-14 shrink-0 items-center gap-3 border-t border-border-base bg-transparent ${
        centered ? "justify-center" : "justify-end"
      }`}
    >
      <Button
        color="default"
        variant="outlined"
        size="medium"
        onClick={onCancel}
      >
        {cancelLabel}
      </Button>
      <Button
        color="primary"
        variant="solid"
        size="medium"
        loading={submitting}
        disabled={disabled}
        onClick={onSubmit}
      >
        {submitLabel}
      </Button>
    </footer>
  );
}
