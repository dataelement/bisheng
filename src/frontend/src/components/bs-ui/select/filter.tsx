import { Checkbox } from "@/components/bs-ui/checkBox";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import { useRef, useState } from "react";
import { getSearchRes } from "@/controllers/API/user";
import { useTranslation } from "react-i18next";

export default function FilterUserGroup({arr, placeholder, onButtonClick, onIsOpen}) {
    let temp = []
    arr.forEach((a, index) => {
        const item = {
            id: index + '',
            name: a.name,
            checked: false
        }
        if(a.name == '默认用户组' ||  a.name == '普通用户') {
            item.checked = true
        }
        temp.push(item)
    })

    const [items, setItems] = useState(temp)
    const handlerChecked = (id) => {
      const newItems = items.map((item:any) => item.id === id ? {...item, checked:!item.checked} : item)
      setItems(newItems)
    }

    const clearChecked = () => {
      setItems(temp)
    }

    const inputRef = useRef(null)
    const getData = () => {
        const res = getSearchRes('zgj')
        onButtonClick(res)
        onIsOpen(false)
    }
    const search = () => {
      console.log(inputRef.current.value)
    }

    const { t } = useTranslation()

  return (
    <div className="grid h-full grid-rows-[25%_50%_25%] gap-y-2">
      <div>
        <SearchInput ref={inputRef} placeholder={placeholder} className="w-[240px]" onChange={search}></SearchInput>
      </div>
      <div> 
        {items.map((i:any) => (
            <div className="flex items-center space-x-2" key={i.id}>
                <Checkbox id={i.id} checked={i.checked} onCheckedChange={() => handlerChecked(i.id)}/>
                <label htmlFor={i.id}>{i.name}</label>
            </div>
        ))}
        {arr.length === 0 && 
        <div className="flex items-center justify-center h-[70px]">
            <Button variant="ghost">Empty~</Button>
        </div>}
      </div>
      <div className="flex justify-between">
        <Button variant="ghost" onClick={clearChecked}>{t('system.reset')}</Button> <Button onClick={getData}>{t('system.confirm')}</Button>
      </div>
    </div>
  );
}
