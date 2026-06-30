import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/Select";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";
import type { RelationLevel, ResourceType } from "~/api/permission";
import { PermissionModelHelpIcon } from "./permissionModelInfo";

export interface RelationModelOption {
  id: string;
  name: string;
  relation: RelationLevel;
  permissions?: string[];
  permissions_explicit?: boolean;
  is_system?: boolean;
}

interface RelationSelectProps {
  value: string;
  onChange: (v: string) => void;
  className?: string;
  disabled?: boolean;
  options?: RelationModelOption[];
  resourceType?: ResourceType;
}

export function RelationSelect({
  value,
  onChange,
  className,
  disabled,
  options,
  resourceType,
}: RelationSelectProps) {
  const localize = useLocalize();
  const fallbackOptions: RelationModelOption[] = [
    {
      id: "owner",
      name: localize("com_permission.level_owner"),
      relation: "owner",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    },
    {
      id: "manager",
      name: localize("com_permission.level_manager"),
      relation: "manager",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    },
    {
      id: "editor",
      name: localize("com_permission.level_editor"),
      relation: "editor",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    },
    {
      id: "viewer",
      name: localize("com_permission.level_viewer"),
      relation: "viewer",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    },
  ];
  const modelOptions = options ?? fallbackOptions;

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger
        className={cn(
          "h-8 rounded-[6px] border-0 bg-white px-1 text-[14px] leading-[22px] text-[#212121] shadow-none hover:bg-white focus:ring-0 data-[placeholder]:text-[#999999] [&>span]:text-[#212121]",
          className
        )}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent
        className="max-h-[240px] rounded-[8px] border-0 bg-white shadow-[0px_6px_20px_1px_rgba(117,145,212,0.12)]"
        sideOffset={8}
        align="start"
      >
        {modelOptions.map((model) => (
          <SelectItem
            key={model.id}
            value={model.id}
            textValue={model.name}
            showIndicator={false}
            className="mb-1 min-h-[32px] rounded-[8px] px-2 py-[5px] pr-2 text-[14px] leading-[22px] text-[#212121] focus:bg-[#E6EDFC] focus:text-[#335CFF] data-[state=checked]:bg-[#E6EDFC] data-[state=checked]:font-normal data-[state=checked]:text-[#335CFF] last:mb-0"
          >
            <span className="flex min-w-0 items-center">
              <span className="truncate">{model.name}</span>
              {resourceType ? (
                <PermissionModelHelpIcon
                  resourceType={resourceType}
                  model={model}
                  localize={localize}
                />
              ) : null}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
