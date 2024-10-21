import { FilterIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { SearchInput } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { useDebounce } from "@/components/bs-ui/utils";
import { getLabelUsersApi, getUsersApi } from "@/controllers/API/user";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function ColFilterUser({ label, onFilter }) {
    const { t } = useTranslation()
    const [open, setOpen] = useState(false);
    const [value, setValue] = useState([]);

    const { options, setOptions, reload, loadMore, search } = useUsersOptions(label)
    const searchDb = useDebounce(search, 200, false)

    const handlerChecked = (id) => {
        setValue(val => {
            const index = val.indexOf(id)
            index === -1 ? val.push(id) : val.splice(index, 1)
            return [...val]
        })
        // 已选项上浮
        const checked = options.filter(o => value.includes(o.id))
        const uncheck = options.filter(o => !value.includes(o.id))
        setOptions([...checked, ...uncheck])
    }

    return <Popover open={open} onOpenChange={(bln) => setOpen(bln)}>
        <PopoverTrigger>
            <FilterIcon onClick={() => setOpen(!open)} className={value.length ? 'text-primary ml-3' : 'text-gray-400 ml-3'} />
        </PopoverTrigger>
        <PopoverContent>
            <div>
                {!label && <SearchInput placeholder={'用户名称'} className="w-[240px]" onChange={(e) => searchDb(e.target.value)}></SearchInput>}
                <div className="mt-2 max-h-[260px] min-h-20 overflow-y-auto">
                    {options.map((el) => (
                        <div className="flex items-center space-x-2 mb-1" key={el.value}>
                            <Checkbox id={el.value} checked={value.includes(el.value)} onCheckedChange={() => handlerChecked(el.value)} />
                            <Label htmlFor={el.value} className="cursor-pointer text-sm truncate">{el.label}</Label>
                        </div>
                    ))}
                    {options.length === 0 && (
                        <div className="flex items-center justify-center h-[70px]">
                            <Button variant="ghost">{t('build.empty')}</Button>
                        </div>
                    )}
                </div>
                <div className="flex justify-between mt-4">
                    <Button variant="ghost" className="px-8 h-8" onClick={() => {
                        setValue([])
                        onFilter([])
                    }}>{t('system.reset')}</Button>
                    <Button className="px-8 h-8" onClick={() => {
                        setOpen(false)
                        onFilter(value)
                    }}>{t('system.confirm')}</Button>
                </div>
            </div>
        </PopoverContent>
    </Popover>
};

// users
const useUsersOptions = (label) => {
    const [options, setOptions] = useState([])
    const optionsRef = useRef([])
    const pageRef = useRef(1)
    const keywordRef = useRef("")

    const loadApps = () => {
        const page = pageRef.current;
        (label ? getLabelUsersApi(label) : getUsersApi({ page, pageSize: 400, name: keywordRef.current })).then((res: any) => {
            const resData = label ? res : res.data
            const newOptions = resData.map(el => ({
                label: el.user_name,
                value: el.user_id
            }))
            optionsRef.current = page === 1 ? newOptions : [...optionsRef.current, ...newOptions]
            setOptions(optionsRef.current)
        })
    }
    useEffect(() => {
        loadApps()
    }, [])

    return {
        options,
        setOptions,
        reload: () => {
            keywordRef.current = ''
            pageRef.current = 1
            loadApps()
        },
        loadMore: () => {
            pageRef.current++
            loadApps()
        },
        search: (keyword) => {
            pageRef.current = 1
            keywordRef.current = keyword
            loadApps()
        }
    }
}