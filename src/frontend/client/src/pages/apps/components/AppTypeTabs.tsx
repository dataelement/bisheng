import { Tabs } from "@bisheng/ui";
import { useEffect } from "react";
import { useLocalize } from "~/hooks";
import { useAppRuntimeEnabled } from "~/hooks/useAppRuntimeEnabled";
import { APP_TYPE_FILTER_LABEL_KEY, type AppTypeFilter, appTypeFilters } from "../appTypes";

interface AppTypeTabsProps {
  value: AppTypeFilter;
  onChange: (value: AppTypeFilter) => void;
  className?: string;
}

export function AppTypeTabs({ value, onChange, className }: AppTypeTabsProps) {
  const localize = useLocalize();
  const filters = appTypeFilters(useAppRuntimeEnabled());
  const activeKey = filters.includes(value) ? value : "all";

  useEffect(() => {
    if (activeKey !== value) onChange(activeKey);
  }, [activeKey, onChange, value]);

  const handleChange = (key: string) => {
    const filter = filters.find((item) => item === key);
    if (filter) onChange(filter);
  };

  return (
    <Tabs
      className={className}
      aria-label={localize("com_app.type_filter")}
      activeKey={activeKey}
      onChange={handleChange}
      items={filters.map((filter) => ({ key: filter, label: localize(APP_TYPE_FILTER_LABEL_KEY[filter]) }))}
    />
  );
}
