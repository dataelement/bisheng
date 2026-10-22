// @ts-strict-ignore
import { Button, SearchInput } from '@bisheng/ui';

import { Checkbox } from '@bisheng/ui';
import React from 'react';
import { useTranslation } from "react-i18next";


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
        <SearchInput placeholder={placeholder} onChange={search} className={"w-[240px]"}></SearchInput>
      </div>
      <div className="mt-2 max-h-[260px] min-h-20 overflow-y-auto">
        {options.map((i) => (
          <div className="flex items-center space-x-2 text-gray-500 mb-1" key={i.id}>
            <Checkbox className="peer" id={i.id} checked={value.includes(i.id)} onCheckedChange={() => onChecked(i.id)} />
            <label htmlFor={i.id} className="cursor-pointer text-sm">{i[nameKey]}</label>
          </div>
        ))}
        {options.length === 0 && (
          <div className="flex items-center justify-center h-[70px]">
            <Button variant="text" color="default">{t('build.empty')}</Button>
          </div>
        )}
      </div>
      <div className="flex justify-between mt-4">
        <Button variant="text" onClick={onClearChecked} color="default">{t('system.reset')}</Button>
        <Button onClick={onOk}>{t('system.confirm')}</Button>
      </div>
    </div>
  );
}

export default React.memo(FilterUserGroup);