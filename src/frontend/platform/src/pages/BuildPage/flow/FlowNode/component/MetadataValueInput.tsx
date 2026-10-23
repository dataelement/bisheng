import { Input } from '@bisheng/ui';
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";

import { Outlined } from "bisheng-icons";
import { format } from "date-fns";
import { useTranslation } from "react-i18next";
import type { MetadataCondition } from "./MetadataFilter";
import NumberInput from "./NumberInput";
import SelectVar from "./SelectVar";
interface MetadataValueInputProps {
    condition: MetadataCondition;
    metadataType?: string;
    nodeId?: string;
    updateCondition: (id: string, field: keyof MetadataCondition, value: string) => void;
}
export function MetadataValueInput({ condition, metadataType, nodeId, updateCondition }: MetadataValueInputProps) {
    const { t } = useTranslation('flow');
    const isEmptyOperator = [`is_empty`, `is_not_empty`].includes(condition.operator);

    if (isEmptyOperator) return <Input placeholder={t('noInputNeeded')} value="" disabled className={"bg-gray-100 h-8"} />;

    if (condition.valueType === "reference") {
      const selectedLabel = condition.valueLabel
        ? condition.valueLabel.split('.').reduce((acc, part, index, array) => index === array.length - 1 ? `${acc}/${part}` : `${acc}.${part}`)
        : "";
      return (
        <div className="flex items-center gap-1 min-w-0">
          <SelectVar
            className="max-w-40 flex-1"
            nodeId={nodeId}
            itemKey={condition.id}
            onSelect={(E: { id: string; name: string }, v: { value: string; label: string }) => {
              updateCondition(condition.id, "value", `${E.id}.${v.value}`);
              updateCondition(condition.id, "valueLabel", `${E.name}/${v.label}`);
            }}
          >
            <div className="no-drag nowheel group flex h-8 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400">
              <span className="flex items-center flex-1 truncate">{selectedLabel || t('selectOption')}</span>
              <Outlined.Down className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
          </SelectVar>
        </div>
      );
    }

    if (metadataType === "String") return <Input placeholder={t('enterValue2')} value={condition.value} onChange={(e) => updateCondition(condition.id, "value", e.target.value)} maxLength={255} className={"h-8"} showCount />;
    if (metadataType === "Number") return (
      <div className="w-full mt-2">
        <NumberInput value={condition.value} onChange={(value: string) => updateCondition(condition.id, "value", value)} />
      </div>
    );
    if (metadataType === "Time") return <DatePicker value={condition.value ? new Date(condition.value) : undefined} placeholder={t('selectTime')} showTime onChange={(d) => updateCondition(condition.id, "value", d ? format(d, "yyyy-MM-dd'T'HH:mm:ss") : "")} />;
    return <Input placeholder={t('enterValue2')} value={condition.value} onChange={(e) => updateCondition(condition.id, "value", e.target.value)} className={"h-8"} />;
  };
