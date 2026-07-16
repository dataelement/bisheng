import { PlusIcon, TrashIcon } from "@/components/bs-icons"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import type {
  DeveloperTokenRouteMatchType,
  DeveloperTokenRouteRule,
} from "@/controllers/API/developerToken"
import { useTranslation } from "react-i18next"
import { MAX_DEVELOPER_TOKEN_ROUTE_RULES } from "./developerTokenRouteValidation"

const MATCH_TYPES: DeveloperTokenRouteMatchType[] = ["METHOD_PATH", "PATH", "PREFIX"]
const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

interface DeveloperTokenRouteAllowlistProps {
  value: DeveloperTokenRouteRule[]
  onChange: (value: DeveloperTokenRouteRule[]) => void
}

export default function DeveloperTokenRouteAllowlist({
  value,
  onChange,
}: DeveloperTokenRouteAllowlistProps) {
  const { t } = useTranslation()

  const handleChange = (index: number, patch: Partial<DeveloperTokenRouteRule>) => {
    onChange(
      value.map((rule, current) =>
        current === index ? { ...rule, ...patch } : rule
      )
    )
  }

  const handleTypeChange = (index: number, matchType: DeveloperTokenRouteMatchType) => {
    handleChange(index, {
      match_type: matchType,
      method: matchType === "METHOD_PATH" ? value[index].method || "GET" : null,
    })
  }

  const handleAdd = () => {
    onChange([...value, { match_type: "METHOD_PATH", method: "GET", path: "" }])
  }

  return (
    <div className="space-y-2 md:col-span-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span>{t("system.developerToken.fields.routeWhitelist")}</span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={value.length >= MAX_DEVELOPER_TOKEN_ROUTE_RULES}
          onClick={handleAdd}
        >
          <PlusIcon className="mr-1 h-4 w-4" />
          {t("system.developerToken.routeRules.add")}
        </Button>
      </div>
      {value.length === 0 ? (
        <div className="border-y py-3 text-xs text-muted-foreground">
          {t("system.developerToken.routeRules.emptyHelp")}
        </div>
      ) : (
        <div className="max-h-72 divide-y overflow-y-auto border-y">
          {value.map((rule, index) => (
            <div
              key={index}
              className="grid gap-2 py-2 md:grid-cols-[150px_110px_minmax(0,1fr)_36px]"
            >
              <Select
                value={rule.match_type}
                onValueChange={(next) =>
                  handleTypeChange(index, next as DeveloperTokenRouteMatchType)
                }
              >
                <SelectTrigger aria-label={t("system.developerToken.routeRules.matchType")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MATCH_TYPES.map((type) => (
                    <SelectItem key={type} value={type}>
                      {t(`system.developerToken.routeRules.types.${type}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {rule.match_type === "METHOD_PATH" ? (
                <Select
                  value={rule.method || "GET"}
                  onValueChange={(method) => handleChange(index, { method })}
                >
                  <SelectTrigger aria-label={t("system.developerToken.routeRules.method")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {METHODS.map((method) => (
                      <SelectItem key={method} value={method}>
                        {method}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <div className="flex h-9 items-center px-3 text-xs text-muted-foreground">
                  {t("system.developerToken.routeRules.anyMethod")}
                </div>
              )}
              <Input
                value={rule.path}
                onChange={(event) => handleChange(index, { path: event.target.value })}
                placeholder={
                  rule.match_type === "PREFIX"
                    ? t("system.developerToken.routeRules.prefixPlaceholder")
                    : t("system.developerToken.routeRules.pathPlaceholder")
                }
              />
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={t("system.developerToken.routeRules.remove")}
                title={t("system.developerToken.routeRules.remove")}
                onClick={() => onChange(value.filter((_, current) => current !== index))}
              >
                <TrashIcon className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
      <div className="text-xs text-muted-foreground">
        {t("system.developerToken.routeRules.prefixHelp")}
      </div>
    </div>
  )
}
