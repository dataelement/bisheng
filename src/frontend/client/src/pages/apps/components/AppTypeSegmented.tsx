import { Segmented } from "@bisheng/ui";
import { useEffect } from "react";
import { useLocalize } from "~/hooks";
import { useAppRuntimeEnabled } from "~/hooks/useAppRuntimeEnabled";
import { APP_TYPE_FILTER_LABEL_KEY, type AppTypeFilter, appTypeFilters } from "../appTypes";

interface AppTypeSegmentedProps {
  value: AppTypeFilter;
  onChange: (value: AppTypeFilter) => void;
  className?: string;
}

/**
 * Kind filter shared by the app center and the app square (v3.1.0-alpha1 F001).
 * "Hosted app" is offered only where the runtime layer is deployed — the server
 * answers an empty page for that kind otherwise.
 */
export function AppTypeSegmented({ value, onChange, className }: AppTypeSegmentedProps) {
  const localize = useLocalize();
  const runtimeEnabled = useAppRuntimeEnabled();
  const filters = appTypeFilters(runtimeEnabled);

  useEffect(() => {
    if (!filters.includes(value)) onChange("all");
  }, [filters, onChange, value]);

  return (
    <Segmented
      size="small"
      className={className}
      options={filters.map((filter) => ({ value: filter, label: localize(APP_TYPE_FILTER_LABEL_KEY[filter]) }))}
      value={filters.includes(value) ? value : "all"}
      onChange={(next) => onChange(next as AppTypeFilter)}
      aria-label={localize("com_app.type_filter")}
    />
  );
}
