import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
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
  )
}
