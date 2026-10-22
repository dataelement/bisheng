import { Select } from "@bisheng/ui";
import useSelectCopy from "~/hooks/useSelectCopy";

export interface RelationModelOption {
  id: string;
  name: string;
  level?: number | null;
}

interface RelationSelectProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  disabled?: boolean;
  options: RelationModelOption[];
  "aria-label"?: string;
}

/** Borderless picker for a footer row, next to the label it belongs to. */
export function RelationSelect({
  value,
  onChange,
  className,
  disabled,
  options,
  "aria-label": ariaLabel,
}: RelationSelectProps) {
  const selectCopy = useSelectCopy();
  return (
    <Select
      {...selectCopy}
      variant="ghost"
      options={options
        .filter((model) => model.id != null && model.id !== "")
        .map((model) => ({ value: model.id, label: model.name }))}
      value={value || null}
      onChange={(next) => next != null && onChange(String(next))}
      disabled={disabled}
      className={className}
      aria-label={ariaLabel}
    />
  );
}
