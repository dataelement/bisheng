import React from 'react';
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";

// 定义组件的 props 类型
interface FilterUserGroupProps {
  value: string[];
  options: { id: string;[key: string]: any }[];
  nameKey?: string;
  placeholder: string;
  onChecked: (id: string) => void;
  search: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onClearChecked: () => void;
  onOk: () => void;
}

const FilterUserGroup: React.FC<FilterUserGroupProps> = ({
  value = [],
  options,
  nameKey = 'name',
  placeholder,
  onChecked,
  search,
  onClearChecked,
  onOk
}) => {
  const { t } = useTranslation();

  return (
    <div className="h-full">
      <div>
        <SearchInput placeholder={placeholder} className="w-[240px]" onChange={search}></SearchInput>
      </div>
      <div className="mt-2 max-h-[260px] min-h-20 overflow-y-auto">
        {options.map((i) => (
          <div className="flex items-center space-x-2 text-gray-500 mb-1" key={i.id}>
            <Checkbox id={i.id} checked={value.includes(i.id)} onCheckedChange={() => onChecked(i.id)} />
            <label htmlFor={i.id} className="cursor-pointer text-sm">{i[nameKey]}</label>
          </div>
        ))}
        {options.length === 0 && (
          <div className="flex items-center justify-center h-[70px]">
            <Button variant="ghost">{t('build.empty')}</Button>
          </div>
        )}
      </div>
      <div className="flex justify-between mt-4">
        <Button variant="ghost" className="px-8 h-8" onClick={onClearChecked}>{t('system.reset')}</Button>
        <Button className="px-8 h-8" onClick={onOk}>{t('system.confirm')}</Button>
      </div>
    </div>
  );
}

export default React.memo(FilterUserGroup);