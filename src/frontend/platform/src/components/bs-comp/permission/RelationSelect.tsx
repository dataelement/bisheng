import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { cn } from "@/utils"
import { useTranslation } from "react-i18next"
import { RelationLevel } from "./types"

export type RelationModelOption = {
  id: string
  name: string
  relation: RelationLevel
}

interface RelationSelectProps {
  value: string
  onChange: (v: string) => void
  className?: string
  disabled?: boolean
  options?: RelationModelOption[]
}

export function RelationSelect({ value, onChange, className, disabled, options }: RelationSelectProps) {
  const { t } = useTranslation('permission')
  const fallbackOptions: RelationModelOption[] = [
    { id: 'owner', name: t('level.owner'), relation: 'owner' },
    { id: 'viewer', name: t('level.viewer'), relation: 'viewer' },
    { id: 'editor', name: t('level.editor'), relation: 'editor' },
    { id: 'manager', name: t('level.manager'), relation: 'manager' },
  ]
  const modelOptions = options ?? fallbackOptions

  return (
    <Select value={value} onValueChange={(v) => onChange(v)} disabled={disabled}>
      <SelectTrigger
        className={cn(
          "h-8 rounded-[6px] border-0 bg-white px-1 text-[14px] leading-[22px] text-[#212121] shadow-none hover:bg-white focus:ring-0 data-[placeholder]:text-[#999999] [&>span]:text-[#212121]",
          className,
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
            showIcon={false}
            className="mb-1 min-h-[32px] rounded-[8px] px-2 py-[5px] pr-2 text-[14px] leading-[22px] text-[#212121] focus:bg-[#E6EDFC] focus:text-[#335CFF] data-[state=checked]:bg-[#E6EDFC] data-[state=checked]:font-normal data-[state=checked]:text-[#335CFF] last:mb-0"
          >
            {model.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
