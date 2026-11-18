import { Button, Input } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";

interface FileMetadataValueFieldsProps {
  values: Record<string, string>;
  types: Record<string, string>;
  onChange: (name: string, value: string) => void;
  onRemove: (name: string) => void;
}
function metadataDate(value: string): Date | undefined {
  if (!value.trim()) return undefined;
  const date = new Date(Number(value) * 1000);
  return Number.isFinite(date.getTime()) ? date : undefined;
}
export function FileMetadataValueFields({ values, types, onChange, onRemove }: FileMetadataValueFieldsProps) {
  const { t } = useTranslation("knowledge");
  return <>
    {Object.entries(values).map(([name, value]) => <div key={name} className="flex items-end gap-2">
      <div className="min-w-0 flex-1 space-y-1">
        <label id={`metadata-label-${name}`} htmlFor={types[name] === "time" ? undefined : `metadata-${name}`}>{name}</label>
        {types[name] === "time" ? <div role="group" aria-labelledby={`metadata-label-${name}`}><DatePicker
          showTime
          value={metadataDate(value)}
          placeholder={name}
          onChange={date => onChange(name, String(Math.floor(date.getTime() / 1000)))}
        /></div> : <Input
          id={`metadata-${name}`}
          type={types[name] === "number" ? "number" : "text"}
          value={value}
          onChange={event => onChange(name, event.target.value)}
        />}
      </div>
      <Button variant="text" aria-label={`${t("delete")} ${name}`} onClick={() => onRemove(name)}>{t("delete")}</Button>
    </div>)}
  </>;
}
