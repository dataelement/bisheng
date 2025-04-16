import MultiSelect from "@/components/bs-ui/select/multi";
import { getUsersApi } from "@/controllers/API/user";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function UsersSelect({ multiple = false, lockedValues = [], value, disabled = false, onChange, children }:
    { multiple?: boolean, lockedValues?: any[], value: any, disabled?: boolean, onChange: (a: any) => any, children?: (fun: any) => React.ReactNode }) {

    const { t } = useTranslation()
    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    const pageRef = useRef(1)
    const reload = (page, name) => {
        getUsersApi({ page, pageSize: 40, name }).then(res => {
            pageRef.current = page
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.user_name, value: el.user_id }))
            setOptions(_ops => page > 1 ? [..._ops, ...opts] : opts)
        })
    }

    useEffect(() => {
        reload(1, '')
    }, [])

    // 加载更多
    const loadMore = (name) => {
        reload(pageRef.current + 1, name)
    }

    return <MultiSelect
        contentClassName=" max-w-[630px]"
        multiple={multiple}
        value={value}
        lockedValues={lockedValues}
        disabled={disabled}
        options={options}
        placeholder={t('system.selectUser')}
        searchPlaceholder={t('system.searchUser')}
        onChange={onChange}
        onLoad={() => reload(1, '')}
        onSearch={(val) => reload(1, val)}
        onScrollLoad={(val) => loadMore(val)}
    >
        {children?.(reload)}
    </MultiSelect>
};
