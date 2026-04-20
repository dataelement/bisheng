import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/Select";
import { useLocalize } from "~/hooks";
import type { RelationLevel } from "~/api/permission";

export interface RelationModelOption {
  id: string;
  name: string;
  relation: RelationLevel;
}

interface RelationSelectProps {
  value: string;
  onChange: (v: string) => void;
  className?: string;
  disabled?: boolean;
  options?: RelationModelOption[];
}

export function RelationSelect({
  value,
  onChange,
  className,
  disabled,
  options,
}: RelationSelectProps) {
  const localize = useLocalize();
  const fallbackOptions: RelationModelOption[] = [
    { id: "owner", name: localize("com_permission.level_owner"), relation: "owner" },
    { id: "viewer", name: localize("com_permission.level_viewer"), relation: "viewer" },
    { id: "editor", name: localize("com_permission.level_editor"), relation: "editor" },
    { id: "manager", name: localize("com_permission.level_manager"), relation: "manager" },
  ];
  const modelOptions = options && options.length ? options : fallbackOptions;

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {modelOptions.map((model) => (
          <SelectItem key={model.id} value={model.id}>
            {model.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
