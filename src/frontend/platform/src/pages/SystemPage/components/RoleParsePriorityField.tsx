import { Label } from "@/components/bs-ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio"
import { useTranslation } from "react-i18next"

export const KNOWLEDGE_PARSE_PRIORITY_KEY = "knowledge_file_parse_priority"

export type KnowledgeParsePriorityValue = "high" | "medium" | "low"

export const DEFAULT_KNOWLEDGE_PARSE_PRIORITY: KnowledgeParsePriorityValue = "medium"

export function normalizeKnowledgeParsePriority(value: unknown): KnowledgeParsePriorityValue {
  return value === "high" || value === "medium" || value === "low"
    ? value
    : DEFAULT_KNOWLEDGE_PARSE_PRIORITY
}

export function mergeKnowledgeParsePriority(
  quotaConfig: Record<string, unknown>,
  priority: KnowledgeParsePriorityValue,
): Record<string, unknown> {
  return { ...quotaConfig, [KNOWLEDGE_PARSE_PRIORITY_KEY]: priority }
}

interface RoleParsePriorityFieldProps {
  value: KnowledgeParsePriorityValue
  onChange: (value: KnowledgeParsePriorityValue) => void
}

const OPTIONS: KnowledgeParsePriorityValue[] = ["high", "medium", "low"]

export default function RoleParsePriorityField({ value, onChange }: RoleParsePriorityFieldProps) {
  const { t } = useTranslation()

  return (
    <div className="rounded-md border p-3">
      <Label>{t("system.knowledgeParsePriority")}</Label>
      <p className="mt-1 text-xs text-muted-foreground">
        {t("system.knowledgeParsePriorityDesc")}
      </p>
      <RadioGroup
        className="mt-3 flex flex-wrap gap-5"
        value={value}
        onValueChange={(nextValue) => onChange(normalizeKnowledgeParsePriority(nextValue))}
      >
        {OPTIONS.map((option) => (
          <label key={option} className="flex cursor-pointer items-center gap-2 text-sm">
            <RadioGroupItem value={option} />
            <span>{t(`system.knowledgeParsePriority${option[0].toUpperCase()}${option.slice(1)}`)}</span>
          </label>
        ))}
      </RadioGroup>
    </div>
  )
}
