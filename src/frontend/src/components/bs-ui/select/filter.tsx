import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";

export default function FilterUserGroup({options, placeholder, 
  onChecked, search, onClearChecked, onOk}) {
    const { t } = useTranslation()

  return (
    <div className="grid h-full grid-rows-[25%_50%_25%] gap-y-2">
      <div>
        <SearchInput placeholder={placeholder} className="w-[240px]" onChange={search}></SearchInput>
      </div>
      <div> 
        {options.map((i:any) => (
            <div className="flex items-center space-x-2" key={i.id}>
                <Checkbox id={i.id} checked={i.checked} onCheckedChange={() => onChecked(i.id)}/>
                <label htmlFor={i.id}>{i.name}</label>
            </div>
        ))}
        {options.length === 0 && 
        <div className="flex items-center justify-center h-[70px]">
            <Button variant="ghost">Empty~</Button>
        </div>}
      </div>
      <div className="flex justify-between">
        <Button variant="ghost" className="px-8" onClick={onClearChecked}>{t('system.reset')}</Button> 
        <Button className="px-8" onClick={onOk}>{t('system.confirm')}</Button>
      </div>
    </div>
  );
}
