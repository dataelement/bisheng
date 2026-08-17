import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/Select";
import { cn } from "~/utils";

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
}

export function RelationSelect({
  value,
  onChange,
  className,
  disabled,
  options,
}: RelationSelectProps) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger
        className={cn(
          "h-8 rounded-md border-0 bg-white px-1 text-[14px] leading-[22px] text-[#212121] shadow-none hover:bg-white focus:ring-0",
          className,
        )}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent
        className="max-h-[240px] rounded-lg border-0 bg-white shadow-[0px_6px_20px_1px_rgba(117,145,212,0.12)]"
        sideOffset={8}
        align="start"
      >
        {options.map((model) => (
          <SelectItem
            key={model.id}
            value={model.id}
            showIndicator={false}
            className="mb-1 min-h-[32px] rounded-lg px-2 py-[5px] pr-2 text-[14px] leading-[22px] last:mb-0"
          >
            {model.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
