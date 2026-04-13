import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { useTranslation } from "react-i18next"
import { RelationLevel } from "./types"

const GRANTABLE_LEVELS: RelationLevel[] = ['viewer', 'editor', 'manager']

interface RelationSelectProps {
  value: RelationLevel
  onChange: (v: RelationLevel) => void
  className?: string
  disabled?: boolean
}

export function RelationSelect({ value, onChange, className, disabled }: RelationSelectProps) {
  const { t } = useTranslation('permission')

  return (
    <Select value={value} onValueChange={(v) => onChange(v as RelationLevel)} disabled={disabled}>
      <SelectTrigger className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {GRANTABLE_LEVELS.map((level) => (
          <SelectItem key={level} value={level}>
            {t(`level.${level}`)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
